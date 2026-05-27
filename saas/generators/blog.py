"""블로그 콘텐츠 생성기."""


def _blog_system(lang):
    from generators.base import lang_note
    return (
        "You are an expert SEO content writer for startups. "
        "Produce a well-structured, keyword-optimized blog post with a compelling H1 title, "
        "an engaging intro, clear H2/H3 sections, scannable bullet points where useful, "
        "and a concise conclusion with a call to action. "
        "Naturally weave in the target keyword without stuffing." + lang_note(lang)
    )


def _blog_prompt(p, lang):
    return (
        f"주제/타깃 키워드: {p['topic']}\n"
        f"톤: {p.get('tone', '전문적이고 신뢰감 있는')}\n"
        f"대상 독자: {p.get('audience', '일반 잠재 고객')}\n"
        f"분량: {p.get('length', '중간 (800~1200 단어)')}\n\n"
        "위 조건으로 SEO에 최적화된 블로그 글을 작성해줘. 메타 디스크립션도 마지막에 제안해줘."
    )


GENERATORS = [
    {
        "key": "blog_seo",
        "label": "SEO 블로그 글",
        "group": "블로그",
        "fields": [
            {"name": "topic", "label": "주제 / 타깃 키워드", "type": "text",
             "placeholder": "예: B2B SaaS 온보딩 자동화", "required": True},
            {"name": "audience", "label": "대상 독자", "type": "text",
             "placeholder": "예: 초기 스타트업 창업자"},
            {"name": "tone", "label": "톤", "type": "select",
             "options": ["전문적이고 신뢰감 있는", "친근하고 캐주얼한", "설득적이고 강렬한", "교육적이고 친절한"]},
            {"name": "length", "label": "분량", "type": "select",
             "options": ["짧게 (400~600 단어)", "중간 (800~1200 단어)", "길게 (1500+ 단어)"]},
        ],
        "system": _blog_system,
        "prompt": _blog_prompt,
    },
]
