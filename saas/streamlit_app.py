"""ContentForge — AI 콘텐츠 생성 SaaS (Streamlit 진입점).

실행: streamlit run streamlit_app.py
"""
import streamlit as st

from core import auth, config, db

st.set_page_config(page_title="ContentForge", page_icon="✍️", layout="centered")


@st.cache_resource
def _client_for(access_token: str, refresh_token: str):
    """유저 토큰으로 인증된 Supabase 클라이언트 (RLS 적용). 토큰별 캐시."""
    from supabase import create_client
    sb = create_client(config.SUPABASE_URL, config.SUPABASE_ANON_KEY)
    sb.auth.set_session(access_token, refresh_token)
    return sb


def _login_gate():
    st.title("✍️ ContentForge")
    st.caption("스타트업·프리랜서를 위한 AI 콘텐츠 생성 도구")
    tab_login, tab_signup = st.tabs(["로그인", "회원가입"])

    with tab_login:
        with st.form("login"):
            email = st.text_input("이메일")
            pw = st.text_input("비밀번호", type="password")
            if st.form_submit_button("로그인", type="primary", use_container_width=True):
                try:
                    res = auth.sign_in(email, pw)
                except Exception as e:
                    st.error(f"로그인 실패: {e}")
                    return
                if res.session:
                    st.session_state.access_token = res.session.access_token
                    st.session_state.refresh_token = res.session.refresh_token
                    st.session_state.user_id = res.user.id
                    st.session_state.email = res.user.email
                    st.rerun()
                else:
                    st.error("로그인에 실패했습니다. 이메일 인증이 필요할 수 있습니다.")

    with tab_signup:
        with st.form("signup"):
            email = st.text_input("이메일 ")
            pw = st.text_input("비밀번호 (6자 이상)", type="password")
            if st.form_submit_button("가입하기", use_container_width=True):
                try:
                    res = auth.sign_up(email, pw)
                except Exception as e:
                    st.error(f"가입 실패: {e}")
                    return
                if res.session:
                    st.session_state.access_token = res.session.access_token
                    st.session_state.refresh_token = res.session.refresh_token
                    st.session_state.user_id = res.user.id
                    st.session_state.email = res.user.email
                    st.rerun()
                else:
                    st.success("가입 완료! 이메일 인증 후 로그인해주세요.")


def _app():
    sb = _client_for(st.session_state.access_token, st.session_state.refresh_token)
    profile = db.ensure_profile(sb, st.session_state.user_id, st.session_state.email)

    with st.sidebar:
        st.title("✍️ ContentForge")
        st.caption(st.session_state.email)
        page = st.radio("메뉴", ["대시보드", "콘텐츠 생성", "생성 이력", "계정"])
        st.divider()
        if st.button("로그아웃"):
            auth.sign_out()
            for k in ("access_token", "refresh_token", "user_id", "email"):
                st.session_state.pop(k, None)
            st.rerun()

    if page == "대시보드":
        from pages_ui.dashboard import show_dashboard
        show_dashboard(sb, profile)
    elif page == "콘텐츠 생성":
        from pages_ui.generate import show_generate
        show_generate(sb, profile)
    elif page == "생성 이력":
        from pages_ui.history import show_history
        show_history(sb, profile)
    elif page == "계정":
        from pages_ui.account import show_account
        show_account(sb, profile)


if "access_token" not in st.session_state:
    _login_gate()
else:
    _app()
