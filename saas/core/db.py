"""Supabase 클라이언트 + 관계형 CRUD (app.py:124-135, 142-163 패턴 기반).

Streamlit/FastAPI 양쪽에서 쓰므로 streamlit 캐시 데코레이터 대신 모듈 싱글톤을 사용한다.
"""
import hashlib
import secrets

from core import config

_anon_client = None
_service_client = None


def get_supabase(service: bool = False):
    """anon 키(기본) 또는 service 키(webhook 권한 쓰기용) 클라이언트 반환."""
    global _anon_client, _service_client
    if service:
        if _service_client is None:
            from supabase import create_client
            _service_client = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
        return _service_client
    if _anon_client is None:
        from supabase import create_client
        _anon_client = create_client(config.SUPABASE_URL, config.SUPABASE_ANON_KEY)
    return _anon_client


# ── profiles ────────────────────────────────────────────
def get_profile(sb, user_id: str) -> dict | None:
    r = sb.table("profiles").select("*").eq("id", user_id).execute()
    return r.data[0] if r.data else None


def ensure_profile(sb, user_id: str, email: str) -> dict:
    existing = get_profile(sb, user_id)
    if existing:
        return existing
    sb.table("profiles").insert(
        {"id": user_id, "email": email, "tier": "free"}
    ).execute()
    return get_profile(sb, user_id)


def set_tier(sb, user_id: str, tier: str):
    sb.table("profiles").update({"tier": tier}).eq("id", user_id).execute()


def set_stripe_customer(sb, user_id: str, customer_id: str):
    sb.table("profiles").update({"stripe_customer_id": customer_id}).eq("id", user_id).execute()


def get_profile_by_customer(sb, customer_id: str) -> dict | None:
    r = sb.table("profiles").select("*").eq("stripe_customer_id", customer_id).execute()
    return r.data[0] if r.data else None


# ── generations ────────────────────────────────────────
def save_generation(sb, user_id, gen_type, language, input_params, output_text, model):
    sb.table("generations").insert({
        "user_id": user_id,
        "type": gen_type,
        "language": language,
        "input_params": input_params,
        "output_text": output_text,
        "model": model,
    }).execute()


def recent_generations(sb, user_id: str, limit: int = 50) -> list[dict]:
    r = (sb.table("generations").select("*")
         .eq("user_id", user_id)
         .order("created_at", desc=True)
         .limit(limit).execute())
    return r.data or []


# ── subscriptions ──────────────────────────────────────
def upsert_subscription(sb, user_id, stripe_sub_id, price_id, status, period_end):
    sb.table("subscriptions").upsert({
        "user_id": user_id,
        "stripe_subscription_id": stripe_sub_id,
        "stripe_price_id": price_id,
        "status": status,
        "current_period_end": period_end,
    }, on_conflict="stripe_subscription_id").execute()


# ── brand_profiles ──────────────────────────────────────
def list_brands(sb, user_id: str) -> list[dict]:
    r = (sb.table("brand_profiles").select("*")
         .eq("user_id", user_id).order("created_at", desc=True).execute())
    return r.data or []


def create_brand(sb, user_id: str, data: dict):
    sb.table("brand_profiles").insert({"user_id": user_id, **data}).execute()


def delete_brand(sb, brand_id: str):
    sb.table("brand_profiles").delete().eq("id", brand_id).execute()


# ── api_keys (Business 티어) ────────────────────────────
def create_api_key(sb, user_id: str, label: str) -> str:
    """원본 키 생성 → 해시만 저장하고 원본을 1회 반환."""
    raw = "cf_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    sb.table("api_keys").insert({
        "user_id": user_id, "key_hash": key_hash, "label": label,
    }).execute()
    return raw


def list_api_keys(sb, user_id: str) -> list[dict]:
    r = (sb.table("api_keys").select("id,label,created_at,last_used_at,revoked")
         .eq("user_id", user_id).eq("revoked", False)
         .order("created_at", desc=True).execute())
    return r.data or []


def revoke_api_key(sb, key_id: str):
    sb.table("api_keys").update({"revoked": True}).eq("id", key_id).execute()
