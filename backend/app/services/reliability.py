"""Per-connector reliability scoring — the platform's trust wedge.

Score is a time-decayed weighted average of recent session outcomes (100 for
a `completed` session, 0 for a station-caused `failed`/`stopped_remotely`
one), penalized by any unresolved Plug Watch crowdsourced reports. A
connector is shown as **Guaranteed** (score >= GUARANTEED_THRESHOLD, no
unresolved reports) — that flag is what session start snapshots for
insurance eligibility (see services/insurance.py).
"""
from __future__ import annotations

import sqlite3

from .. import db

N_SESSIONS = 20
HALF_LIFE_SESSIONS = 5
GUARANTEED_THRESHOLD = 90
PLUGWATCH_PENALTY_PER_REPORT = 15
PLUGWATCH_WINDOW_HOURS = 2
PLUGWATCH_AUTO_FAULT_COUNT = 2


def _report_window_cutoff(c: sqlite3.Connection) -> str:
    return c.execute(
        "SELECT strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?) AS cutoff", (f"-{PLUGWATCH_WINDOW_HOURS} hours",)
    ).fetchone()["cutoff"]


def _unresolved_report_count(c: sqlite3.Connection, connector_id: str) -> int:
    cutoff = _report_window_cutoff(c)
    return c.execute(
        "SELECT COUNT(*) AS n FROM plugwatch_reports WHERE connector_id=? AND resolved=0 AND created_at >= ?",
        (connector_id, cutoff),
    ).fetchone()["n"]


def recompute(c: sqlite3.Connection, connector_id: str) -> float:
    """Recalculate and persist a connector's score + guaranteed flag. Call
    after any session closes or any new Plug Watch report."""
    # stopped_remotely (user-initiated stop) is excluded deliberately — the
    # connector worked fine, the driver just chose to end early, so it
    # shouldn't move the score in either direction.
    sessions = db.rows_to_list(
        c.execute(
            "SELECT status FROM sessions WHERE connector_id=? AND status IN ('completed','failed') "
            "ORDER BY created_at DESC LIMIT ?",
            (connector_id, N_SESSIONS),
        )
    )
    if sessions:
        weighted_sum = 0.0
        weight_total = 0.0
        for i, s in enumerate(sessions):
            weight = 0.5 ** (i / HALF_LIFE_SESSIONS)
            outcome = 100.0 if s["status"] == "completed" else 0.0
            weighted_sum += outcome * weight
            weight_total += weight
        score = weighted_sum / weight_total
    else:
        score = 100.0  # no session history yet — optimistic default until proven otherwise

    unresolved = _unresolved_report_count(c, connector_id)
    score = max(0.0, score - unresolved * PLUGWATCH_PENALTY_PER_REPORT)
    guaranteed = 1 if (score >= GUARANTEED_THRESHOLD and unresolved == 0) else 0

    c.execute(
        "UPDATE connectors SET reliability_score=?, guaranteed=?, updated_at=? WHERE id=?",
        (round(score, 1), guaranteed, db.now_iso(), connector_id),
    )
    return score


def handle_new_report(c: sqlite3.Connection, connector_id: str) -> dict:
    """Called right after a Plug Watch report is inserted. If enough recent
    reports have piled up while the connector still shows available/occupied,
    force it to faulted and open a maintenance ticket — the crowdsourced
    cross-check catching what OCPP StatusNotification alone missed."""
    connector = db.row_to_dict(c.execute("SELECT * FROM connectors WHERE id=?", (connector_id,)).fetchone())
    unresolved = _unresolved_report_count(c, connector_id)

    ticket_opened = False
    if unresolved >= PLUGWATCH_AUTO_FAULT_COUNT and connector["status"] in ("available", "occupied"):
        c.execute(
            "UPDATE connectors SET status='faulted', updated_at=? WHERE id=?",
            (db.now_iso(), connector_id),
        )
        c.execute(
            """INSERT INTO maintenance_tickets (id, station_id, connector_id, issue, status, created_at)
               VALUES (?, ?, ?, ?, 'open', ?)""",
            (
                db.new_id(),
                connector["station_id"],
                connector_id,
                f"Auto-opened: {unresolved} Plug Watch reports flagged this connector while OCPP status still read '{connector['status']}'.",
                db.now_iso(),
            ),
        )
        ticket_opened = True

    score = recompute(c, connector_id)
    return {"unresolved_reports": unresolved, "ticket_opened": ticket_opened, "reliability_score": score}
