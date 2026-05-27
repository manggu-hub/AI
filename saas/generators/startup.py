"""스타트업 전용 콘텐츠 생성기."""


def _pitch_system(lang):
    from generators.base import lang_note
    return (
        "You are a startup pitch coach. Produce structured pitch deck content covering: "
        "Problem, Solution, Market Size, Product, Business Model, Traction, Team, and Ask. "
        "Each slide: a punchy headline and 2-4 concise bullet points." + lang_note(lang)
    )


def _investor_system(lang):
    from generators.base import lang_note
    return (
        "You are a fundraising advisor. Write a concise investor outreach email: "
        "a compelling subject line, a one-line company description, traction highlights, "
        "the round details, and a clear meeting ask. Keep it under 200 words." + lang_note(lang)
    )


def _update_system(lang):
    from generators.base import lang_note
    return (
        "You are a startup operator writing a monthly investor update. Structure it as: "
        "TL;DR, Key Metrics (with MoM change), Wins, Challenges/Lowlights, Asks (how investors "
        "can help), and a closing. Be transparent and data-driven, not promotional." + lang_note(lang)
    )


def _prompt(p, lang):
    return (
        f"스타트업: {p['company']}\n"
        f"한 줄 소개: {p.get('oneliner', '')}\n"
        f"해결하는 문제: {p.get('problem', '')}\n"
        f"트랙션 / 성과: {p.get('traction', '')}\n"
        f"투자 라운드: {p.get('round', '')}\n\n"
        "위 정보로 작성해줘."
    )


def _fields():
    return [
        {"name": "company", "label": "스타트업 이름", "type": "text",
         "placeholder": "예: ContentForge", "required": True},
        {"name": "oneliner", "label": "한 줄 소개", "type": "text",
         "placeholder": "예: 스타트업을 위한 AI 콘텐츠 생성 도구"},
        {"name": "problem", "label": "해결하는 문제", "type": "textarea",
         "placeholder": "예: 마케팅 인력이 없는 초기 팀의 콘텐츠 제작 부담"},
        {"name": "traction", "label": "트랙션 / 성과", "type": "textarea",
         "placeholder": "예: MRR $5K, MoM 30% 성장, 유료 고객 80팀"},
        {"name": "round", "label": "투자 라운드", "type": "text",
         "placeholder": "예: 시드 5억원 라운드"},
    ]


GENERATORS = [
    {"key": "startup_pitch", "label": "피치덱 콘텐츠", "group": "스타트업",
     "fields": _fields(), "system": _pitch_system, "prompt": _prompt},
    {"key": "startup_investor", "label": "투자자 이메일", "group": "스타트업",
     "fields": _fields(), "system": _investor_system, "prompt": _prompt},
    {"key": "startup_update", "label": "투자자 월간 업데이트", "group": "스타트업",
     "fields": _fields(), "system": _update_system, "prompt": _prompt},
]
