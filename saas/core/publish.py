"""콘텐츠 발행/내보내기.

- WordPress: Application Password 기반 1클릭 발행 (OAuth 불필요)
- Webhook: 임의 URL로 JSON POST → Zapier/Make 경유로 LinkedIn·X·Slack 등 어디로든
- 공유 링크: LinkedIn/X/Facebook 공유 다이얼로그 prefill
- HTML 내보내기

LinkedIn/X 네이티브 자동게시는 OAuth 앱 승인 + 공개 콜백이 필요하므로(배포 후),
지금은 Webhook + 공유링크로 동일 목적을 달성한다.
"""
import urllib.parse

import markdown as _md
import requests


def md_to_html(text: str) -> str:
    return _md.markdown(text, extensions=["extra", "sane_lists"])


def to_webhook(url: str, payload: dict, timeout: int = 15) -> int:
    r = requests.post(url, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.status_code


def to_wordpress(site_url: str, username: str, app_password: str,
                 title: str, content_md: str, status: str = "draft",
                 timeout: int = 20) -> str:
    api = site_url.rstrip("/") + "/wp-json/wp/v2/posts"
    r = requests.post(
        api,
        auth=(username, app_password.replace(" ", "")),
        json={"title": title, "content": md_to_html(content_md), "status": status},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json().get("link", "")


def share_links(text: str, url: str = "") -> dict:
    t = urllib.parse.quote(text[:280])
    u = urllib.parse.quote(url)
    return {
        "LinkedIn": f"https://www.linkedin.com/feed/?shareActive=true&text={t}",
        "X (Twitter)": f"https://twitter.com/intent/tweet?text={t}",
        "Facebook": f"https://www.facebook.com/sharer/sharer.php?u={u}&quote={t}",
    }
