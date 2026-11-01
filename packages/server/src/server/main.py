"""FastAPI app. The HTTP API is the only interface to the server."""

from __future__ import annotations

import pathlib

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from server import db, errors
from server.config import Settings
from server.envelope import action, ok
from server.routes import admin, auth, brands, challenges, notes, proposals, runs, score
from server.services import Services

VERSION = "0.0.0"
UI_FILE = pathlib.Path(__file__).parent / "ui" / "index.html"


def create_app(settings: Settings | None = None, services: Services | None = None) -> FastAPI:
    app = FastAPI(title="Vybd Brand Builder", version=VERSION)
    app.state.services = services or Services(settings or Settings())
    errors.install(app)

    @app.get("/healthz")
    def healthz() -> dict:
        """Liveness: process is up. Does not touch the DB."""
        return ok({"service": "vybd-server", "version": VERSION},
                  next_actions=[action("auth.signup", email="you@example.com")])

    @app.get("/readyz")
    def readyz() -> dict:
        """Readiness: DB reachable."""
        up = db.db_ok()
        return {"ok": up, "data": {"database": "up" if up else "down"}}

    @app.get("/ui", response_class=HTMLResponse, include_in_schema=False)
    def ui() -> HTMLResponse:
        """Read-only brand view. Auth happens client-side with the bearer token."""
        return HTMLResponse(UI_FILE.read_text())

    for r in (auth.router, brands.router, challenges.router, notes.router, score.router,
              runs.router, proposals.router, admin.router):
        app.include_router(r)
    return app


app = create_app()
