"""Operator billing API. Three audiences, three route groups in one file
(each with its own full path, like routers/reservations.py, rather than a
single router prefix): `/billing/plans` is the public catalog any
authenticated user can read, `/operator/billing/*` is station_admin-scoped
to the caller's own operator, and `/admin/billing` is super_admin-only
platform-wide visibility (MRR, who's overdue).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db
from ..logging_config import get_logger
from ..services import billing as billing_service

router = APIRouter(tags=["billing"])
log = get_logger("billing")

require_operator = auth.require_role("station_admin", "super_admin")
require_super_admin = auth.require_role("super_admin")


def _invoice_view(row: dict) -> dict:
    return {
        "id": row["id"],
        "period_start": row["period_start"],
        "period_end": row["period_end"],
        "base_fee": row["base_fee"],
        "usage_fee": row["usage_fee"],
        "total": row["total"],
        "status": row["status"],
        "created_at": row["created_at"],
        "paid_at": row["paid_at"],
    }


@router.get("/billing/plans")
def list_plans(user: dict = Depends(auth.get_current_user)):
    conn = db.get_conn()
    return db.rows_to_list(conn.execute("SELECT * FROM subscription_plans ORDER BY sort_order").fetchall())


@router.get("/operator/billing")
def get_billing_overview(user: dict = Depends(require_operator)):
    conn = db.get_conn()
    invoice = billing_service.ensure_current_invoice(conn, user["operator_id"])
    subscription = db.row_to_dict(
        conn.execute("SELECT * FROM operator_subscriptions WHERE operator_id=?", (user["operator_id"],)).fetchone()
    )
    plan = db.row_to_dict(conn.execute("SELECT * FROM subscription_plans WHERE id=?", (subscription["plan_id"],)).fetchone())
    station_count = conn.execute("SELECT COUNT(*) AS n FROM stations WHERE operator_id=?", (user["operator_id"],)).fetchone()["n"]
    return {
        "plan": plan,
        "subscription_status": subscription["status"],
        "station_count": station_count,
        "current_invoice": _invoice_view(invoice),
    }


class ChangePlanRequest(BaseModel):
    plan_id: str


@router.post("/operator/billing/plan")
def change_plan(body: ChangePlanRequest, user: dict = Depends(require_operator)):
    conn = db.get_conn()
    plan = db.row_to_dict(conn.execute("SELECT * FROM subscription_plans WHERE id=?", (body.plan_id,)).fetchone())
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")

    billing_service.ensure_subscription(conn, user["operator_id"])

    if plan["max_stations"] is not None:
        station_count = conn.execute("SELECT COUNT(*) AS n FROM stations WHERE operator_id=?", (user["operator_id"],)).fetchone()["n"]
        if station_count > plan["max_stations"]:
            raise HTTPException(status_code=409, detail=f"This plan supports up to {plan['max_stations']} stations; you have {station_count}")

    now = db.now_iso()
    with db.transaction() as c:
        c.execute("UPDATE operator_subscriptions SET plan_id=?, updated_at=? WHERE operator_id=?", (plan["id"], now, user["operator_id"]))

    log.info("Operator %s switched to plan '%s'", user["operator_id"], plan["id"])
    return db.row_to_dict(conn.execute("SELECT * FROM operator_subscriptions WHERE operator_id=?", (user["operator_id"],)).fetchone())


@router.get("/operator/billing/invoices")
def list_invoices(user: dict = Depends(require_operator)):
    conn = db.get_conn()
    billing_service.ensure_current_invoice(conn, user["operator_id"])
    rows = db.rows_to_list(
        conn.execute("SELECT * FROM invoices WHERE operator_id=? ORDER BY period_start DESC LIMIT 24", (user["operator_id"],)).fetchall()
    )
    return [_invoice_view(r) for r in rows]


@router.post("/operator/billing/invoices/{invoice_id}/pay")
def pay_invoice(invoice_id: str, user: dict = Depends(require_operator)):
    conn = db.get_conn()
    invoice = db.row_to_dict(conn.execute("SELECT * FROM invoices WHERE id=? AND operator_id=?", (invoice_id, user["operator_id"])).fetchone())
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice["status"] == "paid":
        raise HTTPException(status_code=409, detail="Invoice is already paid")

    now = db.now_iso()
    with db.transaction() as c:
        c.execute("UPDATE invoices SET status='paid', paid_at=? WHERE id=?", (now, invoice_id))
        c.execute("UPDATE operator_subscriptions SET status='active', updated_at=? WHERE operator_id=?", (now, user["operator_id"]))

    log.info("Invoice %s for operator %s marked paid (mock payment, total=%s)", invoice_id, user["operator_id"], invoice["total"])
    return _invoice_view(db.row_to_dict(conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()))


@router.get("/admin/billing")
def admin_billing_overview(user: dict = Depends(require_super_admin)):
    conn = db.get_conn()
    operators = db.rows_to_list(conn.execute("SELECT * FROM operators ORDER BY company_name").fetchall())

    result = []
    mrr = 0.0
    for op in operators:
        invoice = billing_service.ensure_current_invoice(conn, op["id"])
        subscription = db.row_to_dict(
            conn.execute("SELECT * FROM operator_subscriptions WHERE operator_id=?", (op["id"],)).fetchone()
        )
        plan = db.row_to_dict(conn.execute("SELECT * FROM subscription_plans WHERE id=?", (subscription["plan_id"],)).fetchone())
        mrr += plan["monthly_fee"]
        result.append({
            "operator_id": op["id"],
            "company_name": op["company_name"],
            "plan_name": plan["name"],
            "subscription_status": subscription["status"],
            "current_invoice_total": invoice["total"],
            "current_invoice_status": invoice["status"],
        })

    return {"mrr": round(mrr, 2), "operators": result}
