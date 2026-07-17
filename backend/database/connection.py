"""
database/connection.py — SQLAlchemy engine and session factory.

Usage:
    from database.connection import init_db, get_session

    init_db()                    # Create all tables (idempotent)
    with get_session() as sess:  # Yields a session, commits on exit
        ...

Database URL handling:
    - sqlite:///<path>           → local file (default for dev/test)
    - sqlite:///:memory:         → in-memory (used by tests)
    - postgres://...             → normalized to postgresql+psycopg2://
    - postgresql://...           → normalized to postgresql+psycopg2://
    - postgresql+psycopg2://...  → used as-is

Neon (and other managed Postgres providers) typically issue connection strings
in the legacy ``postgres://`` form. SQLAlchemy 2.x rejects that scheme, so we
normalise eagerly and force the psycopg2 driver to match the pinned dependency
in requirements.txt.
"""

from __future__ import annotations

import re
from collections.abc import Generator
from contextlib import contextmanager
from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from config import DATABASE_URL
from database.models import Base

_engine: Engine | None = None
_SessionFactory: sessionmaker | None = None


def _validate_neon_host(url: str) -> None:
    """Raise ValueError for Neon URLs missing the region segment.

    Modern Neon connection strings embed the region: e.g.
    ``ep-cool-name-12345.ap-southeast-1.aws.neon.tech``. A bare
    ``ep-cool-name-12345.neon.tech`` does not resolve via DNS, and psycopg2's
    error ("could not translate host name") obscures the root cause.
    """
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return
    if not host.endswith(".neon.tech"):
        return
    # Acceptable hosts have at least 4 dot-separated labels:
    #   ep-<id>.<region>.<cloud>.neon.tech
    # Plus optional `-pooler` suffix on the endpoint label, which is fine.
    if host.count(".") < 3:
        raise ValueError(
            f"Neon hostname {host!r} is missing the region segment. "
            "Expected the form 'ep-<id>.<region>.<cloud>.neon.tech' "
            "(e.g. 'ep-cool-name-12345.ap-southeast-1.aws.neon.tech'). "
            "Copy the connection string from the Neon dashboard's "
            "'Connection Details' panel and update CDT_DATABASE_URL."
        )


_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((?:https?://)?[^)\s]+\)")


def _strip_markdown_links(url: str) -> str:
    """Replace any ``[label](target)`` fragments with just ``label``.

    Tools like Slack, Notion, and some markdown editors auto-format hostnames
    as links; pasting the result into ``CDT_DATABASE_URL`` produces a string
    such as ``postgresql://u:p@[host.neon.tech](http://host.neon.tech)/db``,
    which psycopg2 then rejects with a cryptic DNS error. Unwrapping the
    label lets downstream parsing and Neon-host validation work as intended.
    """
    return _MARKDOWN_LINK_RE.sub(r"\1", url)


def _normalize_db_url(url: str) -> str:
    """Normalise a database URL for SQLAlchemy 2.x.

    - Strips surrounding whitespace (a frequent copy-paste artefact in
      ``.streamlit/secrets.toml`` and shell exports).
    - Unwraps markdown-link syntax (``[host](http://host)``) that some tools
      insert when a hostname is pasted from a rich-text source.
    - ``postgres://...`` (Neon, Heroku-style) → ``postgresql://...``
    - ``postgresql://...`` (no driver) → ``postgresql+psycopg2://...``
    - Validates Neon hostnames so a missing region segment fails fast with a
      helpful error rather than a cryptic DNS failure inside psycopg2.
    - All other schemes (sqlite, postgresql+psycopg2, etc.) returned unchanged.
    """
    url = _strip_markdown_links(url.strip())
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    if url.startswith("postgresql+psycopg2://"):
        _validate_neon_host(url)
    return url


def get_engine() -> Engine:
    """Return (and lazily create) the shared SQLAlchemy engine."""
    global _engine
    if _engine is None:
        url = _normalize_db_url(DATABASE_URL)
        connect_args: dict = {}
        engine_kwargs: dict = {"echo": False}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        else:
            # Managed Postgres (Neon) closes idle connections aggressively;
            # pool_pre_ping detects stale connections before they cause errors.
            engine_kwargs["pool_pre_ping"] = True
        _engine = create_engine(
            url,
            connect_args=connect_args,
            **engine_kwargs,
        )
    return _engine


def init_db() -> None:
    """Create all tables (dev/test convenience). Production schema is managed
    exclusively by Alembic (``alembic upgrade head``); this create_all path
    exists for local SQLite and the in-memory test fixtures only."""
    engine = get_engine()
    Base.metadata.create_all(bind=engine)


def _get_session_factory() -> sessionmaker:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(), autoflush=True, autocommit=False)
    return _SessionFactory


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context manager that provides a transactional database session.

    Commits on clean exit; rolls back on exception.
    """
    factory = _get_session_factory()
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
