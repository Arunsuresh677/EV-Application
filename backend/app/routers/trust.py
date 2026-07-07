"""Trust Engine+ endpoints — the differentiator beyond the base PRD contract:
live reliability detail, crowdsourced Plug Watch reports, insurance claims,
and the driver's credit wallet.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db
from ..services import reliability, rate_limit

router = APIRouter(tags=["trust"])

ISSUE_TYPES = ("wont_charge", "damaged", "blocked", "wrong_status", "other")


class ReportRequest(BaseModel):
    issue_type: str
    note: str | None = None


@router.get("/connectors/{connector_id}/reliability")
def get_reliability(connector_id: str, user: dict = Depends(auth.get_current_user)):
    conn = db.get_conn()
    connector = db.row_to_dict(conn.execute("SELECT * FROM connectors WHERE id=?", (connector_id,)).fetchone())
    if connector is None:
        raise HTTPException(status_code=404, detail="Connector not found")

    recent_sessions = db.rows_to_list(
        conn.execute(
            "SELECT status, created_at FROM sessions WHERE connector_id=? AND status IN ('completed','failed') "
            "ORDER BY created_at DESC LIMIT 20",
            (connector_id,),
        ).fetchall()
    )
    open_reports = db.rows_to_list(
        conn.execute(
            "SELECT id, issue_type, note, created_at FROM plugwatch_reports WHERE connector_id=? AND resolved=0 ORDER BY created_at DESC",
            (connector_id,),
        ).fetchall()
    )

    return {
        "connector_id": connector_id,
        "reliability_score": connector["reliability_score"],
        "guaranteed": bool(connector["guaranteed"]),
        "status": connector["status"],
        "recent_sessions": recent_sessions,
        "open_plugwatch_reports": open_reports,
    }


@router.post("/connectors/{connector_id}/reports", status_code=201)
def report_issue(connector_id: str, body: ReportRequest, user: dict = Depends(auth.get_current_user)):
    if body.issue_type not in ISSUE_TYPES:
        raise HTTPException(status_code=422, detail=f"issue_type must be one of {ISSUE_TYPES}")

    # The auto-fault-flip only needs 2 reports (services/reliability.py) —
    # without this, one account could spam a competitor's connector down
    # by itself. This doesn't stop a multi-account attack, but that's a
    # harder problem (device fingerprinting / account trust scoring) than
    # this pass's scope.
    rate_limit.check(f"plugwatch-report:{user['id']}", max_requests=5, window_seconds=600)

    conn = db.get_conn()
    connector = db.row_to_dict(conn.execute("SELECT id FROM connectors WHERE id=?", (connector_id,)).fetchone())
    if connector is None:
        raise HTTPException(status_code=404, detail="Connector not found")

    report_id = db.new_id()
    with db.transaction() as c:
        c.execute(
            """INSERT INTO plugwatch_reports (id, connector_id, reporter_id, issue_type, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (report_id, connector_id, user["id"], body.issue_type, body.note, db.now_iso()),
        )
        outcome = reliability.handle_new_report(c, connector_id)

    return {"report_id": report_id, **outcome}


@router.get("/users/me/credits")
def get_wallet(user: dict = Depends(auth.get_current_user)):
    conn = db.get_conn()
    entries = db.rows_to_list(
        conn.execute(
            "SELECT id, amount, reason, created_at FROM user_credits WHERE user_id=? ORDER BY created_at DESC",
            (user["id"],),
        ).fetchall()
    )
    balance = sum(e["amount"] for e in entries)
    return {"balance": round(balance, 2), "entries": entries}


@router.get("/sessions/{session_id}/claim")
def get_claim(session_id: str, user: dict = Depends(auth.get_current_user)):
    conn = db.get_conn()
    claim = db.row_to_dict(
        conn.execute(
            "SELECT * FROM insurance_claims WHERE session_id=? AND user_id=?",
            (session_id, user["id"]),
        ).fetchone()
    )
    if claim is None:
        raise HTTPException(status_code=404, detail="No claim for this session")
    return claim
