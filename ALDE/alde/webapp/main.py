from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import init_db
from .jobs import runner
from .routers import agents, audit, auth, health

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "Multi-tenant ALDE platform for deploying, training and testing "
        "multi-agent systems."
    ),
)

app.include_router(health.router, prefix=settings.api_prefix)
app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(agents.router, prefix=settings.api_prefix)
app.include_router(audit.router, prefix=settings.api_prefix)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    runner.start()


@app.on_event("shutdown")
def on_shutdown() -> None:
    runner.stop()

_static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/")
def frontend_index() -> FileResponse:
    return FileResponse(_static_dir / "index.html")
