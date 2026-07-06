"""Station operator dashboard API — station_admin-only, every route scoped
to the caller's own operator_id. This is the actual multi-tenant boundary:
a station_admin at one charging network must never see or touch another
network's stations, connectors, pricing, or tickets.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db

router = APIRouter(prefix="/operator", tags=["operator"])

require_operator = auth.require_role("station_admin", "super_admin")


def _own_station_or_404(conn, station_id: str, operator_id: str) -> dict:
    station = db.row_to_dict(conn.execute("SELECT * FROM stations WHERE id=?", (station_id,)).fetchone())
    if station is None or station["operator_id"] != operator_id:
        raise HTTPException(status_code=404, detail="Station not found")
    return station


def _own_connector_or_404(conn, connector_id: str, operator_id: str) -> tuple[dict, dict]:
    connector = db.row_to_dict(conn.execute("SELECT * FROM connectors WHERE id=?", (connector_id,)).fetchone())
    if connector is None:
        raise HTTPException(status_code=404, detail="Connector not found")
    station = _own_station_or_404(conn, connector["station_id"], operator_id)
    return connector, station


# ---------------------------------------------------------------------------
# Stations & connectors
# ---------------------------------------------------------------------------

class CreateStationRequest(BaseModel):
    name: str
    address: str
    lat: float
    lng: float


class CreateConnectorRequest(BaseModel):
    type: str
    power_kw: float


class UpdateConnectorRequest(BaseModel):
    power_kw: float | None = None
    type: str | None = None
    status: str | None = None  # station_admin can only set 'available' or 'maintenance' manually


@router.get("/stations")
def list_stations(user: dict = Depends(require_operator)):
    conn = db.get_conn()
    stations = db.rows_to_list(
        conn.execute("SELECT * FROM stations WHERE operator_id=? ORDER BY created_at DESC", (user["operator_id"],)).fetchall()
    )
    result = []
    for s in stations:
        connectors = db.rows_to_list(conn.execute("SELECT * FROM connectors WHERE station_id=?", (s["id"],)).fetchall())
        result.append({**s, "connectors": connectors})
    return result


@router.post("/stations", status_code=201)
def create_station(body: CreateStationRequest, user: dict = Depends(require_operator)):
    station_id = db.new_id()
    now = db.now_iso()
    cp_id = f"CP-{station_id[:8]}"
    with db.transaction() as c:
        c.execute(
            """INSERT INTO stations (id, operator_id, name, address, lat, lng, status, ocpp_charge_point_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'online', ?, ?)""",
            (station_id, user["operator_id"], body.name, body.address, body.lat, body.lng, cp_id, now),
        )
    return db.row_to_dict(db.get_conn().execute("SELECT * FROM stations WHERE id=?", (station_id,)).fetchone())


@router.post("/stations/{station_id}/connectors", status_code=201)
def add_connector(station_id: str, body: CreateConnectorRequest, user: dict = Depends(require_operator)):
    conn = db.get_conn()
    _own_station_or_404(conn, station_id, user["operator_id"])

    next_ocpp_id = (
        conn.execute("SELECT COALESCE(MAX(ocpp_connector_id), 0) + 1 AS n FROM connectors WHERE station_id=?", (station_id,)).fetchone()["n"]
    )
    connector_id = db.new_id()
    now = db.now_iso()
    with db.transaction() as c:
        c.execute(
            """INSERT INTO connectors (id, station_id, ocpp_connector_id, type, power_kw, status, reliability_score, guaranteed, updated_at)
               VALUES (?, ?, ?, ?, ?, 'available', 100, 0, ?)""",
            (connector_id, station_id, next_ocpp_id, body.type, body.power_kw, now),
        )
    return db.row_to_dict(conn.execute("SELECT * FROM connectors WHERE id=?", (connector_id,)).fetchone())


@router.patch("/connectors/{connector_id}")
def update_connector(connector_id: str, body: UpdateConnectorRequest, user: dict = Depends(require_operator)):
    conn = db.get_conn()
    connector, _ = _own_connector_or_404(conn, connector_id, user["operator_id"])

    if body.status is not None and body.status not in ("available", "maintenance"):
        raise HTTPException(status_code=422, detail="status can only be manually set to 'available' or 'maintenance'")

    updates = {
        "power_kw": body.power_kw if body.power_kw is not None else connector["power_kw"],
        "type": body.type if body.type is not None else connector["type"],
        "status": body.status if body.status is not None else connector["status"],
    }
    with db.transaction() as c:
        c.execute(
            "UPDATE connectors SET power_kw=?, type=?, status=?, updated_at=? WHERE id=?",
            (updates["power_kw"], updates["type"], updates["status"], db.now_iso(), connector_id),
        )
    return db.row_to_dict(conn.execute("SELECT * FROM connectors WHERE id=?", (connector_id,)).fetchone())


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------

class TariffRequest(BaseModel):
    pricing_model: str
    rate: float


@router.put("/stations/{station_id}/tariffs")
def set_tariff(station_id: str, body: TariffRequest, user: dict = Depends(require_operator)):
    conn = db.get_conn()
    _own_station_or_404(conn, station_id, user["operator_id"])  # path param authorizes; tariffs are operator-wide (see docs/schema.sql)

    if body.pricing_model not in ("per_kwh", "per_minute", "flat"):
        raise HTTPException(status_code=422, detail="Invalid pricing_model")

    tariff_id = db.new_id()
    with db.transaction() as c:
        c.execute(
            "INSERT INTO tariffs (id, operator_id, pricing_model, rate, created_at) VALUES (?, ?, ?, ?, ?)",
            (tariff_id, user["operator_id"], body.pricing_model, body.rate, db.now_iso()),
        )
    return db.row_to_dict(conn.execute("SELECT * FROM tariffs WHERE id=?", (tariff_id,)).fetchone())


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


@router.get("/stations/{station_id}/analytics")
def station_analytics(station_id: str, user: dict = Depends(require_operator)):
    conn = db.get_conn()
    _own_station_or_404(conn, station_id, user["operator_id"])

    connectors = db.rows_to_list(conn.execute("SELECT id, power_kw FROM connectors WHERE station_id=?", (station_id,)).fetchall())
    if not connectors:
        return {"revenue_total": 0, "sessions_count": 0, "utilization_pct": 0, "by_connector": []}

    by_connector = []
    revenue_total = 0.0
    sessions_count = 0
    total_busy_hours = 0.0
    earliest_start: datetime | None = None
    latest_end: datetime | None = None

    for connector in connectors:
        sessions = db.rows_to_list(
            conn.execute("SELECT * FROM sessions WHERE connector_id=?", (connector["id"],)).fetchall()
        )
        conn_revenue = 0.0
        for s in sessions:
            if s["cost"]:
                payment = db.row_to_dict(
                    conn.execute("SELECT amount FROM payments WHERE session_id=? AND status='captured'", (s["id"],)).fetchone()
                )
                if payment:
                    conn_revenue += payment["amount"]
            start, end = _parse_iso(s["start_time"]), _parse_iso(s["end_time"])
            if start and end:
                total_busy_hours += (end - start).total_seconds() / 3600
                earliest_start = start if earliest_start is None or start < earliest_start else earliest_start
                latest_end = end if latest_end is None or end > latest_end else latest_end

        revenue_total += conn_revenue
        sessions_count += len(sessions)
        by_connector.append({"connector_id": connector["id"], "revenue": round(conn_revenue, 2), "sessions": len(sessions)})

    if earliest_start and latest_end and latest_end > earliest_start:
        window_hours = (latest_end - earliest_start).total_seconds() / 3600
        utilization_pct = min(100.0, (total_busy_hours / (window_hours * len(connectors))) * 100) if window_hours > 0 else 0.0
    else:
        utilization_pct = 0.0

    return {
        "revenue_total": round(revenue_total, 2),
        "sessions_count": sessions_count,
        "utilization_pct": round(utilization_pct, 1),
        "by_connector": by_connector,
    }


# ---------------------------------------------------------------------------
# Maintenance tickets
# ---------------------------------------------------------------------------

class UpdateTicketRequest(BaseModel):
    status: str


@router.get("/tickets")
def list_tickets(user: dict = Depends(require_operator)):
    conn = db.get_conn()
    return db.rows_to_list(
        conn.execute(
            """SELECT t.* FROM maintenance_tickets t
               JOIN stations s ON s.id = t.station_id
               WHERE s.operator_id = ?
               ORDER BY (t.status = 'open') DESC, t.created_at DESC""",
            (user["operator_id"],),
        ).fetchall()
    )


@router.patch("/tickets/{ticket_id}")
def update_ticket(ticket_id: str, body: UpdateTicketRequest, user: dict = Depends(require_operator)):
    if body.status not in ("open", "in_progress", "resolved", "closed"):
        raise HTTPException(status_code=422, detail="Invalid status")

    conn = db.get_conn()
    ticket = db.row_to_dict(
        conn.execute(
            """SELECT t.* FROM maintenance_tickets t JOIN stations s ON s.id = t.station_id
               WHERE t.id = ? AND s.operator_id = ?""",
            (ticket_id, user["operator_id"]),
        ).fetchone()
    )
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    resolved_at = db.now_iso() if body.status in ("resolved", "closed") else ticket["resolved_at"]
    with db.transaction() as c:
        c.execute("UPDATE maintenance_tickets SET status=?, resolved_at=? WHERE id=?", (body.status, resolved_at, ticket_id))
    return db.row_to_dict(conn.execute("SELECT * FROM maintenance_tickets WHERE id=?", (ticket_id,)).fetchone())
