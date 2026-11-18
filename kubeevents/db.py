"""Datenbank-Engine, Schema und Volltextindex."""

import logging
from collections.abc import Iterator
from functools import cache
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, event, text
from sqlmodel import Session, SQLModel, create_engine

from kubeevents.config import get_settings
from kubeevents.models import K8sEvent

logger = logging.getLogger(__name__)

FTS_TABLE = "k8sevent_fts"
# Spalten, die die Freitextsuche durchsucht
FTS_COLUMNS = (
    "message",
    "name",
    "involved_name",
    "involved_kind",
    "namespace",
    "reason",
    "type",
    "component",
    "host",
)

# Indizes aus früheren Schema-Versionen, die keine Abfrage mehr nutzt
OBSOLETE_INDEXES = (
    "ix_k8sevent_uid_count",
    "ix_k8sevent_uid",
    "ix_k8sevent_name",
    "ix_k8sevent_reason",
    "ix_k8sevent_involved_name",
    "ix_k8sevent_component",
    "ix_k8sevent_host",
    "ix_k8sevent_first_timestamp",
    "ix_k8sevent_last_timestamp",
    "ix_k8sevent_count",
    "ix_k8sevent_created_at",
)

SQLITE_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA busy_timeout=5000",
    "PRAGMA foreign_keys=ON",
)


def _set_sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    try:
        for pragma in SQLITE_PRAGMAS:
            cursor.execute(pragma)
    finally:
        cursor.close()


@cache
def get_engine() -> Engine:
    db_path = Path(get_settings().db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    event.listen(engine, "connect", _set_sqlite_pragmas)
    return engine


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def init_db() -> None:
    """Legt Tabelle, Indizes und Volltextindex an und räumt alte Indizes ab."""
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        for name in OBSOLETE_INDEXES:
            conn.execute(text(f"DROP INDEX IF EXISTS {name}"))
        # create_all legt Indizes nur für neue Tabellen an
        for index in K8sEvent.__table__.indexes:  # type: ignore[attr-defined]
            index.create(conn, checkfirst=True)
        _setup_fulltext(conn)
    logger.info("Database initialized at %s", get_settings().db_path)


def _setup_fulltext(conn: Connection) -> None:
    """FTS5-Tabelle mit Trigramm-Tokenizer, damit die Suche Teilstrings findet wie LIKE '%q%'."""
    exists = conn.execute(
        text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :name"), {"name": FTS_TABLE}
    ).first()

    cols = ", ".join(FTS_COLUMNS)
    new_cols = ", ".join(f"new.{c}" for c in FTS_COLUMNS)
    old_cols = ", ".join(f"old.{c}" for c in FTS_COLUMNS)

    conn.execute(
        text(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE} USING fts5("
            f"{cols}, content='k8sevent', content_rowid='id', tokenize='trigram')"
        )
    )
    conn.execute(
        text(
            f"CREATE TRIGGER IF NOT EXISTS {FTS_TABLE}_ai AFTER INSERT ON k8sevent BEGIN "
            f"INSERT INTO {FTS_TABLE}(rowid, {cols}) VALUES (new.id, {new_cols}); END"
        )
    )
    conn.execute(
        text(
            f"CREATE TRIGGER IF NOT EXISTS {FTS_TABLE}_ad AFTER DELETE ON k8sevent BEGIN "
            f"INSERT INTO {FTS_TABLE}({FTS_TABLE}, rowid, {cols}) VALUES ('delete', old.id, {old_cols}); END"
        )
    )
    conn.execute(
        text(
            f"CREATE TRIGGER IF NOT EXISTS {FTS_TABLE}_au AFTER UPDATE ON k8sevent BEGIN "
            f"INSERT INTO {FTS_TABLE}({FTS_TABLE}, rowid, {cols}) VALUES ('delete', old.id, {old_cols}); "
            f"INSERT INTO {FTS_TABLE}(rowid, {cols}) VALUES (new.id, {new_cols}); END"
        )
    )

    if not exists:
        logger.info("Building full-text index for existing events")
        conn.execute(text(f"INSERT INTO {FTS_TABLE}({FTS_TABLE}) VALUES ('rebuild')"))
