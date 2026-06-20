from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_config
from app.models import Base, Settings


def engine_options(database_url: str) -> dict:
    options = {"pool_pre_ping": True}
    if database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        # Supabase's transaction pooler does not preserve backend sessions for
        # psycopg prepared statements, so disable automatic preparation.
        options["connect_args"] = {"prepare_threshold": None}
        # The app is a single long-running worker plus polling UI requests.
        # Supabase's pooler should own connection reuse; keeping a local
        # QueuePool can exhaust slots during Render blue/green deploy overlap.
        options["poolclass"] = NullPool
    return options


database_url = get_config().effective_database_url
engine = create_engine(database_url, **engine_options(database_url))
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_lightweight_migrations()
    with SessionLocal() as session:
        settings = session.get(Settings, 1)
        if settings is None:
            session.add(Settings(id=1))
        elif settings.max_reviews > 5000:
            settings.max_reviews = 5000
        session.commit()


def ensure_lightweight_migrations() -> None:
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.execute(text("alter table companies add column if not exists maps_enabled boolean not null default false"))
            connection.execute(text("alter table companies add column if not exists maps_location_hint text not null default 'India'"))
            connection.execute(text("alter table companies add column if not exists reddit_enabled boolean not null default false"))
            connection.execute(text("alter table companies add column if not exists business_type text not null default 'other'"))
            connection.execute(text("alter table companies add column if not exists selected_sources jsonb"))
            connection.execute(
                text(
                    """
                    update companies
                    set selected_sources = jsonb_build_array('play', 'appstore')
                        || case when maps_enabled then jsonb_build_array('maps') else '[]'::jsonb end
                        || case when reddit_enabled then jsonb_build_array('reddit') else '[]'::jsonb end
                    where selected_sources is null
                    """
                )
            )
            connection.execute(text("alter table companies alter column selected_sources set default '[\"play\", \"appstore\"]'::jsonb"))
            connection.execute(text("alter table companies alter column selected_sources set not null"))
            connection.execute(text("alter table companies add column if not exists analysis_goals jsonb not null default '[]'::jsonb"))
            connection.execute(text("alter table companies add column if not exists maps_url text"))
            connection.execute(text("alter table companies add column if not exists instagram_url text"))
            connection.execute(text("alter table companies add column if not exists twitter_url text"))
            connection.execute(text("alter table companies add column if not exists mouthshut_url text"))
            connection.execute(text("alter table companies add column if not exists owner_user_id uuid"))
            connection.execute(text("alter table companies add column if not exists guest_id text"))
            connection.execute(text("create index if not exists companies_owner_user_id_idx on companies(owner_user_id)"))
            connection.execute(text("create index if not exists companies_guest_id_idx on companies(guest_id)"))
            connection.execute(text("alter table runs add column if not exists owner_user_id uuid"))
            connection.execute(text("alter table runs add column if not exists guest_id text"))
            connection.execute(text("create index if not exists runs_owner_user_id_idx on runs(owner_user_id)"))
            connection.execute(text("create index if not exists runs_guest_id_idx on runs(guest_id)"))
            connection.execute(
                text(
                    """
                    create table if not exists users (
                        id uuid primary key,
                        email text not null unique,
                        display_name text,
                        created_at timestamptz not null default now(),
                        last_seen_at timestamptz not null default now()
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    create table if not exists user_sessions (
                        id uuid primary key,
                        user_id uuid not null references users(id),
                        token_hash text not null unique,
                        expires_at timestamptz not null,
                        created_at timestamptz not null default now()
                    )
                    """
                )
            )
            connection.execute(text("create index if not exists user_sessions_user_id_idx on user_sessions(user_id)"))
            connection.execute(text("create index if not exists user_sessions_expires_at_idx on user_sessions(expires_at)"))
            connection.execute(text("alter table reviews add column if not exists l2_theme text"))
            connection.execute(text("create index if not exists reviews_l2_theme_idx on reviews(l2_theme)"))
            connection.execute(text("alter table themes add column if not exists l2_subthemes jsonb not null default '[]'::jsonb"))
            connection.execute(text("alter table settings alter column max_reviews set default 5000"))
            connection.execute(text("alter type review_source add value if not exists 'instagram'"))
            connection.execute(text("alter type review_source add value if not exists 'twitter'"))
            connection.execute(
                text(
                    """
                    create table if not exists worker_leases (
                        name text primary key,
                        owner text not null,
                        locked_until timestamptz not null,
                        updated_at timestamptz not null default now()
                    )
                    """
                )
            )
            connection.execute(text("alter table reviews drop column if exists bucket"))
            connection.execute(text("alter table themes drop column if exists bucket"))
            connection.execute(text("alter table reviews drop column if exists english_gloss"))
            connection.execute(text("alter table reviews drop column if exists severity"))
            connection.execute(text("drop type if exists review_bucket"))
        elif engine.dialect.name == "sqlite":
            columns = {row[1] for row in connection.execute(text("pragma table_info(companies)"))}
            if "maps_enabled" not in columns:
                connection.execute(text("alter table companies add column maps_enabled boolean not null default 0"))
            if "maps_location_hint" not in columns:
                connection.execute(text("alter table companies add column maps_location_hint varchar not null default 'India'"))
            if "reddit_enabled" not in columns:
                connection.execute(text("alter table companies add column reddit_enabled boolean not null default 0"))
            if "business_type" not in columns:
                connection.execute(text("alter table companies add column business_type varchar not null default 'other'"))
            if "selected_sources" not in columns:
                connection.execute(text("alter table companies add column selected_sources json"))
                connection.execute(
                    text(
                        """
                        update companies
                        set selected_sources = case
                            when maps_enabled = 1 and reddit_enabled = 1 then '["play", "appstore", "maps", "reddit"]'
                            when maps_enabled = 1 then '["play", "appstore", "maps"]'
                            when reddit_enabled = 1 then '["play", "appstore", "reddit"]'
                            else '["play", "appstore"]'
                        end
                        """
                    )
                )
            if "analysis_goals" not in columns:
                connection.execute(text("alter table companies add column analysis_goals json not null default '[]'"))
            if "maps_url" not in columns:
                connection.execute(text("alter table companies add column maps_url varchar"))
            if "instagram_url" not in columns:
                connection.execute(text("alter table companies add column instagram_url varchar"))
            if "twitter_url" not in columns:
                connection.execute(text("alter table companies add column twitter_url varchar"))
            if "mouthshut_url" not in columns:
                connection.execute(text("alter table companies add column mouthshut_url varchar"))
            if "owner_user_id" not in columns:
                connection.execute(text("alter table companies add column owner_user_id varchar"))
            if "guest_id" not in columns:
                connection.execute(text("alter table companies add column guest_id varchar"))
            run_columns = {row[1] for row in connection.execute(text("pragma table_info(runs)"))}
            if "owner_user_id" not in run_columns:
                connection.execute(text("alter table runs add column owner_user_id varchar"))
            if "guest_id" not in run_columns:
                connection.execute(text("alter table runs add column guest_id varchar"))
            connection.execute(
                text(
                    """
                    create table if not exists users (
                        id varchar primary key,
                        email varchar not null unique,
                        display_name varchar,
                        created_at datetime default current_timestamp,
                        last_seen_at datetime default current_timestamp
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    create table if not exists user_sessions (
                        id varchar primary key,
                        user_id varchar not null,
                        token_hash varchar not null unique,
                        expires_at datetime not null,
                        created_at datetime default current_timestamp
                    )
                    """
                )
            )
            review_columns = {row[1] for row in connection.execute(text("pragma table_info(reviews)"))}
            if "l2_theme" not in review_columns:
                connection.execute(text("alter table reviews add column l2_theme varchar"))
            if "bucket" in review_columns:
                _drop_sqlite_column(connection, "reviews", "bucket")
            if "english_gloss" in review_columns:
                _drop_sqlite_column(connection, "reviews", "english_gloss")
            if "severity" in review_columns:
                _drop_sqlite_column(connection, "reviews", "severity")
            theme_columns = {row[1] for row in connection.execute(text("pragma table_info(themes)"))}
            if "l2_subthemes" not in theme_columns:
                connection.execute(text("alter table themes add column l2_subthemes json default '[]'"))
            if "bucket" in theme_columns:
                _drop_sqlite_column(connection, "themes", "bucket")
            connection.execute(
                text(
                    """
                    create table if not exists worker_leases (
                        name varchar primary key,
                        owner varchar not null,
                        locked_until datetime not null,
                        updated_at datetime not null default current_timestamp
                    )
                    """
                )
            )


def _drop_sqlite_column(connection, table_name: str, column_name: str) -> None:
    try:
        connection.execute(text(f"alter table {table_name} drop column {column_name}"))
    except Exception:
        # Older SQLite builds cannot drop columns. Local dev DBs can be recreated;
        # production Supabase uses the Postgres path above.
        pass


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
