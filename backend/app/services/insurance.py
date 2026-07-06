"""Guaranteed-charge insurance — automatic payout, no manual claim filing.

A session's `guaranteed_at_start` column snapshots the connector's Guaranteed
badge (see services/reliability.py) at the moment the session was created.
If that session later ends in a station-caused failure, `maybe_file_claim`
is called from within the same transaction that closes the session
(services/ocpp_sim.py) and inserts both the claim record and the matching
wallet credit atomically.
"""
from __future__ import annotations

import sqlite3

from .. import db

CREDIT_AMOUNT = 5.00  # flat goodwill credit (USD-equivalent) on a broken guarantee


def maybe_file_claim(c: sqlite3.Connection, session: dict) -> dict | None:
    if not session.get("guaranteed_at_start"):
        return None

    claim_id = db.new_id()
    now = db.now_iso()
    c.execute(
        """INSERT INTO insurance_claims (id, session_id, connector_id, user_id, reason, credit_amount, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (claim_id, session["id"], session["connector_id"], session["user_id"], "guaranteed_charge_failed", CREDIT_AMOUNT, now),
    )
    c.execute(
        """INSERT INTO user_credits (id, user_id, amount, reason, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (db.new_id(), session["user_id"], CREDIT_AMOUNT, f"Guaranteed-charge insurance claim {claim_id}", now),
    )
    return {"claim_id": claim_id, "credit_amount": CREDIT_AMOUNT}
