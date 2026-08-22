from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .power_bi import PowerBIGuardDefinition
from .power_bi_service import PowerBIGuardService
from .power_bi_storage import PostgresPowerBIGuardStore, SQLitePowerBIGuardStore
from .store import MonitoringStore


def _power_bi_store(
    *,
    db_path: Path,
    workspace_id: str,
    storage_backend: str,
    postgres_dsn: str | None,
):
    if storage_backend == "postgres":
        if not postgres_dsn:
            raise ValueError("Power BI Guard PostgreSQL storage requires a PostgreSQL DSN")
        store = PostgresPowerBIGuardStore(postgres_dsn, workspace_id)
    else:
        guard_path = db_path.with_suffix(db_path.suffix + ".powerbi.db")
        store = SQLitePowerBIGuardStore(guard_path, workspace_id)
    store.initialize()
    return store


def configure_power_bi_web(
    app: FastAPI,
    *,
    templates: Jinja2Templates,
    monitoring_store: MonitoringStore,
    db_path: Path,
    workspace_id: str,
    storage_backend: str,
    postgres_dsn: str | None,
) -> None:
    store = _power_bi_store(
        db_path=db_path,
        workspace_id=workspace_id,
        storage_backend=storage_backend,
        postgres_dsn=postgres_dsn,
    )
    service = PowerBIGuardService(store, monitoring_store)
    app.state.power_bi_store = store
    app.state.power_bi_service = service

    def guard_view(definition: PowerBIGuardDefinition) -> dict[str, object]:
        latest = service.latest_snapshot(definition.id)
        return {
            "guard": definition,
            "latest": latest,
            "health": latest.health.value if latest else "Not checked",
            "href": f"/power-bi/{definition.id}",
        }

    @app.get("/power-bi", response_class=HTMLResponse)
    def power_bi_index(request: Request):
        guards = [guard_view(guard) for guard in service.list_guards()]
        return templates.TemplateResponse(
            request=request,
            name="power_bi.html",
            context={
                "guards": guards,
                "workspace_id": workspace_id,
                "static_css": str(request.url_for("static", path="/app.css")),
                "home_href": "/",
            },
        )

    @app.get("/power-bi/{guard_id}", response_class=HTMLResponse)
    def power_bi_detail(request: Request, guard_id: str):
        definition = service.get_guard(guard_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="Power BI Guard not found")
        latest = service.latest_snapshot(guard_id)
        return templates.TemplateResponse(
            request=request,
            name="power_bi_detail.html",
            context={
                **guard_view(definition),
                "history": service.snapshots(guard_id, limit=12),
                "static_css": str(request.url_for("static", path="/app.css")),
                "home_href": "/",
                "guards_href": "/power-bi",
            },
        )

    @app.get("/api/power-bi/guards")
    def api_power_bi_guards():
        return [guard_view(guard) for guard in service.list_guards()]

    @app.get("/api/power-bi/guards/{guard_id}")
    def api_power_bi_guard(guard_id: str):
        definition = service.get_guard(guard_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="Power BI Guard not found")
        return {
            **guard_view(definition),
            "history": service.snapshots(guard_id, limit=30),
        }

    @app.put("/api/power-bi/guards/{guard_id}")
    def api_upsert_power_bi_guard(guard_id: str, definition: PowerBIGuardDefinition):
        if guard_id != definition.id:
            raise HTTPException(status_code=409, detail="Guard ID does not match request path")
        if definition.workspace_id != workspace_id:
            raise HTTPException(status_code=409, detail="Power BI Guard belongs to another workspace")
        return service.upsert_guard(definition)

    @app.post("/api/power-bi/guards/{guard_id}/check")
    def api_check_power_bi_guard(guard_id: str):
        try:
            return service.check_guard(guard_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
