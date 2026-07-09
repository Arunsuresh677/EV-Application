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


def fresh_connector(client) -> str:  # noqa: ARG001 — `client` just ensures the DB is initialized
    """A brand-new operator/station/connector, isolated from both the seeded
    demo data and every other test. Tests that reserve/occupy a connector
    and don't release it would otherwise exhaust the small shared pool of
    seeded connectors and starve later tests — this sidesteps that."""
    conn = db.get_conn()
    now = db.now_iso()
    operator_id = db.new_id()
    station_id = db.new_id()
    connector_id = db.new_id()
    with db.transaction() as c:
        c.execute("INSERT INTO operators (id, company_name, status, created_at) VALUES (?, 'Test Co', 'active', ?)", (operator_id, now))
        c.execute(
            "INSERT INTO stations (id, operator_id, name, address, lat, lng, status, ocpp_charge_point_id, created_at) "
            "VALUES (?, ?, 'Test Station', '1 Test St', 11.0168, 76.9558, 'online', ?, ?)",
            (station_id, operator_id, f"CP-{station_id[:8]}", now),
        )
        c.execute(
            "INSERT INTO connectors (id, station_id, ocpp_connector_id, type, power_kw, status, reliability_score, guaranteed, updated_at) "
            "VALUES (?, ?, 1, 'CCS2', 50, 'available', 95, 1, ?)",
            (connector_id, station_id, now),
        )
    return connector_id


def add_vehicle(client, token) -> str:
    res = client.post(
        "/v1/users/me/vehicles",
        json={"make": "Test", "model": "EV", "connector_type": "CCS2", "battery_capacity_kwh": 50},
        headers=auth_headers(token),
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]
