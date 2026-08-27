CONFIG_PATH = "config/fda.sources.example.json"


def _load_sources():
    from analystwatch.config import load_sources

    return load_sources(CONFIG_PATH)


def test_fda_examples_are_disabled_bounded_public_api_sources() -> None:
    sources = _load_sources()
    assert [source.id for source in sources] == [
        "openfda-faers-drug-events",
        "openfda-maude-device-events",
    ]

    for source in sources:
        assert source.enabled is False
        assert source.source_type.value == "api"
        assert source.location.startswith("https://api.fda.gov/")
        assert "limit=100" in source.location
        assert "api_key=" not in source.location
        assert source.config.json_record_path == "results"
        assert source.config.expected_refresh_minutes is None
        assert source.config.unique_keys == []
        assert source.config.numeric_fields == []
        assert source.config.request_header_env == {}


def test_fda_examples_use_endpoint_specific_latest_date_evidence() -> None:
    sources = {source.id: source for source in _load_sources()}

    faers = sources["openfda-faers-drug-events"]
    assert faers.config.latest_date_field == "receivedate"
    assert "sort=receivedate:desc" in faers.location

    maude = sources["openfda-maude-device-events"]
    assert maude.config.latest_date_field == "date_received"
    assert "sort=date_received:desc" in maude.location
