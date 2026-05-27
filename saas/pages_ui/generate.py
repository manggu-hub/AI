"""생성 페이지: 생성기 선택 → 동적 폼 → 쿼터 체크 → 결과."""
import streamlit as st

from core import gemini
from generators.base import groups


def show_generate(store, profile):
    st.header("✍️ 콘텐츠 생성")
    tier = profile["tier"]
    ok, used, limit = store.check_quota(tier)

    if limit is not None:
        st.caption(f"이번 달 사용량: {used} / {limit}")
    else:
        st.caption(f"이번 달 사용량: {used} (무제한)")

    grouped = groups()
    col1, col2 = st.columns(2)
    with col1:
        group = st.selectbox("카테고리", list(grouped.keys()))
    with col2:
        spec = st.selectbox(
            "생성기", grouped[group],
            format_func=lambda s: s["label"],
        )
    language = st.radio("출력 언어", ["ko", "en"],
                        format_func=lambda x: "한국어" if x == "ko" else "English",
                        horizontal=True)

    with st.form("gen_form"):
        params = {}
        for f in spec["fields"]:
            label = f["label"] + (" *" if f.get("required") else "")
            if f["type"] == "textarea":
                params[f["name"]] = st.text_area(label, placeholder=f.get("placeholder", ""))
            elif f["type"] == "select":
                params[f["name"]] = st.selectbox(label, f["options"])
            else:
                params[f["name"]] = st.text_input(label, placeholder=f.get("placeholder", ""))
        submitted = st.form_submit_button("생성하기", type="primary", use_container_width=True)

    if submitted:
        missing = [f["label"] for f in spec["fields"]
                   if f.get("required") and not params.get(f["name"], "").strip()]
        if missing:
            st.error(f"필수 항목을 입력해주세요: {', '.join(missing)}")
            return
        if not ok:
            st.warning(f"이번 달 무료 생성 {limit}회를 모두 사용했습니다. "
                       "**계정** 페이지에서 업그레이드하면 더 많이 생성할 수 있어요.")
            return

        with st.spinner("AI가 콘텐츠를 작성 중입니다..."):
            try:
                system = spec["system"](language)
                prompt = spec["prompt"](params, language)
                output, model = gemini.generate(system, prompt, paid=(tier != "free"))
            except Exception as e:
                st.error(f"생성 중 오류가 발생했습니다: {e}")
                return
            store.increment_usage()
            store.save_generation(spec["key"], language, params, output, model)

        st.success("완성됐습니다!")
        st.markdown(output)
        st.download_button("📥 텍스트 다운로드", output,
                           file_name=f"{spec['key']}.md", mime="text/markdown")
        with st.expander("원문 복사용 (코드 블록)"):
            st.code(output, language=None)
