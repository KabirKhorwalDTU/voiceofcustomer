create extension if not exists pgcrypto;

do $$ begin
    create type run_status as enum ('queued', 'scraping', 'classifying', 'done', 'partial', 'failed');
exception
    when duplicate_object then null;
end $$;

do $$ begin
    create type review_source as enum ('play', 'appstore', 'reddit', 'maps', 'mouthshut', 'instagram', 'twitter');
exception
    when duplicate_object then null;
end $$;

create table if not exists companies (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    play_id text,
    app_id text,
    domain text,
    brand_keyword text not null,
    maps_enabled boolean not null default false,
    maps_location_hint text not null default 'India',
    reddit_enabled boolean not null default false,
    business_type text not null default 'other',
    selected_sources jsonb not null default '["play", "appstore"]'::jsonb,
    analysis_goals jsonb not null default '[]'::jsonb,
    maps_url text,
    instagram_url text,
    twitter_url text,
    mouthshut_url text,
    created_at timestamptz not null default now()
);

create unique index if not exists companies_play_id_unique
    on companies (play_id)
    where play_id is not null and play_id <> '';

create unique index if not exists companies_app_id_unique
    on companies (app_id)
    where app_id is not null and app_id <> '';

create table if not exists runs (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id) on delete cascade,
    status run_status not null default 'queued',
    model_used text,
    source_counts jsonb not null default '{}'::jsonb,
    completeness jsonb not null default '{}'::jsonb,
    cost_estimate numeric(10, 4) not null default 0,
    budget_cap numeric(10, 4) not null default 1,
    dedup_ratio numeric(6, 4) not null default 0,
    quarantine_rate numeric(6, 4) not null default 0,
    started_at timestamptz,
    finished_at timestamptz,
    error text,
    created_at timestamptz not null default now()
);

create index if not exists runs_company_started_idx on runs(company_id, started_at desc);
create index if not exists runs_status_idx on runs(status);

create table if not exists reviews (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references runs(id) on delete cascade,
    company_id uuid not null references companies(id) on delete cascade,
    review_hash text not null,
    source review_source not null,
    date date,
    rating integer,
    text text not null,
    language text not null default 'other',
    theme text,
    l2_theme text,
    representative_flag boolean not null default false,
    created_at timestamptz not null default now(),
    constraint reviews_rating_check check (rating is null or (rating >= 1 and rating <= 5)),
    constraint reviews_run_hash_unique unique (run_id, review_hash)
);

create index if not exists reviews_run_idx on reviews(run_id);
create index if not exists reviews_company_theme_idx on reviews(company_id, theme);
create index if not exists reviews_l2_theme_idx on reviews(l2_theme);
create index if not exists reviews_source_idx on reviews(source);
create index if not exists reviews_company_hash_idx on reviews(company_id, review_hash);

create table if not exists themes (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references runs(id) on delete cascade,
    company_id uuid not null references companies(id) on delete cascade,
    theme text not null,
    count integer not null default 0,
    normalized_frequency numeric(8, 6) not null default 0,
    avg_severity numeric(6, 4) not null default 0,
    theme_score numeric(10, 6) not null default 0,
    rank integer not null,
    top_quotes jsonb not null default '[]'::jsonb,
    l2_subthemes jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists themes_run_rank_idx on themes(run_id, rank);

create table if not exists run_logs (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references runs(id) on delete cascade,
    company_id uuid not null references companies(id) on delete cascade,
    stage text not null,
    event text not null,
    status text not null default 'info',
    source text,
    provider text,
    model text,
    attempt integer,
    cost_usd numeric(10, 6) not null default 0,
    input_tokens integer not null default 0,
    output_tokens integer not null default 0,
    total_tokens integer not null default 0,
    details jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists run_logs_run_created_idx on run_logs(run_id, created_at);
create index if not exists run_logs_company_created_idx on run_logs(company_id, created_at);
create index if not exists run_logs_stage_idx on run_logs(stage);
create index if not exists run_logs_source_idx on run_logs(source);
create index if not exists run_logs_status_idx on run_logs(status);

create table if not exists settings (
    id integer primary key default 1 check (id = 1),
    provider text not null default 'gemini',
    model text not null default 'gemini-3.1-flash-lite',
    max_reviews integer not null default 5000,
    batch_size integer not null default 100,
    recency_window_days integer not null default 90,
    dedup_threshold numeric(5, 4) not null default 0.86,
    per_run_budget_usd numeric(10, 4) not null default 1,
    source_weights jsonb not null default '{"play":1,"appstore":1,"reddit":1,"maps":1,"mouthshut":1,"instagram":1,"twitter":1}'::jsonb,
    updated_at timestamptz not null default now()
);

insert into settings (id)
values (1)
on conflict (id) do nothing;

alter table companies add column if not exists maps_enabled boolean not null default false;
alter table companies add column if not exists maps_location_hint text not null default 'India';
alter table companies add column if not exists reddit_enabled boolean not null default false;
alter table companies add column if not exists business_type text not null default 'other';
alter table companies add column if not exists selected_sources jsonb;
update companies
set selected_sources = jsonb_build_array('play', 'appstore')
    || case when maps_enabled then jsonb_build_array('maps') else '[]'::jsonb end
    || case when reddit_enabled then jsonb_build_array('reddit') else '[]'::jsonb end
where selected_sources is null;
alter table companies alter column selected_sources set default '["play", "appstore"]'::jsonb;
alter table companies alter column selected_sources set not null;
alter table companies add column if not exists analysis_goals jsonb not null default '[]'::jsonb;
alter table companies add column if not exists maps_url text;
alter table companies add column if not exists instagram_url text;
alter table companies add column if not exists twitter_url text;
alter table companies add column if not exists mouthshut_url text;
alter type review_source add value if not exists 'instagram';
alter type review_source add value if not exists 'twitter';
alter table reviews add column if not exists l2_theme text;
alter table themes add column if not exists l2_subthemes jsonb not null default '[]'::jsonb;
alter table reviews drop column if exists bucket;
alter table themes drop column if exists bucket;
alter table reviews drop column if exists english_gloss;
alter table reviews drop column if exists severity;
drop type if exists review_bucket;
