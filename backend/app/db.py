from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_config
from app.models import Base, Settings


def engine_options(database_url: str) -> dict:
    options = {"pool_pre_ping": True}
    if database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        # Supabase's transaction pooler does not preserve backend sessions for
        # psycopg prepared statements, so disable automatic preparation.
        options["connect_args"] = {"prepare_threshold": None}
    return options


database_url = get_config().effective_database_url
engine = create_engine(database_url, **engine_options(database_url))
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        if session.get(Settings, 1) is None:
            session.add(Settings(id=1))
            session.commit()


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
