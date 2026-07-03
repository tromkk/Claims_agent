"""Engine/session management. The engine is created lazily so tests can point
DATABASE_URL at a temporary database before first use."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from config import get_settings
from db.models import Base, Policy

logger = logging.getLogger(__name__)

_engine = None
_session_factory = None


def get_engine():
    global _engine, _session_factory
    if _engine is None:
        url = get_settings().database_url
        if url.startswith("sqlite:///"):
            db_path = Path(url.removeprefix("sqlite:///"))
            if str(db_path) != ":memory:":
                db_path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(url)
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def reset_engine() -> None:
    """Dispose the engine so the next access re-reads settings (used by tests)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


@contextmanager
def get_session() -> Iterator[Session]:
    get_engine()
    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    Base.metadata.create_all(get_engine())


def ensure_seeded() -> None:
    """Create tables and seed demo data if the database is empty. Idempotent."""
    init_db()
    with get_session() as session:
        if session.execute(select(Policy).limit(1)).first() is None:
            from db.seed import seed

            logger.info("Empty database detected, seeding demo data")
            seed(session)
