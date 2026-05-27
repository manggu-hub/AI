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

-- ── workspaces / 팀 협업
create table if not exists public.workspaces (
    id          uuid primary key default gen_random_uuid(),
    owner_id    uuid not null references public.profiles(id) on delete cascade,
    owner_email text,
    name        text not null,
    created_at  timestamptz not null default now()
);

create table if not exists public.workspace_members (
    workspace_id uuid not null references public.workspaces(id) on delete cascade,
    email        text not null,
    role         text not null default 'member',
    primary key (workspace_id, email)
);

-- ── brand_profiles (브랜드 보이스 — 차별화 핵심, 개인 또는 워크스페이스 공유)
create table if not exists public.brand_profiles (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null references public.profiles(id) on delete cascade,
    workspace_id uuid references public.workspaces(id) on delete cascade,  -- null = 개인
    name         text not null,
    company      text,
    tone         text,
    audience     text,
    sample       text,          -- 참고 문체 예시
    avoid        text,          -- 피해야 할 표현/금칙어
    created_at   timestamptz not null default now()
);

-- ── integrations (발행 연동: webhook / wordpress)
create table if not exists public.integrations (
    id         uuid primary key default gen_random_uuid(),
    user_id    uuid not null references public.profiles(id) on delete cascade,
    type       text not null,           -- 'webhook' | 'wordpress'
    name       text not null,
    config     jsonb not null,          -- {url} 또는 {site_url, username, app_password}
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
alter table public.profiles          enable row level security;
alter table public.subscriptions     enable row level security;
alter table public.usage_counters    enable row level security;
alter table public.generations       enable row level security;
alter table public.workspaces        enable row level security;
alter table public.workspace_members enable row level security;
alter table public.brand_profiles    enable row level security;
alter table public.integrations      enable row level security;
alter table public.api_keys          enable row level security;

create policy "own profile"       on public.profiles       for all using (auth.uid() = id)      with check (auth.uid() = id);
create policy "own subscriptions" on public.subscriptions  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own usage"         on public.usage_counters for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own generations"   on public.generations    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own integrations"  on public.integrations   for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own api_keys"      on public.api_keys       for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- 워크스페이스: 소유자이거나, 내 이메일이 멤버로 등록된 경우 접근
create policy "ws access" on public.workspaces for all
    using (owner_id = auth.uid()
           or exists (select 1 from public.workspace_members m
                      where m.workspace_id = id and m.email = (auth.jwt() ->> 'email')))
    with check (owner_id = auth.uid());

-- 멤버 목록: 해당 워크스페이스 소유자가 관리, 본인 행은 열람 가능
create policy "ws members" on public.workspace_members for all
    using (email = (auth.jwt() ->> 'email')
           or exists (select 1 from public.workspaces w
                      where w.id = workspace_id and w.owner_id = auth.uid()))
    with check (exists (select 1 from public.workspaces w
                        where w.id = workspace_id and w.owner_id = auth.uid()));

-- 브랜드: 내 개인 브랜드이거나, 내가 접근 가능한 워크스페이스의 브랜드
create policy "brand access" on public.brand_profiles for all
    using (
        (workspace_id is null and user_id = auth.uid())
        or exists (select 1 from public.workspaces w
                   where w.id = workspace_id
                     and (w.owner_id = auth.uid()
                          or exists (select 1 from public.workspace_members m
                                     where m.workspace_id = w.id and m.email = (auth.jwt() ->> 'email')))))
    with check (user_id = auth.uid());

-- service_role 키(FastAPI webhook)는 RLS를 우회하므로 별도 정책 불필요.
-- ⚠️ 워크스페이스 공유 정책은 실제 Supabase 배포 후 2개 계정으로 검증 필요(여기선 로컬 모드로만 테스트됨).
