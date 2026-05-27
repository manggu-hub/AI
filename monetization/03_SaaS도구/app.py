"""
AI 마케팅 카피 생성기 (SaaS MVP)
- 기존 app.py와 동일한 스택(Streamlit + google-genai) 사용 → 같은 방식으로 바로 실행 가능
- 실행:  streamlit run app.py
- 환경변수 GEMINI_API_KEY 필요 (기존 앱과 동일한 키 사용 가능)

이 도구는 3가지로 돈이 됩니다.
  1) 내가 직접 써서 프리랜싱(1번) 작업 속도를 5배로 → 시간당 단가 상승
  2) 전자책(2번) 부록 "바로 쓰는 도구"로 끼워 판매
  3) 남에게 월정액으로 공개 판매(아래 '수익화 가이드' 참고)
"""
import os
import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai import errors as genai_errors
import time as time_module

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

st.set_page_config(page_title="AI 마케팅 카피 생성기", page_icon="✍️", layout="centered")

# ── 카피 유형별 프롬프트 정의 ─────────────────────────────
COPY_TYPES = {
    "상세페이지 카피": {
        "icon": "🛒",
        "system": (
            "너는 매출을 올리는 한국어 세일즈 카피라이터다. "
            "스마트스토어/쿠팡 상세페이지용 카피를 작성한다. "
            "구조: ①시선을 끄는 헤드라인 ②고객의 문제 공감 ③해결과 베네핏(스펙을 '변화'로 번역) "
            "④신뢰 요소 ⑤구매를 부르는 CTA. 과장·허위·의학적 효능 단정은 절대 금지. "
            "자연스럽고 읽기 쉬운 한국어로, 마크다운으로 보기 좋게 정리해라."
        ),
        "fields": ["상품명", "타겟 고객", "핵심 강점(쉼표로 구분)", "가격대", "원하는 톤"],
    },
    "블로그 포스팅(SEO)": {
        "icon": "📝",
        "system": (
            "너는 네이버/티스토리 검색 상위노출에 강한 한국어 블로그 작가다. "
            "주어진 키워드를 제목과 본문에 자연스럽게 녹이되 키워드 남용은 피한다. "
            "구조: 흥미로운 도입 → 소제목으로 나눈 본문(정보 가치 높게) → 정리. "
            "1,200~1,800자, 읽는 사람에게 실질적 도움이 되도록 작성. 마크다운 사용."
        ),
        "fields": ["주제", "타겟 키워드", "타겟 독자", "원하는 톤"],
    },
    "인스타/SNS 캡션": {
        "icon": "📸",
        "system": (
            "너는 인스타그램/스레드 캡션 전문 카피라이터다. "
            "첫 줄에서 시선을 잡고, 짧은 문장으로 끊어 가독성을 높이며, "
            "행동 유도(저장/DM/링크)를 자연스럽게 넣는다. "
            "마지막에 관련 해시태그 8~12개를 제안한다. 이모지는 적절히만."
        ),
        "fields": ["홍보 대상", "핵심 메시지/혜택", "타겟 고객", "원하는 톤"],
    },
    "광고 문구(A/B)": {
        "icon": "📢",
        "system": (
            "너는 퍼포먼스 광고 카피라이터다. "
            "짧고 강력한 광고 문구를 서로 다른 각도로 5개(A/B 테스트용) 제안한다. "
            "각 문구마다 어떤 심리(공포/이득/호기심/긴급성 등)를 노렸는지 한 줄 설명을 붙인다. "
            "과장·허위 표현은 금지."
        ),
        "fields": ["상품/서비스", "핵심 베네핏", "타겟 고객", "프로모션(있다면)"],
    },
}


def generate_copy(system_instruction: str, user_prompt: str) -> str:
    """기존 app.py와 동일한 호출 패턴 (gemini-2.5-flash → flash-lite 폴백)."""
    if not API_KEY:
        return "⚠️ GEMINI_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요."
    client = genai.Client(api_key=API_KEY)
    config = types.GenerateContentConfig(system_instruction=system_instruction)
    contents = [{"role": "user", "parts": [{"text": user_prompt}]}]
    last_error = None
    for model in ("gemini-2.5-flash", "gemini-2.5-flash-lite"):
        for _ in range(2):
            try:
                resp = client.models.generate_content(
                    model=model, contents=contents, config=config
                )
                return resp.text or "결과가 비어 있습니다. 입력을 더 구체적으로 적어보세요."
            except genai_errors.ServerError as e:
                last_error = e
                time_module.sleep(1.5)
            except Exception as e:
                return f"오류가 발생했습니다: {e}"
    return f"서버가 혼잡합니다. 잠시 후 다시 시도해주세요. ({last_error})"


# ── UI ────────────────────────────────────────────────────
st.title("✍️ AI 마케팅 카피 생성기")
st.caption("상품 정보만 넣으면 팔리는 카피가 나옵니다. 결과는 항상 직접 검수 후 사용하세요.")

with st.sidebar:
    st.header("무엇을 만들까요?")
    selected = st.radio(
        "카피 유형",
        list(COPY_TYPES.keys()),
        format_func=lambda k: f"{COPY_TYPES[k]['icon']} {k}",
    )
    st.divider()
    st.markdown(
        "**수익화 팁**\n\n"
        "- 직접 써서 크몽 작업 속도 ↑\n"
        "- 결과를 검수해 납품\n"
        "- 도구 자체를 월정액 판매\n\n"
        "자세한 건 `배포_및_수익화_가이드.md`"
    )

spec = COPY_TYPES[selected]
st.subheader(f"{spec['icon']} {selected}")

# 입력 폼
inputs = {}
with st.form("copy_form"):
    for field in spec["fields"]:
        if "강점" in field or "메시지" in field or "베네핏" in field:
            inputs[field] = st.text_area(field, height=80)
        else:
            inputs[field] = st.text_input(field)
    submitted = st.form_submit_button("✨ 카피 생성하기", use_container_width=True)

if submitted:
    if not any(v.strip() for v in inputs.values()):
        st.warning("최소한 한 개 이상의 항목을 입력해주세요.")
    else:
        prompt = "다음 정보를 바탕으로 작성해줘.\n" + "\n".join(
            f"- {k}: {v}" for k, v in inputs.items() if v.strip()
        )
        with st.spinner("카피를 작성하는 중..."):
            result = generate_copy(spec["system"], prompt)
        st.success("완성! 아래 결과를 검수 후 사용하세요.")
        st.markdown(result)
        st.download_button(
            "📥 텍스트로 저장",
            data=result,
            file_name=f"{selected}_카피.txt",
            mime="text/plain",
            use_container_width=True,
        )

st.divider()
st.caption(
    "⚠️ 생성된 문구는 초안입니다. 허위·과장 광고는 표시광고법 위반이 될 수 있으니 "
    "사실 여부를 반드시 확인하고 수정해 사용하세요."
)
