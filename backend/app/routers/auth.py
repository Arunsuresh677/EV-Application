from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from .. import auth, db
from ..logging_config import get_logger
from ..services import rate_limit

router = APIRouter(tags=["auth"])
log = get_logger("auth")


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    phone: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterOperatorRequest(BaseModel):
    company_name: str
    admin_name: str
    email: EmailStr
    password: str


class RegisterFleetRequest(BaseModel):
    company_name: str
    manager_name: str
    email: EmailStr
    password: str


def _public_user(user: dict) -> dict:
    return {"id": user["id"], "name": user["name"], "email": user["email"], "role": user["role"]}


@router.post("/auth/register", status_code=201)
def register(body: RegisterRequest):
    conn = db.get_conn()
    if conn.execute("SELECT 1 FROM users WHERE email=?", (body.email,)).fetchone():
        raise HTTPException(status_code=409, detail="Email already registered")

    pw_hash, salt = auth.hash_password(body.password)
    user_id = db.new_id()
    with db.transaction() as c:
        c.execute(
            """INSERT INTO users (id, name, email, password_hash, password_salt, phone, role, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'driver', ?)""",
            (user_id, body.name, body.email, pw_hash, salt, body.phone, db.now_iso()),
        )
    user = db.row_to_dict(conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())
    token = auth.issue_token(user_id, "driver")
    return {"token": token, "user": _public_user(user)}


@router.post("/auth/register-operator", status_code=201)
def register_operator(body: RegisterOperatorRequest):
    """Self-service station operator signup — creates a new operator
    (company) and its first station_admin user in one step, with no
    existing account required. This is what lets a real charging network
    sign up on their own instead of needing seed.py run on their behalf."""
    conn = db.get_conn()
    if conn.execute("SELECT 1 FROM users WHERE email=?", (body.email,)).fetchone():
        raise HTTPException(status_code=409, detail="Email already registered")
    if not body.company_name.strip():
        raise HTTPException(status_code=422, detail="Company name is required")

    pw_hash, salt = auth.hash_password(body.password)
    operator_id = db.new_id()
    admin_id = db.new_id()
    now = db.now_iso()
    with db.transaction() as c:
        c.execute(
            "INSERT INTO operators (id, company_name, status, created_at) VALUES (?, ?, 'active', ?)",
            (operator_id, body.company_name.strip(), now),
        )
        c.execute(
            """INSERT INTO users (id, name, email, password_hash, password_salt, role, operator_id, created_at)
               VALUES (?, ?, ?, ?, ?, 'station_admin', ?, ?)""",
            (admin_id, body.admin_name, body.email, pw_hash, salt, operator_id, now),
        )
    user = db.row_to_dict(conn.execute("SELECT * FROM users WHERE id=?", (admin_id,)).fetchone())
    token = auth.issue_token(admin_id, "station_admin")
    return {"token": token, "user": _public_user(user)}


@router.post("/auth/register-fleet", status_code=201)
def register_fleet(body: RegisterFleetRequest):
    """Self-service fleet signup — creates a new fleet (company) and its
    first fleet_manager user in one step. Mirrors register-operator: a
    company that owns EV vehicles can onboard itself with no seed data."""
    conn = db.get_conn()
    if conn.execute("SELECT 1 FROM users WHERE email=?", (body.email,)).fetchone():
        raise HTTPException(status_code=409, detail="Email already registered")
    if not body.company_name.strip():
        raise HTTPException(status_code=422, detail="Company name is required")

    pw_hash, salt = auth.hash_password(body.password)
    fleet_id = db.new_id()
    manager_id = db.new_id()
    now = db.now_iso()
    with db.transaction() as c:
        c.execute(
            "INSERT INTO fleets (id, company_name, created_at) VALUES (?, ?, ?)",
            (fleet_id, body.company_name.strip(), now),
        )
        c.execute(
            """INSERT INTO users (id, name, email, password_hash, password_salt, role, fleet_id, created_at)
               VALUES (?, ?, ?, ?, ?, 'fleet_manager', ?, ?)""",
            (manager_id, body.manager_name, body.email, pw_hash, salt, fleet_id, now),
        )
    user = db.row_to_dict(conn.execute("SELECT * FROM users WHERE id=?", (manager_id,)).fetchone())
    token = auth.issue_token(manager_id, "fleet_manager")
    return {"token": token, "user": _public_user(user)}


@router.post("/auth/login")
def login(body: LoginRequest):
    # Keyed by email, not IP: this is what actually stops credential
    # stuffing against one account regardless of which IP it comes from.
    rate_limit.check(f"login:{body.email.lower()}", max_requests=10, window_seconds=300)

    conn = db.get_conn()
    user = db.row_to_dict(conn.execute("SELECT * FROM users WHERE email=?", (body.email,)).fetchone())
    if user is None or not auth.verify_password(body.password, user["password_hash"], user["password_salt"]):
        log.warning("Failed login attempt for %s", body.email)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = auth.issue_token(user["id"], user["role"])
    return {"token": token, "user": _public_user(user)}


@router.get("/users/me")
def get_me(user: dict = Depends(auth.get_current_user)):
    return _public_user(user)


class VehicleRequest(BaseModel):
    make: str
    model: str
    connector_type: str
    battery_capacity_kwh: float


@router.get("/users/me/vehicles")
def get_my_vehicles(user: dict = Depends(auth.get_current_user)):
    conn = db.get_conn()
    own = db.rows_to_list(
        conn.execute(
            "SELECT id, make, model, connector_type, battery_capacity_kwh FROM vehicles WHERE user_id=?",
            (user["id"],),
        ).fetchall()
    )
    # A fleet_driver's vehicle isn't theirs (vehicles.user_id) — it's the
    # fleet's, assigned to them via fleet_drivers.vehicle_id ("assigned
    # vehicle only" per the PRD's fleet_driver scope). Include it here so
    # the existing driver app just works for fleet drivers with no changes.
    if user["fleet_id"]:
        assigned = db.rows_to_list(
            conn.execute(
                """SELECT v.id, v.make, v.model, v.connector_type, v.battery_capacity_kwh
                   FROM vehicles v JOIN fleet_drivers fd ON fd.vehicle_id = v.id
                   WHERE fd.fleet_id = ? AND fd.user_id = ? AND fd.vehicle_id IS NOT NULL""",
                (user["fleet_id"], user["id"]),
            ).fetchall()
        )
        own += assigned
    return own


@router.post("/users/me/vehicles", status_code=201)
def add_vehicle(body: VehicleRequest, user: dict = Depends(auth.get_current_user)):
    if body.connector_type not in ("CCS2", "CHAdeMO", "TYPE2", "NACS"):
        raise HTTPException(status_code=422, detail="Invalid connector_type")

    vehicle_id = db.new_id()
    with db.transaction() as c:
        c.execute(
            """INSERT INTO vehicles (id, user_id, make, model, connector_type, battery_capacity_kwh, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (vehicle_id, user["id"], body.make, body.model, body.connector_type, body.battery_capacity_kwh, db.now_iso()),
        )
    return db.row_to_dict(db.get_conn().execute("SELECT * FROM vehicles WHERE id=?", (vehicle_id,)).fetchone())


@router.delete("/users/me/vehicles/{vehicle_id}", status_code=204)
def delete_vehicle(vehicle_id: str, user: dict = Depends(auth.get_current_user)):
    conn = db.get_conn()
    vehicle = db.row_to_dict(conn.execute("SELECT id FROM vehicles WHERE id=? AND user_id=?", (vehicle_id, user["id"])).fetchone())
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    try:
        with db.transaction() as c:
            c.execute("DELETE FROM vehicles WHERE id=?", (vehicle_id,))
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="This vehicle has charging history and can't be deleted")
