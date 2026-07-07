"""Minimal structured-ish logging setup — stdlib only.

Not the PRD's full "distributed tracing across REST API -> Kafka -> OCPP
Central System, correlated by session_id" (§5.3) — that needs a real
tracing backend (OpenTelemetry + a collector). This is the version of that
idea that costs nothing to run: every request gets a request_id, it's
returned in the X-Request-ID response header, and it's included in every
log line for that request so operators can grep one request's full story
out of the log even with concurrent traffic.
"""
from __future__ import annotations

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
