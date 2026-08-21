from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd

from analystwatch.models import MonitoringConfig, SourceDefinition, SourceType
from analystwatch.service import MonitorService
from analystwatch.storage import Storage


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="analystwatch-demo-") as workdir:
        root = Path(workdir)
        source_path = root / "market_data.csv"
        baseline = pd.DataFrame(
            {
                "id": range(1, 1001),
                "amount": [8400 + (index % 43) for index in range(1000)],
                "segment": ["A" if index % 2 else "B" for index in range(1000)],
            }
        )
        baseline.to_csv(source_path, index=False)

        service = MonitorService(Storage(root / "demo.db"))
        service.add_source(
            SourceDefinition(
                id="market_data",
                name="Market Data",
                source_type=SourceType.CSV,
                location=str(source_path),
                config=MonitoringConfig(unique_keys=["id"]),
            )
        )

        first = service.check_source("market_data")
        print(f"Run 1: {first.health.value} — baseline {first.id}")

        corrupted = baseline.copy()
        corrupted["amount"] = corrupted["amount"] / 100
        corrupted.to_csv(source_path, index=False)
        second = service.check_source("market_data")
        print(f"Run 2: {second.health.value}")
        for finding in second.findings:
            print(f"- {finding.severity.value} [{finding.detector}] {finding.description}")
            print(f"  baseline={finding.baseline_value} current={finding.current_value}")
            if finding.likely_impact:
                print(f"  impact={finding.likely_impact}")


if __name__ == "__main__":
    main()
