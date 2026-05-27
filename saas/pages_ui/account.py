"""계정: 플랜 업그레이드(Checkout), 결제 관리(Portal), API 키(Business)."""
import streamlit as st

from core import billing, config, db


def show_account(sb, profile):
    st.header("👤 계정")
    tier = profile["tier"]
    st.write(f"**이메일:** {profile['email']}")
    st.write(f"**현재 플랜:** {config.TIER_LABELS.get(tier, tier)}")

    st.divider()
    st.subheader("플랜 업그레이드")
    if tier == "free":
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Pro** — $15/월\n\n월 100회 생성, 고품질 모델")
            if st.button("Pro로 업그레이드", use_container_width=True):
                _checkout(sb, profile, "pro")
        with c2:
            st.markdown("**Business** — $30/월\n\n무제한 생성 + API 접근")
            if st.button("Business로 업그레이드", use_container_width=True):
                _checkout(sb, profile, "business")
    else:
        st.success(f"{config.TIER_LABELS[tier]} 플랜을 이용 중입니다.")
        if st.button("결제 관리 / 플랜 변경 (Stripe)"):
            url = billing.create_portal_url(sb, profile["id"])
            if url:
                st.link_button("Stripe 고객 포털 열기", url)
            else:
                st.error("결제 정보를 찾을 수 없습니다.")

    if tier == "business":
        st.divider()
        _api_keys_section(sb, profile)


def _checkout(sb, profile, tier):
    try:
        url = billing.create_checkout_url(sb, profile["id"], profile["email"], tier)
        st.link_button(f"{tier.capitalize()} 결제 페이지로 이동", url)
    except Exception as e:
        st.error(f"결제 세션 생성 실패: {e}")


def _api_keys_section(sb, profile):
    st.subheader("🔑 API 키 (Business)")
    st.caption("발급된 키는 생성 직후 한 번만 표시됩니다. 안전한 곳에 저장하세요.")

    label = st.text_input("키 이름", placeholder="예: 프로덕션 서버")
    if st.button("새 API 키 발급"):
        raw = db.create_api_key(sb, profile["id"], label or "untitled")
        st.code(raw, language=None)
        st.warning("지금 복사하세요 — 다시 표시되지 않습니다.")

    keys = db.list_api_keys(sb, profile["id"])
    for k in keys:
        col1, col2 = st.columns([4, 1])
        last = k["last_used_at"][:16].replace("T", " ") if k["last_used_at"] else "미사용"
        col1.write(f"**{k['label']}** · 생성 {k['created_at'][:10]} · 마지막 사용 {last}")
        if col2.button("폐기", key=f"rev_{k['id']}"):
            db.revoke_api_key(sb, k["id"])
            st.rerun()
