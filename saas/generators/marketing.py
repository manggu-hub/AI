"""마케팅 카피 생성기."""


def _landing_system(lang):
    from generators.base import lang_note
    return (
        "You are a conversion copywriter. Write landing page copy with: a hero headline, "
        "a supporting subheadline, 3 benefit-driven sections (heading + 1-2 sentences each), "
        "social-proof suggestion, and a primary CTA button text." + lang_note(lang)
    )


def _ad_system(lang):
    from generators.base import lang_note
    return (
        "You are a performance marketing copywriter. Produce 3 distinct ad variations, "
        "each with a headline (under 40 chars) and primary text (under 125 chars), "
        "optimized for click-through." + lang_note(lang)
    )


def _product_system(lang):
    from generators.base import lang_note
    return (
        "You are an e-commerce copywriter. Write a persuasive product description: "
        "a catchy title, a benefit-led paragraph, and a bulleted feature list." + lang_note(lang)
    )


def _prompt(p, lang):
    return (
        f"제품/서비스: {p['product']}\n"
        f"핵심 가치 / 차별점: {p.get('value', '')}\n"
        f"타깃 고객: {p.get('audience', '')}\n"
        f"톤: {p.get('tone', '설득적')}\n\n"
        "위 정보로 카피를 작성해줘."
    )


def _fields():
    return [
        {"name": "product", "label": "제품 / 서비스", "type": "text",
         "placeholder": "예: 프리랜서용 자동 세금계산서 발행 도구", "required": True},
        {"name": "value", "label": "핵심 가치 / 차별점", "type": "textarea",
         "placeholder": "예: 클릭 한 번으로 세금계산서 발행, 국세청 연동"},
        {"name": "audience", "label": "타깃 고객", "type": "text",
         "placeholder": "예: 1인 사업자, 프리랜서"},
        {"name": "tone", "label": "톤", "type": "select",
         "options": ["설득적", "전문적", "친근한", "고급스러운"]},
    ]


GENERATORS = [
    {"key": "mkt_landing", "label": "랜딩페이지 카피", "group": "마케팅",
     "fields": _fields(), "system": _landing_system, "prompt": _prompt},
    {"key": "mkt_ads", "label": "광고 카피 (3종)", "group": "마케팅",
     "fields": _fields(), "system": _ad_system, "prompt": _prompt},
    {"key": "mkt_product", "label": "제품 설명", "group": "마케팅",
     "fields": _fields(), "system": _product_system, "prompt": _prompt},
]
