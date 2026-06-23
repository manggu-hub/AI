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
import google.generativeai as genai

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

# ── 분야별 예상 CPC·RPM 데이터 (한국 기준 추정치)
CPC_RANKING: list[tuple] = [
    # (분야, 유리도, 예상 CPC 달러, 예상 RPM 원, 경쟁도)
    ("보험",           "★★★★★", "$15~50",  "8,000~25,000",  "매우 높음"),
    ("법률/변호사",    "★★★★★", "$20~80",  "10,000~30,000", "매우 높음"),
    ("금융/재테크",    "★★★★★", "$10~30",  "5,000~15,000",  "높음"),
    ("부동산",         "★★★★☆", "$8~25",   "4,000~12,000",  "높음"),
    ("의료/건강",      "★★★★☆", "$5~20",   "3,000~10,000",  "높음"),
    ("IT/소프트웨어",  "★★★★☆", "$5~15",   "3,000~10,000",  "보통"),
    ("자동차",         "★★★☆☆", "$4~12",   "2,500~8,000",   "보통"),
    ("교육/자격증",    "★★★☆☆", "$3~10",   "2,000~6,000",   "보통"),
    ("여행",           "★★★☆☆", "$2~8",    "1,500~5,000",   "보통"),
    ("육아/육아용품",  "★★★☆☆", "$2~6",    "1,000~4,000",   "보통"),
    ("맛집/음식",      "★★☆☆☆", "$1~4",    "800~3,000",     "낮음"),
    ("뷰티/패션",      "★★☆☆☆", "$1~5",    "800~3,000",     "낮음"),
    ("연예/엔터",      "★★☆☆☆", "$0.5~2",  "500~2,000",     "낮음"),
    ("게임",           "★★☆☆☆", "$0.5~3",  "600~2,500",     "낮음"),
]

RPM_BY_NICHE: dict[str, tuple[int, int]] = {
    "보험":          (8000, 25000),
    "법률/변호사":   (10000, 30000),
    "금융/재테크":   (5000, 15000),
    "부동산":        (4000, 12000),
    "의료/건강":     (3000, 10000),
    "IT/소프트웨어": (3000, 10000),
    "자동차":        (2500, 8000),
    "교육/자격증":   (2000, 6000),
    "여행":          (1500, 5000),
    "육아/육아용품": (1000, 4000),
    "맛집/음식":     (800, 3000),
    "뷰티/패션":     (800, 3000),
    "연예/엔터":     (500, 2000),
    "게임":          (600, 2500),
    "기타":          (1000, 4000),
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
def ai_generate(prompt: str, temperature: float = 0.75) -> str:
    if not API_KEY:
        return "⚠️ GEMINI_API_KEY 환경변수가 설정되지 않았습니다."
    try:
        genai.configure(api_key=API_KEY)
        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            generation_config=genai.types.GenerationConfig(
                temperature=temperature,
                max_output_tokens=8192,
            ),
        )
        response = model.generate_content(prompt)
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
   - 도입부 바로 아래: > 📷 **[대표 이미지]** 주제와 관련된 메인 이미지 삽입 권장 (예: "{topic} 관련 실제 사진 또는 인포그래픽")

3. 📖 본문 (H2 소제목 4~6개, 각 H2 아래 H3 2~3개)
   - 각 소제목 아래 300자 이상 상세 설명
   - 구체적 수치, 통계, 사례, 비교 포함
   - 전문용어 사용 후 괄호 안에 쉬운 설명 병기 (E-E-A-T 전문성)
   - "제 경험으로는...", "실제로 해보니..." 등 경험 기반 문장 (E-E-A-T 경험)
   - 독자가 바로 실행할 수 있는 구체적 팁과 단계
   - 핵심 키워드를 자연스럽게 3~5회 삽입 (키워드 스터핑 금지)
   - 본문 중간(2번째 H2 아래)에 반드시 비교/정리 표 1개 삽입:
     마크다운 표 형식 사용 (| 헤더1 | 헤더2 | 헤더3 | 형태)
     예: 방법 비교, 장단점, 단계별 정리, 비용 비교 등 내용에 맞게 구성
   - 본문 중간 H2 섹션마다 1개씩 이미지 가이드 삽입:
     > 📷 **[이미지 추가 권장]** 구체적으로 어떤 이미지/사진을 넣으면 좋은지 설명

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


# ── 면책조항(Disclaimer) 페이지 생성
def gen_disclaimer(site_name: str, niche: str, contact_email: str) -> str:
    is_ymyl, ymyl_cat = detect_ymyl(niche)
    ymyl_note = f"특히 이 사이트는 '{ymyl_cat}' 관련 정보를 다루므로 관련 법적 면책 내용을 상세히 포함해주세요." if is_ymyl else ""
    return ai_generate(f"""
'{site_name}' 사이트의 면책조항(Disclaimer) 페이지를 작성해주세요.
한국어 HTML 형식으로, 구글 애드센스 심사 기준과 국내 법률에 맞게 작성해주세요.
{ymyl_note}

- 사이트명: {site_name}
- 분야: {niche}
- 연락처: {contact_email}

반드시 포함할 내용:
1. 정보 제공 목적 명시 (전문가 조언 대체 불가)
2. 정확성 보장 불가 면책
3. 외부 링크 책임 면제
4. 수익 보장 불가 (수익 관련 콘텐츠일 경우)
5. 저작권 안내
6. 면책조항 변경 권리 유보
7. 문의처

HTML 태그 포함하여 완성된 콘텐츠만 출력해주세요.
""")


# ── 저자 Bio 페이지 생성
def gen_author_bio(site_name: str, niche: str, author_name: str, expertise: str) -> str:
    return ai_generate(f"""
구글 E-E-A-T(경험·전문성·권위성·신뢰성) 기준에 최적화된 저자 소개(Author Bio) 페이지를 작성해주세요.
한국어 HTML 형식으로 작성해주세요.

- 사이트명: {site_name}
- 분야: {niche}
- 저자명/닉네임: {author_name}
- 전문성/경력: {expertise}

반드시 포함할 내용:
1. 저자 소개 헤더 (이름, 직함/역할)
2. 전문성 증명 (경력, 자격, 경험 연수 등)
3. 이 블로그를 운영하는 이유 (동기·가치관)
4. 독자에게 제공할 수 있는 가치
5. 주요 작성 주제 목록
6. 연락처 또는 SNS 링크 (플레이스홀더)
7. E-E-A-T 신뢰 배지 텍스트 (예: "XX년 경력", "실제 경험 기반")

전문적이고 신뢰감 있게, 그러나 친근한 톤으로 작성해주세요.
HTML 태그 포함하여 완성된 콘텐츠만 출력해주세요.
""")


# ── 콘텐츠 캘린더 AI 생성
def gen_content_calendar(niche: str, start_date: str, weeks: int, per_week: int) -> str:
    total = weeks * per_week
    return ai_generate(f"""
'{niche}' 블로그의 {weeks}주치 콘텐츠 발행 캘린더를 만들어주세요.

- 시작일: {start_date}
- 주당 발행 횟수: {per_week}회
- 총 글 수: {total}개

다음 형식의 마크다운 표로 작성해주세요:

| 주차 | 발행일 | 글 제목 (안) | 키워드 | 검색 의도 | 예상 소요 시간 |

조건:
- AdSense 승인에 유리한 정보형/방법형 주제 위주
- 주제가 겹치지 않게 다양하게
- 초반(1~2주): 기초/입문 주제 → 후반: 심화/비교 주제 순서
- 글 제목은 CTR 높게 (숫자, 질문, "하는 법" 등 포함)
- 각 글은 구글 검색자가 실제로 검색할 법한 키워드 기반

한국어로 작성해주세요.
""", temperature=0.7)


# ── 승인 타이밍 점수 계산 (AI 불필요, 순수 로직)
def calc_timing_score(
    article_count: int,
    domain_months: int,
    monthly_visitors: int,
    has_https: bool,
    has_custom_domain: bool,
    completed_pages: list[str],
) -> dict:
    scores = {}

    # 게시글 수 (30점)
    art_score = min(article_count / 15 * 30, 30)
    scores["게시글 수"] = (round(art_score), 30, f"{article_count}개 (목표 15개+)")

    # 도메인 나이 (20점)
    dom_score = min(domain_months / 6 * 20, 20)
    scores["도메인 나이"] = (round(dom_score), 20, f"{domain_months}개월 (권장 6개월+)")

    # 필수 페이지 (25점, 5종 각 5점)
    page_items = ["개인정보처리방침", "소개(About)", "연락처(Contact)", "sitemap.xml", "robots.txt"]
    done = [p for p in page_items if p in completed_pages]
    page_score = len(done) * 5
    scores["필수 페이지"] = (page_score, 25, f"{len(done)}/5개 완료")

    # HTTPS (10점)
    scores["HTTPS"] = (10 if has_https else 0, 10, "적용됨" if has_https else "미적용")

    # 커스텀 도메인 (10점)
    scores["커스텀 도메인"] = (10 if has_custom_domain else 0, 10, "사용 중" if has_custom_domain else "미사용 (무료 서브도메인)")

    # 방문자 수 (5점)
    vis_score = 5 if monthly_visitors >= 100 else (3 if monthly_visitors >= 50 else (1 if monthly_visitors > 0 else 0))
    scores["월 방문자"] = (vis_score, 5, f"{monthly_visitors:,}명/월 (50명+ 권장)")

    total = sum(v[0] for v in scores.values())
    max_total = sum(v[1] for v in scores.values())
    return {"items": scores, "total": total, "max": max_total}


def timing_verdict(total: int) -> tuple[str, str, str]:
    """(판정, 이모지, 조언) 반환"""
    if total >= 80:
        return "지금 바로 신청하세요!", "🟢", "모든 준비가 충분합니다. AdSense 신청 페이지로 이동하세요."
    elif total >= 65:
        return "1~2주 내 신청 가능", "🟡", "게시글을 조금 더 추가하거나 미완성 페이지를 마무리하면 바로 신청 가능합니다."
    elif total >= 45:
        return "2~4주 더 준비하세요", "🟠", "필수 페이지 완성 + 게시글 추가가 우선입니다. 서두르면 거절될 수 있어요."
    else:
        return "아직 이릅니다", "🔴", "기본 요건이 충족되지 않았습니다. 게시글 작성과 필수 페이지 완성부터 시작하세요."


# ── 메타 디스크립션 일괄 생성
def gen_meta_descriptions(titles: list[str], niche: str) -> str:
    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
    return ai_generate(f"""
아래 블로그 글 제목들에 대해 각각 SEO 최적화 메타 디스크립션을 작성해주세요.

분야: {niche}
제목 목록:
{numbered}

각 제목마다 다음 형식으로 출력해주세요:

**[번호]. [제목]**
→ [메타 디스크립션]

규칙:
- 길이: 한국어 70~80자 (검색 결과에서 잘리지 않게)
- 핵심 키워드 자연스럽게 포함
- "이 글에서는...", "~하는 방법을 알아보세요" 같은 클릭 유도 문구
- 글의 핵심 가치/혜택 명시
- 중복 표현 금지, 각각 다른 스타일로 작성

한국어로 작성해주세요.
""", temperature=0.7)


# ── OG 태그 생성 (순수 템플릿)
def gen_og_tags(title: str, description: str, site_name: str, url: str, image_url: str) -> str:
    safe = lambda s: s.replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!-- Open Graph / SNS 공유 태그 -->
<meta property="og:type"        content="article" />
<meta property="og:title"       content="{safe(title)}" />
<meta property="og:description" content="{safe(description)}" />
<meta property="og:site_name"   content="{safe(site_name)}" />
<meta property="og:url"         content="{safe(url)}" />
<meta property="og:image"       content="{safe(image_url)}" />
<meta property="og:locale"      content="ko_KR" />

<!-- Twitter Card -->
<meta name="twitter:card"        content="summary_large_image" />
<meta name="twitter:title"       content="{safe(title)}" />
<meta name="twitter:description" content="{safe(description)}" />
<meta name="twitter:image"       content="{safe(image_url)}" />"""


# ── 수익 예측 계산
def calc_revenue(monthly_visitors: int, niche_key: str, click_rate: float) -> dict:
    rpm_low, rpm_high = RPM_BY_NICHE.get(niche_key, (1000, 4000))
    clicks = int(monthly_visitors * click_rate / 100)
    rev_low  = int(monthly_visitors / 1000 * rpm_low)
    rev_high = int(monthly_visitors / 1000 * rpm_high)
    annual_low  = rev_low * 12
    annual_high = rev_high * 12
    return {
        "monthly_visitors": monthly_visitors,
        "clicks": clicks,
        "rev_low": rev_low,
        "rev_high": rev_high,
        "annual_low": annual_low,
        "annual_high": annual_high,
        "rpm_low": rpm_low,
        "rpm_high": rpm_high,
    }


# ── 글 일괄 생성 (단순 프롬프트 버전 — 빠른 생성용)
def gen_article_quick(topic: str, niche: str) -> str:
    return ai_generate(f"""
당신은 {niche} 분야 전문 블로거입니다.
구글 E-E-A-T 기준, 3200자 이상의 고품질 블로그 글을 작성해주세요.

주제: {topic}
분야: {niche}

반드시 포함:
- ## 목차 (TOC)
- H2 소제목 4개 이상
- H3 소제목 각 H2 아래 2개 이상
- 경험 기반 문장 ("직접 해보니...", "실제로...")
- 핵심 요약 bullet 5개
- CTA (댓글/구독 유도)
- 해시태그 10개 이상
- 면책조항 (YMYL 해당 시)
- 본문 중간에 마크다운 비교/정리 표 1개 (| 헤더 | 형태)
- 각 H2 섹션마다 이미지 삽입 가이드:
  > 📷 **[이미지 추가 권장]** 어떤 이미지를 넣으면 좋은지 구체적으로 안내
- 도입부 아래 대표 이미지 가이드:
  > 📷 **[대표 이미지]** 메인 썸네일로 적합한 이미지 설명

문체: 친근한 구어체, 자연스럽게
형식: 마크다운만 (HTML 금지)
분량: 3200자 이상 필수
""", temperature=0.8)


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

    tabs = st.tabs([
        "🔍 사이트 분석",
        "📊 승인 준비 대시보드",
        "📄 필수 페이지 생성",
        "✍️ 콘텐츠 생성",
        "🔧 SEO 도구",
        "💹 수익 최적화",
        "📋 승인 가이드",
    ])

    with tabs[0]: _tab_analyze()
    with tabs[1]: _tab_dashboard()
    with tabs[2]: _tab_pages()
    with tabs[3]: _tab_content()
    with tabs[4]: _tab_seo_tools()
    with tabs[5]: _tab_monetize()
    with tabs[6]: _tab_guide()


def _tab_dashboard():
    st.header("📊 승인 준비 대시보드")
    st.caption("신청 타이밍 계산 · 포스팅 현황 트래커 · 콘텐츠 캘린더를 한 곳에서 관리하세요.")

    # ════ 섹션 1: 승인 신청 타이밍 계산기 ════
    st.subheader("① 승인 신청 타이밍 계산기")
    st.info("현재 상태를 입력하면 지금 신청해도 될지 즉시 판단해드립니다.")

    col_a, col_b = st.columns(2)
    with col_a:
        article_count   = st.number_input("현재 게시글 수", min_value=0, max_value=500, value=0, step=1)
        domain_months   = st.number_input("도메인 나이 (개월)", min_value=0, max_value=120, value=0, step=1)
        monthly_visitors = st.number_input("월 방문자 수 (추정)", min_value=0, max_value=100000, value=0, step=10)

    with col_b:
        has_https        = st.checkbox("HTTPS 적용됨", value=False)
        has_custom_domain = st.checkbox("커스텀 도메인 사용 중 (무료 서브도메인 아님)", value=False)
        completed_pages  = st.multiselect(
            "완성된 필수 페이지",
            ["개인정보처리방침", "소개(About)", "연락처(Contact)", "sitemap.xml", "robots.txt"],
        )

    if st.button("🧮 지금 신청해도 될까? 계산하기", type="primary", use_container_width=True):
        result = calc_timing_score(
            article_count, domain_months, monthly_visitors,
            has_https, has_custom_domain, completed_pages,
        )
        verdict, v_icon, advice = timing_verdict(result["total"])
        total, max_s = result["total"], result["max"]
        pct = int(total / max_s * 100)
        color = "#2ecc71" if pct >= 80 else ("#f39c12" if pct >= 65 else ("#e67e22" if pct >= 45 else "#e74c3c"))

        st.markdown(f"""
        <div style="background:#f8f9fa;border-radius:12px;padding:20px;margin:12px 0">
          <div style="font-size:13px;color:#666">신청 준비 점수</div>
          <div style="font-size:42px;font-weight:bold;color:{color}">{total}/{max_s}점 &nbsp;
            <span style="font-size:20px">{v_icon} {verdict}</span>
          </div>
          <div style="background:#ddd;border-radius:6px;height:14px;margin:10px 0">
            <div style="background:{color};width:{pct}%;height:14px;border-radius:6px"></div>
          </div>
          <div style="color:#444;margin-top:8px">💡 {advice}</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("**항목별 상세 점수**")
        cols = st.columns(3)
        for i, (name, (score, max_item, detail)) in enumerate(result["items"].items()):
            icon = "✅" if score == max_item else ("⚠️" if score > 0 else "❌")
            with cols[i % 3]:
                st.markdown(
                    f"**{icon} {name}**  \n"
                    f"<span style='font-size:12px;color:#888'>{detail} ({score}/{max_item}점)</span>",
                    unsafe_allow_html=True,
                )

    st.divider()

    # ════ 섹션 2: 포스팅 현황 트래커 ════
    st.subheader("② 포스팅 현황 트래커")

    col_t1, col_t2, col_t3 = st.columns(3)
    with col_t1:
        current_posts = st.number_input("현재 게시글 수", min_value=0, max_value=500, value=0, step=1, key="tr_cur")
    with col_t2:
        target_posts  = st.number_input("목표 게시글 수", min_value=1, max_value=200, value=20, step=1, key="tr_tgt")
    with col_t3:
        posts_per_week = st.number_input("주당 발행 계획", min_value=1, max_value=14, value=3, step=1, key="tr_pw")

    remaining = max(target_posts - current_posts, 0)
    pct_done  = min(int(current_posts / target_posts * 100), 100)
    weeks_left = -(-remaining // posts_per_week)  # ceiling division
    from datetime import date, timedelta
    eta = date.today() + timedelta(weeks=weeks_left)

    bar_color = "#2ecc71" if pct_done >= 100 else ("#f39c12" if pct_done >= 60 else "#3498db")
    st.markdown(f"""
    <div style="background:#f8f9fa;border-radius:12px;padding:16px;margin:12px 0">
      <div style="display:flex;justify-content:space-between;margin-bottom:6px">
        <span style="font-weight:bold">진행률</span>
        <span style="color:{bar_color};font-weight:bold">{pct_done}%</span>
      </div>
      <div style="background:#ddd;border-radius:6px;height:18px">
        <div style="background:{bar_color};width:{pct_done}%;height:18px;border-radius:6px"></div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("완료", f"{current_posts}개")
    m2.metric("남은 글", f"{remaining}개")
    m3.metric("주당 목표", f"{posts_per_week}개")
    m4.metric("예상 완료일", eta.strftime("%m월 %d일") if remaining > 0 else "완료! 🎉")

    if pct_done >= 100:
        st.success("🎉 목표 달성! 필수 페이지 완성 후 AdSense 신청을 진행하세요.")
    elif pct_done >= 75:
        st.info(f"거의 다 왔어요! {remaining}개만 더 쓰면 신청 가능합니다.")
    else:
        st.warning(f"아직 {remaining}개가 필요합니다. 주당 {posts_per_week}개씩 작성하면 {weeks_left}주 후 완료됩니다.")

    st.divider()

    # ════ 섹션 3: 콘텐츠 캘린더 생성 ════
    st.subheader("③ AI 콘텐츠 캘린더 생성")
    st.caption("주제·발행 주기를 입력하면 날짜별 글 주제를 자동으로 배정합니다.")

    col_c1, col_c2, col_c3, col_c4 = st.columns(4)
    with col_c1:
        cal_niche = st.text_input("블로그 분야", placeholder="예: 재테크", key="cal_niche")
    with col_c2:
        cal_start = st.date_input("시작일", value=date.today(), key="cal_start")
    with col_c3:
        cal_weeks = st.number_input("계획 기간 (주)", min_value=2, max_value=12, value=4, step=1, key="cal_weeks")
    with col_c4:
        cal_freq = st.number_input("주당 발행 횟수", min_value=1, max_value=7, value=3, step=1, key="cal_freq")

    if st.button("📅 콘텐츠 캘린더 생성", use_container_width=True, type="primary", key="btn_calendar"):
        if not cal_niche:
            st.warning("블로그 분야를 입력해주세요.")
        else:
            with st.spinner(f"{cal_weeks}주 · 총 {cal_weeks * cal_freq}개 주제 생성 중..."):
                calendar = gen_content_calendar(
                    niche=cal_niche,
                    start_date=cal_start.strftime("%Y년 %m월 %d일"),
                    weeks=cal_weeks,
                    per_week=cal_freq,
                )
                st.session_state["calendar_result"] = calendar

    if "calendar_result" in st.session_state:
        st.markdown(st.session_state["calendar_result"])
        st.download_button(
            "📥 캘린더 다운로드 (.md)",
            data=st.session_state["calendar_result"],
            file_name="content_calendar.md",
            mime="text/markdown",
            use_container_width=True,
        )


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

    # 4·5번째 버튼 — 면책조항 + 저자 Bio
    st.divider()
    col4, col5 = st.columns(2)
    with col4:
        if st.button("⚠️ 면책조항(Disclaimer) 생성", use_container_width=True):
            if not site_name or not contact_email:
                st.warning("사이트 이름과 이메일을 입력해주세요.")
            else:
                with st.spinner("면책조항 작성 중... (YMYL 분야 자동 감지)"):
                    result = gen_disclaimer(site_name, niche or "일반", contact_email)
                    st.session_state["disclaimer_result"] = result

    with col5:
        author_name = st.text_input("저자명/닉네임", placeholder="예: 머니메이커 김철수", key="pg_author")
        expertise   = st.text_input("전문성/경력", placeholder="예: 10년차 재테크 투자자, 경제학 전공", key="pg_expertise")
        if st.button("✍️ 저자 Bio 페이지 생성", use_container_width=True):
            if not site_name or not niche:
                st.warning("사이트 이름과 분야를 입력해주세요.")
            else:
                with st.spinner("E-E-A-T 최적화 저자 소개 페이지 작성 중..."):
                    result = gen_author_bio(site_name, niche, author_name or "운영자", expertise or "해당 분야 전문 블로거")
                    st.session_state["author_bio_result"] = result

    for key, title in [
        ("privacy_result", "🔒 개인정보처리방침"),
        ("about_result", "👤 소개 페이지"),
        ("contact_result", "📧 연락처 페이지"),
        ("disclaimer_result", "⚠️ 면책조항(Disclaimer)"),
        ("author_bio_result", "✍️ 저자 Bio 페이지"),
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


def _tab_seo_tools():
    st.header("🔧 SEO 도구")
    st.caption("메타 디스크립션 일괄 생성 · OG 태그 생성 · 글 일괄 생성")

    # ════ 섹션 1: 메타 디스크립션 일괄 생성 ════
    st.subheader("① 메타 디스크립션 일괄 생성")
    st.info("글 제목 여러 개를 입력하면 각각 클릭률 높은 설명문을 자동 생성합니다.")

    seo_niche = st.text_input("블로그 분야", placeholder="예: 재테크, IT 리뷰 등", key="seo_niche")
    seo_titles_raw = st.text_area(
        "글 제목 목록 (줄바꿈으로 구분, 최대 10개)",
        placeholder="2026 ETF 투자 완전 정복\n월세 vs 전세 어떤 게 유리할까\n...",
        height=150,
        key="seo_titles",
    )

    if st.button("📝 메타 디스크립션 일괄 생성", type="primary", use_container_width=True):
        titles = [t.strip() for t in seo_titles_raw.splitlines() if t.strip()][:10]
        if not titles or not seo_niche:
            st.warning("분야와 제목을 입력해주세요.")
        else:
            with st.spinner(f"{len(titles)}개 메타 디스크립션 생성 중..."):
                result = gen_meta_descriptions(titles, seo_niche)
                st.session_state["meta_result"] = result

    if "meta_result" in st.session_state:
        st.markdown(st.session_state["meta_result"])
        st.download_button(
            "📥 메타 디스크립션 다운로드 (.md)",
            data=st.session_state["meta_result"],
            file_name="meta_descriptions.md",
            mime="text/markdown",
            use_container_width=True,
        )

    st.divider()

    # ════ 섹션 2: OG 태그 생성기 ════
    st.subheader("② OG 태그 생성기 (SNS 공유 최적화)")
    st.info("SNS 공유 시 썸네일·제목·설명이 제대로 뜨도록 OG 태그를 생성합니다.")

    og_col1, og_col2 = st.columns(2)
    with og_col1:
        og_title    = st.text_input("페이지 제목", placeholder="2026 ETF 투자 완전 정복", key="og_title")
        og_site     = st.text_input("사이트명", placeholder="스마트 재테크 블로그", key="og_site")
        og_url      = st.text_input("페이지 URL", placeholder="https://yourblog.com/etf-2026", key="og_url")
    with og_col2:
        og_desc     = st.text_area("설명 (70~80자)", placeholder="ETF 투자 처음이라면? 2026년 추천 ETF TOP 7을 수익률·안전성 기준으로 비교합니다.", height=100, key="og_desc")
        og_image    = st.text_input("대표 이미지 URL", placeholder="https://yourblog.com/images/etf.jpg", key="og_img")

    if st.button("🏷️ OG 태그 생성", use_container_width=True):
        if not og_title:
            st.warning("최소한 제목을 입력해주세요.")
        else:
            tags = gen_og_tags(og_title, og_desc, og_site, og_url, og_image)
            st.session_state["og_result"] = tags

    if "og_result" in st.session_state:
        st.markdown("**생성된 OG 태그** — `<head>` 안에 붙여넣으세요")
        st.code(st.session_state["og_result"], language="html")
        st.download_button(
            "📥 OG 태그 다운로드",
            data=st.session_state["og_result"],
            file_name="og_tags.html",
            mime="text/html",
            use_container_width=True,
        )

    st.divider()

    # ════ 섹션 3: 글 일괄 생성 ════
    st.subheader("③ 글 일괄 생성 (최대 5개)")
    st.info("주제 여러 개를 한 번에 입력하면 순서대로 자동 생성합니다.")

    bulk_niche = st.text_input("블로그 분야", placeholder="예: 재테크", key="bulk_niche")
    bulk_topics_raw = st.text_area(
        "생성할 글 주제 (줄바꿈으로 구분, 최대 5개)",
        placeholder="2026 ETF 투자 완전 정복\n월세 vs 전세 어느 쪽이 유리할까\n직장인 절세 방법 5가지",
        height=130,
        key="bulk_topics",
    )

    if st.button("🚀 일괄 글 생성 시작", type="primary", use_container_width=True, key="btn_bulk"):
        topics = [t.strip() for t in bulk_topics_raw.splitlines() if t.strip()][:5]
        if not topics or not bulk_niche:
            st.warning("분야와 주제를 입력해주세요.")
        else:
            bulk_results = {}
            progress = st.progress(0, text="준비 중...")
            for idx, topic in enumerate(topics):
                progress.progress((idx) / len(topics), text=f"[{idx+1}/{len(topics)}] '{topic}' 생성 중...")
                article = gen_article_quick(topic, bulk_niche)
                bulk_results[topic] = article
            progress.progress(1.0, text=f"완료! {len(topics)}개 생성됨")
            st.session_state["bulk_results"] = bulk_results
            st.success(f"✅ {len(topics)}개 글 생성 완료!")

    if "bulk_results" in st.session_state:
        results = st.session_state["bulk_results"]
        art_tabs = st.tabs([f"📄 {t[:20]}..." if len(t) > 20 else f"📄 {t}" for t in results])
        for tab, (topic, article) in zip(art_tabs, results.items()):
            with tab:
                char_total = len(article)
                st.caption(f"글자 수: {char_total:,}자  {'✅ 3200자 충족' if char_total >= 3200 else '⚠️ 3200자 미달'}")
                preview, raw = st.tabs(["미리보기", "원본"])
                with preview:
                    st.markdown(article)
                with raw:
                    st.code(article, language="markdown")
                st.download_button(
                    f"📥 '{topic[:15]}' 다운로드",
                    data=article,
                    file_name=f"{topic[:30].replace(' ','_')}.md",
                    mime="text/markdown",
                    use_container_width=True,
                    key=f"dl_bulk_{topic[:20]}",
                )

        all_text = "\n\n---\n\n".join(
            f"# {t}\n\n{a}" for t, a in results.items()
        )
        st.download_button(
            "📥 전체 글 한번에 다운로드 (.md)",
            data=all_text,
            file_name="bulk_articles.md",
            mime="text/markdown",
            use_container_width=True,
        )


def _tab_monetize():
    st.header("💹 수익 최적화")
    st.caption("광고 배치 전략 · 예상 수익 계산 · 고CPC 분야 랭킹")

    # ════ 섹션 1: 고CPC 분야 랭킹 ════
    st.subheader("① 분야별 CPC·수익성 랭킹")
    st.info("광고 단가(CPC)가 높은 분야를 선택할수록 같은 방문자 수로 더 많이 법니다.")

    import pandas as pd
    df = pd.DataFrame(
        CPC_RANKING,
        columns=["분야", "수익성", "예상 CPC (USD)", "예상 RPM (원)", "경쟁도"],
    )
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption("※ CPC/RPM은 계절·키워드·광고 품질에 따라 크게 달라질 수 있습니다.")

    st.divider()

    # ════ 섹션 2: 수익 예측 계산기 ════
    st.subheader("② 예상 월수익 계산기")

    rev_col1, rev_col2, rev_col3 = st.columns(3)
    with rev_col1:
        rev_visitors = st.number_input("월 방문자 수", min_value=100, max_value=10_000_000, value=5000, step=100, key="rev_vis")
    with rev_col2:
        niche_options = [r[0] for r in CPC_RANKING] + ["기타"]
        rev_niche = st.selectbox("블로그 분야", niche_options, key="rev_niche")
    with rev_col3:
        rev_ctr = st.slider("광고 클릭률 (%)", min_value=0.5, max_value=5.0, value=2.0, step=0.5, key="rev_ctr")

    if st.button("💰 예상 수익 계산", type="primary", use_container_width=True):
        r = calc_revenue(rev_visitors, rev_niche, rev_ctr)
        st.session_state["rev_result"] = r

    if "rev_result" in st.session_state:
        r = st.session_state["rev_result"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("월 방문자", f"{r['monthly_visitors']:,}명")
        c2.metric("월 클릭 수", f"{r['clicks']:,}회")
        c3.metric("예상 월수익", f"{r['rev_low']:,}~{r['rev_high']:,}원")
        c4.metric("예상 연수익", f"{r['annual_low']//10000}~{r['annual_high']//10000}만원")

        st.markdown(f"""
        <div style="background:#f0fff4;border:1px solid #2ecc71;border-radius:10px;padding:16px;margin:12px 0">
          <b>📊 수익 시뮬레이션</b><br>
          월 방문자 <b>{r['monthly_visitors']:,}명</b> × RPM <b>{r['rpm_low']:,}~{r['rpm_high']:,}원</b> 기준<br>
          예상 월수익: <b style="color:#27ae60">{r['rev_low']:,}원 ~ {r['rev_high']:,}원</b><br>
          예상 연수익: <b style="color:#27ae60">{r['annual_low']//10000}만원 ~ {r['annual_high']//10000}만원</b>
        </div>
        """, unsafe_allow_html=True)

        target_visitors = {
            "월 30만원": max(1, int(300000 / (r['rpm_high'] / 1000))),
            "월 100만원": max(1, int(1000000 / (r['rpm_high'] / 1000))),
            "월 300만원": max(1, int(3000000 / (r['rpm_high'] / 1000))),
        }
        st.markdown("**수익 목표별 필요 방문자 (최적 조건 기준)**")
        tc = st.columns(3)
        for i, (goal, vis) in enumerate(target_visitors.items()):
            tc[i].metric(goal, f"{vis:,}명/월")

    st.divider()

    # ════ 섹션 3: 광고 배치 전략 가이드 ════
    st.subheader("③ 광고 배치 전략 가이드")

    st.markdown("""
### 📍 수익 최대화 광고 위치 TOP 5

| 순위 | 위치 | 클릭률 | 설명 |
|------|------|--------|------|
| 1위 | **글 제목 바로 아래** | ⭐⭐⭐⭐⭐ | 독자가 처음 스크롤할 때 가장 먼저 보는 위치 |
| 2위 | **본문 중간 (H2 2번째 이후)** | ⭐⭐⭐⭐⭐ | 독자가 글에 집중한 상태 — 클릭 가능성 최고 |
| 3위 | **글 끝 (CTA 바로 위)** | ⭐⭐⭐⭐ | 글을 다 읽은 독자 → 다음 행동 유도 |
| 4위 | **사이드바** (PC 전용) | ⭐⭐⭐ | 모바일에서는 효과 거의 없음 |
| 5위 | **글 목록 페이지 중간** | ⭐⭐⭐ | 여러 글 훑어보는 독자에게 노출 |

---

### 📱 모바일 vs PC 전략

| 기기 | 추천 광고 형태 | 금지 사항 |
|------|----------------|-----------|
| **모바일** | 반응형(Responsive) · 320×50 앵커 광고 | 전체 화면 팝업, 콘텐츠 가리는 광고 |
| **PC** | 336×280 큰 직사각형 · 사이드바 160×600 | 과도한 광고 (페이지당 3개 이하 권장) |

---

### 🚫 절대 하면 안 되는 것

- **"광고를 클릭해주세요"** 문구 → 즉시 계정 정지
- **광고와 콘텐츠 혼동** → 광고 위에 "추천 링크" 문구 금지
- **자동 새로고침** 페이지에 광고 배치
- **팝업 뒤** 광고 숨기기
- **성인 콘텐츠** 페이지에 광고 삽입
- **페이지당 광고 과다** (3~4개 이하 권장)

---

### 💡 클릭률 높이는 실전 팁

1. **광고 색상을 사이트 테마와 통일** — 자연스럽게 녹아들수록 CTR↑
2. **텍스트 광고보다 이미지+텍스트 혼합형** 선택
3. **본문 1000~1500자 지점에 광고 삽입** — 독자 몰입 최고점
4. **첫 화면(Above the fold)에 광고 1개** — 스크롤 전 노출 확보
5. **A/B 테스트** — 같은 글에 위치 바꿔가며 클릭률 비교
""")

    if st.button("🤖 AI 맞춤 광고 배치 전략 생성", use_container_width=True, key="btn_ad_strategy"):
        sel_niche = st.session_state.get("rev_niche", "")
        sel_vis   = st.session_state.get("rev_vis", 5000)
        with st.spinner("맞춤 광고 전략 생성 중..."):
            strategy = ai_generate(f"""
'{sel_niche}' 분야 블로그 (월 방문자 약 {sel_vis:,}명)에 최적화된
구글 애드센스 광고 배치 전략을 구체적으로 작성해주세요.

포함 내용:
1. 이 분야 독자 특성 분석 (체류 시간, 관심사)
2. 추천 광고 위치 Top 3 (이유 포함)
3. 추천 광고 형태 (반응형/배너/인피드 등)
4. CTR 높이는 테마·색상 설정 팁
5. 수익 극대화를 위한 월별 최적화 계획

한국어로, 실용적이고 구체적으로 작성해주세요.
""")
            st.markdown(strategy)


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
