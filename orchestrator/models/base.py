"""SQLAlchemy base and session management."""

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from orchestrator.config import get_settings


class Base(DeclarativeBase):
    pass


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, connection_record) -> None:
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()


@lru_cache
def get_engine():
    settings = get_settings()
    connect_args = {}
    if settings.database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(settings.database_url, connect_args=connect_args)


@lru_cache
def get_session_factory():
    return sessionmaker(bind=get_engine(), autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    from sqlalchemy import inspect, text

    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    if inspector.has_table("registration_requests"):
        columns = {col["name"] for col in inspector.get_columns("registration_requests")}
        if "display_code" not in columns:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE registration_requests "
                        "ADD COLUMN display_code VARCHAR(6) NOT NULL DEFAULT '000000'"
                    )
                )
    if inspector.has_table("jobs"):
        job_columns = {col["name"] for col in inspector.get_columns("jobs")}
        with engine.begin() as conn:
            if "stage" not in job_columns:
                conn.execute(text("ALTER TABLE jobs ADD COLUMN stage VARCHAR(32)"))
            if "stage_updated_at" not in job_columns:
                conn.execute(text("ALTER TABLE jobs ADD COLUMN stage_updated_at DATETIME"))
