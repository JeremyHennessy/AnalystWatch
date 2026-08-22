from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException

from .service import MonitorService
from .teams_delivery import (
    TeamsWorkflowAdapter,
    TeamsWorkflowDestination,
    deliver_teams_candidate,
)


def _adapter_from_environment() -> TeamsWorkflowAdapter | None:
    webhook_url = os.environ.get("ANALYSTWATCH_TEAMS_WORKFLOW_WEBHOOK_URL")
    if webhook_url is None:
        return None
    if not webhook_url or webhook_url != webhook_url.strip():
        raise ValueError(
            "ANALYSTWATCH_TEAMS_WORKFLOW_WEBHOOK_URL must be a trimmed non-empty secret/value"
        )
    base_url = os.environ.get("ANALYSTWATCH_PUBLIC_BASE_URL")
    if base_url is None or not base_url or base_url != base_url.strip():
        raise ValueError(
            "ANALYSTWATCH_PUBLIC_BASE_URL is required when Teams Workflows delivery is configured"
        )
    return TeamsWorkflowAdapter(
        TeamsWorkflowDestination(webhook_url=webhook_url, base_url=base_url)
    )


def configure_teams_web(
    app: FastAPI,
    *,
    monitoring_service: MonitorService,
    adapter: TeamsWorkflowAdapter | None = None,
) -> None:
    resolved_adapter = adapter if adapter is not None else _adapter_from_environment()
    app.state.teams_workflow_configured = resolved_adapter is not None

    @app.get("/api/delivery/teams/status")
    def teams_delivery_status() -> dict[str, bool]:
        return {"configured": resolved_adapter is not None}

    @app.post("/api/delivery-attempts/teams")
    def api_deliver_teams(candidate_id: str, idempotency_key: str):
        if resolved_adapter is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Microsoft Teams Workflows delivery is not configured. "
                    "Set ANALYSTWATCH_TEAMS_WORKFLOW_WEBHOOK_URL and ANALYSTWATCH_PUBLIC_BASE_URL."
                ),
            )
        created_at = datetime.now(timezone.utc)
        try:
            return deliver_teams_candidate(
                monitoring_service.storage,
                candidate_id,
                idempotency_key,
                resolved_adapter,
                created_at=created_at,
                claim_owner=monitoring_service.execution_owner,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
