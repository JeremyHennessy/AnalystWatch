from __future__ import annotations

from typing import Annotated
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .models import DeliveryReconciliationOutcome
from .reconciliation import (
    DEFAULT_QUEUE_LIMIT,
    DEFAULT_STALE_AFTER_MINUTES,
    build_delivery_reconciliation_queue,
)
from .service import MonitorService

MAX_STALE_AFTER_MINUTES = 10_080
MAX_QUEUE_LIMIT = 500
MAX_RECONCILIATION_FORM_BYTES = 4096
MAX_RECONCILIATION_NOTE_LENGTH = 2000


def _single_form_value(form: dict[str, list[str]], name: str) -> str:
    values = form.get(name, [])
    if len(values) != 1:
        raise ValueError(f"Expected exactly one {name} field")
    return values[0]


def configure_reconciliation_web(
    app: FastAPI,
    *,
    templates: Jinja2Templates,
    monitoring_service: MonitorService,
) -> None:
    def queue(
        stale_after_minutes: int = DEFAULT_STALE_AFTER_MINUTES,
        limit: int = DEFAULT_QUEUE_LIMIT,
    ):
        return build_delivery_reconciliation_queue(
            monitoring_service.storage,
            stale_after_minutes=stale_after_minutes,
            limit=limit,
        )

    @app.get("/reconciliation", response_class=HTMLResponse)
    def reconciliation_index(
        request: Request,
        stale_after_minutes: Annotated[
            int,
            Query(ge=1, le=MAX_STALE_AFTER_MINUTES),
        ] = DEFAULT_STALE_AFTER_MINUTES,
    ):
        current_queue = queue(stale_after_minutes=stale_after_minutes)
        return templates.TemplateResponse(
            request=request,
            name="reconciliation.html",
            context={
                "queue": current_queue,
                "static_css": str(request.url_for("static", path="/app.css")),
                "forms_css": str(request.url_for("static", path="/onboard.css")),
                "home_href": "/",
            },
        )

    @app.get("/api/delivery-reconciliation")
    def api_delivery_reconciliation(
        stale_after_minutes: Annotated[
            int,
            Query(ge=1, le=MAX_STALE_AFTER_MINUTES),
        ] = DEFAULT_STALE_AFTER_MINUTES,
        limit: Annotated[int, Query(ge=1, le=MAX_QUEUE_LIMIT)] = DEFAULT_QUEUE_LIMIT,
    ):
        return queue(stale_after_minutes=stale_after_minutes, limit=limit)

    @app.post("/reconciliation/{attempt_id}/resolve")
    async def reconcile_from_ui(request: Request, attempt_id: str):
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/x-www-form-urlencoded":
            raise HTTPException(status_code=415, detail="Expected URL-encoded reconciliation form")
        body = await request.body()
        if len(body) > MAX_RECONCILIATION_FORM_BYTES:
            raise HTTPException(status_code=413, detail="Reconciliation form is too large")
        try:
            form = parse_qs(body.decode("utf-8"), keep_blank_values=True)
            outcome = DeliveryReconciliationOutcome(_single_form_value(form, "outcome"))
            note = _single_form_value(form, "note")
        except (UnicodeDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if len(note) > MAX_RECONCILIATION_NOTE_LENGTH:
            raise HTTPException(status_code=400, detail="Reconciliation note is too long")

        auth_context = getattr(request.state, "auth_context", None)
        reviewer = auth_context.principal.user_id if auth_context is not None else None
        try:
            monitoring_service.reconcile_delivery_attempt(
                attempt_id,
                outcome,
                note,
                reviewer=reviewer,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return RedirectResponse(url="/reconciliation", status_code=303)
