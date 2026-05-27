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


# ── workspaces / 팀 ─────────────────────────────────────
def list_workspaces(sb, user_id: str, email: str) -> list[dict]:
    owned = sb.table("workspaces").select("*").eq("owner_id", user_id).execute().data or []
    mrows = sb.table("workspace_members").select("workspace_id").eq("email", email).execute().data or []
    member_ids = [m["workspace_id"] for m in mrows]
    member_ws = []
    if member_ids:
        member_ws = sb.table("workspaces").select("*").in_("id", member_ids).execute().data or []
    seen, out = set(), []
    for w in owned + member_ws:
        if w["id"] not in seen:
            seen.add(w["id"]); out.append(w)
    return out


def create_workspace(sb, user_id: str, email: str, name: str) -> str:
    r = sb.table("workspaces").insert(
        {"owner_id": user_id, "owner_email": email, "name": name}
    ).execute()
    return r.data[0]["id"]


def invite_member(sb, ws_id: str, email: str):
    sb.table("workspace_members").upsert(
        {"workspace_id": ws_id, "email": email, "role": "member"},
        on_conflict="workspace_id,email",
    ).execute()


def list_members(sb, ws_id: str) -> list[dict]:
    ws = sb.table("workspaces").select("owner_email").eq("id", ws_id).execute().data
    out = [{"email": ws[0]["owner_email"], "role": "owner"}] if ws else []
    rows = sb.table("workspace_members").select("email,role").eq("workspace_id", ws_id).execute().data or []
    out += [{"email": r["email"], "role": r["role"]} for r in rows]
    return out


def remove_member(sb, ws_id: str, email: str):
    sb.table("workspace_members").delete().eq("workspace_id", ws_id).eq("email", email).execute()


# ── brand_profiles (개인 + 워크스페이스 공유) ──────────────
def list_brands(sb, user_id: str, ws_ids: list[str] | None = None) -> list[dict]:
    personal = (sb.table("brand_profiles").select("*")
                .eq("user_id", user_id).is_("workspace_id", "null")
                .order("created_at", desc=True).execute().data or [])
    shared = []
    if ws_ids:
        shared = (sb.table("brand_profiles").select("*")
                  .in_("workspace_id", ws_ids).execute().data or [])
    return personal + shared


def create_brand(sb, user_id: str, data: dict, workspace_id: str | None = None):
    sb.table("brand_profiles").insert(
        {"user_id": user_id, "workspace_id": workspace_id, **data}
    ).execute()


def delete_brand(sb, brand_id: str):
    sb.table("brand_profiles").delete().eq("id", brand_id).execute()


# ── integrations ────────────────────────────────────────
def list_integrations(sb, user_id: str) -> list[dict]:
    r = (sb.table("integrations").select("*")
         .eq("user_id", user_id).order("created_at", desc=True).execute())
    return r.data or []


def create_integration(sb, user_id: str, type_: str, name: str, cfg: dict):
    sb.table("integrations").insert(
        {"user_id": user_id, "type": type_, "name": name, "config": cfg}
    ).execute()


def delete_integration(sb, integration_id: str):
    sb.table("integrations").delete().eq("id", integration_id).execute()


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
