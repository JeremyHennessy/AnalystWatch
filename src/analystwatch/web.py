from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .models import (
    DeliveryAttempt,
    DeliveryReconciliationOutcome,
    NotificationCandidate,
    ObservationReviewState,
    SourceDefinition,
    SourceType,
)
from .service import MonitorService
from .storage import Storage
from .workspace import DEFAULT_WORKSPACE_ID, WorkspaceStore, validate_workspace_id

PACKAGE_DIR = Path(__file__).parent


def _public_location(source: SourceDefinition) -> str:
    if source.source_type != SourceType.API:
        return source.location
    parts = urlsplit(source.location)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _candidate_state_counts(candidates: list[NotificationCandidate]) -> dict[str, int]:
    counts = {"Pending": 0, "Eligible": 0, "Suppressed": 0}
    for candidate in candidates:
        counts[candidate.state.value] = counts.get(candidate.state.value, 0) + 1
    return counts


def _attempt_state_counts(attempts: list[DeliveryAttempt]) -> dict[str, int]:
    counts = {"Prepared": 0, "Succeeded": 0, "Failed": 0}
    for attempt in attempts:
        counts[attempt.state.value] = counts.get(attempt.state.value, 0) + 1
    return counts


def create_app(
    db_path: str | Path | None = None,
    workspace_id: str | None = None,
) -> FastAPI:
    resolved_db = Path(db_path or os.environ.get("ANALYSTWATCH_DB", "instance/analystwatch.db"))
    resolved_workspace = validate_workspace_id(
        workspace_id
        if workspace_id is not None
        else os.environ.get("ANALYSTWATCH_WORKSPACE_ID", DEFAULT_WORKSPACE_ID)
    )
    raw_storage = Storage(resolved_db)
    storage = WorkspaceStore(raw_storage, resolved_workspace)
    service = MonitorService(storage)

    app = FastAPI(title="AnalystWatch", version="0.10.0")
    app.state.storage = raw_storage
    app.state.workspace_storage = storage
    app.state.service = service
    app.state.workspace_id = resolved_workspace
    templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")

    def require_source_workspace(source: SourceDefinition) -> None:
        if source.workspace_id != resolved_workspace:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Source workspace {source.workspace_id!r} does not match bound workspace "
                    f"{resolved_workspace!r}"
                ),
            )

    def source_view(source: SourceDefinition) -> dict[str, object]:
        latest = storage.get_latest(source.id)
        baseline = storage.get_baseline(source.id)
        last_successful = storage.get_last_successful(source.id)
        latest_review = storage.get_review(latest.id) if latest else None
        baseline_review = service.baseline_review(source.id) if latest and baseline else None
        candidates = service.notification_candidates(source.id, limit=100)
        attempts = service.delivery_attempts(source_id=source.id, limit=100)
        return {
            "source": source,
            "public_location": _public_location(source),
            "latest": latest,
            "baseline": baseline,
            "last_successful": last_successful,
            "latest_review": latest_review,
            "baseline_review": baseline_review,
            "incident": service.incident(source.id),
            "notification_candidates": candidates,
            "notification_candidate_count": len(candidates),
            "notification_candidate_states": _candidate_state_counts(candidates),
            "delivery_attempts": attempts,
            "delivery_attempt_count": len(attempts),
            "delivery_attempt_states": _attempt_state_counts(attempts),
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

    @app.post("/sources/{source_id}/review")
    def review_from_ui(source_id: str, state: ObservationReviewState):
        latest = storage.get_latest(source_id)
        if latest is None:
            raise HTTPException(status_code=409, detail="No observation available to review")
        try:
            service.review_observation(source_id, latest.id, state)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return RedirectResponse(url=f"/sources/{source_id}", status_code=303)

    @app.post("/sources/{source_id}/baseline")
    def baseline_from_ui(
        source_id: str,
        candidate_id: str,
        expected_current_baseline_id: str,
    ):
        try:
            service.promote_baseline_after_review(
                source_id,
                candidate_id,
                expected_current_baseline_id,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return RedirectResponse(url=f"/sources/{source_id}", status_code=303)

    @app.post("/api/preflight")
    def api_preflight(source: SourceDefinition):
        return service.preflight_source(source)

    @app.post("/api/onboard")
    def api_onboard(source: SourceDefinition):
        require_source_workspace(source)
        try:
            return service.onboard_source(source)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/sources")
    def create_source(source: SourceDefinition):
        require_source_workspace(source)
        try:
            return service.onboard_source(source)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.put("/api/sources/{source_id}")
    def update_source(source_id: str, replacement: SourceDefinition):
        require_source_workspace(replacement)
        try:
            return service.update_source(source_id, replacement)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

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

    @app.get("/api/sources/{source_id}/incident")
    def api_incident(source_id: str):
        try:
            return service.incident(source_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/notification-candidates")
    def api_notification_candidates(source_id: str | None = None, limit: int = 100):
        try:
            return service.notification_candidates(source_id, limit=limit)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/notification-candidates/evaluate")
    def api_evaluate_notification_candidates(source_id: str):
        try:
            return service.evaluate_pending_notification_candidates(source_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/delivery-attempts")
    def api_delivery_attempts(
        candidate_id: str | None = None,
        source_id: str | None = None,
        limit: int = 100,
    ):
        try:
            return service.delivery_attempts(
                candidate_id=candidate_id,
                source_id=source_id,
                limit=limit,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/delivery-attempts/retry-status")
    def api_delivery_retry_status(candidate_id: str):
        try:
            return service.delivery_retry_decision(candidate_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/delivery-attempts/dry-run")
    def api_dry_run_delivery(candidate_id: str, idempotency_key: str):
        try:
            return service.dry_run_delivery(candidate_id, idempotency_key)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/delivery-attempts/{attempt_id}/reconcile")
    def api_reconcile_delivery_attempt(
        attempt_id: str,
        outcome: DeliveryReconciliationOutcome,
        note: str,
    ):
        try:
            return service.reconcile_delivery_attempt(attempt_id, outcome, note)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/sources/{source_id}/baseline-review")
    def api_baseline_review(source_id: str, observation_id: str | None = None):
        try:
            return service.baseline_review(source_id, observation_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/sources/{source_id}/observations/{observation_id}/review")
    def api_review_observation(
        source_id: str,
        observation_id: str,
        state: ObservationReviewState,
    ):
        try:
            return service.review_observation(source_id, observation_id, state)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

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
    def api_promote_baseline(
        source_id: str,
        observation_id: str,
        expected_current_baseline_id: str,
    ):
        try:
            return service.promote_baseline_after_review(
                source_id,
                observation_id,
                expected_current_baseline_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return app


app = create_app()
