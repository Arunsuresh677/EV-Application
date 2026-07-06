from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from .. import auth, db

router = APIRouter(tags=["auth"])


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    phone: str | None = None


class LoginRequest(BaseModel):
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


@router.post("/auth/login")
def login(body: LoginRequest):
    conn = db.get_conn()
    user = db.row_to_dict(conn.execute("SELECT * FROM users WHERE email=?", (body.email,)).fetchone())
    if user is None or not auth.verify_password(body.password, user["password_hash"], user["password_salt"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = auth.issue_token(user["id"], user["role"])
    return {"token": token, "user": _public_user(user)}


@router.get("/users/me")
def get_me(user: dict = Depends(auth.get_current_user)):
    return _public_user(user)


@router.get("/users/me/vehicles")
def get_my_vehicles(user: dict = Depends(auth.get_current_user)):
    conn = db.get_conn()
    return db.rows_to_list(
        conn.execute(
            "SELECT id, make, model, connector_type, battery_capacity_kwh FROM vehicles WHERE user_id=?",
            (user["id"],),
        ).fetchall()
    )
