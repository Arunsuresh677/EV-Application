"""Reservations — docs/api-spec.yaml documented this and the schema already
had the table; these tests cover the actual implementation: hold a
connector, cancel frees it, starting a session fulfills it, and expiry is
lazy (checked whenever relevant data is read, not on a timer).
"""
from __future__ import annotations

from app import db

from .conftest import add_vehicle, auth_headers, fresh_connector, register_driver, unique_email


class TestReservationLifecycle:
    def test_reserve_holds_connector_and_lists_it(self, client):
        driver = register_driver(client)
        token = driver["token"]
        connector_id = fresh_connector(client)

        res = client.post("/v1/reservations", json={"connector_id": connector_id}, headers=auth_headers(token))
        assert res.status_code == 201, res.text
        reservation = res.json()
        assert reservation["status"] == "active"
        assert reservation["connector_id"] == connector_id

        mine = client.get("/v1/users/me/reservations", headers=auth_headers(token)).json()
        assert any(r["id"] == reservation["id"] for r in mine)

    def test_reserving_already_reserved_connector_fails(self, client):
        first_token = register_driver(client)["token"]
        connector_id = fresh_connector(client)
        first = client.post("/v1/reservations", json={"connector_id": connector_id}, headers=auth_headers(first_token))
        assert first.status_code == 201

        second_token = register_driver(client)["token"]
        second = client.post("/v1/reservations", json={"connector_id": connector_id}, headers=auth_headers(second_token))
        assert second.status_code == 409

    def test_cancel_frees_the_connector(self, client):
        token = register_driver(client)["token"]
        connector_id = fresh_connector(client)
        reservation = client.post("/v1/reservations", json={"connector_id": connector_id}, headers=auth_headers(token)).json()

        cancel = client.post(f"/v1/reservations/{reservation['id']}/cancel", headers=auth_headers(token))
        assert cancel.status_code == 200
        assert cancel.json()["status"] == "cancelled"

        # Freed up — someone else can reserve it now.
        other_token = register_driver(client)["token"]
        res = client.post("/v1/reservations", json={"connector_id": connector_id}, headers=auth_headers(other_token))
        assert res.status_code == 201

    def test_cannot_cancel_someone_elses_reservation(self, client):
        owner_token = register_driver(client)["token"]
        connector_id = fresh_connector(client)
        reservation = client.post("/v1/reservations", json={"connector_id": connector_id}, headers=auth_headers(owner_token)).json()

        other_token = register_driver(client)["token"]
        res = client.post(f"/v1/reservations/{reservation['id']}/cancel", headers=auth_headers(other_token))
        assert res.status_code == 404


class TestReservationFulfillment:
    def test_starting_session_with_reservation_succeeds_and_fulfills_it(self, client):
        token = register_driver(client)["token"]
        vehicle_id = add_vehicle(client, token)
        connector_id = fresh_connector(client)
        reservation = client.post("/v1/reservations", json={"connector_id": connector_id}, headers=auth_headers(token)).json()

        session_res = client.post(
            "/v1/sessions",
            json={"connector_id": connector_id, "vehicle_id": vehicle_id, "reservation_id": reservation["id"]},
            headers={**auth_headers(token), "Idempotency-Key": unique_email("reservation-session")},
        )
        assert session_res.status_code == 201, session_res.text

        mine = client.get("/v1/users/me/reservations", headers=auth_headers(token)).json()
        fulfilled = next(r for r in mine if r["id"] == reservation["id"])
        assert fulfilled["status"] == "fulfilled"

    def test_wrong_users_reservation_id_rejected(self, client):
        owner_token = register_driver(client)["token"]
        connector_id = fresh_connector(client)
        reservation = client.post("/v1/reservations", json={"connector_id": connector_id}, headers=auth_headers(owner_token)).json()

        other_token = register_driver(client)["token"]
        other_vehicle = add_vehicle(client, other_token)
        res = client.post(
            "/v1/sessions",
            json={"connector_id": connector_id, "vehicle_id": other_vehicle, "reservation_id": reservation["id"]},
            headers={**auth_headers(other_token), "Idempotency-Key": unique_email("wrong-reservation")},
        )
        assert res.status_code == 404


class TestReservationExpiry:
    def test_expired_reservation_frees_connector_lazily(self, client):
        token = register_driver(client)["token"]
        connector_id = fresh_connector(client)
        reservation = client.post("/v1/reservations", json={"connector_id": connector_id}, headers=auth_headers(token)).json()

        # Force it into the past directly — the API only allows 1-120 minute
        # holds, so this is the only way to test lazy expiry without a real wait.
        conn = db.get_conn()
        with db.transaction() as c:
            c.execute("UPDATE reservations SET expiry_time = '2000-01-01T00:00:00.000Z' WHERE id=?", (reservation["id"],))

        # Any read path that touches reservations should lazily expire it.
        mine = client.get("/v1/users/me/reservations", headers=auth_headers(token)).json()
        expired = next(r for r in mine if r["id"] == reservation["id"])
        assert expired["status"] == "expired"

        # And the connector should be free again for someone else.
        other_token = register_driver(client)["token"]
        res = client.post("/v1/reservations", json={"connector_id": connector_id}, headers=auth_headers(other_token))
        assert res.status_code == 201
