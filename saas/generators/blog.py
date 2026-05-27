"""블로그 콘텐츠 생성기 — 프리랜서 전문성 어필용."""


def _blog_system(lang):
    from generators.base import lang_note
    return (
        "You are an expert content strategist for freelancers. "
        "Write a blog post that positions the author as a credible expert in their field, "
        "naturally attracts potential clients through genuinely helpful content, "
        "and subtly demonstrates expertise without being promotional. "
        "Structure: an attention-grabbing title, engaging intro that hooks the reader, "
        "practical insights with real examples, clear H2/H3 sections, "
        "and a soft CTA at the end that invites readers to work together." + lang_note(lang)
    )


def _blog_prompt(p, lang):
    return (
        f"전문 분야: {p['topic']}\n"
        f"보여주고 싶은 전문성: {p.get('expertise', '')}\n"
        f"타깃 클라이언트: {p.get('audience', '잠재 클라이언트')}\n"
        f"분량: {p.get('length', '중간 (800~1200 단어)')}\n\n"
        "위 조건으로 클라이언트를 끌어당기는 전문성 블로그 글을 작성해줘. "
        "글 마지막에 자연스럽게 협업 문의를 유도하는 CTA를 넣어줘."
    )


GENERATORS = [
    {
        "key": "blog_seo",
        "label": "전문성 블로그",
        "group": "개인 브랜딩",
        "fields": [
            {"name": "topic", "label": "주제 / 전문 분야", "type": "text",
             "placeholder": "예: 스타트업 랜딩페이지 디자인 실수 5가지", "required": True},
            {"name": "expertise", "label": "어필하고 싶은 전문성", "type": "text",
             "placeholder": "예: 전환율 최적화, UX 디자인 7년 경력"},
            {"name": "audience", "label": "타깃 클라이언트", "type": "text",
             "placeholder": "예: 앱 출시를 앞둔 스타트업 대표"},
            {"name": "length", "label": "분량", "type": "select",
             "options": ["짧게 (400~600 단어)", "중간 (800~1200 단어)", "길게 (1500+ 단어)"]},
        ],
        "system": _blog_system,
        "prompt": _blog_prompt,
    },
]
