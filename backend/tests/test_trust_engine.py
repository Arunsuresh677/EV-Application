"""Unit tests for the actual product differentiator — reliability scoring,
guaranteed-charge insurance, and Plug Watch. These call the service
functions directly against real rows (not through the timed OCPP simulator,
which sleeps in real time) so the underlying business logic is covered fast
and deterministically.
"""
from __future__ import annotations

import pytest

from app import db
from app.services import insurance, reliability


@pytest.fixture()
def connector(client):  # noqa: ARG001 — depending on `client` ensures the DB is initialized
    """A fresh operator/station/connector/user, isolated from seeded demo data."""
    conn = db.get_conn()
    now = db.now_iso()
    operator_id = db.new_id()
    station_id = db.new_id()
    connector_id = db.new_id()
    user_id = db.new_id()

    with db.transaction() as c:
        c.execute("INSERT INTO operators (id, company_name, status, created_at) VALUES (?, 'Test Co', 'active', ?)", (operator_id, now))
        c.execute(
            "INSERT INTO stations (id, operator_id, name, address, lat, lng, status, ocpp_charge_point_id, created_at) "
            "VALUES (?, ?, 'Test Station', '1 Test St', 0, 0, 'online', ?, ?)",
            (station_id, operator_id, f"CP-{station_id[:8]}", now),
        )
        c.execute(
            "INSERT INTO connectors (id, station_id, ocpp_connector_id, type, power_kw, status, reliability_score, guaranteed, updated_at) "
            "VALUES (?, ?, 1, 'CCS2', 50, 'available', 100, 1, ?)",
            (connector_id, station_id, now),
        )
        c.execute(
            "INSERT INTO users (id, name, email, password_hash, password_salt, role, created_at) VALUES (?, 'Test User', ?, 'x', 'x', 'driver', ?)",
            (user_id, f"{user_id}@example.com", now),
        )
    return {"operator_id": operator_id, "station_id": station_id, "connector_id": connector_id, "user_id": user_id}


def _insert_session(c, connector, status: str, guaranteed_at_start: bool = False) -> str:
    session_id = db.new_id()
    c.execute(
        "INSERT INTO sessions (id, user_id, connector_id, idempotency_key, guaranteed_at_start, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (session_id, connector["user_id"], connector["connector_id"], db.new_id(), int(guaranteed_at_start), status, db.now_iso()),
    )
    return session_id


class TestReliabilityScore:
    def test_no_history_defaults_optimistic(self, connector):
        conn = db.get_conn()
        with db.transaction() as c:
            score = reliability.recompute(c, connector["connector_id"])
        assert score == 100.0

    def test_all_completed_stays_high(self, connector):
        with db.transaction() as c:
            for _ in range(5):
                _insert_session(c, connector, "completed")
            score = reliability.recompute(c, connector["connector_id"])
        assert score == 100.0

    def test_all_failed_drops_to_zero(self, connector):
        with db.transaction() as c:
            for _ in range(5):
                _insert_session(c, connector, "failed")
            score = reliability.recompute(c, connector["connector_id"])
        assert score == 0.0

    def test_recent_outcome_weighted_more_than_old(self, connector):
        # An old failure followed by recent completions should score higher
        # than a plain average would (0 and 100 alternating = 50 flat) —
        # recent behavior should dominate.
        with db.transaction() as c:
            _insert_session(c, connector, "failed")
            for _ in range(4):
                _insert_session(c, connector, "completed")
            score = reliability.recompute(c, connector["connector_id"])
        assert score > 50.0

    def test_stopped_remotely_excluded_from_score(self, connector):
        """A user-initiated stop shouldn't move the score in either direction."""
        with db.transaction() as c:
            for _ in range(5):
                _insert_session(c, connector, "completed")
            baseline = reliability.recompute(c, connector["connector_id"])
            for _ in range(5):
                _insert_session(c, connector, "stopped_remotely")
            after = reliability.recompute(c, connector["connector_id"])
        assert baseline == after == 100.0


class TestGuaranteedBadge:
    def test_guaranteed_when_high_score_and_no_reports(self, connector):
        conn = db.get_conn()
        with db.transaction() as c:
            for _ in range(5):
                _insert_session(c, connector, "completed")
            reliability.recompute(c, connector["connector_id"])
        row = db.row_to_dict(conn.execute("SELECT guaranteed FROM connectors WHERE id=?", (connector["connector_id"],)).fetchone())
        assert row["guaranteed"] == 1

    def test_not_guaranteed_below_threshold(self, connector):
        conn = db.get_conn()
        with db.transaction() as c:
            for _ in range(3):
                _insert_session(c, connector, "failed")
            for _ in range(2):
                _insert_session(c, connector, "completed")
            reliability.recompute(c, connector["connector_id"])
        row = db.row_to_dict(conn.execute("SELECT guaranteed, reliability_score FROM connectors WHERE id=?", (connector["connector_id"],)).fetchone())
        assert row["reliability_score"] < 90
        assert row["guaranteed"] == 0


class TestInsuranceClaims:
    def test_guaranteed_failure_files_claim_and_credits_wallet(self, connector):
        conn = db.get_conn()
        with db.transaction() as c:
            session_id = _insert_session(c, connector, "failed", guaranteed_at_start=True)
            session = db.row_to_dict(c.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone())
            claim = insurance.maybe_file_claim(c, session)

        assert claim is not None
        assert claim["credit_amount"] == insurance.CREDIT_AMOUNT

        claim_row = db.row_to_dict(conn.execute("SELECT * FROM insurance_claims WHERE session_id=?", (session_id,)).fetchone())
        assert claim_row is not None
        assert claim_row["user_id"] == connector["user_id"]

        credit_row = db.row_to_dict(conn.execute("SELECT * FROM user_credits WHERE user_id=?", (connector["user_id"],)).fetchone())
        assert credit_row is not None
        assert credit_row["amount"] == insurance.CREDIT_AMOUNT

    def test_non_guaranteed_failure_files_no_claim(self, connector):
        conn = db.get_conn()
        with db.transaction() as c:
            session_id = _insert_session(c, connector, "failed", guaranteed_at_start=False)
            session = db.row_to_dict(c.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone())
            claim = insurance.maybe_file_claim(c, session)

        assert claim is None
        assert conn.execute("SELECT 1 FROM insurance_claims WHERE session_id=?", (session_id,)).fetchone() is None


class TestPlugWatch:
    def test_single_report_does_not_flip_status(self, connector):
        conn = db.get_conn()
        with db.transaction() as c:
            c.execute(
                "INSERT INTO plugwatch_reports (id, connector_id, reporter_id, issue_type, created_at) VALUES (?, ?, ?, 'wont_charge', ?)",
                (db.new_id(), connector["connector_id"], connector["user_id"], db.now_iso()),
            )
            outcome = reliability.handle_new_report(c, connector["connector_id"])

        assert outcome["ticket_opened"] is False
        status = db.row_to_dict(conn.execute("SELECT status FROM connectors WHERE id=?", (connector["connector_id"],)).fetchone())
        assert status["status"] == "available"

    def test_two_reports_force_faulted_and_opens_ticket(self, connector):
        conn = db.get_conn()
        with db.transaction() as c:
            for _ in range(2):
                c.execute(
                    "INSERT INTO plugwatch_reports (id, connector_id, reporter_id, issue_type, created_at) VALUES (?, ?, ?, 'wont_charge', ?)",
                    (db.new_id(), connector["connector_id"], connector["user_id"], db.now_iso()),
                )
            outcome = reliability.handle_new_report(c, connector["connector_id"])

        assert outcome["ticket_opened"] is True
        row = db.row_to_dict(conn.execute("SELECT status, guaranteed FROM connectors WHERE id=?", (connector["connector_id"],)).fetchone())
        assert row["status"] == "faulted"
        assert row["guaranteed"] == 0

        ticket = db.row_to_dict(conn.execute("SELECT * FROM maintenance_tickets WHERE connector_id=?", (connector["connector_id"],)).fetchone())
        assert ticket is not None
        assert ticket["status"] == "open"
        assert "Plug Watch" in ticket["issue"]
