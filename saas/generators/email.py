"""이메일 콘텐츠 생성기."""


def _newsletter_system(lang):
    from generators.base import lang_note
    return (
        "You are an email marketing expert. Write an engaging newsletter: a subject line, "
        "a preview text, a warm intro, 2-3 content blocks with subheadings, and a clear CTA." + lang_note(lang)
    )


def _cold_system(lang):
    from generators.base import lang_note
    return (
        "You are a B2B sales expert. Write a concise cold outreach email (under 150 words): "
        "a personalized subject line, a relevant hook, one clear value proposition, "
        "and a low-friction CTA. Avoid spammy language." + lang_note(lang)
    )


def _prompt(p, lang):
    return (
        f"발신자/회사: {p.get('sender', '')}\n"
        f"수신 대상: {p.get('audience', '')}\n"
        f"핵심 메시지 / 목적: {p['message']}\n"
        f"톤: {p.get('tone', '전문적이면서 친근한')}\n\n"
        "위 정보로 이메일을 작성해줘."
    )


def _fields():
    return [
        {"name": "message", "label": "핵심 메시지 / 목적", "type": "textarea",
         "placeholder": "예: 신규 기능 출시 안내 및 무료 체험 유도", "required": True},
        {"name": "sender", "label": "발신자 / 회사", "type": "text",
         "placeholder": "예: 김창업, ContentForge"},
        {"name": "audience", "label": "수신 대상", "type": "text",
         "placeholder": "예: 기존 무료 사용자"},
        {"name": "tone", "label": "톤", "type": "select",
         "options": ["전문적이면서 친근한", "격식 있는", "캐주얼한", "긴급함을 주는"]},
    ]


GENERATORS = [
    {"key": "email_newsletter", "label": "뉴스레터", "group": "이메일",
     "fields": _fields(), "system": _newsletter_system, "prompt": _prompt},
    {"key": "email_cold", "label": "콜드 이메일", "group": "이메일",
     "fields": _fields(), "system": _cold_system, "prompt": _prompt},
]
