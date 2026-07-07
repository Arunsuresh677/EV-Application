from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .logging_config import get_logger
from .routers import admin, auth as auth_router
from .routers import fleet, operator, payments, sessions, stations, trust
from .seed import run as seed_run
from .services import ocpp_sim

WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"
log = get_logger("http")

app = FastAPI(title="EV Charging Platform API", version="1.0")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Every request gets a request_id, logged with method/path/status/
    duration and echoed back in X-Request-ID — enough to grep one request's
    story out of the log without a real tracing backend."""
    request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:12])
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = round((time.monotonic() - start) * 1000, 1)
    response.headers["X-Request-ID"] = request_id
    log.info(
        "%s %s -> %s (%sms) [%s]",
        request.method, request.url.path, response.status_code, duration_ms, request_id,
    )
    return response


@app.on_event("startup")
async def on_startup() -> None:
    db.init_db()
    seed_run()
    ocpp_sim.set_main_loop(asyncio.get_running_loop())


app.include_router(auth_router.router, prefix="/v1")
app.include_router(stations.router, prefix="/v1")
app.include_router(sessions.router, prefix="/v1")
app.include_router(trust.router, prefix="/v1")
app.include_router(payments.router, prefix="/v1")
app.include_router(operator.router, prefix="/v1")
app.include_router(admin.router, prefix="/v1")
app.include_router(fleet.router, prefix="/v1")

if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")

    @app.get("/")
    def serve_index():
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/operator")
    def serve_operator_dashboard():
        return FileResponse(WEB_DIR / "operator.html")

    @app.get("/admin")
    def serve_admin_dashboard():
        return FileResponse(WEB_DIR / "admin.html")

    @app.get("/fleet")
    def serve_fleet_dashboard():
        return FileResponse(WEB_DIR / "fleet.html")
