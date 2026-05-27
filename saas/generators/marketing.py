"""수주 핵심 생성기 — 크몽/숨고 서비스 페이지, 홍보 카피."""


def _kmong_system(lang):
    from generators.base import lang_note
    return (
        "You are a conversion copywriter specializing in Korean freelance platforms (크몽, 숨고, 탈잉). "
        "Write a compelling service listing page that: "
        "1) Opens with a title showing the concrete result/benefit the client gets (not the service name), "
        "2) Clearly explains what the client receives step by step, "
        "3) Builds trust with specific process details and why you're qualified, "
        "4) Handles common client objections naturally, "
        "5) Closes with a compelling CTA. "
        "Use plain Korean that any client can understand. Avoid vague claims." + lang_note(lang)
    )


def _ad_system(lang):
    from generators.base import lang_note
    return (
        "You are a freelancer marketing copywriter. "
        "Produce 3 distinct promotional copy variations for social media or ads. "
        "Each variation: a hook headline (under 40 chars) and body text (under 125 chars). "
        "Focus on the client's pain point and the concrete result they get." + lang_note(lang)
    )


def _profile_system(lang):
    from generators.base import lang_note
    return (
        "You are a freelancer profile writing expert. "
        "Write a compelling freelancer profile description that: "
        "clearly states what you do and who you help, "
        "builds immediate credibility with specific experience and results, "
        "shows personality to stand out from generic profiles, "
        "and ends with a clear invitation to work together." + lang_note(lang)
    )


def _pr_system(lang):
    from generators.base import lang_note
    return (
        "You are a PR writer. Write a press release in standard format: "
        "a strong headline, opening paragraph answering who/what/when/where/why, "
        "2-3 body paragraphs with a quote, a boilerplate about section, and media contact." + lang_note(lang)
    )


def _kmong_prompt(p, lang):
    return (
        f"서비스 종류: {p['service']}\n"
        f"내가 제공하는 것 (구체적으로): {p.get('deliverable', '')}\n"
        f"타깃 클라이언트: {p.get('audience', '')}\n"
        f"내 경력/차별점: {p.get('strength', '')}\n\n"
        "위 정보로 크몽/숨고 서비스 상세페이지를 작성해줘. "
        "클라이언트가 '이 사람한테 맡기고 싶다'는 느낌이 들도록 설득력 있게 써줘."
    )


def _ad_prompt(p, lang):
    return (
        f"서비스/전문 분야: {p['service']}\n"
        f"클라이언트의 고통점: {p.get('pain', '')}\n"
        f"내가 해결해주는 것: {p.get('deliverable', '')}\n\n"
        "위 정보로 서비스 홍보 카피 3가지 버전을 작성해줘."
    )


def _profile_prompt(p, lang):
    return (
        f"전문 분야: {p['service']}\n"
        f"주요 경력/성과: {p.get('strength', '')}\n"
        f"주로 돕는 클라이언트 유형: {p.get('audience', '')}\n\n"
        "위 정보로 프리랜서 프로필 소개글을 작성해줘."
    )


def _kmong_fields():
    return [
        {"name": "service", "label": "서비스 종류", "type": "text",
         "placeholder": "예: 스타트업 브랜드 아이덴티티 디자인", "required": True},
        {"name": "deliverable", "label": "클라이언트가 받는 것 (구체적으로)", "type": "textarea",
         "placeholder": "예: 로고 3종 + 컬러 팔레트 + 폰트 가이드 + 명함 디자인"},
        {"name": "audience", "label": "주요 클라이언트", "type": "text",
         "placeholder": "예: 앱 출시 준비 중인 스타트업, 브랜드 리뉴얼이 필요한 소상공인"},
        {"name": "strength", "label": "내 경력 / 차별점", "type": "textarea",
         "placeholder": "예: 7년 경력, 스타트업 30곳 작업, 브랜드 런칭 후 투자 유치 성공 사례 다수"},
    ]


GENERATORS = [
    {"key": "mkt_landing", "label": "크몽/숨고 서비스 페이지", "group": "수주 핵심",
     "fields": _kmong_fields(), "system": _kmong_system, "prompt": _kmong_prompt},
    {"key": "mkt_ads", "label": "서비스 홍보 카피 (3종)", "group": "홍보 문구",
     "fields": [
         {"name": "service", "label": "서비스/전문 분야", "type": "text",
          "placeholder": "예: 퍼포먼스 마케팅 대행", "required": True},
         {"name": "pain", "label": "클라이언트 고통점", "type": "text",
          "placeholder": "예: 광고비는 쓰는데 전환이 안 됨"},
         {"name": "deliverable", "label": "내가 해결해주는 것", "type": "text",
          "placeholder": "예: ROAS 3배 이상 보장"},
     ], "system": _ad_system, "prompt": _ad_prompt},
    {"key": "mkt_product", "label": "프리랜서 프로필 소개글", "group": "홍보 문구",
     "fields": [
         {"name": "service", "label": "전문 분야", "type": "text",
          "placeholder": "예: iOS/Android 앱 개발", "required": True},
         {"name": "strength", "label": "주요 경력/성과", "type": "textarea",
          "placeholder": "예: 5년 경력, 출시 앱 20개, 앱스토어 인기 차트 진입 경험"},
         {"name": "audience", "label": "주로 돕는 클라이언트", "type": "text",
          "placeholder": "예: MVP 빠르게 만들어야 하는 스타트업"},
     ], "system": _profile_system, "prompt": _profile_prompt},
    {"key": "mkt_pr", "label": "보도자료", "group": "홍보 문구",
     "fields": _kmong_fields(), "system": _pr_system, "prompt": _kmong_prompt},
]
