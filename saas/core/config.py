"""환경변수 로딩 + 요금제/모델 설정 (app.py:36-37 패턴 재사용)."""
import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

# ── 시크릿
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_PRO = os.getenv("STRIPE_PRICE_PRO", "")
STRIPE_PRICE_BUSINESS = os.getenv("STRIPE_PRICE_BUSINESS", "")
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8501")

# ── 요금제: 월 생성 한도 (None = 무제한)
TIER_LIMITS = {
    "free": 10,
    "pro": 100,
    "business": None,
}

# 무제한(Business) 공정사용 상한 — 폭주로 인한 API 비용/마진 손실 방지.
# 한도 자체는 "무제한"으로 표시하되, 이 선을 넘으면 차단하고 문의 안내.
FAIR_USE_CAP = 2000

TIER_LABELS = {
    "free": "Free",
    "pro": "Pro ($15/mo)",
    "business": "Business ($30/mo)",
}

# ── Stripe price ID → tier 매핑
PRICE_TO_TIER = {
    STRIPE_PRICE_PRO: "pro",
    STRIPE_PRICE_BUSINESS: "business",
}

# ── Gemini 모델 (유료=flash 우선, 무료=flash-lite 우선)
MODELS_PAID = ("gemini-2.5-flash", "gemini-2.5-flash-lite")
MODELS_FREE = ("gemini-2.5-flash-lite", "gemini-2.5-flash")

# ── 한국 표준시 (app.py:56-64 재사용)
KST = timezone(timedelta(hours=9))


def now_kst() -> datetime:
    return datetime.now(KST).replace(tzinfo=None)


def current_period() -> str:
    """쿼터 집계용 'YYYY-MM' (KST 기준). 새 달이면 자동으로 카운터 리셋됨."""
    return now_kst().strftime("%Y-%m")


def tier_limit(tier: str) -> int | None:
    return TIER_LIMITS.get(tier, TIER_LIMITS["free"])


def has_supabase() -> bool:
    """Supabase 자격증명이 있으면 클라우드 모드, 없으면 로컬 모드."""
    return bool(SUPABASE_URL and SUPABASE_ANON_KEY)


def has_stripe() -> bool:
    return bool(STRIPE_SECRET_KEY and STRIPE_PRICE_PRO)
