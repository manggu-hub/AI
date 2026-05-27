"""팀/워크스페이스: 생성 후 멤버를 초대하면 브랜드 보이스를 공유한다."""
import streamlit as st


def show_team(store, profile):
    st.header("👥 팀 / 워크스페이스")
    st.caption("워크스페이스를 만들고 팀원 이메일을 초대하면, 워크스페이스에 저장한 "
               "브랜드 보이스를 팀원이 함께 사용할 수 있습니다.")

    with st.expander("➕ 새 워크스페이스 만들기"):
        with st.form("ws_form"):
            name = st.text_input("워크스페이스 이름", placeholder="예: 마케팅팀")
            if st.form_submit_button("생성", type="primary"):
                if not name.strip():
                    st.error("이름을 입력하세요.")
                else:
                    store.create_workspace(name)
                    st.success("생성됐습니다.")
                    st.rerun()

    workspaces = store.list_workspaces()
    if not workspaces:
        st.info("아직 워크스페이스가 없습니다.")
        return

    st.subheader("내 워크스페이스")
    for w in workspaces:
        is_owner = w["owner_id"] == profile["id"]
        with st.expander(f"👥 {w['name']}" + (" (소유자)" if is_owner else " (멤버)")):
            members = store.list_members(w["id"])
            st.write("**멤버**")
            for m in members:
                col1, col2 = st.columns([4, 1])
                col1.write(f"- {m['email']} · {m['role']}")
                if is_owner and m["role"] != "owner":
                    if col2.button("제외", key=f"rm_{w['id']}_{m['email']}"):
                        store.remove_member(w["id"], m["email"])
                        st.rerun()
            if is_owner:
                with st.form(f"invite_{w['id']}"):
                    email = st.text_input("초대할 이메일", key=f"inv_{w['id']}")
                    if st.form_submit_button("초대"):
                        if email and "@" in email:
                            store.invite_member(w["id"], email)
                            st.success(f"{email} 초대됨")
                            st.rerun()
                        else:
                            st.error("유효한 이메일을 입력하세요.")
