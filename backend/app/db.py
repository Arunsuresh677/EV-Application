"""Thin stdlib sqlite3 wrapper — no ORM.

Kept deliberately simple: one shared connection per process (SQLite handles
concurrent readers fine for this dev/demo scale; a production swap to
Postgres would go through the same query call sites, just via psycopg/asyncpg
instead). WAL mode lets the FastAPI event loop and the OCPP simulator task
read/write concurrently without "database is locked" errors.
"""
from __future__ import annotations

import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "evplatform.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema_sqlite.sql"

_local = threading.local()


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


def init_db(reset: bool = False) -> None:
    if reset and DB_PATH.exists():
        DB_PATH.unlink()
        for suffix in ("-wal", "-shm"):
            p = Path(str(DB_PATH) + suffix)
            if p.exists():
                p.unlink()
    conn = get_conn()
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


@contextmanager
def transaction():
    """Wrap a block of writes in a single BEGIN/COMMIT (rolls back on error)."""
    conn = get_conn()
    conn.execute("BEGIN")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def new_id() -> str:
    return uuid.uuid4().hex


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def rows_to_list(rows) -> list:
    return [dict(r) for r in rows]
