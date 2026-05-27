"""생성 결과 아래에 붙는 발행/공유 UI 블록 (생성 페이지·이력 페이지 공용)."""
import streamlit as st

from core import publish


def publish_block(store, output: str, title: str, key: str):
    with st.expander("📤 발행 / 공유"):
        st.download_button("HTML 내보내기", publish.md_to_html(output),
                           file_name=f"{title or 'content'}.html", mime="text/html",
                           key=f"html_{key}")

        st.markdown("**공유 링크** (클릭 시 작성 화면이 열립니다)")
        cols = st.columns(3)
        for col, (name, url) in zip(cols, publish.share_links(output).items()):
            col.link_button(name, url, use_container_width=True)

        integrations = store.list_integrations()
        if not integrations:
            st.caption("⚙️ **연동** 페이지에서 WordPress/Webhook을 등록하면 여기서 바로 발행할 수 있습니다.")
            return

        st.markdown("**바로 발행**")
        names = {i["name"]: i for i in integrations}
        choice = st.selectbox("대상 연동", list(names.keys()), key=f"pubsel_{key}")
        it = names[choice]
        wp_status = "draft"
        if it["type"] == "wordpress":
            wp_status = st.radio("발행 상태", ["draft", "publish"], horizontal=True,
                                 format_func=lambda s: "임시저장" if s == "draft" else "바로 발행",
                                 key=f"wpst_{key}")
        if st.button("발행하기", key=f"pub_{key}", type="primary"):
            _do_publish(it, title, output, wp_status)


def _do_publish(it, title, output, wp_status):
    cfg = it["config"]
    try:
        if it["type"] == "wordpress":
            link = publish.to_wordpress(cfg["site_url"], cfg["username"], cfg["app_password"],
                                        title or "Untitled", output, status=wp_status)
            st.success(f"발행 완료: {link or '(링크 없음)'}")
        else:
            code = publish.to_webhook(cfg["url"], {"title": title, "content": output})
            st.success(f"Webhook 전송 완료 (HTTP {code})")
    except Exception as e:
        st.error(f"발행 실패: {e}")
