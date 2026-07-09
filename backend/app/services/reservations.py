"""Connector reservations — hold a spot for a short window instead of
finding it taken when you arrive. No background scheduler exists in this
dev sandbox, so expiry is lazy: checked and applied whenever reservation or
connector-availability data is about to be read, not on a timer. A stale
reservation is functionally expired the moment anything looks at it, which
is all that matters for correctness here.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from .. import db

DEFAULT_HOLD_MINUTES = 30


def iso_plus_minutes(minutes: int) -> str:
    """Same format as db.now_iso() — needed so lexicographic string
    comparison against expiry_time stays valid."""
    dt = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def expire_stale_reservations(conn: sqlite3.Connection) -> None:
    now = db.now_iso()
    stale = db.rows_to_list(
        conn.execute("SELECT id, connector_id FROM reservations WHERE status='active' AND expiry_time < ?", (now,)).fetchall()
    )
    if not stale:
        return

    with db.transaction() as c:
        for r in stale:
            c.execute("UPDATE reservations SET status='expired' WHERE id=?", (r["id"],))
            # Only revert if still 'reserved' — don't clobber if it became
            # occupied/faulted/maintenance for an unrelated reason since.
            c.execute("UPDATE connectors SET status='available', updated_at=? WHERE id=? AND status='reserved'", (now, r["connector_id"]))
