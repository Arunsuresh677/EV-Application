"""Seed demo data: two unrelated operators (so the operator dashboard's
multi-tenant isolation is provably testable), each with their own
station_admin login, stations, and tariff. Voltway Networks additionally
gets a demo driver account, a vehicle, a mock payment method, and one
deliberately flaky connector so the Trust Engine+ behavior — reliability
scoring, guaranteed badges, insurance payouts, Plug Watch — is actually
observable.

Run directly (`python -m app.seed`) or import `run()` — idempotent, skips
seeding if the demo driver already exists.
"""
from __future__ import annotations

from . import db
from .auth import hash_password

DEMO_EMAIL = "driver@demo.dev"
DEMO_PASSWORD = "chargeme123"
OPERATOR_EMAIL = "operator@demo.dev"
OPERATOR_PASSWORD = "operate123"
OPERATOR2_EMAIL = "beacon-admin@demo.dev"
OPERATOR2_PASSWORD = "operate123"
SUPER_ADMIN_EMAIL = "admin@voltpath.dev"
SUPER_ADMIN_PASSWORD = "platform123"
FLEET_MANAGER_EMAIL = "fleet-manager@demo.dev"
FLEET_MANAGER_PASSWORD = "fleet12345"
FLEET_DRIVER_EMAIL = "fleet-driver@demo.dev"
FLEET_DRIVER_PASSWORD = "fleet12345"


def _seed_operator(c, now: str, company_name: str, admin_email: str, admin_password: str, admin_name: str, stations: list[dict], tariff_rate: float) -> str:
    operator_id = db.new_id()
    c.execute(
        "INSERT INTO operators (id, company_name, status, created_at) VALUES (?, ?, 'active', ?)",
        (operator_id, company_name, now),
    )

    admin_id = db.new_id()
    pw_hash, salt = hash_password(admin_password)
    c.execute(
        """INSERT INTO users (id, name, email, password_hash, password_salt, role, operator_id, created_at)
           VALUES (?, ?, ?, ?, ?, 'station_admin', ?, ?)""",
        (admin_id, admin_name, admin_email, pw_hash, salt, operator_id, now),
    )

    c.execute(
        "INSERT INTO tariffs (id, operator_id, pricing_model, rate, created_at) VALUES (?, ?, 'per_kwh', ?, ?)",
        (db.new_id(), operator_id, tariff_rate, now),
    )

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
            guaranteed = 1 if (conn_spec["score"] >= 90 and not conn_spec.get("flaky")) else 0
            c.execute(
                """INSERT INTO connectors
                   (id, station_id, ocpp_connector_id, type, power_kw, status, reliability_score, guaranteed, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'available', ?, ?, ?)""",
                (connector_id, station_id, i, conn_spec["type"], conn_spec["power_kw"], conn_spec["score"], guaranteed, now),
            )
            if conn_spec.get("flaky"):
                print(f"Seeded flaky connector {connector_id} at {station['name']} for demoing Trust Engine+ behavior.")

    return operator_id


def run() -> None:
    db.init_db()
    conn = db.get_conn()

    existing = conn.execute("SELECT id FROM users WHERE email = ?", (DEMO_EMAIL,)).fetchone()
    if existing:
        print(f"Seed data already present (user {DEMO_EMAIL} exists) — skipping.")
        return

    now = db.now_iso()

    with db.transaction() as c:
        _seed_operator(
            c, now,
            company_name="Voltway Networks",
            admin_email=OPERATOR_EMAIL,
            admin_password=OPERATOR_PASSWORD,
            admin_name="Voltway Admin",
            tariff_rate=0.42,
            stations=[
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
                {
                    "name": "Gandhipuram Charging Hub",
                    "address": "Gandhipuram, Coimbatore",
                    "lat": 11.0183,
                    "lng": 76.9725,
                    "connectors": [
                        {"power_kw": 60, "type": "CCS2", "score": 96, "flaky": False},
                        {"power_kw": 22, "type": "TYPE2", "score": 92, "flaky": False},
                    ],
                },
                {
                    "name": "RS Puram Fast Charge",
                    "address": "DB Road, RS Puram, Coimbatore",
                    "lat": 11.0018,
                    "lng": 76.9629,
                    "connectors": [
                        {"power_kw": 30, "type": "CCS2", "score": 89, "flaky": False},
                    ],
                },
            ],
        )

        # A second, unrelated operator — exists purely to prove the
        # operator dashboard's tenant isolation: this station_admin must
        # never see Voltway's stations, and vice versa.
        _seed_operator(
            c, now,
            company_name="Beacon EV Networks",
            admin_email=OPERATOR2_EMAIL,
            admin_password=OPERATOR2_PASSWORD,
            admin_name="Beacon Admin",
            tariff_rate=0.38,
            stations=[
                {
                    "name": "Beacon Plaza Charger",
                    "address": "8 Beacon Way",
                    "lat": 37.8199,
                    "lng": -122.2783,
                    "connectors": [
                        {"power_kw": 120, "type": "CCS2", "score": 93, "flaky": False},
                    ],
                },
            ],
        )

        user_id = db.new_id()
        pw_hash, salt = hash_password(DEMO_PASSWORD)
        c.execute(
            """INSERT INTO users (id, name, email, password_hash, password_salt, phone, role, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'driver', ?)""",
            (user_id, "Demo Driver", DEMO_EMAIL, pw_hash, salt, "+1-555-0100", now),
        )

        # Platform super_admin — deliberately no operator_id, since this
        # role sees across every operator (routers/admin.py), not one.
        super_admin_id = db.new_id()
        sa_pw_hash, sa_salt = hash_password(SUPER_ADMIN_PASSWORD)
        c.execute(
            """INSERT INTO users (id, name, email, password_hash, password_salt, role, created_at)
               VALUES (?, ?, ?, ?, ?, 'super_admin', ?)""",
            (super_admin_id, "Platform Admin", SUPER_ADMIN_EMAIL, sa_pw_hash, sa_salt, now),
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

        # Demo fleet: a company that owns EV vehicles and employs drivers —
        # distinct from both a charging-network operator and a personal
        # driver account. The driver has no payment method of their own,
        # since "billing auto-routes to company" (PRD) — see
        # routers/fleet.py's cost-report, which is what actually gets billed.
        fleet_id = db.new_id()
        c.execute("INSERT INTO fleets (id, company_name, created_at) VALUES (?, ?, ?)", (fleet_id, "Zenith Logistics", now))

        fleet_manager_id = db.new_id()
        fm_hash, fm_salt = hash_password(FLEET_MANAGER_PASSWORD)
        c.execute(
            """INSERT INTO users (id, name, email, password_hash, password_salt, role, fleet_id, created_at)
               VALUES (?, ?, ?, ?, ?, 'fleet_manager', ?, ?)""",
            (fleet_manager_id, "Zenith Fleet Manager", FLEET_MANAGER_EMAIL, fm_hash, fm_salt, fleet_id, now),
        )

        fleet_driver_id = db.new_id()
        fd_hash, fd_salt = hash_password(FLEET_DRIVER_PASSWORD)
        c.execute(
            """INSERT INTO users (id, name, email, password_hash, password_salt, role, fleet_id, created_at)
               VALUES (?, ?, ?, ?, ?, 'fleet_driver', ?, ?)""",
            (fleet_driver_id, "Zenith Fleet Driver", FLEET_DRIVER_EMAIL, fd_hash, fd_salt, fleet_id, now),
        )

        fleet_vehicle_id = db.new_id()
        c.execute(
            """INSERT INTO vehicles (id, fleet_id, make, model, connector_type, battery_capacity_kwh, created_at)
               VALUES (?, ?, 'Tata', 'Nexon EV', 'CCS2', 40.5, ?)""",
            (fleet_vehicle_id, fleet_id, now),
        )
        c.execute(
            "INSERT INTO fleet_vehicles (fleet_id, vehicle_id, charge_cap_pct) VALUES (?, ?, 90)",
            (fleet_id, fleet_vehicle_id),
        )
        c.execute(
            "INSERT INTO fleet_drivers (fleet_id, user_id, vehicle_id) VALUES (?, ?, ?)",
            (fleet_id, fleet_driver_id, fleet_vehicle_id),
        )

    print(f"Seed complete. Driver login: {DEMO_EMAIL} / {DEMO_PASSWORD}")
    print(f"Voltway operator login: {OPERATOR_EMAIL} / {OPERATOR_PASSWORD}")
    print(f"Beacon operator login: {OPERATOR2_EMAIL} / {OPERATOR2_PASSWORD}")
    print(f"Platform super_admin login: {SUPER_ADMIN_EMAIL} / {SUPER_ADMIN_PASSWORD}")
    print(f"Zenith fleet manager login: {FLEET_MANAGER_EMAIL} / {FLEET_MANAGER_PASSWORD}")
    print(f"Zenith fleet driver login: {FLEET_DRIVER_EMAIL} / {FLEET_DRIVER_PASSWORD}")


if __name__ == "__main__":
    run()
