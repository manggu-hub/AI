"""생성 이력: 타입/언어 필터."""
import streamlit as st

from generators.base import GENERATORS


def show_history(store, profile):
    st.header("📚 생성 이력")
    rows = store.recent_generations(limit=200)
    if not rows:
        st.info("아직 생성한 콘텐츠가 없습니다.")
        return

    types_present = sorted({r["type"] for r in rows})
    c1, c2 = st.columns(2)
    with c1:
        type_filter = st.selectbox(
            "유형", ["전체"] + types_present,
            format_func=lambda t: "전체" if t == "전체"
            else (GENERATORS.get(t, {}).get("label", t)),
        )
    with c2:
        lang_filter = st.selectbox("언어", ["전체", "ko", "en"])

    for r in rows:
        if type_filter != "전체" and r["type"] != type_filter:
            continue
        if lang_filter != "전체" and r["language"] != lang_filter:
            continue
        spec = GENERATORS.get(r["type"])
        label = spec["label"] if spec else r["type"]
        with st.expander(f"{label} · {r['language']} · {r['created_at'][:16].replace('T', ' ')}"):
            st.markdown(r["output_text"])
            st.download_button("📥 다운로드", r["output_text"],
                               file_name=f"{r['type']}_{r['id'][:8]}.md",
                               mime="text/markdown", key=f"dl_{r['id']}")
