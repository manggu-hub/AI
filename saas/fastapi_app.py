"""FastAPI: Stripe webhook + Business 티어 공개 API.

실행: uvicorn fastapi_app:app --port 8000
Streamlit이 받을 수 없는 두 가지(웹훅 수신, REST API)만 담당하는 얇은 서비스.
"""
import hashlib

import stripe
from fastapi import FastAPI, Header, HTTPException, Request

from core import config, db, usage
from core.billing import tier_from_price
from generators.base import GENERATORS

app = FastAPI(title="ContentForge API")
stripe.api_key = config.STRIPE_SECRET_KEY


@app.get("/healthz")
def healthz():
    return {"ok": True}


# ════════════════════════════════════════════════════════
#  Stripe Webhook — 결제 이벤트로 profiles.tier 전환
# ════════════════════════════════════════════════════════
@app.post("/stripe/webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, config.STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"signature 검증 실패: {e}")

    sb = db.get_supabase(service=True)
    etype = event["type"]
    obj = event["data"]["object"]

    if etype == "checkout.session.completed":
        user_id = (obj.get("metadata") or {}).get("user_id")
        customer_id = obj.get("customer")
        sub_id = obj.get("subscription")
        if user_id and customer_id:
            db.set_stripe_customer(sb, user_id, customer_id)
        if sub_id:
            sub = stripe.Subscription.retrieve(sub_id)
            _apply_subscription(sb, user_id, sub)

    elif etype in ("customer.subscription.updated", "customer.subscription.created"):
        user_id = _resolve_user(sb, obj)
        _apply_subscription(sb, user_id, obj)

    elif etype == "customer.subscription.deleted":
        user_id = _resolve_user(sb, obj)
        if user_id:
            db.set_tier(sb, user_id, "free")

    return {"received": True}


def _resolve_user(sb, sub_obj):
    user_id = (sub_obj.get("metadata") or {}).get("user_id")
    if user_id:
        return user_id
    profile = db.get_profile_by_customer(sb, sub_obj.get("customer"))
    return profile["id"] if profile else None


def _apply_subscription(sb, user_id, sub):
    if not user_id:
        return
    price_id = sub["items"]["data"][0]["price"]["id"]
    status = sub.get("status")
    tier = tier_from_price(price_id) if status in ("active", "trialing") else "free"
    db.set_tier(sb, user_id, tier)
    period_end = sub.get("current_period_end")
    from datetime import datetime, timezone
    period_iso = (datetime.fromtimestamp(period_end, tz=timezone.utc).isoformat()
                  if period_end else None)
    db.upsert_subscription(sb, user_id, sub["id"], price_id, status, period_iso)


# ════════════════════════════════════════════════════════
#  Business 티어 공개 API
# ════════════════════════════════════════════════════════
@app.post("/v1/generate")
async def api_generate(request: Request, authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer API 키가 필요합니다.")
    raw_key = authorization.split(" ", 1)[1].strip()
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    sb = db.get_supabase(service=True)
    r = (sb.table("api_keys").select("user_id")
         .eq("key_hash", key_hash).eq("revoked", False).execute())
    if not r.data:
        raise HTTPException(status_code=401, detail="유효하지 않은 API 키입니다.")
    user_id = r.data[0]["user_id"]

    profile = db.get_profile(sb, user_id)
    tier = profile["tier"] if profile else "free"
    if tier != "business":
        raise HTTPException(status_code=403, detail="API 접근은 Business 플랜 전용입니다.")

    ok, _used, _limit = usage.check_quota(sb, user_id, tier)
    if not ok:
        raise HTTPException(status_code=429, detail="월 사용 한도를 초과했습니다.")

    body = await request.json()
    gen_key = body.get("type")
    spec = GENERATORS.get(gen_key)
    if not spec:
        raise HTTPException(status_code=400, detail=f"알 수 없는 type: {gen_key}")
    lang = body.get("language", "ko")
    params = body.get("params", {})

    from core import gemini
    from generators.base import with_brand
    system = with_brand(spec["system"](lang), body.get("brand"))
    prompt = spec["prompt"](params, lang)
    try:
        output, model = gemini.generate(system, prompt, paid=True)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"생성 실패: {e}")

    usage.increment_usage(sb, user_id)
    db.save_generation(sb, user_id, gen_key, lang, params, output, model)
    sb.table("api_keys").update(
        {"last_used_at": config.now_kst().isoformat()}
    ).eq("key_hash", key_hash).execute()

    return {"output": output, "model": model}
