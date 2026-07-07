"""Auth, RBAC, and multi-tenant isolation — the actual security boundaries
this platform depends on for being sold to multiple, unrelated customers.

Tests that need a stable seeded account (Voltway/Beacon/etc., created by
app/seed.py) use those directly. Anything destructive (suspending an
account) creates its own fresh operator instead, since other tests rely on
the seeded ones staying active regardless of run order.
"""
from __future__ import annotations

from .conftest import auth_headers, register_driver, unique_email


def login(client, email, password):
    res = client.post("/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()


class TestRegisterAndLogin:
    def test_register_creates_driver_role(self, client):
        data = register_driver(client)
        assert data["user"]["role"] == "driver"
        me = client.get("/v1/users/me", headers=auth_headers(data["token"]))
        assert me.status_code == 200
        assert me.json()["email"] == data["user"]["email"]

    def test_duplicate_email_rejected(self, client):
        email = unique_email("dup")
        register_driver(client, email=email)
        res = client.post("/v1/auth/register", json={"name": "Again", "email": email, "password": "somepass123"})
        assert res.status_code == 409

    def test_wrong_password_rejected(self, client):
        email = unique_email("wrongpw")
        register_driver(client, email=email, password="correct-password")
        res = client.post("/v1/auth/login", json={"email": email, "password": "wrong-password"})
        assert res.status_code == 401


class TestLoginRateLimit:
    def test_exceeding_attempts_returns_429(self, client):
        email = unique_email("bruteforce")
        statuses = [
            client.post("/v1/auth/login", json={"email": email, "password": "guess"}).status_code
            for _ in range(12)
        ]
        assert statuses[:10] == [401] * 10
        assert statuses[10] == 429
        assert statuses[11] == 429


class TestRoleBasedAccess:
    def test_driver_cannot_access_operator_endpoints(self, client):
        driver = register_driver(client)
        res = client.get("/v1/operator/stations", headers=auth_headers(driver["token"]))
        assert res.status_code == 403

    def test_operator_cannot_access_admin_endpoints(self, client):
        token = login(client, "operator@demo.dev", "operate123")["token"]
        res = client.get("/v1/admin/stats", headers=auth_headers(token))
        assert res.status_code == 403

    def test_operator_cannot_access_fleet_endpoints(self, client):
        token = login(client, "operator@demo.dev", "operate123")["token"]
        res = client.get("/v1/fleet/roster", headers=auth_headers(token))
        assert res.status_code == 403

    def test_missing_token_rejected(self, client):
        res = client.get("/v1/operator/stations")
        assert res.status_code == 401


class TestOperatorTenantIsolation:
    def test_voltway_and_beacon_stations_are_disjoint(self, client):
        voltway_token = login(client, "operator@demo.dev", "operate123")["token"]
        beacon_token = login(client, "beacon-admin@demo.dev", "operate123")["token"]

        voltway_stations = client.get("/v1/operator/stations", headers=auth_headers(voltway_token)).json()
        beacon_stations = client.get("/v1/operator/stations", headers=auth_headers(beacon_token)).json()

        assert len(voltway_stations) > 0
        assert len(beacon_stations) > 0
        voltway_ids = {s["id"] for s in voltway_stations}
        beacon_ids = {s["id"] for s in beacon_stations}
        assert voltway_ids.isdisjoint(beacon_ids)

    def test_operator_cannot_patch_another_operators_connector(self, client):
        voltway_token = login(client, "operator@demo.dev", "operate123")["token"]
        beacon_token = login(client, "beacon-admin@demo.dev", "operate123")["token"]

        beacon_stations = client.get("/v1/operator/stations", headers=auth_headers(beacon_token)).json()
        beacon_connector_id = beacon_stations[0]["connectors"][0]["id"]

        res = client.patch(
            f"/v1/operator/connectors/{beacon_connector_id}",
            json={"status": "maintenance"},
            headers=auth_headers(voltway_token),
        )
        assert res.status_code == 404  # not "not owned" — deliberately indistinguishable from not existing


class TestSuspension:
    def test_suspended_operator_blocked_then_reactivated(self, client):
        # A fresh operator, not one of the shared seeded ones — this test
        # is destructive and other tests depend on Voltway/Beacon staying active.
        reg = client.post(
            "/v1/auth/register-operator",
            json={"company_name": "Suspend Test Co", "admin_name": "Test Admin", "email": unique_email("suspend-test"), "password": "suspendme123"},
        )
        assert reg.status_code == 201
        operator_admin_email = reg.json()["user"]["email"]

        super_admin_token = login(client, "admin@voltpath.dev", "platform123")["token"]
        operators = client.get("/v1/admin/operators", headers=auth_headers(super_admin_token)).json()
        target = next(o for o in operators if o["company_name"] == "Suspend Test Co")

        # Suspend it.
        res = client.patch(f"/v1/admin/operators/{target['id']}", json={"status": "suspended"}, headers=auth_headers(super_admin_token))
        assert res.status_code == 200

        operator_token = login(client, operator_admin_email, "suspendme123")["token"]
        blocked = client.get("/v1/operator/stations", headers=auth_headers(operator_token))
        assert blocked.status_code == 403

        # Reactivate it.
        res = client.patch(f"/v1/admin/operators/{target['id']}", json={"status": "active"}, headers=auth_headers(super_admin_token))
        assert res.status_code == 200

        operator_token = login(client, operator_admin_email, "suspendme123")["token"]
        allowed = client.get("/v1/operator/stations", headers=auth_headers(operator_token))
        assert allowed.status_code == 200
