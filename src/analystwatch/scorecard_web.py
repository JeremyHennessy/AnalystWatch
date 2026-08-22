from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from .dependencies import AssetKind
from .scorecards import ReliabilityScorecard


class DownstreamImpactSummary(BaseModel):
    total: int = Field(ge=0)
    counts: dict[str, int]


class ReliabilityScorecardResponse(BaseModel):
    scorecard: ReliabilityScorecard
    downstream_impact: DownstreamImpactSummary


def api_source_scorecard(request: Request, source_id: str) -> ReliabilityScorecardResponse:
    service = request.app.state.scorecard_service
    try:
        scorecard = service.scorecard(source_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    impact = DownstreamImpactSummary(total=0, counts={})
    dependency_service = getattr(request.app.state, "dependency_service", None)
    if dependency_service is not None:
        try:
            radius = dependency_service.blast_radius(AssetKind.SOURCE, source_id)
        except KeyError:
            pass
        else:
            impact = DownstreamImpactSummary(
                total=radius.total,
                counts=dict(sorted(radius.counts.items())),
            )

    return ReliabilityScorecardResponse(
        scorecard=scorecard,
        downstream_impact=impact,
    )


def configure_scorecard_web(app: FastAPI) -> None:
    app.add_api_route(
        "/api/sources/{source_id}/scorecard",
        api_source_scorecard,
        methods=["GET"],
        response_model=ReliabilityScorecardResponse,
    )
