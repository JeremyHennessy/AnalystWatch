from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from analystwatch.config import load_sources
from analystwatch.models import SourceType


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "fda.sources.example.json"


def test_fda_examples_are_disabled_bounded_public_api_sources() -> None:
    sources = load_sources(CONFIG_PATH)
    assert [source.id for source in sources] == [
        "openfda-faers-drug-events",
        "openfda-maude-device-events",
    ]

    for source in sources:
        assert source.enabled is False
        assert source.source_type == SourceType.API
        parsed = urlsplit(source.location)
        assert parsed.scheme == "https"
        assert parsed.netloc == "api.fda.gov"
        assert "limit=100" in parsed.query
        assert "api_key=" not in parsed.query
        assert source.config.json_record_path == "results"
        assert source.config.expected_refresh_minutes is None
        assert source.config.unique_keys == []
        assert source.config.numeric_fields == []
        assert source.config.request_header_env == {}


def test_fda_examples_use_endpoint_specific_latest_date_evidence() -> None:
    sources = {source.id: source for source in load_sources(CONFIG_PATH)}

    faers = sources["openfda-faers-drug-events"]
    assert faers.config.latest_date_field == "receivedate"
    assert "sort=receivedate:desc" in faers.location

    maude = sources["openfda-maude-device-events"]
    assert maude.config.latest_date_field == "date_received"
    assert "sort=date_received:desc" in maude.location
