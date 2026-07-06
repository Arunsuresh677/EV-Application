"""Stand-in for a real OCPP Central System + physical charger fleet.

There's no hardware or Central System in this dev sandbox, so a background
asyncio task plays that role for the lifetime of a session: it "sends"
StatusNotification-equivalent connector state changes and MeterValues-
equivalent energy ticks, published to any WebSocket subscribed to that
session (`/ws/sessions/{id}`) — the same shape the PRD describes for live
telemetry, just sourced from a simulator instead of a real charger.

A connector's reliability score biases whether its simulated session
succeeds or station-faults partway through, which is what makes the
Trust Engine+ behavior (reliability drift, guaranteed badges, automatic
insurance payouts) actually observable end-to-end.
"""
from __future__ import annotations

import asyncio
import random

from .. import db
from . import insurance, reliability

TICK_SECONDS = 1.5
AUTO_REPAIR_DELAY_SECONDS = 20

_subscribers: dict[str, list[asyncio.Queue]] = {}
_stop_events: dict[str, asyncio.Event] = {}
_main_loop: asyncio.AbstractEventLoop | None = None
_last_message: dict[str, dict] = {}


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Called once from the FastAPI startup hook, which runs on the real
    event loop. FastAPI dispatches sync `def` endpoints to a worker thread,
    so `asyncio.create_task` from inside one of those has no running loop to
    attach to — launch_session() below hands the coroutine to this loop
    instead via run_coroutine_threadsafe."""
    global _main_loop
    _main_loop = loop


def launch_session(session_id: str, connector_id: str) -> None:
    assert _main_loop is not None, "set_main_loop() must be called during FastAPI startup"
    asyncio.run_coroutine_threadsafe(run_session(session_id, connector_id), _main_loop)


def subscribe(session_id: str) -> asyncio.Queue:
    """A client can connect after the simulator has already published its
    first message or two (POST /sessions returns, then the client opens the
    WebSocket — there's always a small gap). Replaying the last known message
    means a late subscriber still sees current state instead of being stuck
    on stale defaults until the next tick."""
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.setdefault(session_id, []).append(q)
    last = _last_message.get(session_id)
    if last is not None:
        q.put_nowait(last)
    return q


def unsubscribe(session_id: str, q: asyncio.Queue) -> None:
    subs = _subscribers.get(session_id, [])
    if q in subs:
        subs.remove(q)


def request_stop(session_id: str) -> bool:
    """Called from the /sessions/{id}/stop endpoint. Returns False if there's
    no active simulated session to stop (e.g. it already finished)."""
    ev = _stop_events.get(session_id)
    if ev is None:
        return False
    ev.set()
    return True


async def _publish(session_id: str, message: dict) -> None:
    _last_message[session_id] = message
    for q in list(_subscribers.get(session_id, [])):
        await q.put(message)


async def run_session(session_id: str, connector_id: str) -> None:
    """Launched as a fire-and-forget asyncio task right after a session row
    is inserted (see routers/sessions.py). Simulates the full session
    lifecycle: occupy -> meter ticks -> completed or station-fault."""
    conn = db.get_conn()
    connector = db.row_to_dict(conn.execute("SELECT * FROM connectors WHERE id=?", (connector_id,)).fetchone())
    tariff = db.row_to_dict(conn.execute("SELECT * FROM tariffs LIMIT 1").fetchone())
    rate = tariff["rate"] if tariff else 0.40

    fail_probability = max(0.0, (100 - connector["reliability_score"]) / 100 * 0.85)
    will_fail = random.random() < fail_probability
    fail_at_tick = random.randint(2, 5) if will_fail else None
    total_ticks = fail_at_tick if will_fail else random.randint(8, 14)

    power_kw = min(connector["power_kw"], random.uniform(0.6, 1.0) * connector["power_kw"])
    energy_kwh = 0.0
    stop_event = _stop_events.setdefault(session_id, asyncio.Event())

    with db.transaction() as c:
        c.execute("UPDATE sessions SET status='active', start_time=? WHERE id=?", (db.now_iso(), session_id))
        c.execute("UPDATE connectors SET status='occupied', updated_at=? WHERE id=?", (db.now_iso(), connector_id))
    await _publish(session_id, {"type": "status", "status": "active"})

    user_stopped = False
    for tick in range(1, total_ticks + 1):
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=TICK_SECONDS)
            user_stopped = True
            break
        except asyncio.TimeoutError:
            pass

        energy_kwh += power_kw * (TICK_SECONDS / 3600)
        db.get_conn().execute(
            "INSERT INTO meter_values (session_id, reading_kwh, power_kw, recorded_at) VALUES (?, ?, ?, ?)",
            (session_id, round(energy_kwh, 3), power_kw, db.now_iso()),
        )
        await _publish(
            session_id,
            {
                "type": "meter_value",
                "tick": tick,
                "of": total_ticks,
                "energy_kwh": round(energy_kwh, 3),
                "power_kw": round(power_kw, 1),
                "cost": round(energy_kwh * rate, 2),
            },
        )

    _stop_events.pop(session_id, None)

    if user_stopped:
        await _finish_session(session_id, connector_id, energy_kwh, rate, status="stopped_remotely", fail_reason=None)
    elif will_fail:
        await _finish_session(
            session_id,
            connector_id,
            energy_kwh,
            rate,
            status="failed",
            fail_reason="station_fault: connector faulted mid-session (OCPP StatusNotification: Faulted)",
        )
    else:
        await _finish_session(session_id, connector_id, energy_kwh, rate, status="completed", fail_reason=None)


async def _finish_session(session_id: str, connector_id: str, energy_kwh: float, rate: float, status: str, fail_reason: str | None) -> None:
    cost = round(energy_kwh * rate, 2)
    claim = None

    with db.transaction() as c:
        c.execute(
            "UPDATE sessions SET status=?, end_time=?, energy_kwh=?, cost=?, fail_reason=? WHERE id=?",
            (status, db.now_iso(), round(energy_kwh, 3), cost, fail_reason, session_id),
        )
        session = db.row_to_dict(c.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone())

        if status == "failed":
            c.execute("UPDATE connectors SET status='faulted', updated_at=? WHERE id=?", (db.now_iso(), connector_id))
            claim = insurance.maybe_file_claim(c, session)
        else:
            c.execute("UPDATE connectors SET status='available', updated_at=? WHERE id=?", (db.now_iso(), connector_id))
            c.execute(
                """INSERT INTO payments (id, session_id, payment_method_id, amount, status, psp_reference, created_at)
                   VALUES (?, ?, (SELECT id FROM payment_methods WHERE user_id=? AND is_default=1 LIMIT 1), ?, 'captured', ?, ?)""",
                (db.new_id(), session_id, session["user_id"], cost, f"psp_mock_{db.new_id()[:12]}", db.now_iso()),
            )

        reliability.recompute(c, connector_id)

    await _publish(
        session_id,
        {"type": "final", "status": status, "energy_kwh": round(energy_kwh, 3), "cost": cost, "fail_reason": fail_reason, "claim": claim},
    )

    if status == "failed":
        asyncio.create_task(_auto_repair(connector_id))


async def _auto_repair(connector_id: str, delay_seconds: int = AUTO_REPAIR_DELAY_SECONDS) -> None:
    """Dev convenience only: brings a faulted demo connector back to
    available after a short delay so the flaky connector can be retried
    without a manual DB reset. In production this is the station
    admin/support ticket-resolution flow, not a timer."""
    await asyncio.sleep(delay_seconds)
    with db.transaction() as c:
        row = db.row_to_dict(c.execute("SELECT status FROM connectors WHERE id=?", (connector_id,)).fetchone())
        if row and row["status"] == "faulted":
            c.execute("UPDATE connectors SET status='available', updated_at=? WHERE id=?", (db.now_iso(), connector_id))
