"""Reserve a connector in advance — docs/api-spec.yaml already documented
this and the schema (docs/schema.sql) already had the table; this is that
contract actually implemented.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db
from ..services import reservations as reservations_service

router = APIRouter(tags=["reservations"])


class CreateReservationRequest(BaseModel):
    connector_id: str
    hold_minutes: int = reservations_service.DEFAULT_HOLD_MINUTES


def _reservation_view(row: dict) -> dict:
    return {
        "id": row["id"],
        "connector_id": row["connector_id"],
        "start_time": row["start_time"],
        "expiry_time": row["expiry_time"],
        "status": row["status"],
    }


@router.post("/reservations", status_code=201)
def create_reservation(body: CreateReservationRequest, user: dict = Depends(auth.get_current_user)):
    if not (1 <= body.hold_minutes <= 120):
        raise HTTPException(status_code=422, detail="hold_minutes must be between 1 and 120")

    conn = db.get_conn()
    reservations_service.expire_stale_reservations(conn)

    connector = db.row_to_dict(conn.execute("SELECT * FROM connectors WHERE id=?", (body.connector_id,)).fetchone())
    if connector is None:
        raise HTTPException(status_code=404, detail="Connector not found")
    if connector["status"] != "available":
        raise HTTPException(status_code=409, detail=f"Connector not available to reserve (status={connector['status']})")

    now = db.now_iso()
    expiry = reservations_service.iso_plus_minutes(body.hold_minutes)
    reservation_id = db.new_id()
    with db.transaction() as c:
        c.execute(
            "INSERT INTO reservations (id, user_id, connector_id, start_time, expiry_time, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'active', ?)",
            (reservation_id, user["id"], body.connector_id, now, expiry, now),
        )
        c.execute("UPDATE connectors SET status='reserved', updated_at=? WHERE id=?", (now, body.connector_id))

    return _reservation_view(db.row_to_dict(conn.execute("SELECT * FROM reservations WHERE id=?", (reservation_id,)).fetchone()))


@router.get("/users/me/reservations")
def list_my_reservations(user: dict = Depends(auth.get_current_user)):
    conn = db.get_conn()
    reservations_service.expire_stale_reservations(conn)
    rows = db.rows_to_list(
        conn.execute("SELECT * FROM reservations WHERE user_id=? ORDER BY created_at DESC LIMIT 20", (user["id"],)).fetchall()
    )
    return [_reservation_view(r) for r in rows]


@router.post("/reservations/{reservation_id}/cancel")
def cancel_reservation(reservation_id: str, user: dict = Depends(auth.get_current_user)):
    conn = db.get_conn()
    reservations_service.expire_stale_reservations(conn)

    reservation = db.row_to_dict(conn.execute("SELECT * FROM reservations WHERE id=? AND user_id=?", (reservation_id, user["id"])).fetchone())
    if reservation is None:
        raise HTTPException(status_code=404, detail="Reservation not found")
    if reservation["status"] != "active":
        raise HTTPException(status_code=409, detail=f"Reservation is '{reservation['status']}', not active")

    now = db.now_iso()
    with db.transaction() as c:
        c.execute("UPDATE reservations SET status='cancelled' WHERE id=?", (reservation_id,))
        c.execute("UPDATE connectors SET status='available', updated_at=? WHERE id=? AND status='reserved'", (now, reservation["connector_id"]))

    return _reservation_view(db.row_to_dict(conn.execute("SELECT * FROM reservations WHERE id=?", (reservation_id,)).fetchone()))
