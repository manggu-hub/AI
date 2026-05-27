"""발행 연동 관리: WordPress / Webhook."""
import streamlit as st


def show_integrations(store, profile):
    st.header("🔌 발행 연동")
    st.caption("연동을 등록하면 생성 결과를 워드프레스에 바로 발행하거나, "
               "Webhook으로 Zapier·Make에 보내 LinkedIn·X·Slack 등 어디로든 자동 게시할 수 있습니다.")

    tab_wp, tab_hook = st.tabs(["WordPress", "Webhook"])

    with tab_wp:
        st.markdown("WordPress 관리자 → 사용자 → **애플리케이션 비밀번호**를 발급해 입력하세요.")
        with st.form("wp_form"):
            name = st.text_input("연동 이름", placeholder="예: 회사 블로그")
            site = st.text_input("사이트 URL", placeholder="https://example.com")
            user = st.text_input("사용자명")
            pw = st.text_input("애플리케이션 비밀번호", type="password")
            if st.form_submit_button("WordPress 연동 추가", type="primary"):
                if not (name and site and user and pw):
                    st.error("모든 항목을 입력하세요.")
                else:
                    store.create_integration("wordpress", name,
                                             {"site_url": site, "username": user, "app_password": pw})
                    st.success("추가됐습니다.")
                    st.rerun()

    with tab_hook:
        st.markdown("Zapier/Make의 'Webhook' 트리거 URL을 붙여넣으면, 생성 결과가 JSON으로 전송됩니다.")
        with st.form("hook_form"):
            name = st.text_input("연동 이름 ", placeholder="예: Zapier → LinkedIn")
            url = st.text_input("Webhook URL", placeholder="https://hooks.zapier.com/...")
            if st.form_submit_button("Webhook 연동 추가", type="primary"):
                if not (name and url):
                    st.error("모든 항목을 입력하세요.")
                else:
                    store.create_integration("webhook", name, {"url": url})
                    st.success("추가됐습니다.")
                    st.rerun()

    st.divider()
    st.subheader("등록된 연동")
    items = store.list_integrations()
    if not items:
        st.info("아직 등록된 연동이 없습니다.")
        return
    for it in items:
        col1, col2 = st.columns([4, 1])
        target = it["config"].get("site_url") or it["config"].get("url", "")
        col1.write(f"**{it['name']}** · `{it['type']}` · {target}")
        if col2.button("삭제", key=f"delint_{it['id']}"):
            store.delete_integration(it["id"])
            st.rerun()
