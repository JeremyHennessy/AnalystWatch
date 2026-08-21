from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import httpx

from .detectors import detect_freshness, detect_profile_changes, health_from_findings
from .ingest import ingest_source
from .models import Finding, HealthStatus, Observation, RunDecision, SourceDefinition
from .preflight import SourcePreflight, preflight_source
from .profile import profile_dataframe
from .scheduler import run_decision
from .storage import Storage


class MonitorService:
    def __init__(self, storage: Storage):
        self.storage = storage
        self.storage.initialize()

    def add_source(self, source: SourceDefinition) -> SourceDefinition:
        self.storage.upsert_source(source)
        return source

    def add_sources(self, sources: list[SourceDefinition]) -> list[SourceDefinition]:
        for source in sources:
            self.add_source(source)
        return sources

    def preflight_source(
        self,
        source: SourceDefinition,
        *,
        client: httpx.Client | None = None,
        now: datetime | None = None,
    ) -> SourcePreflight:
        return preflight_source(source, client=client, now=now)

    def onboard_source(
        self,
        source: SourceDefinition,
        *,
        client: httpx.Client | None = None,
        now: datetime | None = None,
    ) -> SourcePreflight:
        if self.storage.get_source(source.id) is not None:
            raise ValueError(
                f"Source ID already exists: {source.id}. "
                "Editing existing sources is a separate workflow."
            )
        preflight = self.preflight_source(source, client=client, now=now)
        if not preflight.ready:
            return preflight
        self.add_source(source)
        return preflight.model_copy(update={"accepted": True})

    def get_run_decision(
        self,
        source_id: str,
        *,
        now: datetime | None = None,
    ) -> RunDecision:
        source = self.storage.get_source(source_id)
        if source is None:
            raise KeyError(f"Unknown source: {source_id}")
        return run_decision(self.storage, source, now=now)

    def check_due_sources(self, *, now: datetime | None = None) -> list[Observation]:
        observations: list[Observation] = []
        for source in self.storage.list_sources():
            decision = run_decision(self.storage, source, now=now)
            if decision.due:
                observations.append(self.check_source(source.id, now=now))
        return observations

    def check_all_sources(self, *, now: datetime | None = None) -> list[Observation]:
        return [
            self.check_source(source.id, now=now)
            for source in self.storage.list_sources()
            if source.enabled
        ]

    def check_source(
        self,
        source_id: str,
        *,
        client: httpx.Client | None = None,
        now: datetime | None = None,
    ) -> Observation:
        source = self.storage.get_source(source_id)
        if source is None:
            raise KeyError(f"Unknown source: {source_id}")
        if not source.enabled:
            raise ValueError(f"Source is disabled: {source_id}")

        observed_at = now or datetime.now(timezone.utc)
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)

        baseline = self.storage.get_baseline(source_id)
        reference_observations = self.storage.list_reference_observations(
            source_id, limit=source.config.history_window_size
        )
        history_profiles = [
            item.profile for item in reference_observations if item.profile is not None
        ]

        result = ingest_source(source, client=client)
        findings: list[Finding] = []
        profile = None

        if not result.available or result.dataframe is None:
            findings.append(
                Finding(
                    severity=HealthStatus.CRITICAL,
                    detector="availability",
                    description="Source could not be read successfully.",
                    current_value=result.error,
                    baseline_value="available" if baseline else None,
                    why_flagged=result.error or "The source returned no usable dataset.",
                    confidence="high",
                    likely_impact="Dependent analysis cannot be refreshed reliably.",
                    suggested_investigation="Check the source path/URL and upstream availability.",
                )
            )
        else:
            profile = profile_dataframe(
                result.dataframe,
                source.config.latest_date_field,
                infer_latest_date_field=source.config.infer_latest_date_field,
                numeric_fields=source.config.numeric_fields,
            )
            findings.extend(
                detect_freshness(
                    config=source.config,
                    profile=profile,
                    source_modified_at=result.source_modified_at,
                    observed_at=observed_at,
                )
            )
            if baseline and baseline.profile:
                findings.extend(
                    detect_profile_changes(
                        baseline.profile,
                        profile,
                        source.config,
                        history=history_profiles,
                    )
                )

        health = health_from_findings(findings)
        observation = Observation(
            id=str(uuid4()),
            source_id=source_id,
            observed_at=observed_at,
            available=result.available,
            health=health,
            findings=findings,
            profile=profile,
            http_status=result.http_status,
            response_ms=result.response_ms,
            source_modified_at=result.source_modified_at,
            response_etag=result.response_etag,
            error=result.error,
            is_baseline=baseline is None and result.available and profile is not None,
        )
        self.storage.save_observation(observation, set_baseline=observation.is_baseline)
        return observation
