from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from .. import auth, db
from ..services import ocpp_sim, rate_limit
from ..services import reservations as reservations_service

router = APIRouter(tags=["sessions"])


class StartSessionRequest(BaseModel):
    connector_id: str
    vehicle_id: str
    reservation_id: str | None = None


def _session_view(row: dict) -> dict:
    view = {
        "id": row["id"],
        "connector_id": row["connector_id"],
        "status": row["status"],
        "start_time": row["start_time"],
        "end_time": row["end_time"],
        "energy_kwh": row["energy_kwh"],
        "cost": row["cost"],
        "guaranteed_at_start": bool(row["guaranteed_at_start"]),
        "fail_reason": row["fail_reason"],
        "claim_amount": None,
    }
    if row["status"] == "failed":
        claim = db.row_to_dict(
            db.get_conn().execute("SELECT credit_amount FROM insurance_claims WHERE session_id=?", (row["id"],)).fetchone()
        )
        if claim:
            view["claim_amount"] = claim["credit_amount"]
    return view


@router.post("/sessions", status_code=201)
def start_session(
    body: StartSessionRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    user: dict = Depends(auth.get_current_user),
):
    conn = db.get_conn()

    existing = db.row_to_dict(conn.execute("SELECT * FROM sessions WHERE idempotency_key=?", (idempotency_key,)).fetchone())
    if existing:
        return _session_view(existing)

    # Per the PRD's anti-fraud requirement: a burst of distinct start attempts
    # from one account (e.g. testing a stolen RFID/QR across many connectors)
    # should get slowed down, not silently allowed at full speed.
    rate_limit.check(f"session-start:{user['id']}", max_requests=10, window_seconds=60)

    reservations_service.expire_stale_reservations(conn)

    # A connector held by the caller's own active reservation is fine to
    # start on even though its status reads 'reserved', not 'available' —
    # that's the whole point of reserving ahead of time.
    reservation = None
    if body.reservation_id:
        reservation = db.row_to_dict(
            conn.execute(
                "SELECT * FROM reservations WHERE id=? AND user_id=? AND status='active'", (body.reservation_id, user["id"])
            ).fetchone()
        )
        if reservation is None or reservation["connector_id"] != body.connector_id:
            raise HTTPException(status_code=404, detail="Reservation not found or doesn't match this connector")

    connector = db.row_to_dict(conn.execute("SELECT * FROM connectors WHERE id=?", (body.connector_id,)).fetchone())
    if connector is None:
        raise HTTPException(status_code=404, detail="Connector not found")
    connector_usable = connector["status"] == "available" or (reservation is not None and connector["status"] == "reserved")
    if not connector_usable:
        raise HTTPException(status_code=409, detail=f"Connector no longer available (status={connector['status']})")

    # A fleet driver's vehicle isn't theirs by vehicles.user_id — it's the
    # fleet's, assigned via fleet_drivers.vehicle_id (mirrors the same check
    # in routers/auth.py's get_my_vehicles).
    vehicle = db.row_to_dict(conn.execute("SELECT * FROM vehicles WHERE id=? AND user_id=?", (body.vehicle_id, user["id"])).fetchone())
    if vehicle is None and user["fleet_id"]:
        vehicle = db.row_to_dict(
            conn.execute(
                "SELECT v.* FROM vehicles v JOIN fleet_drivers fd ON fd.vehicle_id = v.id WHERE fd.fleet_id=? AND fd.user_id=? AND v.id=?",
                (user["fleet_id"], user["id"], body.vehicle_id),
            ).fetchone()
        )
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    session_id = db.new_id()
    with db.transaction() as c:
        c.execute(
            """INSERT INTO sessions
               (id, user_id, connector_id, vehicle_id, reservation_id, idempotency_key, guaranteed_at_start, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (session_id, user["id"], body.connector_id, body.vehicle_id, body.reservation_id, idempotency_key, connector["guaranteed"], db.now_iso()),
        )
        if reservation is not None:
            c.execute("UPDATE reservations SET status='fulfilled' WHERE id=?", (reservation["id"],))

    session = db.row_to_dict(conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone())
    ocpp_sim.launch_session(session_id, body.connector_id)
    return _session_view(session)


@router.post("/sessions/{session_id}/stop")
def stop_session(session_id: str, user: dict = Depends(auth.get_current_user)):
    conn = db.get_conn()
    session = db.row_to_dict(conn.execute("SELECT * FROM sessions WHERE id=? AND user_id=?", (session_id, user["id"])).fetchone())
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["status"] not in ("pending", "active"):
        return _session_view(session)

    ocpp_sim.request_stop(session_id)
    return {"status": "stop_requested"}


@router.get("/sessions/{session_id}")
def get_session(session_id: str, user: dict = Depends(auth.get_current_user)):
    conn = db.get_conn()
    session = db.row_to_dict(conn.execute("SELECT * FROM sessions WHERE id=? AND user_id=?", (session_id, user["id"])).fetchone())
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return _session_view(session)


@router.get("/users/me/sessions")
def get_history(limit: int = Query(20, le=100), user: dict = Depends(auth.get_current_user)):
    conn = db.get_conn()
    rows = db.rows_to_list(
        conn.execute(
            "SELECT * FROM sessions WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user["id"], limit),
        ).fetchall()
    )
    return [_session_view(r) for r in rows]


@router.websocket("/ws/sessions/{session_id}")
async def session_telemetry(websocket: WebSocket, session_id: str, token: str = Query(...)):
    try:
        claims = auth.decode_token(token)
    except HTTPException:
        await websocket.close(code=4401)
        return

    conn = db.get_conn()
    session = db.row_to_dict(conn.execute("SELECT * FROM sessions WHERE id=? AND user_id=?", (session_id, claims["uid"])).fetchone())
    if session is None:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    queue = ocpp_sim.subscribe(session_id)
    try:
        while True:
            message = await queue.get()
            await websocket.send_json(message)
            if message.get("type") == "final":
                break
    except WebSocketDisconnect:
        pass
    finally:
        ocpp_sim.unsubscribe(session_id, queue)
