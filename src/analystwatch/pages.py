from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlsplit, urlunsplit

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .google_sheets import public_google_sheets_location
from .incidents import latest_incident
from .models import DeliveryAttempt, NotificationCandidate, SourceDefinition, SourceType
from .row_diff import strip_row_diff_raw_payloads
from .scheduler import run_decision
from .storage import Storage

PACKAGE_DIR = Path(__file__).parent


def _public_location(source: SourceDefinition) -> str:
    if source.source_type == SourceType.MICROSOFT_EXCEL:
        parsed = urlparse(source.location)
        table_name = (parse_qs(parsed.query).get("table") or [""])[0].strip()
        return f"Microsoft 365 Excel · {table_name}" if table_name else "Microsoft 365 Excel"
    if source.source_type == SourceType.GOOGLE_SHEETS:
        return public_google_sheets_location(source.location)
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


def _public_finding(finding):
    if not finding.detector.startswith("data_rule:"):
        return finding
    return finding.model_copy(
        update={
            "detector": "data_rule",
            "description": "A configured Data Rule failed.",
            "baseline_value": "Private configured Data Rule",
            "why_flagged": "Current data did not satisfy a private configured Data Rule.",
            "likely_impact": "A declared business-data invariant is not satisfied.",
            "suggested_investigation": (
                "Review the private Data Rule in AnalystWatch and inspect the upstream data."
            ),
        }
    )


def _public_observation(observation):
    if observation is None:
        return None
    public = strip_row_diff_raw_payloads(observation)
    return public.model_copy(
        update={"findings": [_public_finding(finding) for finding in public.findings]}
    )


def _source_view(storage: Storage, source: SourceDefinition, *, now: datetime) -> dict[str, object]:
    latest = storage.get_latest(source.id)
    baseline = storage.get_baseline(source.id)
    last_successful = storage.get_last_successful(source.id)
    decision = run_decision(storage, source, now=now)
    candidates = storage.list_notification_candidates(source.id, limit=100)
    attempts = storage.list_delivery_attempts(source_id=source.id, limit=100)
    return {
        "source": source,
        "public_location": _public_location(source),
        "latest": _public_observation(latest),
        "baseline": baseline,
        "last_successful": last_successful,
        "latest_review": storage.get_review(latest.id) if latest else None,
        "incident": latest_incident(storage.list_observations(source.id, limit=200)),
        "notification_candidates": candidates,
        "notification_candidate_count": len(candidates),
        "notification_candidate_states": _candidate_state_counts(candidates),
        "delivery_attempt_count": len(attempts),
        "delivery_attempt_states": _attempt_state_counts(attempts),
        "health": latest.health.value if latest else "Not checked",
        "schedule": decision,
    }


def _public_state(storage: Storage, *, generated_at: datetime) -> dict[str, object]:
    sources: list[dict[str, object]] = []
    for source in storage.list_sources():
        latest = storage.get_latest(source.id)
        public_latest = _public_observation(latest)
        baseline = storage.get_baseline(source.id)
        review = storage.get_review(latest.id) if latest else None
        incident = latest_incident(storage.list_observations(source.id, limit=200))
        candidates = storage.list_notification_candidates(source.id, limit=1000)
        attempts = storage.list_delivery_attempts(source_id=source.id, limit=1000)
        sources.append(
            {
                "id": source.id,
                "name": source.name,
                "source_type": source.source_type.value,
                "location": _public_location(source),
                "enabled": source.enabled,
                "monitor_interval_minutes": source.config.monitor_interval_minutes,
                "notification_transitions": [
                    item.value for item in source.config.notification_transitions
                ],
                "delivery_retry_minutes": source.config.delivery_retry_minutes,
                "health": latest.health.value if latest else "Not checked",
                "review_state": review.state.value if review else None,
                "incident": incident.model_dump(mode="json") if incident else None,
                "notification_candidate_count": len(candidates),
                "notification_candidate_states": _candidate_state_counts(candidates),
                "delivery_attempt_count": len(attempts),
                "delivery_attempt_states": _attempt_state_counts(attempts),
                "latest": json.loads(public_latest.model_dump_json()) if public_latest else None,
                "baseline_id": baseline.id if baseline else None,
            }
        )
    return {"generated_at": generated_at.isoformat(), "sources": sources}


def build_pages_site(
    storage: Storage,
    output_dir: str | Path,
    *,
    generated_at: datetime | None = None,
) -> Path:
    output = Path(output_dir)
    generated = generated_at or datetime.now(timezone.utc)
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)

    if output.exists():
        shutil.rmtree(output)
    (output / "static").mkdir(parents=True)
    (output / "sources").mkdir(parents=True)
    shutil.copy2(PACKAGE_DIR / "static" / "app.css", output / "static" / "app.css")
    (output / ".nojekyll").write_text("", encoding="utf-8")

    env = Environment(
        loader=FileSystemLoader(PACKAGE_DIR / "templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    index_template = env.get_template("index.html")
    source_template = env.get_template("source.html")

    source_views: list[dict[str, object]] = []
    for source in storage.list_sources():
        view = _source_view(storage, source, now=generated)
        view["href"] = f"sources/{source.id}/"
        source_views.append(view)

        source_dir = output / "sources" / source.id
        source_dir.mkdir(parents=True)
        detail = source_template.render(
            **view,
            history=storage.list_observations(source.id, limit=12),
            static_mode=True,
            static_css="../../static/app.css",
            home_href="../../",
            generated_at=generated,
        )
        (source_dir / "index.html").write_text(detail, encoding="utf-8")

    index = index_template.render(
        sources=source_views,
        static_mode=True,
        static_css="static/app.css",
        generated_at=generated,
    )
    (output / "index.html").write_text(index, encoding="utf-8")
    (output / "state.json").write_text(
        json.dumps(_public_state(storage, generated_at=generated), indent=2),
        encoding="utf-8",
    )
    return output
