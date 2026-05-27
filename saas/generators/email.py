"""이메일 생성기 — 클라이언트 영업 및 소통용."""


def _cold_system(lang):
    from generators.base import lang_note
    return (
        "You are a freelance business development expert. "
        "Write a concise cold outreach email to a potential client (under 150 words). "
        "Structure: personalized subject line, a relevant hook showing you understand their situation, "
        "one clear value proposition with a specific result you can deliver, "
        "and a low-friction CTA (asking for a short call, not a commitment). "
        "Sound like a trusted expert reaching out, not a salesperson. Avoid spammy language." + lang_note(lang)
    )


def _followup_system(lang):
    from generators.base import lang_note
    return (
        "You are a freelance client communication expert. "
        "Write a warm follow-up email that: reminds the client of the previous interaction, "
        "adds new value (insight, relevant example, or update), "
        "and gently re-invites them to connect. "
        "Keep it under 100 words. Friendly but professional." + lang_note(lang)
    )


def _newsletter_system(lang):
    from generators.base import lang_note
    return (
        "You are an email marketing expert for freelancers. "
        "Write a client newsletter that keeps existing clients engaged and top-of-mind. "
        "Include: a subject line, a brief personal update or insight, "
        "one genuinely useful tip for the client, and a soft CTA for referrals or new projects." + lang_note(lang)
    )


def _cold_prompt(p, lang):
    return (
        f"내 전문 분야: {p.get('service', '')}\n"
        f"연락할 클라이언트 유형: {p.get('audience', '')}\n"
        f"내가 해결해줄 수 있는 문제: {p['message']}\n"
        f"참고할 클라이언트 정보 (있으면): {p.get('context', '')}\n\n"
        "위 정보로 클라이언트에게 보낼 콜드 이메일을 작성해줘."
    )


def _general_prompt(p, lang):
    return (
        f"내 전문 분야/서비스: {p.get('service', '')}\n"
        f"수신 대상: {p.get('audience', '')}\n"
        f"핵심 메시지: {p['message']}\n\n"
        "위 정보로 이메일을 작성해줘."
    )


GENERATORS = [
    {
        "key": "email_cold",
        "label": "클라이언트 영업 이메일",
        "group": "클라이언트 소통",
        "fields": [
            {"name": "message", "label": "내가 해결해줄 수 있는 문제", "type": "textarea",
             "placeholder": "예: 광고비 대비 전환율이 낮은 문제를 ROAS 최적화로 해결", "required": True},
            {"name": "service", "label": "내 전문 분야", "type": "text",
             "placeholder": "예: 퍼포먼스 마케터, 5년 경력"},
            {"name": "audience", "label": "연락할 클라이언트", "type": "text",
             "placeholder": "예: 온라인 쇼핑몰 운영하는 대표님"},
            {"name": "context", "label": "클라이언트 관련 정보 (선택)", "type": "text",
             "placeholder": "예: 최근 인스타 광고를 시작한 것 같음"},
        ],
        "system": _cold_system,
        "prompt": _cold_prompt,
    },
    {
        "key": "email_newsletter",
        "label": "클라이언트 뉴스레터",
        "group": "클라이언트 소통",
        "fields": [
            {"name": "message", "label": "이번 호 주제 / 공유할 내용", "type": "textarea",
             "placeholder": "예: 최근 완성한 프로젝트 소개 + 디자인 트렌드 한 가지", "required": True},
            {"name": "service", "label": "내 전문 분야", "type": "text",
             "placeholder": "예: 브랜드 디자이너"},
            {"name": "audience", "label": "수신 대상", "type": "text",
             "placeholder": "예: 기존 클라이언트 및 잠재 고객"},
        ],
        "system": _newsletter_system,
        "prompt": _general_prompt,
    },
    {
        "key": "email_followup",
        "label": "팔로업 이메일",
        "group": "클라이언트 소통",
        "fields": [
            {"name": "message", "label": "이전 대화 내용 / 팔로업 이유", "type": "textarea",
             "placeholder": "예: 지난주 미팅 후 견적서 보냈는데 답변이 없는 상태", "required": True},
            {"name": "service", "label": "내 전문 분야", "type": "text",
             "placeholder": "예: 웹 개발자"},
            {"name": "audience", "label": "클라이언트", "type": "text",
             "placeholder": "예: 쇼핑몰 리뉴얼 문의한 대표님"},
        ],
        "system": _followup_system,
        "prompt": _general_prompt,
    },
]
