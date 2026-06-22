"""
구글 애드센스 승인 도우미
- 사이트 분석 → 체크리스트 → AI 콘텐츠 생성 → 필수 페이지 자동 생성
"""

import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from dataclasses import dataclass, field
from typing import Optional

import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

# ── AdSense 정책 기준값
MIN_WORD_COUNT = 300          # 페이지당 최소 단어 수
MIN_ARTICLE_COUNT = 15        # 최소 게시글 수 (추정)
MIN_CONTENT_PAGES = 5         # 필수 콘텐츠 페이지 수

# ── YMYL(Your Money Your Life) 키워드 — 구글이 가장 엄격하게 심사하는 분야
YMYL_MAP: dict[str, list[str]] = {
    "금융/재테크": [
        "주식", "투자", "etf", "펀드", "암호화폐", "코인", "비트코인", "이더리움",
        "대출", "보험", "연금", "세금", "부동산", "청약", "재테크", "절세", "배당",
    ],
    "건강/의료": [
        "질병", "증상", "치료", "약", "의약품", "다이어트", "수술", "병원",
        "암", "당뇨", "고혈압", "우울증", "불면증", "영양제", "건강기능식품",
    ],
    "법률": [
        "소송", "계약", "법률", "변호사", "이혼", "상속", "법적", "판결",
        "민사", "형사", "고소", "고발",
    ],
    "뉴스/정치": ["대통령", "국회", "선거", "정치", "정부 정책"],
}


def detect_ymyl(text: str) -> tuple[bool, str]:
    """텍스트에서 YMYL 카테고리 감지. (is_ymyl, category_name) 반환"""
    lower = text.lower()
    for category, keywords in YMYL_MAP.items():
        if any(kw in lower for kw in keywords):
            return True, category
    return False, ""


# ════════════════════════════════════════
#  HTML 파싱 유틸
# ════════════════════════════════════════
class _SiteParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self.description = ""
        self.text_parts: list[str] = []
        self.links: list[str] = []
        self.has_viewport = False
        self.has_canonical = False
        self.has_robots = False
        self.h1_count = 0
        self.img_count = 0
        self.img_without_alt = 0
        self._in_script = False
        self._in_style = False
        self._in_body = False
        self._current_tag = ""

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        self._current_tag = tag
        if tag == "script":
            self._in_script = True
        elif tag == "style":
            self._in_style = True
        elif tag == "meta":
            name = attrs_dict.get("name", "").lower()
            prop = attrs_dict.get("property", "").lower()
            content = attrs_dict.get("content", "")
            if name == "description" or prop == "og:description":
                self.description = content
            elif name == "viewport":
                self.has_viewport = True
            elif name == "robots":
                self.has_robots = True
            http_equiv = attrs_dict.get("http-equiv", "").lower()
            if http_equiv == "content-type":
                pass
        elif tag == "link":
            if attrs_dict.get("rel") == "canonical":
                self.has_canonical = True
        elif tag == "a":
            href = attrs_dict.get("href", "")
            if href and not href.startswith("#"):
                self.links.append(href)
        elif tag == "h1":
            self.h1_count += 1
        elif tag == "img":
            self.img_count += 1
            if not attrs_dict.get("alt", "").strip():
                self.img_without_alt += 1
        elif tag == "body":
            self._in_body = True

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_script = False
        elif tag == "style":
            self._in_style = False

    def handle_data(self, data):
        if self._in_script or self._in_style:
            return
        if self._current_tag == "title":
            self.title = data.strip()
        text = data.strip()
        if text:
            self.text_parts.append(text)

    @property
    def full_text(self) -> str:
        return " ".join(self.text_parts)

    @property
    def word_count(self) -> int:
        return len(self.full_text.split())


@dataclass
class CheckItem:
    name: str
    passed: bool
    detail: str
    weight: int = 1   # 점수 가중치


@dataclass
class SiteReport:
    url: str
    reachable: bool = False
    is_https: bool = False
    title: str = ""
    description: str = ""
    word_count: int = 0
    has_viewport: bool = False
    has_canonical: bool = False
    has_privacy_policy: bool = False
    has_about_page: bool = False
    has_contact_page: bool = False
    has_sitemap: bool = False
    has_robots_txt: bool = False
    internal_links: int = 0
    img_count: int = 0
    img_without_alt: int = 0
    h1_count: int = 0
    text_sample: str = ""
    error: str = ""
    checks: list[CheckItem] = field(default_factory=list)

    @property
    def score(self) -> int:
        if not self.checks:
            return 0
        total_weight = sum(c.weight for c in self.checks)
        passed_weight = sum(c.weight for c in self.checks if c.passed)
        return int(passed_weight / total_weight * 100) if total_weight else 0

    @property
    def approval_tier(self) -> tuple[str, str]:
        s = self.score
        if s >= 85:
            return "승인 가능성 높음", "🟢"
        elif s >= 65:
            return "준비 중", "🟡"
        else:
            return "개선 필요", "🔴"


# ════════════════════════════════════════
#  크롤러
# ════════════════════════════════════════
def _fetch(url: str, timeout: int = 10) -> tuple[Optional[str], Optional[str]]:
    """URL → (html, error)"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; AdSenseChecker/1.0)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            charset = resp.headers.get_content_charset("utf-8")
            return resp.read().decode(charset, errors="replace"), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:
        return None, str(e)


def _check_path(base: str, path: str) -> bool:
    """base URL + path 접근 가능 여부"""
    url = urllib.parse.urljoin(base, path)
    html, err = _fetch(url, timeout=6)
    return html is not None and err is None


def analyze_site(url: str) -> SiteReport:
    report = SiteReport(url=url)

    # HTTPS 확인
    report.is_https = url.startswith("https://")

    # 홈페이지 크롤링
    html, error = _fetch(url)
    if error or not html:
        report.error = error or "응답 없음"
        report.reachable = False
        return report

    report.reachable = True

    # HTML 파싱
    parser = _SiteParser()
    try:
        parser.feed(html)
    except Exception:
        pass

    report.title = parser.title
    report.description = parser.description
    report.word_count = parser.word_count
    report.has_viewport = parser.has_viewport
    report.has_canonical = parser.has_canonical
    report.h1_count = parser.h1_count
    report.img_count = parser.img_count
    report.img_without_alt = parser.img_without_alt
    report.text_sample = parser.full_text[:1000]

    # 내부 링크 수
    parsed = urllib.parse.urlparse(url)
    base_domain = parsed.netloc
    internal = [l for l in parser.links if base_domain in l or l.startswith("/")]
    report.internal_links = len(internal)

    # 필수 페이지 존재 여부 (링크 기반 + 직접 접근)
    lower_links = " ".join(parser.links).lower() + html.lower()
    report.has_privacy_policy = (
        "privacy" in lower_links
        or "개인정보" in lower_links
        or _check_path(url, "/privacy-policy")
        or _check_path(url, "/privacy")
    )
    report.has_about_page = (
        "/about" in lower_links
        or "소개" in lower_links
        or _check_path(url, "/about")
    )
    report.has_contact_page = (
        "contact" in lower_links
        or "연락" in lower_links
        or "문의" in lower_links
        or _check_path(url, "/contact")
    )
    report.has_sitemap = _check_path(url, "/sitemap.xml")
    report.has_robots_txt = _check_path(url, "/robots.txt")

    # 체크리스트 생성
    report.checks = _build_checks(report)
    return report


def _build_checks(r: SiteReport) -> list[CheckItem]:
    checks = []

    def add(name, passed, detail, weight=1):
        checks.append(CheckItem(name, passed, detail, weight))

    add("HTTPS 적용", r.is_https, "보안 연결(SSL) 필수", weight=3)
    add("사이트 접근 가능", r.reachable, "구글 봇이 접근 가능해야 함", weight=3)
    add("타이틀 태그", bool(r.title), f"현재: '{r.title[:40]}'" if r.title else "타이틀 없음", weight=2)
    add(
        "메타 설명",
        bool(r.description),
        f"현재 길이: {len(r.description)}자" if r.description else "메타 설명 없음",
        weight=2,
    )
    add(
        "콘텐츠 분량",
        r.word_count >= MIN_WORD_COUNT,
        f"감지된 단어 수: {r.word_count:,}개 (홈 기준, 최소 {MIN_WORD_COUNT}+)",
        weight=3,
    )
    add("모바일 최적화", r.has_viewport, "viewport 메타 태그 필요", weight=2)
    add("개인정보처리방침", r.has_privacy_policy, "AdSense 필수 정책 페이지", weight=3)
    add("소개(About) 페이지", r.has_about_page, "신뢰성 향상에 필수", weight=2)
    add("연락처(Contact) 페이지", r.has_contact_page, "사이트 신뢰도 향상", weight=2)
    add(
        "H1 태그",
        r.h1_count == 1,
        f"H1 태그: {r.h1_count}개 (1개 권장)",
        weight=1,
    )
    add(
        "이미지 alt 텍스트",
        r.img_without_alt == 0,
        f"alt 없는 이미지: {r.img_without_alt}개",
        weight=1,
    )
    add("사이트맵(sitemap.xml)", r.has_sitemap, "검색엔진 색인 효율 향상", weight=1)
    add("robots.txt", r.has_robots_txt, "크롤러 접근 제어 파일", weight=1)
    add(
        "내부 링크",
        r.internal_links >= 5,
        f"내부 링크: {r.internal_links}개 (5개 이상 권장)",
        weight=1,
    )

    # YMYL 감지 — 해당 분야면 추가 정책 페이지 필요
    ymyl_detected, ymyl_cat = detect_ymyl(r.title + " " + r.text_sample)
    if ymyl_detected:
        has_disclaimer = (
            "disclaimer" in r.text_sample.lower()
            or "면책" in r.text_sample
            or "참고용" in r.text_sample
            or "전문가" in r.text_sample
        )
        add(
            f"YMYL 면책조항 ({ymyl_cat})",
            has_disclaimer,
            f"'{ymyl_cat}' 분야는 구글이 최고 수준으로 심사합니다. "
            "면책조항·전문가 검토 문구·출처 명시가 없으면 승인 거절 가능성↑",
            weight=3,
        )

    return checks


# ════════════════════════════════════════
#  Gemini AI 콘텐츠 생성
# ════════════════════════════════════════
def _gemini_client():
    if not API_KEY:
        return None
    return genai.Client(api_key=API_KEY)


def ai_generate(prompt: str, temperature: float = 0.75) -> str:
    client = _gemini_client()
    if not client:
        return "⚠️ GEMINI_API_KEY 환경변수가 설정되지 않았습니다."
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=8192,
            ),
        )
        return response.text
    except Exception as e:
        return f"AI 생성 오류: {e}"


def gen_privacy_policy(site_name: str, site_url: str, contact_email: str) -> str:
    return ai_generate(f"""
다음 정보로 구글 애드센스 승인에 적합한 개인정보처리방침 페이지 전문을 작성해주세요.
HTML 형식으로, 한국어로, 실제 사이트에 바로 붙여넣을 수 있게 완성도 높게 작성해주세요.

- 사이트명: {site_name}
- 사이트 URL: {site_url}
- 연락처 이메일: {contact_email}
- 날짜: 2026년 6월

포함 내용:
1. 수집하는 개인정보 항목
2. 개인정보 수집 및 이용목적
3. 개인정보 보유 및 이용기간
4. 쿠키 정책 (구글 애드센스 관련)
5. 제3자 광고 네트워크 (Google AdSense)
6. 사용자 권리
7. 문의처

HTML 태그 포함하여 완성된 콘텐츠만 출력해주세요.
""")


def gen_about_page(site_name: str, niche: str, site_url: str) -> str:
    return ai_generate(f"""
다음 정보로 구글 애드센스 승인에 도움이 되는 '소개(About Us)' 페이지를 작성해주세요.
한국어로, HTML 형식으로, 신뢰감과 전문성을 주는 콘텐츠로 작성해주세요.

- 사이트명: {site_name}
- 주제/분야: {niche}
- 사이트 URL: {site_url}

포함 내용:
1. 사이트/블로그 소개 (목적, 가치)
2. 운영자 소개 (익명 가능, 전문성 강조)
3. 제공하는 콘텐츠 종류
4. 독자에게 주는 가치
5. 운영 철학

HTML 태그 포함하여 완성된 콘텐츠만 출력해주세요.
""")


# ── ① 승인 잘되는 주제 자동 선정
def gen_adsense_topics(niche: str) -> str:
    return ai_generate(f"""
'{niche}' 분야에서 구글 애드센스 승인과 수익화에 유리한 블로그 주제 10개를 선정해주세요.

각 주제마다 다음 정보를 표 형식으로 작성해주세요:
| 번호 | 주제 제목 | 검색 의도 | AdSense 유리도 | 예상 CPC 수준 | 이유 |

- 검색 의도: 정보형/비교형/구매형/방법형 중 하나
- AdSense 유리도: ★★★★★ ~ ★★☆☆☆ (5점 만점)
- 예상 CPC 수준: 높음/보통/낮음
- 이유: 왜 이 주제가 애드센스 승인과 수익화에 유리한지 한 줄로

조건:
- 구글 정책 위반 주제 제외 (성인, 도박, 의약품 과장 등)
- 광고 단가(CPC)가 높은 틈새 주제 우선
- 검색량이 있으면서 경쟁이 적당한 주제
- 한국어 검색자가 많은 주제

한국어로 작성해주세요.
""", temperature=0.6)


# ── ② SEO 키워드 분석
def gen_keyword_research(topic: str, niche: str) -> str:
    return ai_generate(f"""
다음 블로그 주제에 대한 SEO 키워드 분석을 해주세요.

- 주제: {topic}
- 분야: {niche}

다음 형식으로 작성해주세요:

## 🎯 주요 타겟 키워드 (메인)
- 키워드 1개: 검색 의도, 월간 검색량 추정, 경쟁도

## 🔍 보조 키워드 (서브, 5개)
번호, 키워드, 검색 의도, 활용 위치(제목/소제목/본문)

## 💡 LSI 키워드 (연관어, 10개)
자연스럽게 본문에 삽입할 연관 키워드 목록

## 🏷️ 롱테일 키워드 (5개)
구체적 검색어, 경쟁이 낮고 전환율 높은 키워드

## 📌 제목에 꼭 넣을 핵심 단어
CTR을 높이는 파워워드와 숫자 조합 추천

한국어로 작성해주세요.
""", temperature=0.5)


# ── ③ CTR 높이는 제목 생성
def gen_seo_titles(topic: str, keywords: str) -> str:
    return ai_generate(f"""
다음 주제와 키워드로 클릭률(CTR)을 극대화하는 블로그 제목 5개를 생성해주세요.

- 주제: {topic}
- 핵심 키워드: {keywords}

각 제목 유형별로 1개씩:
1. 숫자형: "N가지", "N단계" 등 숫자 포함
2. 질문형: 독자의 궁금증을 자극하는 질문
3. 방법형: "하는 법", "방법", "가이드" 포함
4. 비교/순위형: "추천", "순위", "비교" 포함
5. 감성/공감형: 독자의 고민/감정에 공감하는 제목

각 제목 옆에 왜 CTR이 높은지 한 줄 이유도 작성해주세요.
제목은 40~60자 사이로, 검색 결과에서 잘리지 않게 만들어주세요.

한국어로 작성해주세요.
""", temperature=0.8)


# ── ④ E-E-A-T 완전 반영 고품질 글 생성 (3200자+)
def gen_quality_article(
    topic: str,
    niche: str,
    keywords: str,
    title: str,
    search_intent: str,
    is_ymyl: bool = False,
    ymyl_category: str = "",
) -> str:
    ymyl_block = ""
    if is_ymyl:
        ymyl_block = f"""
【YMYL 필수 지침 — '{ymyl_category}' 분야】
- 글 상단에 "이 글은 정보 제공 목적으로 작성되었으며, 전문가 상담을 대체하지 않습니다" 문구 삽입
- 주요 수치·사실에는 출처(공식 기관, 보고서 등) 반드시 명시
- 글 말미에 면책조항(Disclaimer) 섹션 별도 추가
- 저자 소개란에 관련 자격·경력 언급 (간략하게)
- 극단적 수익·효과 약속 문구 금지
"""

    return ai_generate(f"""
당신은 {niche} 분야의 10년 경력 전문 블로거입니다.
구글 E-E-A-T(경험·전문성·권위성·신뢰성) 원칙을 완벽히 반영한 고품질 블로그 글을 작성해주세요.
{ymyl_block}

【기본 정보】
- 제목: {title}
- 주제: {topic}
- 분야: {niche}
- 핵심 키워드: {keywords}
- 검색 의도: {search_intent}

【필수 구조 — 반드시 이 순서로 작성】

1. 📌 목차 (클릭 가능한 앵커 링크 형태로, ## 목차 헤더 아래 번호 목록)

2. 🔥 도입부 (150자 이상)
   - 독자의 고민/문제 상황에 공감하는 문장으로 시작
   - "저도 처음에는..." "많은 분들이..." 같은 경험 공유 문장 포함
   - 이 글을 읽으면 얻을 수 있는 것 명시

3. 📖 본문 (H2 소제목 4~6개, 각 H2 아래 H3 2~3개)
   - 각 소제목 아래 300자 이상 상세 설명
   - 구체적 수치, 통계, 사례, 비교 포함
   - 전문용어 사용 후 괄호 안에 쉬운 설명 병기 (E-E-A-T 전문성)
   - "제 경험으로는...", "실제로 해보니..." 등 경험 기반 문장 (E-E-A-T 경험)
   - 독자가 바로 실행할 수 있는 구체적 팁과 단계
   - 핵심 키워드를 자연스럽게 3~5회 삽입 (키워드 스터핑 금지)

4. ✅ 핵심 요약 (글머리 기호 5~7개로 이 글의 핵심 정리)

5. 💬 CTA (Call-to-Action)
   - 댓글 유도: "여러분의 경험은 어떠신가요? 댓글로 알려주세요!"
   - 구독/북마크 유도
   - 관련 글 추천 (예시 제목 2개)

6. #️⃣ 해시태그 (10~15개, 줄 맨 아래)
   - #{niche}관련 태그들을 #태그 형태로 나열

【문체 원칙 — 사람이 쓴 것처럼】
- 딱딱한 AI 문체 금지. 친근하고 대화하듯 자연스럽게
- 문장 길이를 다양하게 (짧은 문장 + 긴 문장 혼합)
- "사실은요...", "솔직히 말씀드리면...", "이건 정말 중요한데요" 같은 구어체 표현 자연스럽게 포함
- 단락마다 1~2줄의 짧은 임팩트 문장 삽입
- 독자를 "여러분"으로 지칭

【분량 기준】
- 전체 3,200자 이상 (한국어 기준, 공백 포함)
- 본문만 2,500자 이상

마크다운 형식으로만 출력해주세요. (HTML 태그 금지)
""", temperature=0.8)


# ── sitemap.xml 자동 생성
def gen_sitemap_xml(site_url: str, urls: list[str]) -> str:
    from datetime import date
    today = date.today().isoformat()
    base = site_url.rstrip("/")
    items = []
    for raw in urls:
        u = raw.strip()
        if not u:
            continue
        if not u.startswith("http"):
            u = base + "/" + u.lstrip("/")
        items.append(f"""  <url>
    <loc>{u}</loc>
    <lastmod>{today}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>""")
    # 홈페이지를 priority 1.0으로 맨 앞
    home_entry = f"""  <url>
    <loc>{base}/</loc>
    <lastmod>{today}</lastmod>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>"""
    body = home_entry + "\n" + "\n".join(items) if items else home_entry
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{body}
</urlset>"""


# ── robots.txt 자동 생성
def gen_robots_txt(site_url: str) -> str:
    base = site_url.rstrip("/")
    return f"""User-agent: *
Allow: /

# 관리자·로그인 영역 차단
Disallow: /admin/
Disallow: /wp-admin/
Disallow: /login/
Disallow: /private/
Disallow: /?s=
Disallow: /search/
Disallow: /tag/*/feed/
Disallow: /comments/feed/

# 이미지·미디어 허용
Allow: /wp-content/uploads/

# 사이트맵 위치
Sitemap: {base}/sitemap.xml

# 크롤 속도 (과부하 방지)
Crawl-delay: 1
"""


# ── 글 품질 자동 채점
def score_article(article: str, keywords: str) -> dict:
    """생성된 글을 10개 기준으로 채점, 점수 dict 반환"""
    scores = {}
    text = article

    # 1. 글자 수 (3200자 이상)
    char_count = len(text)
    scores["글자 수 (3,200자+)"] = (
        (5 if char_count >= 3200 else (3 if char_count >= 2000 else 1)),
        f"{char_count:,}자",
        5,
    )

    # 2. 목차(TOC) 포함
    has_toc = "목차" in text or "## 목차" in text or "# 목차" in text
    scores["목차(TOC) 포함"] = (5 if has_toc else 0, "있음" if has_toc else "없음", 5)

    # 3. H2 소제목 4개 이상
    h2_count = text.count("\n## ")
    scores["H2 소제목 (4개+)"] = (
        (5 if h2_count >= 4 else (3 if h2_count >= 2 else 1)),
        f"{h2_count}개",
        5,
    )

    # 4. H3 소제목 4개 이상
    h3_count = text.count("\n### ")
    scores["H3 소제목 (4개+)"] = (
        (5 if h3_count >= 4 else (3 if h3_count >= 2 else 1)),
        f"{h3_count}개",
        5,
    )

    # 5. E-E-A-T 신호 (경험·전문 관련 어휘)
    eeat_words = ["경험", "전문", "실제로", "직접", "해보니", "추천", "전문가", "연구", "통계", "출처"]
    eeat_found = [w for w in eeat_words if w in text]
    scores["E-E-A-T 신호어"] = (
        (5 if len(eeat_found) >= 5 else (3 if len(eeat_found) >= 2 else 1)),
        f"{len(eeat_found)}개 감지: {', '.join(eeat_found[:4])}",
        5,
    )

    # 6. CTA 포함
    cta_words = ["댓글", "구독", "공유", "북마크", "알림", "팔로우", "저장"]
    has_cta = any(w in text for w in cta_words)
    scores["CTA 포함"] = (5 if has_cta else 0, "있음" if has_cta else "없음", 5)

    # 7. 해시태그 포함
    hashtag_count = len(re.findall(r"#\S+", text))
    scores["해시태그 (10개+)"] = (
        (5 if hashtag_count >= 10 else (3 if hashtag_count >= 5 else 1)),
        f"{hashtag_count}개",
        5,
    )

    # 8. 핵심 키워드 밀도 (3~8회 — 과도하면 패널티)
    if keywords:
        main_kw = keywords.split(",")[0].strip()
        kw_count = text.lower().count(main_kw.lower())
        density_ok = 3 <= kw_count <= 8
        scores["키워드 밀도 (3~8회)"] = (
            (5 if density_ok else (2 if kw_count > 0 else 0)),
            f"'{main_kw}' {kw_count}회 등장",
            5,
        )
    else:
        scores["키워드 밀도 (3~8회)"] = (3, "키워드 미입력", 5)

    # 9. 요약/정리 섹션
    summary_words = ["요약", "정리", "마무리", "핵심", "결론"]
    has_summary = any(w in text for w in summary_words)
    scores["핵심 요약 섹션"] = (5 if has_summary else 0, "있음" if has_summary else "없음", 5)

    # 10. 자연스러운 구어체
    colloquial = ["솔직히", "사실은", "여러분", "저도", "해보니", "정말", "실제로", "그래서"]
    col_found = [w for w in colloquial if w in text]
    scores["자연스러운 문체"] = (
        (5 if len(col_found) >= 4 else (3 if len(col_found) >= 2 else 1)),
        f"구어체 표현 {len(col_found)}개 감지",
        5,
    )

    return scores


def _render_article_score(scores: dict) -> None:
    """채점 결과를 Streamlit으로 렌더링"""
    total = sum(v[0] for v in scores.values())
    max_total = sum(v[2] for v in scores.values())
    pct = int(total / max_total * 100)

    color = "#2ecc71" if pct >= 80 else ("#f39c12" if pct >= 60 else "#e74c3c")
    grade = "A (우수)" if pct >= 80 else ("B (보통)" if pct >= 60 else "C (개선 필요)")

    st.markdown(f"""
    <div style="background:#f8f9fa;border-radius:12px;padding:16px;margin-bottom:12px">
      <div style="font-size:14px;color:#666;margin-bottom:4px">글 품질 점수</div>
      <div style="font-size:36px;font-weight:bold;color:{color}">{pct}점 &nbsp;<span style="font-size:18px">{grade}</span></div>
      <div style="background:#ddd;border-radius:6px;height:12px;margin-top:8px">
        <div style="background:{color};width:{pct}%;height:12px;border-radius:6px"></div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    cols = st.columns(2)
    for i, (name, (score, detail, max_s)) in enumerate(scores.items()):
        icon = "✅" if score == max_s else ("⚠️" if score > 0 else "❌")
        with cols[i % 2]:
            st.markdown(
                f"**{icon} {name}**  \n"
                f"<span style='color:#888;font-size:12px'>{detail} ({score}/{max_s})</span>",
                unsafe_allow_html=True,
            )


def gen_improvement_plan(report: SiteReport) -> str:
    failed = [c for c in report.checks if not c.passed]
    failed_str = "\n".join(f"- {c.name}: {c.detail}" for c in failed)
    return ai_generate(f"""
다음은 구글 애드센스 승인을 위한 사이트 분석 결과입니다.
실패한 체크항목들을 바탕으로 우선순위별 개선 실행 계획을 작성해주세요.

사이트: {report.url}
현재 점수: {report.score}/100
승인 상태: {report.approval_tier[0]}

개선 필요 항목:
{failed_str if failed_str else "없음"}

각 항목에 대해:
1. 왜 중요한지
2. 구체적인 해결 방법 (단계별)
3. 예상 소요 시간

한국어로, 실용적이고 구체적으로 작성해주세요.
""")


# ════════════════════════════════════════
#  Streamlit UI
# ════════════════════════════════════════
def main():
    st.set_page_config(
        page_title="구글 애드센스 승인 도우미",
        page_icon="💰",
        layout="wide",
    )

    st.title("💰 구글 애드센스 승인 도우미")
    st.caption("사이트 분석 → 체크리스트 → AI 콘텐츠 생성으로 한번에 승인!")

    tab_analyze, tab_pages, tab_content, tab_guide = st.tabs(
        ["🔍 사이트 분석", "📄 필수 페이지 생성", "✍️ 콘텐츠 생성", "📋 승인 가이드"]
    )

    # ── Tab 1: 사이트 분석
    with tab_analyze:
        _tab_analyze()

    # ── Tab 2: 필수 페이지 생성
    with tab_pages:
        _tab_pages()

    # ── Tab 3: 콘텐츠 생성
    with tab_content:
        _tab_content()

    # ── Tab 4: 승인 가이드
    with tab_guide:
        _tab_guide()


def _tab_analyze():
    st.header("🔍 사이트 분석")
    st.info("사이트 URL을 입력하면 애드센스 승인 기준으로 자동 분석합니다.")

    url = st.text_input(
        "사이트 URL",
        placeholder="https://yourblog.com",
        help="https:// 포함한 전체 URL을 입력하세요",
    )

    if st.button("🚀 분석 시작", type="primary", use_container_width=True):
        if not url:
            st.warning("URL을 입력해주세요.")
            return
        if not url.startswith("http"):
            url = "https://" + url

        with st.spinner("사이트 분석 중... (30초 이내)"):
            report = analyze_site(url)
            st.session_state["report"] = report

    report: Optional[SiteReport] = st.session_state.get("report")
    if not report:
        return

    if not report.reachable:
        st.error(f"사이트 접근 실패: {report.error}")
        st.info("사이트가 실제로 운영 중인지, URL이 올바른지 확인해주세요.")
        return

    # 점수 대시보드
    tier_label, tier_icon = report.approval_tier
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("승인 준비 점수", f"{report.score}/100", delta=tier_icon + " " + tier_label)
    with col2:
        st.metric("단어 수 (홈)", f"{report.word_count:,}개")
    with col3:
        st.metric("내부 링크", f"{report.internal_links}개")
    with col4:
        st.metric("이미지", f"{report.img_count}개 (alt 누락: {report.img_without_alt})")

    # 진행률 바
    color = "green" if report.score >= 85 else ("orange" if report.score >= 65 else "red")
    st.markdown(f"""
    <div style="background:#eee;border-radius:8px;height:20px;width:100%;margin:10px 0">
      <div style="background:{color};width:{report.score}%;height:20px;border-radius:8px;
                  display:flex;align-items:center;justify-content:center;color:white;font-weight:bold;font-size:12px">
        {report.score}%
      </div>
    </div>
    """, unsafe_allow_html=True)

    # 체크리스트
    st.subheader("체크리스트")
    for check in report.checks:
        icon = "✅" if check.passed else "❌"
        weight_str = "⭐" * check.weight
        with st.expander(f"{icon} {check.name}  {weight_str}", expanded=not check.passed):
            st.write(check.detail)
            if not check.passed:
                st.caption("→ 개선이 필요한 항목입니다.")

    # AI 개선 계획
    st.divider()
    if st.button("🤖 AI 맞춤 개선 계획 생성", use_container_width=True):
        with st.spinner("AI가 개선 계획을 작성하는 중..."):
            plan = gen_improvement_plan(report)
            st.markdown("### 🗂️ AI 맞춤 개선 실행 계획")
            st.markdown(plan)


def _tab_pages():
    st.header("📄 필수 페이지 자동 생성")
    st.info("애드센스 승인에 필수인 페이지를 AI가 자동으로 작성해줍니다.")

    site_name = st.text_input("사이트/블로그 이름", placeholder="예: 스마트 리뷰 블로그")
    site_url = st.text_input("사이트 URL", placeholder="https://yourblog.com")
    contact_email = st.text_input("연락처 이메일", placeholder="contact@yourblog.com")
    niche = st.text_input("주제/분야", placeholder="예: IT 리뷰, 육아, 여행, 재테크 등")

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("🔒 개인정보처리방침 생성", use_container_width=True):
            if not site_name or not contact_email:
                st.warning("사이트 이름과 이메일을 입력해주세요.")
            else:
                with st.spinner("개인정보처리방침 작성 중..."):
                    result = gen_privacy_policy(site_name, site_url, contact_email)
                    st.session_state["privacy_result"] = result

    with col2:
        if st.button("👤 소개(About) 페이지 생성", use_container_width=True):
            if not site_name or not niche:
                st.warning("사이트 이름과 주제를 입력해주세요.")
            else:
                with st.spinner("소개 페이지 작성 중..."):
                    result = gen_about_page(site_name, niche, site_url)
                    st.session_state["about_result"] = result

    with col3:
        if st.button("📧 연락처 페이지 생성", use_container_width=True):
            if not site_name or not contact_email:
                st.warning("사이트 이름과 이메일을 입력해주세요.")
            else:
                with st.spinner("연락처 페이지 작성 중..."):
                    prompt = f"""
{site_name} 사이트의 연락처(Contact) 페이지를 작성해주세요.
이메일: {contact_email}
HTML 형식으로, 신뢰감 있고 친근한 톤으로 작성해주세요.
"""
                    result = ai_generate(prompt)
                    st.session_state["contact_result"] = result

    for key, title in [
        ("privacy_result", "🔒 개인정보처리방침"),
        ("about_result", "👤 소개 페이지"),
        ("contact_result", "📧 연락처 페이지"),
    ]:
        if key in st.session_state:
            st.divider()
            st.subheader(title)
            content = st.session_state[key]
            st.code(content, language="html")
            st.download_button(
                f"{title} 다운로드",
                data=content,
                file_name=f"{key.replace('_result','')}.html",
                mime="text/html",
                use_container_width=True,
            )

    # ── sitemap.xml / robots.txt 자동 생성
    st.divider()
    st.subheader("🗺️ sitemap.xml + robots.txt 자동 생성")
    st.caption("사이트 분석에서 누락됐던 두 파일을 바로 생성해 서버에 올리세요.")

    pg_site_url = st.text_input(
        "사이트 URL (sitemap용)",
        placeholder="https://yourblog.com",
        key="pg_site_url",
    )
    pg_extra_urls = st.text_area(
        "추가 페이지 URL (줄바꿈으로 구분, 상대경로 가능)",
        placeholder="/about\n/contact\n/privacy-policy\n/posts/article-1\n/posts/article-2",
        height=120,
        key="pg_extra_urls",
    )

    col_sm, col_rb = st.columns(2)
    with col_sm:
        if st.button("🗺️ sitemap.xml 생성", use_container_width=True):
            if not pg_site_url:
                st.warning("사이트 URL을 입력해주세요.")
            else:
                extra = [u for u in pg_extra_urls.splitlines() if u.strip()]
                xml = gen_sitemap_xml(pg_site_url, extra)
                st.session_state["sitemap_xml"] = xml

    with col_rb:
        if st.button("🤖 robots.txt 생성", use_container_width=True):
            if not pg_site_url:
                st.warning("사이트 URL을 입력해주세요.")
            else:
                txt = gen_robots_txt(pg_site_url)
                st.session_state["robots_txt"] = txt

    if "sitemap_xml" in st.session_state:
        st.markdown("**sitemap.xml** — 루트 디렉토리(`/sitemap.xml`)에 업로드하세요")
        st.code(st.session_state["sitemap_xml"], language="xml")
        st.download_button(
            "📥 sitemap.xml 다운로드",
            data=st.session_state["sitemap_xml"],
            file_name="sitemap.xml",
            mime="application/xml",
            use_container_width=True,
        )

    if "robots_txt" in st.session_state:
        st.markdown("**robots.txt** — 루트 디렉토리(`/robots.txt`)에 업로드하세요")
        st.code(st.session_state["robots_txt"], language="nginx")
        st.download_button(
            "📥 robots.txt 다운로드",
            data=st.session_state["robots_txt"],
            file_name="robots.txt",
            mime="text/plain",
            use_container_width=True,
        )


def _tab_content():
    st.header("✍️ E-E-A-T 고품질 콘텐츠 생성")
    st.info(
        "**9가지 요소 자동 반영**: E-E-A-T · 검색 의도 구조 · CTR 제목 · 승인 주제 선정 · "
        "3200자+ · 전문성/신뢰성 · 자연스러운 문체 · SEO 키워드 · 목차/해시태그/CTA"
    )

    # ── Step 0: 기본 설정
    niche = st.text_input(
        "블로그 분야",
        placeholder="예: 재테크, IT 기기 리뷰, 육아, 여행, 건강 등",
        key="ct_niche",
    )

    st.divider()

    # ── Step 1: 승인 잘되는 주제 자동 선정
    st.subheader("① 승인 잘되는 주제 자동 선정")
    if st.button("🎯 AdSense 최적 주제 10개 추천", use_container_width=True, key="btn_topics"):
        if not niche:
            st.warning("분야를 먼저 입력해주세요.")
        else:
            with st.spinner("AdSense 유리도·CPC·검색 의도 분석 중..."):
                st.session_state["topic_table"] = gen_adsense_topics(niche)

    if "topic_table" in st.session_state:
        st.markdown(st.session_state["topic_table"])

    topic = st.text_input(
        "선택한 주제 (위 추천에서 복사하거나 직접 입력)",
        placeholder="예: 2026 ETF 투자 완전 정복",
        key="ct_topic",
    )

    # YMYL 실시간 경고
    if topic or niche:
        is_ymyl, ymyl_cat = detect_ymyl((topic or "") + " " + (niche or ""))
        if is_ymyl:
            st.warning(
                f"⚠️ **YMYL 주제 감지: {ymyl_cat}**\n\n"
                "구글은 이 분야를 **최고 수준**으로 심사합니다. 승인받으려면 아래를 반드시 지키세요:\n"
                "- 글 말미에 **면책조항** 필수 (\"본 글은 참고용이며 전문가 상담을 권장합니다\")\n"
                "- **출처·근거 자료** 명시 (공식 통계, 기관 링크)\n"
                "- **저자 전문성** 소개 (자격증, 경력 등)\n"
                "- 개인정보처리방침에 **YMYL 면책 조항** 추가\n\n"
                "→ 글 생성 시 이 내용이 자동으로 반영됩니다."
            )

    st.divider()

    # ── Step 2: SEO 키워드 분석
    st.subheader("② 검색 상위 노출 키워드 분석")
    if st.button("🔍 키워드 분석 실행", use_container_width=True, key="btn_kw"):
        if not topic or not niche:
            st.warning("분야와 주제를 먼저 입력해주세요.")
        else:
            with st.spinner("주요 키워드 · 서브 키워드 · LSI · 롱테일 분석 중..."):
                st.session_state["kw_result"] = gen_keyword_research(topic, niche)

    if "kw_result" in st.session_state:
        with st.expander("키워드 분석 결과 보기", expanded=True):
            st.markdown(st.session_state["kw_result"])

    keywords = st.text_input(
        "사용할 핵심 키워드 (콤마로 구분)",
        placeholder="예: ETF 투자, ETF 추천 2026, 배당 ETF",
        key="ct_kw",
    )

    st.divider()

    # ── Step 3: CTR 높이는 제목 생성
    st.subheader("③ CTR 높이는 제목 생성")
    if st.button("✨ 클릭률 최적화 제목 5개 생성", use_container_width=True, key="btn_title"):
        if not topic or not keywords:
            st.warning("주제와 키워드를 먼저 입력해주세요.")
        else:
            with st.spinner("숫자형·질문형·방법형·비교형·감성형 제목 생성 중..."):
                st.session_state["titles"] = gen_seo_titles(topic, keywords)

    if "titles" in st.session_state:
        with st.expander("생성된 제목 5개 보기", expanded=True):
            st.markdown(st.session_state["titles"])

    selected_title = st.text_input(
        "사용할 제목 선택 (위에서 복사하거나 직접 입력)",
        placeholder="예: ETF 투자 처음이라면? 2026 배당 ETF 추천 TOP 7",
        key="ct_title",
    )

    search_intent = st.selectbox(
        "검색 의도",
        ["정보형 (알고 싶어요)", "방법형 (어떻게 하나요)", "비교형 (뭐가 나은가요)", "구매형 (살 거예요)"],
        key="ct_intent",
    )

    st.divider()

    # ── Step 4: 완전한 글 생성
    st.subheader("④ E-E-A-T 완전 반영 고품질 글 생성 (3,200자+)")

    col_gen, col_info = st.columns([2, 1])
    with col_info:
        st.markdown("""
**자동 포함 요소:**
- 목차 (Table of Contents)
- E-E-A-T 경험/전문성 문장
- 검색 의도 맞춤 구조
- 핵심 키워드 자연 삽입
- 핵심 요약 bullet
- CTA (댓글·구독 유도)
- 해시태그 10~15개
- 자연스러운 구어체
""")
    with col_gen:
        if st.button(
            "🚀 글 생성 시작 (3,200자 이상)",
            type="primary",
            use_container_width=True,
            key="btn_article",
        ):
            if not topic or not niche or not keywords or not selected_title:
                st.warning("분야 · 주제 · 키워드 · 제목을 모두 입력해주세요.")
            else:
                is_ymyl, ymyl_cat = detect_ymyl(topic + " " + niche)
                with st.spinner("E-E-A-T 고품질 글 작성 중... (약 1~2분)"):
                    article = gen_quality_article(
                        topic=topic,
                        niche=niche,
                        keywords=keywords,
                        title=selected_title,
                        search_intent=search_intent,
                        is_ymyl=is_ymyl,
                        ymyl_category=ymyl_cat,
                    )
                    st.session_state["article"] = article
                    st.session_state["article_kw"] = keywords

    # ── 결과 출력
    if "article" in st.session_state:
        st.divider()
        article = st.session_state["article"]
        saved_kw = st.session_state.get("article_kw", keywords)

        # 품질 자동 채점
        st.subheader("⑤ 글 품질 자동 채점")
        scores = score_article(article, saved_kw)
        _render_article_score(scores)

        st.divider()

        char_total = len(article)
        char_no_space = len(article.replace(" ", ""))

        col_m1, col_m2, col_m3 = st.columns(3)
        with col_m1:
            st.metric("총 글자 수 (공백 포함)", f"{char_total:,}자")
        with col_m2:
            st.metric("순 글자 수 (공백 제외)", f"{char_no_space:,}자")
        with col_m3:
            status = "✅ 충족" if char_total >= 3200 else "⚠️ 부족"
            st.metric("3,200자 기준", status)

        tab_preview, tab_raw = st.tabs(["📖 미리보기", "📝 마크다운 원본"])
        with tab_preview:
            st.markdown(article)
        with tab_raw:
            st.code(article, language="markdown")

        safe_title = st.session_state.get("ct_title", "article")
        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            st.download_button(
                "📥 마크다운 다운로드 (.md)",
                data=article,
                file_name="article.md",
                mime="text/markdown",
                use_container_width=True,
            )
        with col_dl2:
            html_content = (
                f"<html><head><meta charset='utf-8'>"
                f"<title>{safe_title}</title></head>"
                f"<body>{article}</body></html>"
            )
            st.download_button(
                "📥 HTML 다운로드 (.html)",
                data=html_content,
                file_name="article.html",
                mime="text/html",
                use_container_width=True,
            )


def _tab_guide():
    st.header("📋 구글 애드센스 승인 완전 가이드")

    st.markdown("""
## 🎯 승인의 핵심 3가지

| 요소 | 중요도 | 설명 |
|------|--------|------|
| 콘텐츠 품질 | ⭐⭐⭐⭐⭐ | 독창적, 유익, 충분한 분량 |
| 정책 준수 | ⭐⭐⭐⭐⭐ | 개인정보처리방침, 저작권 준수 |
| 사이트 구조 | ⭐⭐⭐⭐ | 탐색 가능, 모바일 최적화 |

---

## ✅ 승인 전 필수 체크리스트

### 1. 콘텐츠 요구사항
- [ ] **최소 15~20개 이상의 독창적 포스팅** (각 500단어+)
- [ ] 복사/붙여넣기 콘텐츠 없음 (표절 0%)
- [ ] 특정 주제에 집중 (틈새 블로그 유리)
- [ ] 최근 30일 내 꾸준한 업데이트

### 2. 필수 페이지
- [ ] **개인정보처리방침** (Google 정책 명시 포함)
- [ ] **소개(About) 페이지**
- [ ] **연락처(Contact) 페이지**
- [ ] (선택) 면책조항, 저작권 안내

### 3. 기술 요구사항
- [ ] HTTPS (SSL 인증서 적용)
- [ ] 모바일 반응형 디자인
- [ ] 페이지 로딩 속도 3초 이내
- [ ] robots.txt 설정
- [ ] sitemap.xml 제출 (구글 서치 콘솔)
- [ ] 정상적인 내비게이션 메뉴

### 4. 도메인 관련
- [ ] 커스텀 도메인 사용 (무료 서브도메인 불리)
- [ ] 도메인 등록 6개월+ 경과 권장
- [ ] 소유권 확인 완료 (서치 콘솔)

---

## 🚫 즉시 거절 사유

| 거절 사유 | 설명 |
|-----------|------|
| 성인 콘텐츠 | 포르노, 성적 표현 |
| 폭력/혐오 | 증오 발언, 폭력 조장 |
| 저작권 침해 | 타 사이트 복사 콘텐츠 |
| 불법 콘텐츠 | 해킹, 마약, 도박 조장 |
| 개인정보처리방침 미비 | 정책 페이지 없음 |
| 콘텐츠 부족 | 게시글 수 부족 |

---

## 📅 승인까지 추천 일정

```
Week 1-2: 사이트 설정 + 필수 페이지 작성
Week 3-6: 고품질 포스팅 15개+ 작성
Week 7:   구글 서치 콘솔 등록 + 사이트맵 제출
Week 8:   애드센스 신청
```

---

## 💡 승인률을 높이는 꿀팁

1. **틈새 주제 선택**: 음식, 여행, IT, 재테크 등 명확한 카테고리
2. **긴 글 위주**: 1,000단어 이상 글이 많을수록 유리
3. **이미지 alt 태그**: 모든 이미지에 설명 텍스트
4. **외부 링크 절제**: 무분별한 아웃바운드 링크 자제
5. **광고 클릭 유도 금지**: "광고를 클릭해주세요" 문구 절대 금지
6. **신청 전 충분한 트래픽**: 월 100+ 방문자 확보 후 신청

---

## 🔄 재신청 전략 (거절 후)

1. 거절 사유 메일 꼼꼼히 확인
2. 해당 사유 완전히 수정
3. 콘텐츠 5~10개 추가
4. **최소 2~4주 후** 재신청
5. 구글 서치 콘솔에서 색인 상태 확인
""")

    st.divider()
    st.subheader("🔗 유용한 공식 링크")
    st.markdown("""
- [AdSense 정책 센터](https://support.google.com/adsense/answer/48182)
- [Google Search Console](https://search.google.com/search-console)
- [PageSpeed Insights](https://pagespeed.web.dev/)
- [Google AdSense 신청](https://adsense.google.com/start/)
""")


if __name__ == "__main__":
    main()
