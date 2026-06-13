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
        elif settings.max_reviews < 10000:
            settings.max_reviews = 10000
        session.commit()


def ensure_lightweight_migrations() -> None:
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.execute(text("alter table companies add column if not exists reddit_enabled boolean not null default false"))
            connection.execute(text("alter table reviews add column if not exists l2_theme text"))
            connection.execute(text("create index if not exists reviews_l2_theme_idx on reviews(l2_theme)"))
            connection.execute(text("alter table themes add column if not exists l2_subthemes jsonb not null default '[]'::jsonb"))
            connection.execute(text("alter table settings alter column max_reviews set default 10000"))
        elif engine.dialect.name == "sqlite":
            columns = {row[1] for row in connection.execute(text("pragma table_info(companies)"))}
            if "reddit_enabled" not in columns:
                connection.execute(text("alter table companies add column reddit_enabled boolean not null default 0"))
            review_columns = {row[1] for row in connection.execute(text("pragma table_info(reviews)"))}
            if "l2_theme" not in review_columns:
                connection.execute(text("alter table reviews add column l2_theme varchar"))
            theme_columns = {row[1] for row in connection.execute(text("pragma table_info(themes)"))}
            if "l2_subthemes" not in theme_columns:
                connection.execute(text("alter table themes add column l2_subthemes json default '[]'"))


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
