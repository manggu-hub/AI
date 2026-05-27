"""소셜 미디어 콘텐츠 생성기."""


def _social_system(platform):
    def fn(lang):
        from generators.base import lang_note
        rules = {
            "LinkedIn": "Write a professional LinkedIn post: a strong hook in the first line, "
                        "short punchy paragraphs, a clear insight or story, and 3-5 relevant hashtags.",
            "Twitter/X": "Write a Twitter/X thread (3-6 tweets). Each tweet under 280 chars, "
                         "numbered, with a hook tweet first and a CTA last.",
            "Instagram": "Write an Instagram caption: an attention-grabbing first line, "
                         "emojis used tastefully, line breaks for readability, and 8-12 hashtags.",
        }
        return (
            f"You are a social media expert creating content for startups and freelancers. "
            f"{rules[platform]}" + lang_note(lang)
        )
    return fn


def _social_prompt(p, lang):
    return (
        f"홍보 대상 / 메시지: {p['topic']}\n"
        f"목표: {p.get('goal', '인지도 향상')}\n"
        f"톤: {p.get('tone', '전문적')}\n\n"
        "위 내용으로 게시물을 작성해줘."
    )


def _spec(key, platform):
    return {
        "key": key,
        "label": f"{platform} 게시물",
        "group": "소셜 미디어",
        "fields": [
            {"name": "topic", "label": "홍보 대상 / 핵심 메시지", "type": "textarea",
             "placeholder": "예: 새 제품 출시 — AI 기반 고객 응대 자동화 도구", "required": True},
            {"name": "goal", "label": "목표", "type": "select",
             "options": ["인지도 향상", "리드 확보", "참여 유도", "제품 출시 알림", "채용"]},
            {"name": "tone", "label": "톤", "type": "select",
             "options": ["전문적", "친근한", "유머러스", "영감을 주는"]},
        ],
        "system": _social_system(platform),
        "prompt": _social_prompt,
    }


GENERATORS = [
    _spec("social_linkedin", "LinkedIn"),
    _spec("social_twitter", "Twitter/X"),
    _spec("social_instagram", "Instagram"),
]
