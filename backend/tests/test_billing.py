"""Operator billing — the SaaS fee VoltPath charges the charging networks
using the platform. Covers the default free-tier assignment, usage-fee
calculation from real session revenue, invoice idempotency within a billing
period, mock payment, lazy overdue detection, and that a plan downgrade is
rejected when it would leave an operator over the new plan's station limit.
"""
from __future__ import annotations

from app import db

from .conftest import auth_headers, unique_email


def register_operator(client, company_name=None, email=None, password="operate123") -> dict:
    res = client.post(
        "/v1/auth/register-operator",
        json={
            "company_name": company_name or f"Test Charging Co {unique_email('x')}",
            "admin_name": "Test Admin",
            "email": email or unique_email("operator"),
            "password": password,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


class TestDefaultPlan:
    def test_new_operator_starts_on_starter_plan(self, client):
        token = register_operator(client)["token"]
        overview = client.get("/v1/operator/billing", headers=auth_headers(token)).json()
        assert overview["plan"]["id"] == "starter"
        assert overview["subscription_status"] == "active"
        assert overview["current_invoice"]["status"] == "pending"
        assert overview["current_invoice"]["base_fee"] == 0


class TestUsageFee:
    def test_invoice_usage_fee_reflects_completed_session_revenue(self, client):
        token = register_operator(client)["token"]
        me = client.get("/v1/users/me", headers=auth_headers(token)).json()

        station = client.post(
            "/v1/operator/stations",
            json={"name": "Fee Test Station", "address": "1 Fee St", "lat": 11.0, "lng": 76.9},
            headers=auth_headers(token),
        ).json()
        connector = client.post(
            f"/v1/operator/stations/{station['id']}/connectors",
            json={"type": "CCS2", "power_kw": 50},
            headers=auth_headers(token),
        ).json()

        # Insert a completed session directly — the platform fee applies to
        # settled revenue, not the real-time OCPP simulation this test
        # doesn't need to run.
        conn = db.get_conn()
        now = db.now_iso()
        with db.transaction() as c:
            c.execute(
                "INSERT INTO sessions (id, user_id, connector_id, idempotency_key, status, cost, created_at) "
                "VALUES (?, ?, ?, ?, 'completed', 100.0, ?)",
                (db.new_id(), me["id"], connector["id"], db.new_id(), now),
            )

        overview = client.get("/v1/operator/billing", headers=auth_headers(token)).json()
        # Starter plan: 3% platform fee.
        assert overview["current_invoice"]["usage_fee"] == 3.0
        assert overview["current_invoice"]["total"] == 3.0


class TestInvoiceIdempotency:
    def test_reading_billing_twice_does_not_duplicate_the_invoice(self, client):
        token = register_operator(client)["token"]
        first = client.get("/v1/operator/billing", headers=auth_headers(token)).json()
        second = client.get("/v1/operator/billing", headers=auth_headers(token)).json()
        assert first["current_invoice"]["id"] == second["current_invoice"]["id"]

        invoices = client.get("/v1/operator/billing/invoices", headers=auth_headers(token)).json()
        assert len(invoices) == 1


class TestPayInvoice:
    def test_pay_marks_invoice_paid_and_rejects_double_payment(self, client):
        token = register_operator(client)["token"]
        invoice_id = client.get("/v1/operator/billing", headers=auth_headers(token)).json()["current_invoice"]["id"]

        paid = client.post(f"/v1/operator/billing/invoices/{invoice_id}/pay", headers=auth_headers(token))
        assert paid.status_code == 200
        assert paid.json()["status"] == "paid"
        assert paid.json()["paid_at"] is not None

        again = client.post(f"/v1/operator/billing/invoices/{invoice_id}/pay", headers=auth_headers(token))
        assert again.status_code == 409

    def test_cannot_pay_another_operators_invoice(self, client):
        owner_token = register_operator(client)["token"]
        invoice_id = client.get("/v1/operator/billing", headers=auth_headers(owner_token)).json()["current_invoice"]["id"]

        other_token = register_operator(client)["token"]
        res = client.post(f"/v1/operator/billing/invoices/{invoice_id}/pay", headers=auth_headers(other_token))
        assert res.status_code == 404


class TestPlanChange:
    def test_switch_to_growth_plan(self, client):
        token = register_operator(client)["token"]
        res = client.post("/v1/operator/billing/plan", json={"plan_id": "growth"}, headers=auth_headers(token))
        assert res.status_code == 200
        assert res.json()["plan_id"] == "growth"

        overview = client.get("/v1/operator/billing", headers=auth_headers(token)).json()
        assert overview["plan"]["id"] == "growth"

    def test_downgrade_rejected_when_over_new_plans_station_limit(self, client):
        token = register_operator(client)["token"]
        # Starter caps at 2 stations — add 3 to exceed it.
        for i in range(3):
            res = client.post(
                "/v1/operator/stations",
                json={"name": f"Station {i}", "address": "1 St", "lat": 11.0, "lng": 76.9},
                headers=auth_headers(token),
            )
            assert res.status_code == 201

        # Already on starter by default; force onto growth first so the
        # downgrade back to starter is the thing under test.
        client.post("/v1/operator/billing/plan", json={"plan_id": "growth"}, headers=auth_headers(token))

        res = client.post("/v1/operator/billing/plan", json={"plan_id": "starter"}, headers=auth_headers(token))
        assert res.status_code == 409

    def test_unknown_plan_rejected(self, client):
        token = register_operator(client)["token"]
        res = client.post("/v1/operator/billing/plan", json={"plan_id": "does-not-exist"}, headers=auth_headers(token))
        assert res.status_code == 404


class TestOverdueLazyFlip:
    def test_stale_pending_invoice_flips_to_overdue(self, client):
        token = register_operator(client)["token"]
        invoice_id = client.get("/v1/operator/billing", headers=auth_headers(token)).json()["current_invoice"]["id"]

        # Force the period into the distant past directly — same lazy-expiry
        # test pattern as test_reservations.py, since there's no real way to
        # wait a real billing period out in a test.
        conn = db.get_conn()
        with db.transaction() as c:
            c.execute("UPDATE invoices SET period_end = '2000-01-01T00:00:00.000Z' WHERE id=?", (invoice_id,))

        invoices = client.get("/v1/operator/billing/invoices", headers=auth_headers(token)).json()
        stale = next(i for i in invoices if i["id"] == invoice_id)
        assert stale["status"] == "overdue"

        overview = client.get("/v1/operator/billing", headers=auth_headers(token)).json()
        assert overview["subscription_status"] == "past_due"


class TestAdminBillingOverview:
    def test_super_admin_sees_operator_in_platform_billing(self, client):
        token = register_operator(client, company_name=f"Visible Co {unique_email('x')}")["token"]
        me = client.get("/v1/users/me", headers=auth_headers(token)).json()
        company_row = db.row_to_dict(db.get_conn().execute("SELECT operator_id FROM users WHERE id=?", (me["id"],)).fetchone())
        operator_id = company_row["operator_id"]

        super_admin_token = client.post(
            "/v1/auth/login", json={"email": "admin@voltpath.dev", "password": "platform123"}
        ).json()["token"]

        overview = client.get("/v1/admin/billing", headers=auth_headers(super_admin_token)).json()
        assert isinstance(overview["mrr"], float)
        assert any(op["operator_id"] == operator_id for op in overview["operators"])

    def test_station_admin_cannot_access_platform_billing(self, client):
        token = register_operator(client)["token"]
        res = client.get("/v1/admin/billing", headers=auth_headers(token))
        assert res.status_code == 403
