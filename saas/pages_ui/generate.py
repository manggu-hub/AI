"""생성 페이지: 생성기 선택 → (브랜드 보이스) → 폼 → 결과 → 재생성/변형/수정."""
import streamlit as st

from core import gemini
from generators.base import groups, refine_system, variations_note, with_brand


def _run(store, tier, spec, params, lang, brand, *, variations=False, refine_from=None, instruction=None):
    """1회 Gemini 호출 = 1회 사용량. 결과를 session_state에 저장."""
    ok, used, limit = store.check_quota(tier)
    if not ok:
        st.warning("이번 달 한도를 모두 사용했습니다. **계정** 페이지에서 업그레이드하세요.")
        return
    with st.spinner("AI가 작성 중입니다..."):
        try:
            if refine_from is not None:
                system = with_brand(refine_system(lang), brand)
                prompt = f"[원본 초안]\n{refine_from}\n\n[수정 요청]\n{instruction}"
            else:
                system = with_brand(spec["system"](lang), brand)
                prompt = spec["prompt"](params, lang)
                if variations:
                    system += variations_note(3)
            output, model = gemini.generate(system, prompt, paid=(tier != "free"))
        except Exception as e:
            st.error(f"생성 중 오류: {e}")
            return
        store.increment_usage()
        store.save_generation(spec["key"], lang, params, output, model)
    st.session_state.last_gen = {
        "spec_key": spec["key"], "params": params, "lang": lang,
        "brand_id": brand["id"] if brand else None, "output": output, "model": model,
    }


def show_generate(store, profile):
    st.header("✍️ 콘텐츠 생성")
    tier = profile["tier"]
    ok, used, limit = store.check_quota(tier)
    st.caption(f"이번 달 사용량: {used}" + (f" / {limit}" if limit is not None else " (무제한 · 공정사용)"))

    grouped = groups()
    col1, col2 = st.columns(2)
    with col1:
        group = st.selectbox("카테고리", list(grouped.keys()))
    with col2:
        spec = st.selectbox("생성기", grouped[group], format_func=lambda s: s["label"])

    c3, c4 = st.columns(2)
    with c3:
        language = st.radio("출력 언어", ["ko", "en"],
                            format_func=lambda x: "한국어" if x == "ko" else "English",
                            horizontal=True)
    with c4:
        brands = store.list_brands()
        brand_map = {b["name"]: b for b in brands}
        brand_name = st.selectbox("브랜드 보이스 (선택)", ["없음"] + list(brand_map.keys()))
    brand = brand_map.get(brand_name)

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
        cgen, cvar = st.columns(2)
        submitted = cgen.form_submit_button("생성하기", type="primary", use_container_width=True)
        variations = cvar.form_submit_button("변형 3개 생성", use_container_width=True)

    if submitted or variations:
        missing = [f["label"] for f in spec["fields"]
                   if f.get("required") and not params.get(f["name"], "").strip()]
        if missing:
            st.error(f"필수 항목을 입력해주세요: {', '.join(missing)}")
        else:
            _run(store, tier, spec, params, language, brand, variations=variations)

    _render_result(store, tier)


def _render_result(store, tier):
    lg = st.session_state.get("last_gen")
    if not lg:
        return
    from generators.base import GENERATORS
    spec = GENERATORS[lg["spec_key"]]
    brand = next((b for b in store.list_brands() if b["id"] == lg["brand_id"]), None)

    st.divider()
    st.success("완성됐습니다!")
    st.markdown(lg["output"])
    st.download_button("📥 다운로드", lg["output"], file_name=f"{lg['spec_key']}.md",
                       mime="text/markdown")

    st.divider()
    cols = st.columns(2)
    if cols[0].button("🔄 다시 생성", use_container_width=True):
        _run(store, tier, spec, lg["params"], lg["lang"], brand)
        st.rerun()
    if cols[1].button("✨ 변형 3개", use_container_width=True):
        _run(store, tier, spec, lg["params"], lg["lang"], brand, variations=True)
        st.rerun()

    with st.form("refine_form"):
        instruction = st.text_input("✏️ 수정 요청",
                                    placeholder="예: 더 짧게, 수치를 강조해서, 더 캐주얼하게")
        if st.form_submit_button("수정 반영") and instruction.strip():
            _run(store, tier, spec, lg["params"], lg["lang"], brand,
                 refine_from=lg["output"], instruction=instruction)
            st.rerun()
