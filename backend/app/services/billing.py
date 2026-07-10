"""Operator billing — the SaaS fee VoltPath charges the charging networks
that use the platform: a flat monthly plan fee plus a small cut of that
operator's completed-session revenue, billed in calendar-month periods.

No real payment gateway exists yet (see the mock PSP in routers/payments.py)
so "paying" an invoice is the same kind of mock action: it flips status
without moving real money. Period rollover and overdue detection are lazy —
computed whenever billing data is read, not on a timer — same pattern as
services/reservations.py, since this stack has no background scheduler.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from .. import db

OVERDUE_GRACE_DAYS = 7
DEFAULT_PLAN_ID = "starter"

_ISO_FMT = "%Y-%m-%dT%H:%M:%S.%f"


def _parse_iso(iso_str: str) -> datetime:
    return datetime.strptime(iso_str[:-1], _ISO_FMT).replace(tzinfo=timezone.utc)


def _to_iso(dt: datetime) -> str:
    return dt.strftime(_ISO_FMT)[:-3] + "Z"


def _current_period_bounds() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month, next_year = (1, start.year + 1) if start.month == 12 else (start.month + 1, start.year)
    end = start.replace(year=next_year, month=next_month)
    return _to_iso(start), _to_iso(end)


def ensure_subscription(conn: sqlite3.Connection, operator_id: str) -> dict:
    """Every operator gets a Starter subscription the first time their
    billing data is touched — self-registered operators never explicitly
    "sign up" for a plan, they just start on the free tier."""
    row = db.row_to_dict(conn.execute("SELECT * FROM operator_subscriptions WHERE operator_id=?", (operator_id,)).fetchone())
    if row is not None:
        return row
    now = db.now_iso()
    with db.transaction() as c:
        c.execute(
            "INSERT INTO operator_subscriptions (operator_id, plan_id, status, created_at, updated_at) VALUES (?, ?, 'active', ?, ?)",
            (operator_id, DEFAULT_PLAN_ID, now, now),
        )
    return db.row_to_dict(conn.execute("SELECT * FROM operator_subscriptions WHERE operator_id=?", (operator_id,)).fetchone())


def _period_session_revenue(conn: sqlite3.Connection, operator_id: str, period_start: str, period_end: str) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(s.cost), 0) AS total FROM sessions s "
        "JOIN connectors c ON s.connector_id = c.id "
        "JOIN stations st ON c.station_id = st.id "
        "WHERE st.operator_id=? AND s.status='completed' AND s.created_at >= ? AND s.created_at < ?",
        (operator_id, period_start, period_end),
    ).fetchone()
    return row["total"] if row and row["total"] else 0.0


def _flag_overdue(conn: sqlite3.Connection, operator_id: str) -> None:
    now_dt = datetime.now(timezone.utc)
    pending = db.rows_to_list(
        conn.execute("SELECT id, period_end FROM invoices WHERE operator_id=? AND status='pending'", (operator_id,)).fetchall()
    )
    overdue_ids = [inv["id"] for inv in pending if _parse_iso(inv["period_end"]) + timedelta(days=OVERDUE_GRACE_DAYS) < now_dt]
    if not overdue_ids:
        return

    now = db.now_iso()
    with db.transaction() as c:
        for inv_id in overdue_ids:
            c.execute("UPDATE invoices SET status='overdue' WHERE id=?", (inv_id,))
        c.execute("UPDATE operator_subscriptions SET status='past_due', updated_at=? WHERE operator_id=?", (now, operator_id))


def ensure_current_invoice(conn: sqlite3.Connection, operator_id: str) -> dict:
    """Return this billing period's invoice for `operator_id`, creating it
    on first read of a new period (base fee from the current plan, usage fee
    from completed sessions so far this period)."""
    subscription = ensure_subscription(conn, operator_id)
    period_start, period_end = _current_period_bounds()

    invoice = db.row_to_dict(
        conn.execute("SELECT * FROM invoices WHERE operator_id=? AND period_start=?", (operator_id, period_start)).fetchone()
    )
    if invoice is None:
        plan = db.row_to_dict(conn.execute("SELECT * FROM subscription_plans WHERE id=?", (subscription["plan_id"],)).fetchone())
        base_fee = plan["monthly_fee"]
        usage_fee = round(_period_session_revenue(conn, operator_id, period_start, period_end) * plan["platform_fee_percent"], 2)
        invoice_id = db.new_id()
        now = db.now_iso()
        with db.transaction() as c:
            c.execute(
                "INSERT INTO invoices (id, operator_id, period_start, period_end, base_fee, usage_fee, total, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                (invoice_id, operator_id, period_start, period_end, base_fee, usage_fee, round(base_fee + usage_fee, 2), now),
            )
        invoice = db.row_to_dict(conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone())

    _flag_overdue(conn, operator_id)
    return db.row_to_dict(conn.execute("SELECT * FROM invoices WHERE id=?", (invoice["id"],)).fetchone())
