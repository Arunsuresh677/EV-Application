"""Session-start correctness (idempotency, ownership) and the fleet module —
including a regression test for the "fleet driver can't start a session with
their assigned vehicle" bug found while building it (fixed in
routers/sessions.py by also checking the fleet_drivers link, not just
vehicles.user_id).
"""
from __future__ import annotations

import time

from app import db

from .conftest import (
    add_vehicle as _add_vehicle,
    auth_headers,
    fresh_connector,
    register_driver,
    unique_email,
)


class TestIdempotentSessionStart:
    def test_same_idempotency_key_returns_same_session(self, client):
        driver = register_driver(client)
        token = driver["token"]
        vehicle_id = _add_vehicle(client, token)
        connector_id = fresh_connector(client)

        body = {"connector_id": connector_id, "vehicle_id": vehicle_id}
        key = unique_email("idem-key")  # any unique string works as the key

        first = client.post("/v1/sessions", json=body, headers={**auth_headers(token), "Idempotency-Key": key})
        second = client.post("/v1/sessions", json=body, headers={**auth_headers(token), "Idempotency-Key": key})

        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["id"] == second.json()["id"]

    def test_occupied_connector_rejects_new_session(self, client):
        driver = register_driver(client)
        token = driver["token"]
        vehicle_id = _add_vehicle(client, token)
        connector_id = fresh_connector(client)

        first = client.post(
            "/v1/sessions",
            json={"connector_id": connector_id, "vehicle_id": vehicle_id},
            headers={**auth_headers(token), "Idempotency-Key": unique_email("occ-1")},
        )
        assert first.status_code == 201

        time.sleep(0.5)  # let the background task mark the connector occupied

        second = client.post(
            "/v1/sessions",
            json={"connector_id": connector_id, "vehicle_id": vehicle_id},
            headers={**auth_headers(token), "Idempotency-Key": unique_email("occ-2")},
        )
        assert second.status_code == 409


class TestVehicleOwnership:
    def test_cannot_start_session_with_someone_elses_vehicle(self, client):
        owner_token = register_driver(client)["token"]
        vehicle_id = _add_vehicle(client, owner_token)

        other_token = register_driver(client)["token"]
        connector_id = fresh_connector(client)

        res = client.post(
            "/v1/sessions",
            json={"connector_id": connector_id, "vehicle_id": vehicle_id},
            headers={**auth_headers(other_token), "Idempotency-Key": unique_email("wrong-vehicle")},
        )
        assert res.status_code == 404


class TestFleetDriverSessions:
    def test_fleet_driver_sees_assigned_vehicle(self, client):
        res = client.post("/v1/auth/login", json={"email": "fleet-driver@demo.dev", "password": "fleet12345"})
        token = res.json()["token"]
        vehicles = client.get("/v1/users/me/vehicles", headers=auth_headers(token)).json()
        assert len(vehicles) >= 1
        assert any(v["make"] == "Tata" for v in vehicles)

    def test_fleet_driver_can_start_session_with_assigned_vehicle(self, client):
        """Regression test: fleet vehicles are linked via fleet_drivers, not
        vehicles.user_id — session-start must check both places."""
        res = client.post("/v1/auth/login", json={"email": "fleet-driver@demo.dev", "password": "fleet12345"})
        token = res.json()["token"]
        vehicles = client.get("/v1/users/me/vehicles", headers=auth_headers(token)).json()
        fleet_vehicle_id = next(v["id"] for v in vehicles if v["make"] == "Tata")
        connector_id = fresh_connector(client)

        res = client.post(
            "/v1/sessions",
            json={"connector_id": connector_id, "vehicle_id": fleet_vehicle_id},
            headers={**auth_headers(token), "Idempotency-Key": unique_email("fleet-session")},
        )
        assert res.status_code == 201, res.text

    def test_fleet_driver_has_no_personal_payment_method(self, client):
        """'Billing auto-routes to company' — a fleet driver shouldn't need
        (or have) a personal card on file."""
        res = client.post("/v1/auth/login", json={"email": "fleet-driver@demo.dev", "password": "fleet12345"})
        token = res.json()["token"]
        methods = client.get("/v1/payments/methods", headers=auth_headers(token)).json()
        assert methods == []


class TestFleetCostReport:
    def test_cost_report_aggregates_completed_sessions(self, client):
        # A dedicated, fresh fleet — isolated from the shared seeded one so
        # exact-value assertions here are safe regardless of test order.
        reg = client.post(
            "/v1/auth/register-fleet",
            json={"company_name": "Report Test Fleet", "manager_name": "Manager", "email": unique_email("fleet-mgr"), "password": "reportme123"},
        )
        assert reg.status_code == 201
        manager_token = reg.json()["token"]

        driver_email = unique_email("fleet-driver")
        add_driver = client.post(
            "/v1/fleet/drivers",
            json={"name": "Report Driver", "email": driver_email, "password": "reportme123"},
            headers=auth_headers(manager_token),
        )
        assert add_driver.status_code == 201
        driver_user_id = add_driver.json()["user_id"]

        add_vehicle = client.post(
            "/v1/fleet/vehicles",
            json={"make": "Test", "model": "Fleet EV", "connector_type": "CCS2", "battery_capacity_kwh": 40},
            headers=auth_headers(manager_token),
        )
        assert add_vehicle.status_code == 201
        vehicle_id = add_vehicle.json()["id"]

        assign = client.post(
            f"/v1/fleet/drivers/{driver_user_id}/assign-vehicle", json={"vehicle_id": vehicle_id}, headers=auth_headers(manager_token)
        )
        assert assign.status_code == 200

        # Insert a completed session directly — bypassing the real-time OCPP
        # simulator (which sleeps for real seconds) since this test is about
        # the aggregation query, not the simulator.
        conn = db.get_conn()
        with db.transaction() as c:
            c.execute(
                "INSERT INTO sessions (id, user_id, connector_id, vehicle_id, idempotency_key, status, energy_kwh, cost, created_at) "
                "VALUES (?, ?, (SELECT id FROM connectors LIMIT 1), ?, ?, 'completed', 12.5, 5.25, ?)",
                (db.new_id(), driver_user_id, vehicle_id, db.new_id(), db.now_iso()),
            )

        report = client.get("/v1/fleet/cost-report", headers=auth_headers(manager_token)).json()
        assert len(report) == 1
        assert report[0]["driver_name"] == "Report Driver"
        assert report[0]["sessions"] == 1
        assert report[0]["energy_kwh"] == 12.5
        assert report[0]["cost"] == 5.25

    def test_cost_report_csv_export(self, client):
        reg = client.post(
            "/v1/auth/register-fleet",
            json={"company_name": "CSV Test Fleet", "manager_name": "Manager", "email": unique_email("csv-mgr"), "password": "csvtest123"},
        )
        manager_token = reg.json()["token"]

        res = client.get("/v1/fleet/cost-report", params={"format": "csv"}, headers=auth_headers(manager_token))
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/csv")
        assert "driver_name,email,sessions,energy_kwh,cost" in res.text
