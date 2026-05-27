# ContentForge — AI 콘텐츠 생성 SaaS

스타트업·프리랜서를 위한 AI 콘텐츠 생성 도구. 블로그/SNS/마케팅 카피/이메일/피치덱을
한국어·영어로 생성하고, 월 구독(Freemium)으로 수익화한다.

- **메인 앱**: Streamlit (`streamlit_app.py`)
- **결제 웹훅 + Business API**: FastAPI (`fastapi_app.py`)
- **DB + 인증**: Supabase (Postgres + Auth)
- **결제**: Stripe
- **생성 엔진**: Google Gemini

## 핵심 기능

- **13종 생성기**: 블로그, 소셜(LinkedIn/X/Instagram), 마케팅(랜딩·광고·제품·보도자료),
  이메일(뉴스레터·콜드), 스타트업(피치덱·투자자 이메일·월간 업데이트)
- **브랜드 보이스**: 회사 톤·대상·문체 예시를 저장해 모든 생성에 일관 적용 (범용 AI 대비 차별점)
- **재생성 / 변형 3개 / 수정 루프**: 일회성이 아니라 결과를 반복 다듬기
- **한국어·영어** 출력 토글
- **사용량 쿼터 + 공정사용 상한**(무제한 티어 비용 가드레일)

## 요금제

| 플랜 | 가격 | 월 생성 한도 | 기능 |
|------|------|------------|------|
| Free | $0 | 10회 | 전체 생성기 |
| Pro | $15/월 | 100회 | 고품질 모델 |
| Business | $30/월 | 무제한(공정사용 2000) | + REST API |

## 빠른 시작 (로컬 모드 — 외부 계정 불필요)

Supabase/Stripe 없이 **Gemini API 키만** 있으면 전체 앱이 바로 돕니다.
계정·생성물·사용량은 `data/*.json`(gitignore됨)에 로컬 저장되고, 플랜은
계정 페이지에서 버튼으로 직접 전환해 테스트할 수 있습니다.

```bash
cd saas
pip install -r requirements.txt
echo "GEMINI_API_KEY=발급받은키" > .env
streamlit run streamlit_app.py
```

회원가입 → 콘텐츠 생성 → 사용량 쿼터 → 이력 → 플랜 전환까지 그대로 동작합니다.
실제 다중 사용자 서비스로 배포하려면 아래 클라우드 모드를 설정하세요.

## 설치 & 실행 (클라우드 모드 — 실서비스)

```bash
cd saas
pip install -r requirements.txt
cp .env.example .env      # 값 채우기
```

Supabase 자격증명이 채워지면 자동으로 클라우드 모드(멀티유저 + RLS)로 전환됩니다.

### 1. Supabase 설정
1. [supabase.com](https://supabase.com)에서 프로젝트 생성
2. SQL Editor에 `schema.sql` 붙여넣어 실행 (테이블 + RLS 생성)
3. Project Settings → API에서 `URL`, `anon key`, `service_role key`를 `.env`에 입력
4. Authentication → 이메일 인증은 테스트 중엔 꺼두면 가입 즉시 로그인됨

### 2. Stripe 설정
1. Test mode에서 Product 2개 생성: Pro($15/월), Business($30/월) — recurring
2. 각 Price ID(`price_...`)를 `.env`의 `STRIPE_PRICE_PRO`, `STRIPE_PRICE_BUSINESS`에 입력
3. `STRIPE_SECRET_KEY` 입력
4. Customer Portal 활성화 (Settings → Billing → Customer portal)

### 3. 앱 실행
```bash
streamlit run streamlit_app.py          # 메인 앱 (localhost:8501)
uvicorn fastapi_app:app --port 8000     # webhook + API (별도 터미널)
```

### 4. Stripe webhook (로컬 테스트)
```bash
stripe listen --forward-to localhost:8000/stripe/webhook
# 출력된 whsec_... 를 .env의 STRIPE_WEBHOOK_SECRET에 입력
```
Test 카드 `4242 4242 4242 4242`로 결제 → `profiles.tier`가 자동 전환된다.

## Business API 사용 예시
```bash
curl -X POST https://<your-fastapi-host>/v1/generate \
  -H "Authorization: Bearer cf_xxx" \
  -H "Content-Type: application/json" \
  -d '{"type":"blog_seo","language":"ko","params":{"topic":"B2B 온보딩 자동화"}}'
```

## 배포
- Streamlit → Streamlit Community Cloud 또는 Railway/Render
- FastAPI → Railway/Render (`uvicorn fastapi_app:app`), Stripe webhook URL로 등록
- 시크릿은 각 플랫폼 환경변수에 입력

## 새 생성기 추가
`generators/`에 모듈을 만들어 `GENERATORS` 리스트를 정의하고 `generators/base.py`의
`_MODULES`에 추가하면 UI·API에 자동 노출된다.
