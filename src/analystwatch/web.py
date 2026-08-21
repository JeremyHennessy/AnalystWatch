from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .models import SourceDefinition
from .service import MonitorService
from .storage import Storage

PACKAGE_DIR = Path(__file__).parent


def create_app(db_path: str | Path | None = None) -> FastAPI:
    resolved_db = Path(db_path or os.environ.get("ANALYSTWATCH_DB", "instance/analystwatch.db"))
    storage = Storage(resolved_db)
    service = MonitorService(storage)

    app = FastAPI(title="AnalystWatch", version="0.3.0")
    app.state.storage = storage
    app.state.service = service
    templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")

    def source_view(source: SourceDefinition) -> dict[str, object]:
        latest = storage.get_latest(source.id)
        baseline = storage.get_baseline(source.id)
        last_successful = storage.get_last_successful(source.id)
        return {
            "source": source,
            "public_location": source.location,
            "latest": latest,
            "baseline": baseline,
            "last_successful": last_successful,
            "health": latest.health.value if latest else "Not checked",
            "schedule": service.get_run_decision(source.id),
            "href": f"/sources/{source.id}",
        }

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        sources = [source_view(source) for source in storage.list_sources()]
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "sources": sources,
                "static_mode": False,
                "static_css": str(request.url_for("static", path="/app.css")),
                "generated_at": datetime.now(timezone.utc),
            },
        )

    @app.get("/sources/new", response_class=HTMLResponse)
    def new_source(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="onboard.html",
            context={
                "static_css": str(request.url_for("static", path="/app.css")),
                "onboard_css": str(request.url_for("static", path="/onboard.css")),
                "home_href": "/",
            },
        )

    @app.get("/sources/{source_id}", response_class=HTMLResponse)
    def source_detail(request: Request, source_id: str):
        source = storage.get_source(source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Source not found")
        return templates.TemplateResponse(
            request=request,
            name="source.html",
            context={
                **source_view(source),
                "history": storage.list_observations(source_id, limit=12),
                "static_mode": False,
                "static_css": str(request.url_for("static", path="/app.css")),
                "home_href": "/",
                "generated_at": datetime.now(timezone.utc),
            },
        )

    @app.post("/sources/{source_id}/check")
    def check_from_ui(source_id: str):
        try:
            service.check_source(source_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return RedirectResponse(url=f"/sources/{source_id}", status_code=303)

    @app.post("/api/preflight")
    def api_preflight(source: SourceDefinition):
        return service.preflight_source(source)

    @app.post("/api/onboard")
    def api_onboard(source: SourceDefinition):
        try:
            return service.onboard_source(source)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/sources", response_model=SourceDefinition)
    def create_source(source: SourceDefinition):
        return service.add_source(source)

    @app.get("/api/sources")
    def api_sources() -> list[dict[str, object]]:
        return [source_view(source) for source in storage.list_sources()]

    @app.get("/api/sources/{source_id}")
    def api_source(source_id: str) -> dict[str, object]:
        source = storage.get_source(source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Source not found")
        return {
            **source_view(source),
            "history": storage.list_observations(source_id, limit=20),
        }

    @app.get("/api/schedule")
    def api_schedule():
        return [service.get_run_decision(source.id) for source in storage.list_sources()]

    @app.post("/api/check-due")
    def api_check_due():
        return service.check_due_sources()

    @app.post("/api/sources/{source_id}/check")
    def api_check(source_id: str):
        try:
            return service.check_source(source_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/sources/{source_id}/baseline")
    def api_promote_baseline(source_id: str, observation_id: str | None = None):
        target = observation_id or (
            storage.get_latest(source_id).id if storage.get_latest(source_id) else None
        )
        if target is None:
            raise HTTPException(status_code=409, detail="No observation available")
        try:
            return storage.promote_baseline(source_id, target)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return app


app = create_app()
