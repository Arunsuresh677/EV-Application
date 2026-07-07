"""Platform super-admin API — VoltPath's own team managing the whole
platform, not any single charging network. Distinct from routers/operator.py
(which is scoped to one operator's own data): every route here is
`super_admin`-only and deliberately has no operator_id filter, since seeing
across all operators is the entire point.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db
from ..logging_config import get_logger

router = APIRouter(prefix="/admin", tags=["admin"])
log = get_logger("admin")

require_super_admin = auth.require_role("super_admin")


@router.get("/operators")
def list_operators(user: dict = Depends(require_super_admin)):
    conn = db.get_conn()
    operators = db.rows_to_list(conn.execute("SELECT * FROM operators ORDER BY created_at DESC").fetchall())
    result = []
    for op in operators:
        station_count = conn.execute("SELECT COUNT(*) AS n FROM stations WHERE operator_id=?", (op["id"],)).fetchone()["n"]
        admin_count = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE operator_id=? AND role='station_admin'", (op["id"],)
        ).fetchone()["n"]
        result.append({**op, "station_count": station_count, "admin_count": admin_count})
    return result


class UpdateOperatorStatusRequest(BaseModel):
    status: str


@router.patch("/operators/{operator_id}")
def update_operator_status(operator_id: str, body: UpdateOperatorStatusRequest, user: dict = Depends(require_super_admin)):
    if body.status not in ("active", "suspended"):
        raise HTTPException(status_code=422, detail="status must be 'active' or 'suspended'")

    conn = db.get_conn()
    operator = db.row_to_dict(conn.execute("SELECT * FROM operators WHERE id=?", (operator_id,)).fetchone())
    if operator is None:
        raise HTTPException(status_code=404, detail="Operator not found")

    with db.transaction() as c:
        c.execute("UPDATE operators SET status=? WHERE id=?", (body.status, operator_id))

    log.warning("Operator %s (%s) status changed to '%s' by super_admin %s", operator_id, operator["company_name"], body.status, user["id"])
    return db.row_to_dict(conn.execute("SELECT * FROM operators WHERE id=?", (operator_id,)).fetchone())


@router.get("/stats")
def platform_stats(user: dict = Depends(require_super_admin)):
    conn = db.get_conn()
    operators_total = conn.execute("SELECT COUNT(*) AS n FROM operators").fetchone()["n"]
    stations_total = conn.execute("SELECT COUNT(*) AS n FROM stations").fetchone()["n"]
    drivers_total = conn.execute("SELECT COUNT(*) AS n FROM users WHERE role='driver'").fetchone()["n"]
    sessions_total = conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"]
    revenue_total = conn.execute("SELECT COALESCE(SUM(amount), 0) AS total FROM payments WHERE status='captured'").fetchone()["total"]
    open_tickets = conn.execute("SELECT COUNT(*) AS n FROM maintenance_tickets WHERE status IN ('open', 'in_progress')").fetchone()["n"]

    return {
        "operators_total": operators_total,
        "stations_total": stations_total,
        "drivers_total": drivers_total,
        "sessions_total": sessions_total,
        "revenue_total": round(revenue_total, 2),
        "open_tickets": open_tickets,
    }
