-- Users (synced from Clerk via webhook)
create table if not exists users (
  id          text primary key,          -- Clerk user ID (user_xxx)
  email       text not null unique,
  name        text,
  plan        text not null default 'free' check (plan in ('free', 'pro', 'business')),
  created_at  timestamptz not null default now()
);

-- API keys
create table if not exists api_keys (
  id          uuid primary key default gen_random_uuid(),
  user_id     text not null references users(id) on delete cascade,
  key_hash    text not null unique,       -- sha256 of the actual key, never store plaintext
  key_prefix  text not null,             -- first 8 chars shown in UI, e.g. "sk_live_"
  name        text not null default 'Default',
  created_at  timestamptz not null default now(),
  last_used   timestamptz
);

-- Usage logs
create table if not exists usage_logs (
  id          bigserial primary key,
  user_id     text not null references users(id) on delete cascade,
  key_id      uuid references api_keys(id) on delete set null,
  endpoint    text not null,             -- '/analyze', '/quick-score', '/metadata'
  url         text,                      -- URL that was analyzed
  score       int,
  status      int not null default 200,
  duration_ms int,
  created_at  timestamptz not null default now()
);

-- Index for fast per-user daily usage queries
create index if not exists usage_logs_user_date
  on usage_logs (user_id, created_at desc);

-- View: requests today per user
create or replace view usage_today as
  select
    user_id,
    count(*) as requests
  from usage_logs
  where created_at >= current_date
  group by user_id;
