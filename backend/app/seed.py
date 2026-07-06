"""Seed demo data: one operator, three stations (one deliberately flaky
connector so the Trust Engine+ behavior — reliability scoring, guaranteed
badges, insurance payouts — is actually observable), a demo driver account,
a vehicle, and a mock payment method.

Run directly (`python -m app.seed`) or import `run()` — idempotent, skips
seeding if the demo user already exists.
"""
from __future__ import annotations

from . import db
from .auth import hash_password

DEMO_EMAIL = "driver@demo.dev"
DEMO_PASSWORD = "chargeme123"


def run() -> None:
    db.init_db()
    conn = db.get_conn()

    existing = conn.execute("SELECT id FROM users WHERE email = ?", (DEMO_EMAIL,)).fetchone()
    if existing:
        print(f"Seed data already present (user {DEMO_EMAIL} exists) — skipping.")
        return

    now = db.now_iso()

    with db.transaction() as c:
        operator_id = db.new_id()
        c.execute(
            "INSERT INTO operators (id, company_name, status, created_at) VALUES (?, ?, 'active', ?)",
            (operator_id, "Voltway Networks", now),
        )

        user_id = db.new_id()
        pw_hash, salt = hash_password(DEMO_PASSWORD)
        c.execute(
            """INSERT INTO users (id, name, email, password_hash, password_salt, phone, role, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'driver', ?)""",
            (user_id, "Demo Driver", DEMO_EMAIL, pw_hash, salt, "+1-555-0100", now),
        )

        vehicle_id = db.new_id()
        c.execute(
            """INSERT INTO vehicles (id, user_id, make, model, connector_type, battery_capacity_kwh, created_at)
               VALUES (?, ?, 'Hyundai', 'Ioniq 5', 'CCS2', 77.4, ?)""",
            (vehicle_id, user_id, now),
        )

        payment_method_id = db.new_id()
        c.execute(
            """INSERT INTO payment_methods (id, user_id, psp_token, brand, last4, is_default, created_at)
               VALUES (?, ?, 'tok_demo_mock', 'visa', '4242', 1, ?)""",
            (payment_method_id, user_id, now),
        )

        tariff_id = db.new_id()
        c.execute(
            """INSERT INTO tariffs (id, operator_id, pricing_model, rate, created_at)
               VALUES (?, ?, 'per_kwh', 0.42, ?)""",
            (tariff_id, operator_id, now),
        )

        stations = [
            {
                "name": "Downtown Transit Plaza",
                "address": "100 Market St",
                "lat": 37.7935,
                "lng": -122.3964,
                "connectors": [
                    {"power_kw": 150, "type": "CCS2", "score": 97, "flaky": False},
                    {"power_kw": 62.5, "type": "CHAdeMO", "score": 91, "flaky": False},
                ],
            },
            {
                "name": "Riverside Shopping Center",
                "address": "450 Riverside Ave",
                "lat": 37.7749,
                "lng": -122.4194,
                "connectors": [
                    {"power_kw": 50, "type": "CCS2", "score": 55, "flaky": True},
                ],
            },
            {
                "name": "Harborview Garage",
                "address": "22 Harbor Blvd",
                "lat": 37.8044,
                "lng": -122.2712,
                "connectors": [
                    {"power_kw": 350, "type": "CCS2", "score": 95, "flaky": False},
                    {"power_kw": 11, "type": "TYPE2", "score": 88, "flaky": False},
                ],
            },
        ]

        for station in stations:
            station_id = db.new_id()
            cp_id = f"CP-{station_id[:8]}"
            c.execute(
                """INSERT INTO stations (id, operator_id, name, address, lat, lng, status, ocpp_charge_point_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'online', ?, ?)""",
                (station_id, operator_id, station["name"], station["address"], station["lat"], station["lng"], cp_id, now),
            )
            for i, conn_spec in enumerate(station["connectors"], start=1):
                connector_id = db.new_id()
                guaranteed = 1 if (conn_spec["score"] >= 90 and not conn_spec["flaky"]) else 0
                c.execute(
                    """INSERT INTO connectors
                       (id, station_id, ocpp_connector_id, type, power_kw, status, reliability_score, guaranteed, updated_at)
                       VALUES (?, ?, ?, ?, ?, 'available', ?, ?, ?)""",
                    (connector_id, station_id, i, conn_spec["type"], conn_spec["power_kw"], conn_spec["score"], guaranteed, now),
                )
                if conn_spec["flaky"]:
                    print(f"Seeded flaky connector {connector_id} at {station['name']} for demoing Trust Engine+ behavior.")

    print(f"Seed complete. Demo login: {DEMO_EMAIL} / {DEMO_PASSWORD}")


if __name__ == "__main__":
    run()
