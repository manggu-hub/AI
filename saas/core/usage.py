"""사용량 추적 + 쿼터 (usage_counters: 유저×월 1행, select-then-upsert)."""
from core import config


def get_usage(sb, user_id: str) -> int:
    period = config.current_period()
    r = (sb.table("usage_counters").select("count")
         .eq("user_id", user_id).eq("period", period).execute())
    return r.data[0]["count"] if r.data else 0


def check_quota(sb, user_id: str, tier: str) -> tuple[bool, int, int | None]:
    """(허용 여부, 현재 사용량, 한도) 반환. 한도 None = 무제한."""
    limit = config.tier_limit(tier)
    used = get_usage(sb, user_id)
    if limit is None:
        return True, used, None
    return used < limit, used, limit


def increment_usage(sb, user_id: str):
    period = config.current_period()
    r = (sb.table("usage_counters").select("id,count")
         .eq("user_id", user_id).eq("period", period).execute())
    if r.data:
        row = r.data[0]
        sb.table("usage_counters").update(
            {"count": row["count"] + 1}
        ).eq("id", row["id"]).execute()
    else:
        sb.table("usage_counters").insert(
            {"user_id": user_id, "period": period, "count": 1}
        ).execute()
