-- ════════════════════════════════════════════════════════
--  ContentForge SaaS — Supabase 스키마
--  Supabase 대시보드 → SQL Editor 에 붙여넣어 실행하세요.
-- ════════════════════════════════════════════════════════

-- ── profiles (auth.users 와 1:1)
create table if not exists public.profiles (
    id                 uuid primary key references auth.users(id) on delete cascade,
    email              text,
    stripe_customer_id text,
    tier               text not null default 'free',
    created_at         timestamptz not null default now()
);

-- ── subscriptions
create table if not exists public.subscriptions (
    id                     uuid primary key default gen_random_uuid(),
    user_id                uuid not null references public.profiles(id) on delete cascade,
    stripe_subscription_id text unique,
    stripe_price_id        text,
    status                 text,
    current_period_end     timestamptz,
    created_at             timestamptz not null default now(),
    updated_at             timestamptz not null default now()
);

-- ── usage_counters (유저 × 월 1행)
create table if not exists public.usage_counters (
    id        uuid primary key default gen_random_uuid(),
    user_id   uuid not null references public.profiles(id) on delete cascade,
    period    text not null,                -- 'YYYY-MM' (KST)
    count     int  not null default 0,
    unique(user_id, period)
);

-- ── generations (출력 저장 + 감사 로그)
create table if not exists public.generations (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null references public.profiles(id) on delete cascade,
    type         text,
    language     text,
    input_params jsonb,
    output_text  text,
    model        text,
    created_at   timestamptz not null default now()
);

-- ── brand_profiles (브랜드 보이스 — 차별화 핵심)
create table if not exists public.brand_profiles (
    id         uuid primary key default gen_random_uuid(),
    user_id    uuid not null references public.profiles(id) on delete cascade,
    name       text not null,
    company    text,
    tone       text,
    audience   text,
    sample     text,          -- 참고 문체 예시
    avoid      text,          -- 피해야 할 표현/금칙어
    created_at timestamptz not null default now()
);

-- ── api_keys (Business 티어 프로그래매틱 접근)
create table if not exists public.api_keys (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null references public.profiles(id) on delete cascade,
    key_hash     text not null,             -- SHA-256 해시만 저장
    label        text,
    created_at   timestamptz not null default now(),
    last_used_at timestamptz,
    revoked      boolean not null default false
);

-- ════════════════════════════════════════════════════════
--  Row Level Security: 각 유저는 자기 행만 접근
-- ════════════════════════════════════════════════════════
alter table public.profiles       enable row level security;
alter table public.subscriptions  enable row level security;
alter table public.usage_counters enable row level security;
alter table public.generations    enable row level security;
alter table public.brand_profiles enable row level security;
alter table public.api_keys       enable row level security;

create policy "own profile"       on public.profiles       for all using (auth.uid() = id)      with check (auth.uid() = id);
create policy "own subscriptions" on public.subscriptions  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own usage"         on public.usage_counters for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own generations"   on public.generations    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own brands"        on public.brand_profiles for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own api_keys"      on public.api_keys       for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- service_role 키(FastAPI webhook)는 RLS를 우회하므로 별도 정책 불필요.
