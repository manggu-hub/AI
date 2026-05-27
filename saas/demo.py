"""로그인·DB 없이 생성 품질만 빠르게 확인하는 CLI 데모.

사용법:
    GEMINI_API_KEY=... python demo.py            # 대표 생성기 3종 샘플
    GEMINI_API_KEY=... python demo.py blog_seo   # 특정 생성기만
    python demo.py --list                        # 생성기 목록
"""
import sys

from generators.base import GENERATORS

# 생성기별 샘플 입력
SAMPLES = {
    "blog_seo": {"topic": "B2B SaaS 온보딩 자동화", "audience": "초기 스타트업 창업자",
                 "tone": "전문적이고 신뢰감 있는", "length": "중간 (800~1200 단어)"},
    "social_linkedin": {"topic": "AI 콘텐츠 생성 도구 ContentForge 출시", "goal": "리드 확보", "tone": "전문적"},
    "social_twitter": {"topic": "AI 콘텐츠 생성 도구 출시", "goal": "인지도 향상", "tone": "유머러스"},
    "social_instagram": {"topic": "신제품 출시", "goal": "참여 유도", "tone": "친근한"},
    "mkt_landing": {"product": "프리랜서용 자동 세금계산서 발행 도구",
                    "value": "클릭 한 번으로 발행, 국세청 연동", "audience": "1인 사업자", "tone": "설득적"},
    "mkt_ads": {"product": "AI 콘텐츠 생성 SaaS", "value": "10분 만에 블로그 글 완성",
                "audience": "마케터", "tone": "설득적"},
    "mkt_product": {"product": "노이즈 캔슬링 이어버드", "value": "40시간 재생, 멀티포인트 연결",
                    "audience": "직장인", "tone": "고급스러운"},
    "email_newsletter": {"message": "신규 기능 출시 안내 및 무료 체험 유도",
                         "sender": "ContentForge 팀", "audience": "기존 무료 사용자", "tone": "전문적이면서 친근한"},
    "email_cold": {"message": "콘텐츠 제작 시간 90% 단축 솔루션 소개",
                   "sender": "김창업, ContentForge", "audience": "스타트업 마케팅 담당자", "tone": "전문적이면서 친근한"},
    "startup_pitch": {"company": "ContentForge", "oneliner": "스타트업을 위한 AI 콘텐츠 생성 도구",
                      "problem": "마케팅 인력이 없는 초기 팀의 콘텐츠 제작 부담",
                      "traction": "MRR $5K, MoM 30% 성장, 유료 80팀", "round": "시드 5억원"},
    "startup_investor": {"company": "ContentForge", "oneliner": "스타트업을 위한 AI 콘텐츠 생성 도구",
                         "problem": "초기 팀의 콘텐츠 제작 부담", "traction": "MRR $5K, MoM 30%", "round": "시드 5억원"},
}

DEFAULT_KEYS = ["blog_seo", "social_linkedin", "mkt_landing"]


def run(key, lang="ko"):
    from core import gemini  # GEMINI_API_KEY 확인 후 임포트
    spec = GENERATORS[key]
    params = SAMPLES.get(key, {f["name"]: "샘플" for f in spec["fields"]})
    system = spec["system"](lang)
    prompt = spec["prompt"](params, lang)
    print("\n" + "=" * 70)
    print(f"[{spec['label']}]  ({key}, {lang})")
    print("입력:", params)
    print("-" * 70)
    output, model = gemini.generate(system, prompt, paid=False)
    print(output)
    print(f"\n(model: {model})")


def main():
    args = sys.argv[1:]
    if "--list" in args:
        for k, v in GENERATORS.items():
            print(f"  {k:20s} {v['label']}")
        return
    keys = [a for a in args if not a.startswith("-")] or DEFAULT_KEYS
    lang = "en" if "--en" in args else "ko"
    for k in keys:
        if k not in GENERATORS:
            print(f"알 수 없는 생성기: {k} (--list 로 목록 확인)")
            continue
        run(k, lang)


if __name__ == "__main__":
    main()
