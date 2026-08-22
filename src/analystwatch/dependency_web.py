from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .dependencies import AssetKind, DependencyEdge
from .dependency_service import DependencyService
from .dependency_storage import PostgresDependencyStore, SQLiteDependencyStore
from .scorecard_web import router as scorecard_router


def _dependency_store(
    *,
    db_path: Path,
    workspace_id: str,
    storage_backend: str,
    postgres_dsn: str | None,
):
    if storage_backend == "postgres":
        if not postgres_dsn:
            raise ValueError("Dependency PostgreSQL storage requires a PostgreSQL DSN")
        store = PostgresDependencyStore(postgres_dsn, workspace_id)
    else:
        dependency_path = db_path.with_suffix(db_path.suffix + ".dependencies.db")
        store = SQLiteDependencyStore(dependency_path, workspace_id)
    store.initialize()
    return store


def configure_dependency_web(
    app: FastAPI,
    *,
    templates: Jinja2Templates,
    db_path: Path,
    workspace_id: str,
    storage_backend: str,
    postgres_dsn: str | None,
) -> DependencyService:
    store = _dependency_store(
        db_path=db_path,
        workspace_id=workspace_id,
        storage_backend=storage_backend,
        postgres_dsn=postgres_dsn,
    )
    service = DependencyService(store)
    app.state.dependency_store = store
    app.state.dependency_service = service
    app.include_router(scorecard_router)

    @app.get("/dependencies", response_class=HTMLResponse)
    def dependency_index(request: Request):
        roots = []
        for asset in service.roots():
            roots.append(
                {
                    "asset": asset,
                    "blast_radius": service.blast_radius(asset.kind, asset.id),
                }
            )
        return templates.TemplateResponse(
            request=request,
            name="dependencies.html",
            context={
                "roots": roots,
                "edges": service.edges(),
                "asset_count": len(service.assets()),
                "workspace_id": workspace_id,
                "static_css": str(request.url_for("static", path="/app.css")),
                "home_href": "/",
            },
        )

    @app.get("/api/dependencies/edges")
    def api_dependency_edges():
        return service.edges()

    @app.put("/api/dependencies/edges/{edge_id}")
    def api_upsert_dependency_edge(edge_id: str, edge: DependencyEdge):
        if edge_id != edge.id:
            raise HTTPException(
                status_code=409,
                detail="Dependency edge ID does not match request path",
            )
        if edge.workspace_id != workspace_id:
            raise HTTPException(
                status_code=409,
                detail="Dependency edge belongs to another workspace",
            )
        try:
            return service.upsert_edge(edge)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.delete("/api/dependencies/edges/{edge_id}")
    def api_delete_dependency_edge(edge_id: str):
        if not service.delete_edge(edge_id):
            raise HTTPException(status_code=404, detail="Dependency edge not found")
        return {"deleted": True, "edge_id": edge_id}

    @app.get("/api/dependencies/assets")
    def api_dependency_assets():
        return service.assets()

    @app.get("/api/dependencies/blast-radius")
    def api_dependency_blast_radius(kind: AssetKind, asset_id: str):
        try:
            return service.blast_radius(kind, asset_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return service
