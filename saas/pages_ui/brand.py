"""브랜드 보이스 관리: 회사 톤/대상/예시를 저장해 모든 생성에 일관 적용."""
import streamlit as st


def show_brand(store, profile):
    st.header("🎨 브랜드 보이스")
    st.caption("브랜드를 저장해두면 콘텐츠 생성 시 톤·대상·문체를 일관되게 적용합니다. "
               "이게 범용 AI와 다른 핵심 차별점입니다.")

    with st.expander("➕ 새 브랜드 추가", expanded=False):
        with st.form("brand_form"):
            name = st.text_input("브랜드 이름 *", placeholder="예: 우리 회사 공식 보이스")
            company = st.text_input("회사 / 제품", placeholder="예: ContentForge")
            tone = st.text_input("톤앤매너", placeholder="예: 전문적이지만 친근하고, 군더더기 없는")
            audience = st.text_input("핵심 독자", placeholder="예: 초기 스타트업 창업자와 마케터")
            sample = st.text_area("참고 문체 예시", placeholder="우리 브랜드다운 글 한두 문단을 붙여넣으세요. 스타일을 모방합니다.")
            avoid = st.text_input("피해야 할 표현 / 금칙어", placeholder="예: 과장된 수식어, 느낌표 남발")
            if st.form_submit_button("저장", type="primary"):
                if not name.strip():
                    st.error("브랜드 이름은 필수입니다.")
                else:
                    store.create_brand({
                        "name": name, "company": company, "tone": tone,
                        "audience": audience, "sample": sample, "avoid": avoid,
                    })
                    st.success("저장됐습니다.")
                    st.rerun()

    brands = store.list_brands()
    if not brands:
        st.info("아직 등록된 브랜드가 없습니다. 위에서 하나 추가해보세요.")
        return

    st.subheader("등록된 브랜드")
    for b in brands:
        with st.expander(f"🎨 {b['name']}"):
            if b.get("company"):
                st.write(f"**회사/제품:** {b['company']}")
            if b.get("tone"):
                st.write(f"**톤:** {b['tone']}")
            if b.get("audience"):
                st.write(f"**독자:** {b['audience']}")
            if b.get("sample"):
                st.write(f"**문체 예시:** {b['sample']}")
            if b.get("avoid"):
                st.write(f"**금칙:** {b['avoid']}")
            if st.button("삭제", key=f"del_{b['id']}"):
                store.delete_brand(b["id"])
                st.rerun()
