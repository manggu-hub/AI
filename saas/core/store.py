"""스토리지 추상화: 클라우드(Supabase) 또는 로컬(JSON) 백엔드.

UI/페이지는 Store 인스턴스의 동일한 메서드만 호출하므로 백엔드 차이를 신경 쓰지 않는다.
- 클라우드: SupabaseStore (core.db / core.usage 위임, RLS 적용)
- 로컬:     LocalStore (data/*.json, 외부 계정 없이 즉시 실행/데모 가능)
"""
import hashlib
import json
import secrets
import uuid
from pathlib import Path

from core import config, db, usage

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _load(name, default):
    p = DATA_DIR / name
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def _save(name, data):
    DATA_DIR.mkdir(exist_ok=True)
    (DATA_DIR / name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _hash_pw(pw: str, salt: str) -> str:
    return hashlib.sha256((salt + pw).encode()).hexdigest()


# ════════════════════════════════════════════════════════
#  로컬 백엔드
# ════════════════════════════════════════════════════════
class LocalStore:
    backend = "local"

    def __init__(self, user_id: str, email: str):
        self.user_id = user_id
        self.email = email

    # ── 인증 (인스턴스 생성 전 사용) ──
    @staticmethod
    def sign_up(email: str, pw: str):
        if not email or "@" not in email:
            return None, "유효한 이메일을 입력하세요."
        if len(pw) < 6:
            return None, "비밀번호는 6자 이상이어야 합니다."
        users = _load("users.json", {})
        if email in users:
            return None, "이미 가입된 이메일입니다."
        salt = secrets.token_hex(8)
        uid = str(uuid.uuid4())
        users[email] = {"id": uid, "email": email, "salt": salt, "pw": _hash_pw(pw, salt)}
        _save("users.json", users)
        return {"id": uid, "email": email}, None

    @staticmethod
    def sign_in(email: str, pw: str):
        users = _load("users.json", {})
        u = users.get(email)
        if not u or u["pw"] != _hash_pw(pw, u["salt"]):
            return None, "이메일 또는 비밀번호가 올바르지 않습니다."
        return {"id": u["id"], "email": email}, None

    # ── 프로필 ──
    def ensure_profile(self):
        profiles = _load("profiles.json", {})
        if self.user_id not in profiles:
            profiles[self.user_id] = {
                "id": self.user_id, "email": self.email,
                "tier": "free", "stripe_customer_id": None,
            }
            _save("profiles.json", profiles)
        return profiles[self.user_id]

    def get_profile(self):
        return _load("profiles.json", {}).get(self.user_id)

    def set_tier(self, tier: str):
        profiles = _load("profiles.json", {})
        if self.user_id in profiles:
            profiles[self.user_id]["tier"] = tier
            _save("profiles.json", profiles)

    # ── 사용량 ──
    def check_quota(self, tier: str):
        limit = config.tier_limit(tier)
        used = _load("usage.json", {}).get(f"{self.user_id}:{config.current_period()}", 0)
        if limit is None:
            return used < config.FAIR_USE_CAP, used, None
        return used < limit, used, limit

    def increment_usage(self):
        u = _load("usage.json", {})
        k = f"{self.user_id}:{config.current_period()}"
        u[k] = u.get(k, 0) + 1
        _save("usage.json", u)

    # ── 생성물 ──
    def save_generation(self, gen_type, language, input_params, output_text, model):
        gens = _load("generations.json", [])
        gens.append({
            "id": str(uuid.uuid4()), "user_id": self.user_id, "type": gen_type,
            "language": language, "input_params": input_params,
            "output_text": output_text, "model": model,
            "created_at": config.now_kst().isoformat(),
        })
        _save("generations.json", gens)

    def recent_generations(self, limit: int = 50):
        gens = [g for g in _load("generations.json", []) if g["user_id"] == self.user_id]
        gens.sort(key=lambda g: g["created_at"], reverse=True)
        return gens[:limit]

    # ── 워크스페이스 / 팀 ──
    def list_workspaces(self):
        wss = _load("workspaces.json", [])
        members = _load("workspace_members.json", [])
        my = {m["workspace_id"] for m in members if m["email"] == self.email}
        return [w for w in wss if w["owner_id"] == self.user_id or w["id"] in my]

    def create_workspace(self, name: str):
        wss = _load("workspaces.json", [])
        wid = str(uuid.uuid4())
        wss.append({"id": wid, "owner_id": self.user_id, "owner_email": self.email,
                    "name": name, "created_at": config.now_kst().isoformat()})
        _save("workspaces.json", wss)
        return wid

    def invite_member(self, ws_id: str, email: str):
        members = _load("workspace_members.json", [])
        if not any(m["workspace_id"] == ws_id and m["email"] == email for m in members):
            members.append({"workspace_id": ws_id, "email": email, "role": "member"})
            _save("workspace_members.json", members)

    def list_members(self, ws_id: str):
        ws = next((w for w in _load("workspaces.json", []) if w["id"] == ws_id), None)
        out = [{"email": ws["owner_email"], "role": "owner"}] if ws else []
        out += [{"email": m["email"], "role": m["role"]}
                for m in _load("workspace_members.json", []) if m["workspace_id"] == ws_id]
        return out

    def remove_member(self, ws_id: str, email: str):
        members = [m for m in _load("workspace_members.json", [])
                   if not (m["workspace_id"] == ws_id and m["email"] == email)]
        _save("workspace_members.json", members)

    # ── 브랜드 보이스 (개인 + 워크스페이스 공유) ──
    def list_brands(self):
        ws_ids = {w["id"] for w in self.list_workspaces()}
        out = []
        for b in _load("brands.json", []):
            wid = b.get("workspace_id")
            if wid is None and b["user_id"] == self.user_id:
                out.append(b)
            elif wid is not None and wid in ws_ids:
                out.append(b)
        return out

    def create_brand(self, data: dict, workspace_id: str | None = None):
        brands = _load("brands.json", [])
        brands.append({"id": str(uuid.uuid4()), "user_id": self.user_id,
                       "workspace_id": workspace_id,
                       "created_at": config.now_kst().isoformat(), **data})
        _save("brands.json", brands)

    def delete_brand(self, brand_id: str):
        brands = [b for b in _load("brands.json", []) if b["id"] != brand_id]
        _save("brands.json", brands)

    # ── 발행 연동 ──
    def list_integrations(self):
        return [i for i in _load("integrations.json", []) if i["user_id"] == self.user_id]

    def create_integration(self, type_: str, name: str, cfg: dict):
        items = _load("integrations.json", [])
        items.append({"id": str(uuid.uuid4()), "user_id": self.user_id,
                      "type": type_, "name": name, "config": cfg,
                      "created_at": config.now_kst().isoformat()})
        _save("integrations.json", items)

    def delete_integration(self, integration_id: str):
        items = [i for i in _load("integrations.json", []) if i["id"] != integration_id]
        _save("integrations.json", items)

    # ── API 키 ──
    def create_api_key(self, label: str) -> str:
        raw = "cf_" + secrets.token_urlsafe(32)
        keys = _load("api_keys.json", [])
        keys.append({
            "id": str(uuid.uuid4()), "user_id": self.user_id,
            "key_hash": hashlib.sha256(raw.encode()).hexdigest(),
            "label": label, "created_at": config.now_kst().isoformat(),
            "last_used_at": None, "revoked": False,
        })
        _save("api_keys.json", keys)
        return raw

    def list_api_keys(self):
        return [k for k in _load("api_keys.json", [])
                if k["user_id"] == self.user_id and not k["revoked"]]

    def revoke_api_key(self, key_id: str):
        keys = _load("api_keys.json", [])
        for k in keys:
            if k["id"] == key_id:
                k["revoked"] = True
        _save("api_keys.json", keys)


# ════════════════════════════════════════════════════════
#  클라우드 백엔드 (Supabase 위임)
# ════════════════════════════════════════════════════════
class SupabaseStore:
    backend = "cloud"

    def __init__(self, sb, user_id: str, email: str):
        self.sb = sb
        self.user_id = user_id
        self.email = email

    def ensure_profile(self):
        return db.ensure_profile(self.sb, self.user_id, self.email)

    def get_profile(self):
        return db.get_profile(self.sb, self.user_id)

    def set_tier(self, tier: str):
        db.set_tier(self.sb, self.user_id, tier)

    def check_quota(self, tier: str):
        return usage.check_quota(self.sb, self.user_id, tier)

    def increment_usage(self):
        usage.increment_usage(self.sb, self.user_id)

    def save_generation(self, gen_type, language, input_params, output_text, model):
        db.save_generation(self.sb, self.user_id, gen_type, language,
                           input_params, output_text, model)

    def recent_generations(self, limit: int = 50):
        return db.recent_generations(self.sb, self.user_id, limit)

    def list_workspaces(self):
        return db.list_workspaces(self.sb, self.user_id, self.email)

    def create_workspace(self, name: str):
        return db.create_workspace(self.sb, self.user_id, self.email, name)

    def invite_member(self, ws_id: str, email: str):
        db.invite_member(self.sb, ws_id, email)

    def list_members(self, ws_id: str):
        return db.list_members(self.sb, ws_id)

    def remove_member(self, ws_id: str, email: str):
        db.remove_member(self.sb, ws_id, email)

    def list_brands(self):
        ws_ids = [w["id"] for w in self.list_workspaces()]
        return db.list_brands(self.sb, self.user_id, ws_ids)

    def create_brand(self, data: dict, workspace_id: str | None = None):
        db.create_brand(self.sb, self.user_id, data, workspace_id)

    def delete_brand(self, brand_id: str):
        db.delete_brand(self.sb, brand_id)

    def list_integrations(self):
        return db.list_integrations(self.sb, self.user_id)

    def create_integration(self, type_: str, name: str, cfg: dict):
        db.create_integration(self.sb, self.user_id, type_, name, cfg)

    def delete_integration(self, integration_id: str):
        db.delete_integration(self.sb, integration_id)

    def create_api_key(self, label: str) -> str:
        return db.create_api_key(self.sb, self.user_id, label)

    def list_api_keys(self):
        return db.list_api_keys(self.sb, self.user_id)

    def revoke_api_key(self, key_id: str):
        db.revoke_api_key(self.sb, key_id)
