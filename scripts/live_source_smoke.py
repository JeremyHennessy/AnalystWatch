from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from analystwatch.config import load_sources
from analystwatch.models import HealthStatus, SourceType
from analystwatch.service import MonitorService
from analystwatch.storage import Storage


def run(config_path: str | Path) -> int:
    sources = load_sources(config_path)
    failures: list[str] = []
    summaries: list[dict[str, object]] = []

    with tempfile.TemporaryDirectory(prefix="analystwatch-live-smoke-") as workdir:
        service = MonitorService(Storage(Path(workdir) / "smoke.db"))
        service.add_sources(sources)
        for source in sources:
            # This workflow is the external/public upstream gate. Local demo fixtures are
            # intentionally excluded because their fixed sample dates are not live evidence.
            if not source.enabled or source.source_type != SourceType.API:
                continue
            observation = service.check_source(source.id)
            profile = observation.profile
            source_failures: list[str] = []

            if not observation.available or profile is None:
                source_failures.append(observation.error or "source produced no profile")
            if observation.health == HealthStatus.CRITICAL:
                source_failures.append("source health is Critical")

            if profile is not None:
                for field in source.config.numeric_fields:
                    column = profile.columns.get(field)
                    if column is None:
                        source_failures.append(f"configured numeric field missing: {field}")
                    elif column.dtype != "numeric" or column.numeric is None:
                        source_failures.append(
                            f"configured numeric field was not profiled numerically: {field}"
                        )
                if source.config.latest_date_field and profile.latest_date is None:
                    source_failures.append(
                        "configured latest-date field had no parseable values: "
                        f"{source.config.latest_date_field}"
                    )

            summaries.append(
                {
                    "source_id": source.id,
                    "health": observation.health.value,
                    "available": observation.available,
                    "rows": profile.row_count if profile else None,
                    "latest_date": (
                        profile.latest_date.isoformat()
                        if profile and profile.latest_date
                        else None
                    ),
                    "response_ms": observation.response_ms,
                    "failures": source_failures,
                }
            )
            failures.extend(f"{source.id}: {failure}" for failure in source_failures)

    print(json.dumps({"sources": summaries, "failures": failures}, indent=2))
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate configured sources against live upstreams"
    )
    parser.add_argument("config", nargs="?", default="config/sources.json")
    args = parser.parse_args()
    return run(args.config)


if __name__ == "__main__":
    raise SystemExit(main())
