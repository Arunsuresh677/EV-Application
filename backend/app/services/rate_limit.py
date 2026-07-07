"""In-memory sliding-window rate limiter.

Per the PRD's security requirements (§5.2): "Rate limiting ... on
RemoteStartTransaction to prevent charge-fraud" and general brute-force
protection on auth. In-memory is a deliberate scope choice — this is a
single-process dev/pilot deployment; a multi-instance production deployment
would swap this for a shared store (Redis INCR + EXPIRE is the standard
pattern) without changing the call sites below.
"""
from __future__ import annotations

import time
from collections import defaultdict

from fastapi import HTTPException

from ..logging_config import get_logger

log = get_logger("rate_limit")

_hits: dict[str, list[float]] = defaultdict(list)


def check(key: str, max_requests: int, window_seconds: float) -> None:
    """Raise 429 if `key` has exceeded `max_requests` within `window_seconds`.
    Otherwise records this attempt and returns."""
    now = time.monotonic()
    window_start = now - window_seconds
    attempts = _hits[key]

    # Prune expired attempts — keeps memory bounded without a background sweep.
    while attempts and attempts[0] < window_start:
        attempts.pop(0)

    if len(attempts) >= max_requests:
        # This is the cheap version of the PRD's "anomaly detection" ask —
        # a real system would feed this into an alerting pipeline, not just
        # a log line, but the signal (who, what, how often) is the same.
        log.warning("Rate limit exceeded for %r (%s attempts in %ss)", key, len(attempts), window_seconds)
        raise HTTPException(status_code=429, detail="Too many attempts — please slow down and try again shortly")

    attempts.append(now)
