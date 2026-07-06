from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .routers import auth as auth_router
from .routers import payments, sessions, stations, trust
from .seed import run as seed_run
from .services import ocpp_sim

WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"

app = FastAPI(title="EV Charging Platform API", version="1.0")


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

if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")

    @app.get("/")
    def serve_index():
        return FileResponse(WEB_DIR / "index.html")
