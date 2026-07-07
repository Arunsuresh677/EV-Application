"""Fleet manager API — companies that own EV vehicles and employ drivers,
distinct from both charging-network operators (routers/operator.py) and the
platform admin (routers/admin.py). Every route is `fleet_manager`-only and
scoped to the caller's own fleet_id — one company's roster/costs are never
visible to another's.
"""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, EmailStr

from .. import auth, db

router = APIRouter(prefix="/fleet", tags=["fleet"])

require_fleet_manager = auth.require_role("fleet_manager")

CONNECTOR_TYPES = ("CCS2", "CHAdeMO", "TYPE2", "NACS")


# ---------------------------------------------------------------------------
# Roster
# ---------------------------------------------------------------------------

@router.get("/roster")
def get_roster(user: dict = Depends(require_fleet_manager)):
    conn = db.get_conn()
    drivers = db.rows_to_list(
        conn.execute(
            """SELECT u.id AS user_id, u.name AS driver_name, u.email, fd.vehicle_id
               FROM fleet_drivers fd JOIN users u ON u.id = fd.user_id
               WHERE fd.fleet_id = ?""",
            (user["fleet_id"],),
        ).fetchall()
    )

    result = []
    for d in drivers:
        vehicle = None
        status = "needs_attention"  # no vehicle assigned yet
        if d["vehicle_id"]:
            vehicle = db.row_to_dict(conn.execute("SELECT * FROM vehicles WHERE id=?", (d["vehicle_id"],)).fetchone())
            fv = db.row_to_dict(
                conn.execute("SELECT charge_cap_pct FROM fleet_vehicles WHERE fleet_id=? AND vehicle_id=?", (user["fleet_id"], d["vehicle_id"])).fetchone()
            )
            if vehicle and fv:
                vehicle["charge_cap_pct"] = fv["charge_cap_pct"]
            active = conn.execute(
                "SELECT 1 FROM sessions WHERE user_id=? AND vehicle_id=? AND status='active'", (d["user_id"], d["vehicle_id"])
            ).fetchone()
            status = "charging" if active else "idle"
        result.append({"user_id": d["user_id"], "driver_name": d["driver_name"], "email": d["email"], "vehicle": vehicle, "status": status})
    return result


class AddDriverRequest(BaseModel):
    name: str
    email: EmailStr
    password: str


@router.post("/drivers", status_code=201)
def add_driver(body: AddDriverRequest, user: dict = Depends(require_fleet_manager)):
    conn = db.get_conn()
    if conn.execute("SELECT 1 FROM users WHERE email=?", (body.email,)).fetchone():
        raise HTTPException(status_code=409, detail="Email already registered")

    pw_hash, salt = auth.hash_password(body.password)
    driver_id = db.new_id()
    now = db.now_iso()
    with db.transaction() as c:
        c.execute(
            """INSERT INTO users (id, name, email, password_hash, password_salt, role, fleet_id, created_at)
               VALUES (?, ?, ?, ?, ?, 'fleet_driver', ?, ?)""",
            (driver_id, body.name, body.email, pw_hash, salt, user["fleet_id"], now),
        )
        c.execute("INSERT INTO fleet_drivers (fleet_id, user_id, vehicle_id) VALUES (?, ?, NULL)", (user["fleet_id"], driver_id))
    return {"user_id": driver_id, "name": body.name, "email": body.email}


# ---------------------------------------------------------------------------
# Vehicles & assignment
# ---------------------------------------------------------------------------

class FleetVehicleRequest(BaseModel):
    make: str
    model: str
    connector_type: str
    battery_capacity_kwh: float


@router.get("/vehicles")
def list_fleet_vehicles(user: dict = Depends(require_fleet_manager)):
    conn = db.get_conn()
    return db.rows_to_list(
        conn.execute(
            """SELECT v.*, fv.charge_cap_pct FROM vehicles v
               JOIN fleet_vehicles fv ON fv.vehicle_id = v.id
               WHERE fv.fleet_id = ?""",
            (user["fleet_id"],),
        ).fetchall()
    )


@router.post("/vehicles", status_code=201)
def add_fleet_vehicle(body: FleetVehicleRequest, user: dict = Depends(require_fleet_manager)):
    if body.connector_type not in CONNECTOR_TYPES:
        raise HTTPException(status_code=422, detail=f"connector_type must be one of {CONNECTOR_TYPES}")

    vehicle_id = db.new_id()
    now = db.now_iso()
    with db.transaction() as c:
        c.execute(
            """INSERT INTO vehicles (id, fleet_id, make, model, connector_type, battery_capacity_kwh, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (vehicle_id, user["fleet_id"], body.make, body.model, body.connector_type, body.battery_capacity_kwh, now),
        )
        c.execute("INSERT INTO fleet_vehicles (fleet_id, vehicle_id, charge_cap_pct) VALUES (?, ?, 100)", (user["fleet_id"], vehicle_id))
    return db.row_to_dict(db.get_conn().execute("SELECT * FROM vehicles WHERE id=?", (vehicle_id,)).fetchone())


class AssignVehicleRequest(BaseModel):
    vehicle_id: str | None = None  # null unassigns


@router.post("/drivers/{user_id}/assign-vehicle")
def assign_vehicle(user_id: str, body: AssignVehicleRequest, user: dict = Depends(require_fleet_manager)):
    conn = db.get_conn()
    driver = db.row_to_dict(conn.execute("SELECT 1 FROM fleet_drivers WHERE fleet_id=? AND user_id=?", (user["fleet_id"], user_id)).fetchone())
    if driver is None:
        raise HTTPException(status_code=404, detail="Driver not found in this fleet")

    if body.vehicle_id is not None:
        vehicle = db.row_to_dict(
            conn.execute("SELECT 1 FROM fleet_vehicles WHERE fleet_id=? AND vehicle_id=?", (user["fleet_id"], body.vehicle_id)).fetchone()
        )
        if vehicle is None:
            raise HTTPException(status_code=404, detail="Vehicle not found in this fleet")

    with db.transaction() as c:
        c.execute("UPDATE fleet_drivers SET vehicle_id=? WHERE fleet_id=? AND user_id=?", (body.vehicle_id, user["fleet_id"], user_id))
    return {"status": "ok"}


class PolicyRequest(BaseModel):
    charge_cap_pct: int


@router.patch("/vehicles/{vehicle_id}/policy")
def set_vehicle_policy(vehicle_id: str, body: PolicyRequest, user: dict = Depends(require_fleet_manager)):
    if not (0 < body.charge_cap_pct <= 100):
        raise HTTPException(status_code=422, detail="charge_cap_pct must be between 1 and 100")

    conn = db.get_conn()
    fv = db.row_to_dict(conn.execute("SELECT 1 FROM fleet_vehicles WHERE fleet_id=? AND vehicle_id=?", (user["fleet_id"], vehicle_id)).fetchone())
    if fv is None:
        raise HTTPException(status_code=404, detail="Vehicle not found in this fleet")

    with db.transaction() as c:
        c.execute("UPDATE fleet_vehicles SET charge_cap_pct=? WHERE fleet_id=? AND vehicle_id=?", (body.charge_cap_pct, user["fleet_id"], vehicle_id))
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Cost export — "billing auto-routes to company" (PRD) means a fleet_driver's
# sessions are never billed to a personal card (see ocpp_sim.py's payment
# capture: no default payment method just means no card charge, which is
# exactly correct for a fleet driver). This report IS the company's bill.
# ---------------------------------------------------------------------------

@router.get("/cost-report")
def cost_report(format: str = Query("json", pattern="^(json|csv)$"), user: dict = Depends(require_fleet_manager)):
    conn = db.get_conn()
    drivers = db.rows_to_list(
        conn.execute(
            "SELECT u.id, u.name, u.email FROM fleet_drivers fd JOIN users u ON u.id = fd.user_id WHERE fd.fleet_id=?",
            (user["fleet_id"],),
        ).fetchall()
    )

    rows = []
    for d in drivers:
        agg = conn.execute(
            """SELECT COUNT(*) AS sessions, COALESCE(SUM(energy_kwh), 0) AS energy, COALESCE(SUM(cost), 0) AS cost
               FROM sessions WHERE user_id=? AND status IN ('completed', 'stopped_remotely')""",
            (d["id"],),
        ).fetchone()
        rows.append(
            {
                "driver_name": d["name"],
                "email": d["email"],
                "sessions": agg["sessions"],
                "energy_kwh": round(agg["energy"], 3),
                "cost": round(agg["cost"], 2),
            }
        )

    if format == "csv":
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=["driver_name", "email", "sessions", "energy_kwh", "cost"])
        writer.writeheader()
        writer.writerows(rows)
        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=fleet-cost-report.csv"},
        )

    return rows
