"""ContentForge — AI 콘텐츠 생성 SaaS (Streamlit 진입점).

실행: streamlit run streamlit_app.py

Supabase 자격증명이 있으면 클라우드 모드(멀티유저 + RLS),
없으면 로컬 모드(data/*.json)로 외부 계정 없이 즉시 동작한다.
"""
import streamlit as st

from core import config
from core.store import LocalStore, SupabaseStore

st.set_page_config(page_title="수주AI", page_icon="🎯", layout="centered")


@st.cache_resource
def _client_for(access_token: str, refresh_token: str):
    """유저 토큰으로 인증된 Supabase 클라이언트 (RLS 적용). 토큰별 캐시."""
    from supabase import create_client
    sb = create_client(config.SUPABASE_URL, config.SUPABASE_ANON_KEY)
    sb.auth.set_session(access_token, refresh_token)
    return sb


def _get_store():
    if config.has_supabase():
        sb = _client_for(st.session_state.access_token, st.session_state.refresh_token)
        return SupabaseStore(sb, st.session_state.user_id, st.session_state.email)
    return LocalStore(st.session_state.user_id, st.session_state.email)


def _set_session(user_id, email, access=None, refresh=None):
    st.session_state.user_id = user_id
    st.session_state.email = email
    if access:
        st.session_state.access_token = access
        st.session_state.refresh_token = refresh


def _login_gate():
    cloud = config.has_supabase()
    st.title("🎯 수주AI")
    st.caption("프리랜서 수주율을 높이는 AI 콘텐츠 도구")
    if not cloud:
        st.info("🔧 로컬 모드로 실행 중입니다 (Supabase 미설정). "
                "계정과 데이터는 이 컴퓨터에만 저장됩니다.")

    tab_login, tab_signup = st.tabs(["로그인", "회원가입"])

    with tab_login:
        with st.form("login"):
            email = st.text_input("이메일")
            pw = st.text_input("비밀번호", type="password")
            if st.form_submit_button("로그인", type="primary", use_container_width=True):
                _do_login(cloud, email, pw)

    with tab_signup:
        with st.form("signup"):
            email = st.text_input("이메일 ")
            pw = st.text_input("비밀번호 (6자 이상)", type="password")
            if st.form_submit_button("가입하기", use_container_width=True):
                _do_signup(cloud, email, pw)


def _do_login(cloud, email, pw):
    if cloud:
        from core import auth
        try:
            res = auth.sign_in(email, pw)
        except Exception as e:
            st.error(f"로그인 실패: {e}")
            return
        if res.session:
            _set_session(res.user.id, res.user.email,
                         res.session.access_token, res.session.refresh_token)
            st.rerun()
        else:
            st.error("로그인 실패. 이메일 인증이 필요할 수 있습니다.")
    else:
        user, err = LocalStore.sign_in(email, pw)
        if err:
            st.error(err)
        else:
            _set_session(user["id"], user["email"])
            st.rerun()


def _do_signup(cloud, email, pw):
    if cloud:
        from core import auth
        try:
            res = auth.sign_up(email, pw)
        except Exception as e:
            st.error(f"가입 실패: {e}")
            return
        if res.session:
            _set_session(res.user.id, res.user.email,
                         res.session.access_token, res.session.refresh_token)
            st.rerun()
        else:
            st.success("가입 완료! 이메일 인증 후 로그인해주세요.")
    else:
        user, err = LocalStore.sign_up(email, pw)
        if err:
            st.error(err)
        else:
            _set_session(user["id"], user["email"])
            st.rerun()


def _logout():
    if config.has_supabase():
        from core import auth
        auth.sign_out()
    for k in ("access_token", "refresh_token", "user_id", "email"):
        st.session_state.pop(k, None)
    st.rerun()


def _app():
    store = _get_store()
    profile = store.ensure_profile()

    with st.sidebar:
        st.title("🎯 수주AI")
        st.caption(st.session_state.email)
        page = st.radio("메뉴", ["대시보드", "콘텐츠 생성", "브랜드 보이스", "팀",
                                 "생성 이력", "연동", "계정"])
        st.divider()
        legal = st.radio("문서", ["—", "이용약관", "개인정보처리방침"], label_visibility="collapsed")
        st.divider()
        if st.button("로그아웃"):
            _logout()

    if legal == "이용약관":
        from pages_ui.legal import show_terms
        show_terms()
        return
    if legal == "개인정보처리방침":
        from pages_ui.legal import show_privacy
        show_privacy()
        return

    if page == "대시보드":
        from pages_ui.dashboard import show_dashboard
        show_dashboard(store, profile)
    elif page == "콘텐츠 생성":
        from pages_ui.generate import show_generate
        show_generate(store, profile)
    elif page == "브랜드 보이스":
        from pages_ui.brand import show_brand
        show_brand(store, profile)
    elif page == "팀":
        from pages_ui.team import show_team
        show_team(store, profile)
    elif page == "생성 이력":
        from pages_ui.history import show_history
        show_history(store, profile)
    elif page == "연동":
        from pages_ui.integrations import show_integrations
        show_integrations(store, profile)
    elif page == "계정":
        from pages_ui.account import show_account
        show_account(store, profile)


if "user_id" not in st.session_state:
    _login_gate()
else:
    _app()
