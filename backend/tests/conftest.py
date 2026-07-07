"""Shared test fixtures.

The test DB is one real temp *file* (not `:memory:`) shared for the whole
session — same reasoning as production (backend/app/db.py): FastAPI
dispatches sync `def` endpoints to a thread pool, each thread gets its own
sqlite3 connection, and `:memory:` databases aren't visible across separate
connections. A real file is, so every thread sees the same data.

Tests don't get a wiped DB between each other — instead, each test creates
its own uniquely-named data (see `unique_email`) rather than assuming it's
the only row in a table. This sidesteps a real risk with per-test resets:
a stale sqlite3 connection cached in a reused thread-pool worker thread
would otherwise keep pointing at a deleted file.
"""
from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("EVPLATFORM_SECRET_KEY", "dGVzdC1zZWNyZXQta2V5LWZvci10ZXN0aW5nLW9ubHkh")

from app import db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _test_database(tmp_path_factory):
    db.DB_PATH = tmp_path_factory.mktemp("data") / "test.db"
    db.init_db(reset=True)


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def register_driver(client, name="Test Driver", email=None, password="testpass123") -> dict:
    email = email or unique_email("driver")
    res = client.post("/v1/auth/register", json={"name": name, "email": email, "password": password})
    assert res.status_code == 201, res.text
    return res.json()


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
