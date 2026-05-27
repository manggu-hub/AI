"""수주 핵심 생성기 — 제안서, 케이스 스터디, 보고서."""


def _proposal_system(lang):
    from generators.base import lang_note
    return (
        "You are a freelance proposal writing expert. "
        "Write a winning client proposal that: "
        "1) Opens by reflecting the client's problem back to them (shows you truly understood their brief), "
        "2) Presents your solution and specific approach clearly, "
        "3) Explains why you're the right person with relevant experience, "
        "4) Outlines scope, deliverables, and rough timeline, "
        "5) Ends with clear next steps. "
        "Be specific and confident. Focus on the client's outcome, not your process. "
        "Avoid generic phrases like 'I am passionate about' or 'I would love to help'." + lang_note(lang)
    )


def _case_study_system(lang):
    from generators.base import lang_note
    return (
        "You are a portfolio writing expert for freelancers. "
        "Write a compelling case study using the Problem → Approach → Result structure. "
        "Make it client-focused: start with the client's challenge, "
        "explain your strategic thinking (not just execution), "
        "highlight measurable results where possible, "
        "and end with a key takeaway that shows your unique value. "
        "This should read like a story, not a resume bullet point." + lang_note(lang)
    )


def _report_system(lang):
    from generators.base import lang_note
    return (
        "You are a freelance project communication expert. "
        "Write a clear, professional project progress report for a client. "
        "Structure: brief summary of current status, "
        "what was completed this period, what's next, "
        "any blockers or decisions needed from the client, "
        "and timeline update. "
        "Be transparent and concise. Clients should feel informed and confident." + lang_note(lang)
    )


def _proposal_prompt(p, lang):
    return (
        f"클라이언트 요청 내용: {p['problem']}\n"
        f"내 전문 분야/경력: {p.get('expertise', '')}\n"
        f"제안하는 솔루션/접근법: {p.get('solution', '')}\n"
        f"예상 납기/일정: {p.get('timeline', '')}\n\n"
        "위 정보로 클라이언트를 설득할 수 있는 프리랜서 제안서를 작성해줘."
    )


def _case_prompt(p, lang):
    return (
        f"프로젝트 종류: {p['problem']}\n"
        f"클라이언트가 가진 문제/도전: {p.get('expertise', '')}\n"
        f"내가 한 작업/접근법: {p.get('solution', '')}\n"
        f"결과/성과 (수치 포함 가능): {p.get('timeline', '')}\n\n"
        "위 정보로 포트폴리오 케이스 스터디를 작성해줘. "
        "잠재 클라이언트가 읽고 '이 사람한테 맡기고 싶다'는 느낌이 들어야 해."
    )


def _report_prompt(p, lang):
    return (
        f"프로젝트명/종류: {p['problem']}\n"
        f"이번 주 완료한 작업: {p.get('expertise', '')}\n"
        f"다음 단계 계획: {p.get('solution', '')}\n"
        f"클라이언트 확인 필요 사항: {p.get('timeline', '')}\n\n"
        "위 정보로 클라이언트에게 보낼 프로젝트 진행 보고서를 작성해줘."
    )


def _proposal_fields():
    return [
        {"name": "problem", "label": "클라이언트 요청 내용", "type": "textarea",
         "placeholder": "예: 6월 오픈 예정인 뷰티 브랜드 쇼핑몰 디자인, 모바일 최적화 필수", "required": True},
        {"name": "expertise", "label": "내 전문 분야 / 관련 경력", "type": "textarea",
         "placeholder": "예: 뷰티/라이프스타일 브랜드 쇼핑몰 디자인 10건 이상, Shopify 전문"},
        {"name": "solution", "label": "제안하는 접근법", "type": "textarea",
         "placeholder": "예: 1주 리서치 → 와이어프레임 확인 → 디자인 2라운드 → 개발 핸드오프"},
        {"name": "timeline", "label": "예상 납기 / 일정", "type": "text",
         "placeholder": "예: 착수 후 4주, 5월 말 최종 납품 가능"},
    ]


def _case_fields():
    return [
        {"name": "problem", "label": "프로젝트 종류", "type": "text",
         "placeholder": "예: 스타트업 앱 UI/UX 디자인", "required": True},
        {"name": "expertise", "label": "클라이언트가 가진 문제", "type": "textarea",
         "placeholder": "예: 기존 앱이 복잡해서 신규 유저 이탈률이 70%에 달했음"},
        {"name": "solution", "label": "내가 한 작업 / 접근법", "type": "textarea",
         "placeholder": "예: 유저 인터뷰 5명 진행 후 핵심 플로우 3개로 압축, 온보딩 단계 7→3단계로 축소"},
        {"name": "timeline", "label": "결과 / 성과", "type": "textarea",
         "placeholder": "예: 리뉴얼 후 이탈률 40%로 감소, 앱스토어 평점 3.2→4.6 상승"},
    ]


def _report_fields():
    return [
        {"name": "problem", "label": "프로젝트명", "type": "text",
         "placeholder": "예: ABC 쇼핑몰 리뉴얼 프로젝트", "required": True},
        {"name": "expertise", "label": "이번 주 완료한 작업", "type": "textarea",
         "placeholder": "예: 메인 페이지 디자인 완료, 상품 상세 페이지 1차 시안 전달"},
        {"name": "solution", "label": "다음 단계 계획", "type": "textarea",
         "placeholder": "예: 시안 피드백 반영 → 장바구니/결제 페이지 작업"},
        {"name": "timeline", "label": "클라이언트 확인 필요 사항", "type": "textarea",
         "placeholder": "예: 상세 페이지 시안 피드백 목요일까지 부탁드립니다"},
    ]


GENERATORS = [
    {"key": "startup_pitch", "label": "클라이언트 제안서", "group": "수주 핵심",
     "fields": _proposal_fields(), "system": _proposal_system, "prompt": _proposal_prompt},
    {"key": "startup_investor", "label": "포트폴리오 케이스 스터디", "group": "수주 핵심",
     "fields": _case_fields(), "system": _case_study_system, "prompt": _case_prompt},
    {"key": "startup_update", "label": "프로젝트 진행 보고서", "group": "클라이언트 소통",
     "fields": _report_fields(), "system": _report_system, "prompt": _report_prompt},
]
