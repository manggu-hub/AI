"""소셜 미디어 콘텐츠 생성기 — 프리랜서 개인 브랜딩용."""


def _linkedin_system(lang):
    from generators.base import lang_note
    return (
        "You are a personal branding expert for freelancers on LinkedIn. "
        "Write a LinkedIn post that positions the author as a go-to expert, "
        "attracts inbound client inquiries, and gets meaningful engagement. "
        "Structure: a strong hook in the first line (before 'see more'), "
        "a relatable story or insight, practical takeaway, and a subtle CTA. "
        "Short punchy paragraphs, no jargon, 3-5 relevant hashtags at the end." + lang_note(lang)
    )


def _instagram_system(lang):
    from generators.base import lang_note
    return (
        "You are a social media strategist for freelancers. "
        "Write an Instagram caption that showcases expertise through portfolio or behind-the-scenes content, "
        "builds trust with potential clients, and encourages engagement. "
        "Attention-grabbing first line, tasteful emojis, line breaks for readability, "
        "and 8-12 hashtags including niche-specific ones." + lang_note(lang)
    )


def _twitter_system(lang):
    from generators.base import lang_note
    return (
        "You are a thought leadership writer for freelancers on X (Twitter). "
        "Write a thread (3-6 tweets) that shares a genuine insight from your work, "
        "positions you as an expert, and drives profile visits. "
        "Hook tweet first (under 280 chars), numbered tweets, CTA at the end." + lang_note(lang)
    )


def _social_prompt(p, lang):
    return (
        f"공유할 내용 / 핵심 메시지: {p['topic']}\n"
        f"내 전문 분야: {p.get('expertise', '')}\n"
        f"목표: {p.get('goal', '잠재 클라이언트 유입')}\n\n"
        "위 내용으로 게시물을 작성해줘."
    )


def _fields(placeholder):
    return [
        {"name": "topic", "label": "공유할 내용 / 핵심 메시지", "type": "textarea",
         "placeholder": placeholder, "required": True},
        {"name": "expertise", "label": "내 전문 분야", "type": "text",
         "placeholder": "예: 브랜드 디자이너, 퍼포먼스 마케터"},
        {"name": "goal", "label": "목표", "type": "select",
         "options": ["잠재 클라이언트 유입", "전문성 어필", "포트폴리오 홍보", "팔로워 참여 유도"]},
    ]


GENERATORS = [
    {
        "key": "social_linkedin",
        "label": "LinkedIn 포스트",
        "group": "개인 브랜딩",
        "fields": _fields("예: 클라이언트 미팅에서 항상 받는 질문과 내 답변"),
        "system": _linkedin_system,
        "prompt": _social_prompt,
    },
    {
        "key": "social_instagram",
        "label": "인스타그램 포트폴리오",
        "group": "개인 브랜딩",
        "fields": _fields("예: 최근 완성한 앱 UI 작업물 소개"),
        "system": _instagram_system,
        "prompt": _social_prompt,
    },
    {
        "key": "social_twitter",
        "label": "X(트위터) 포스트",
        "group": "개인 브랜딩",
        "fields": _fields("예: 프리랜서 3년 하면서 깨달은 제안서 작성법"),
        "system": _twitter_system,
        "prompt": _social_prompt,
    },
]
