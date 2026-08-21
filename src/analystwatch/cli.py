from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import uvicorn

from .config import load_sources
from .models import (
    DeliveryReconciliationOutcome,
    IncidentTransition,
    MonitoringConfig,
    SourceDefinition,
    SourceType,
)
from .pages import build_pages_site
from .service import MonitorService
from .storage import Storage


def _service(db: str) -> MonitorService:
    return MonitorService(Storage(db))


def _parse_header_env(items: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in items:
        header, separator, env_name = item.partition("=")
        if not separator or not header.strip() or not env_name.strip():
            raise SystemExit("--request-header-env must use Header-Name=ENV_VAR syntax")
        result[header.strip()] = env_name.strip()
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="analystwatch")
    parser.add_argument(
        "--db",
        default=os.environ.get("ANALYSTWATCH_DB", "instance/analystwatch.db"),
        help="SQLite database path",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add-source", help="Preflight and add/update a monitored source")
    add.add_argument("--id", required=True)
    add.add_argument("--name", required=True)
    add.add_argument("--type", required=True, choices=[item.value for item in SourceType])
    add.add_argument("--location", required=True)
    add.add_argument("--expected-refresh-minutes", type=int)
    add.add_argument("--monitor-interval-minutes", type=int, default=60)
    add.add_argument("--latest-date-field")
    add.add_argument("--infer-latest-date-field", action="store_true")
    add.add_argument("--sheet-name")
    add.add_argument("--json-record-path")
    add.add_argument("--unique-key", action="append", default=[])
    add.add_argument("--request-header-env", action="append", default=[])
    add.add_argument(
        "--notification-transition",
        action="append",
        default=[],
        choices=[item.value for item in IncidentTransition],
        help="Transition eligible for future notification delivery; repeat to enable multiple",
    )
    add.add_argument(
        "--delivery-retry-minutes",
        type=int,
        default=0,
        help="Delay after a Failed delivery attempt before a new key may retry",
    )
    add.add_argument("--history-window-size", type=int, default=5)
    add.add_argument("--min-history-observations", type=int, default=3)

    sync = sub.add_parser("sync-sources", help="Upsert sources from a JSON configuration file")
    sync.add_argument("path")

    check = sub.add_parser("check", help="Run one source check")
    check.add_argument("source_id")

    sub.add_parser("check-due", help="Run only sources whose monitoring interval has elapsed")
    sub.add_parser("check-all", help="Run every enabled source")
    sub.add_parser("schedule", help="Show current due/next-check decisions")
    sub.add_parser("list", help="List monitored sources")

    incident = sub.add_parser("incident", help="Show the latest derived incident for a source")
    incident.add_argument("source_id")

    candidates = sub.add_parser(
        "notification-candidates",
        help="List transition candidates; no delivery is performed",
    )
    candidates.add_argument("--source-id")
    candidates.add_argument("--limit", type=int, default=100)

    evaluate = sub.add_parser(
        "evaluate-notification-candidates",
        help="Evaluate legacy Pending candidates against the current source policy",
    )
    evaluate.add_argument("source_id")

    attempts = sub.add_parser(
        "delivery-attempts",
        help="List persisted delivery attempts; dry-run attempts only",
    )
    attempts.add_argument("--candidate-id")
    attempts.add_argument("--source-id")
    attempts.add_argument("--limit", type=int, default=100)

    retry_status = sub.add_parser(
        "delivery-retry-status",
        help="Show retry readiness independently from source monitoring cadence",
    )
    retry_status.add_argument("candidate_id")

    dry_run = sub.add_parser(
        "dry-run-delivery",
        help="Execute a local dry-run attempt with no external delivery",
    )
    dry_run.add_argument("candidate_id")
    dry_run.add_argument("--idempotency-key", required=True)

    reconcile = sub.add_parser(
        "reconcile-delivery-attempt",
        help="Resolve a Prepared attempt after explicit review",
    )
    reconcile.add_argument("attempt_id")
    reconcile.add_argument(
        "--outcome",
        required=True,
        choices=[item.value for item in DeliveryReconciliationOutcome],
    )
    reconcile.add_argument("--note", required=True)

    baseline_review = sub.add_parser("baseline-review", help="Review a baseline candidate")
    baseline_review.add_argument("source_id")
    baseline_review.add_argument("--observation-id")

    baseline = sub.add_parser(
        "promote-baseline",
        help="Promote a reviewed Healthy observation to baseline",
    )
    baseline.add_argument("source_id")
    baseline.add_argument("--observation-id")
    baseline.add_argument("--expected-baseline-id", required=True)

    pages = sub.add_parser("build-pages", help="Render a read-only static GitHub Pages site")
    pages.add_argument("--output", default="site")

    serve = sub.add_parser("serve", help="Run the local dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    return parser


def _print_observations(observations) -> None:
    print(
        json.dumps(
            [json.loads(observation.model_dump_json()) for observation in observations],
            indent=2,
        )
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    service = _service(args.db)

    if args.command == "add-source":
        config = MonitoringConfig(
            expected_refresh_minutes=args.expected_refresh_minutes,
            monitor_interval_minutes=args.monitor_interval_minutes,
            latest_date_field=args.latest_date_field,
            infer_latest_date_field=args.infer_latest_date_field,
            sheet_name=args.sheet_name,
            json_record_path=args.json_record_path,
            unique_keys=args.unique_key,
            request_header_env=_parse_header_env(args.request_header_env),
            notification_transitions=[
                IncidentTransition(item) for item in args.notification_transition
            ],
            delivery_retry_minutes=args.delivery_retry_minutes,
            history_window_size=args.history_window_size,
            min_history_observations=args.min_history_observations,
        )
        source = SourceDefinition(
            id=args.id,
            name=args.name,
            source_type=SourceType(args.type),
            location=args.location,
            config=config,
        )
        if service.storage.get_source(source.id) is None:
            result = service.onboard_source(source)
        else:
            result = service.update_source(source.id, source)
        print(result.model_dump_json(indent=2))
        return 0 if result.ready and result.accepted else 2

    if args.command == "sync-sources":
        sources = load_sources(args.path)
        service.add_sources(sources)
        print(json.dumps({"synced": [source.id for source in sources]}, indent=2))
        return 0

    if args.command == "check":
        observation = service.check_source(args.source_id)
        print(observation.model_dump_json(indent=2))
        return 0 if observation.health.value != "Critical" else 2

    if args.command == "check-due":
        _print_observations(service.check_due_sources())
        return 0

    if args.command == "check-all":
        _print_observations(service.check_all_sources())
        return 0

    if args.command == "schedule":
        decisions = [
            service.get_run_decision(source.id).model_dump(mode="json")
            for source in service.storage.list_sources()
        ]
        print(json.dumps(decisions, indent=2))
        return 0

    if args.command == "list":
        for source in service.storage.list_sources():
            latest = service.storage.get_latest(source.id)
            status = latest.health.value if latest else "Not checked"
            decision = service.get_run_decision(source.id)
            next_check = (
                decision.next_check_at.isoformat()
                if decision.next_check_at
                else "due/disabled"
            )
            print(f"{source.id}\t{status}\t{next_check}\t{source.name}\t{source.location}")
        return 0

    if args.command == "incident":
        incident_state = service.incident(args.source_id)
        print(incident_state.model_dump_json(indent=2) if incident_state else "null")
        return 0

    if args.command == "notification-candidates":
        items = service.notification_candidates(args.source_id, limit=args.limit)
        print(json.dumps([item.model_dump(mode="json") for item in items], indent=2))
        return 0

    if args.command == "evaluate-notification-candidates":
        items = service.evaluate_pending_notification_candidates(args.source_id)
        print(json.dumps([item.model_dump(mode="json") for item in items], indent=2))
        return 0

    if args.command == "delivery-attempts":
        items = service.delivery_attempts(
            candidate_id=args.candidate_id,
            source_id=args.source_id,
            limit=args.limit,
        )
        print(json.dumps([item.model_dump(mode="json") for item in items], indent=2))
        return 0

    if args.command == "delivery-retry-status":
        decision = service.delivery_retry_decision(args.candidate_id)
        print(decision.model_dump_json(indent=2))
        return 0 if decision.due else 2

    if args.command == "dry-run-delivery":
        attempt = service.dry_run_delivery(args.candidate_id, args.idempotency_key)
        print(attempt.model_dump_json(indent=2))
        return 0 if attempt.state.value == "Succeeded" else 2

    if args.command == "reconcile-delivery-attempt":
        attempt = service.reconcile_delivery_attempt(
            args.attempt_id,
            DeliveryReconciliationOutcome(args.outcome),
            args.note,
        )
        print(attempt.model_dump_json(indent=2))
        return 0

    if args.command == "baseline-review":
        review = service.baseline_review(args.source_id, args.observation_id)
        print(review.model_dump_json(indent=2))
        return 0 if review.ready else 2

    if args.command == "promote-baseline":
        latest = service.storage.get_latest(args.source_id)
        target = args.observation_id or (latest.id if latest else None)
        if target is None:
            raise SystemExit("No observation available to promote")
        observation = service.promote_baseline_after_review(
            args.source_id,
            target,
            args.expected_baseline_id,
        )
        print(json.dumps({"source_id": args.source_id, "baseline": observation.id}, indent=2))
        return 0

    if args.command == "build-pages":
        output = build_pages_site(service.storage, args.output)
        print(json.dumps({"output": str(output)}, indent=2))
        return 0

    if args.command == "serve":
        os.environ["ANALYSTWATCH_DB"] = str(Path(args.db))
        uvicorn.run("analystwatch.web:app", host=args.host, port=args.port, reload=False)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
