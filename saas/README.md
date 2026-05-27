# ContentForge — AI 콘텐츠 생성 SaaS

스타트업·프리랜서를 위한 AI 콘텐츠 생성 도구. 블로그/SNS/마케팅 카피/이메일/피치덱을
한국어·영어로 생성하고, 월 구독(Freemium)으로 수익화한다.

- **메인 앱**: Streamlit (`streamlit_app.py`)
- **결제 웹훅 + Business API**: FastAPI (`fastapi_app.py`)
- **DB + 인증**: Supabase (Postgres + Auth)
- **결제**: Stripe
- **생성 엔진**: Google Gemini

## 요금제

| 플랜 | 가격 | 월 생성 한도 | 기능 |
|------|------|------------|------|
| Free | $0 | 10회 | 전체 생성기 |
| Pro | $15/월 | 100회 | 고품질 모델 |
| Business | $30/월 | 무제한 | + REST API |

## 설치 & 실행

```bash
cd saas
pip install -r requirements.txt
cp .env.example .env      # 값 채우기
```

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
