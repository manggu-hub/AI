"""대시보드: 사용량 미터 + 플랜 + 최근 생성물."""
import streamlit as st

from core import config, db, usage
from generators.base import GENERATORS


def show_dashboard(sb, profile):
    st.header("📊 대시보드")
    tier = profile["tier"]
    _ok, used, limit = usage.check_quota(sb, profile["id"], tier)

    c1, c2, c3 = st.columns(3)
    c1.metric("현재 플랜", config.TIER_LABELS.get(tier, tier))
    c2.metric("이번 달 생성", used)
    c3.metric("월 한도", "무제한" if limit is None else limit)

    if limit is not None:
        st.progress(min(used / limit, 1.0))
        if used >= limit:
            st.warning("한도를 모두 사용했습니다. **계정** 페이지에서 업그레이드하세요.")

    st.divider()
    st.subheader("최근 생성물")
    rows = db.recent_generations(sb, profile["id"], limit=5)
    if not rows:
        st.info("아직 생성한 콘텐츠가 없습니다. **콘텐츠 생성**에서 시작해보세요!")
        return
    for r in rows:
        spec = GENERATORS.get(r["type"])
        label = spec["label"] if spec else r["type"]
        with st.expander(f"{label} · {r['created_at'][:16].replace('T', ' ')}"):
            st.markdown(r["output_text"])
