"""Orchestrator tests: merge logic + valid data.json output, all offline."""

import json
import os

import pytest

from scrapers import common, run_all


def test_build_data_no_creds_is_valid():
    # Zero env -> every provider ok=false, but output is schema-valid.
    data = run_all.build_data(env={})
    assert data["schemaVersion"] == common.SCHEMA_VERSION
    assert data["updatedAt"].endswith("Z")
    assert set(data["providers"].keys()) == {"clp", "towngas", "wsd"}
    for entry in data["providers"].values():
        assert common.validate_provider_dict(entry)
        assert entry["ok"] is False


def test_build_data_validates_against_schema():
    jsonschema = pytest.importorskip("jsonschema")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "schema.json"), encoding="utf-8") as fh:
        schema = json.load(fh)
    data = run_all.build_data(env={})
    jsonschema.validate(data, schema)


def test_merge_successful_scrape_wins():
    scraped = common.make_provider("clp", ok=True, value=100.0, source="scrape")
    manual = {"providers": {"clp": {"value": 999.0}}}
    merged = run_all.merge_provider("clp", scraped, manual, None)
    assert merged["value"] == 100.0
    assert merged["source"] == "scrape"


def test_merge_falls_back_to_manual():
    scraped = common.error_result("towngas", "login failed")
    manual = {"providers": {"towngas": {"value": 42.0, "unit": "units"}}}
    merged = run_all.merge_provider("towngas", scraped, manual, None)
    assert merged["value"] == 42.0
    assert merged["source"] == "manual"
    assert "login failed" in merged["error"]


def test_merge_carries_over_previous_as_stale():
    scraped = common.error_result("wsd", "network error")
    previous = {
        "providers": {
            "wsd": common.make_provider(
                "wsd", ok=True, value=21.0, source="scrape"
            )
        }
    }
    merged = run_all.merge_provider("wsd", scraped, None, previous)
    assert merged["value"] == 21.0
    assert merged["stale"] is True
    assert merged["ok"] is False


def test_merge_pure_error_when_nothing_available():
    scraped = common.error_result("clp", "no creds")
    merged = run_all.merge_provider("clp", scraped, None, None)
    assert merged["ok"] is False
    assert merged["value"] is None


def test_manual_overrides_when_provider_manual_mode():
    env = {"CLP_PROVIDER_MODE": "manual"}
    # Need manual_data.json on disk to have a value; simulate via build using the
    # real repo manual_data.json (which seeds null), so result should be ok=false.
    data = run_all.build_data(env=env)
    assert data["providers"]["clp"]["source"] == "manual"
    assert data["providers"]["clp"]["ok"] is False


def test_write_and_reload(tmp_path):
    data = run_all.build_data(env={})
    out = tmp_path / "data.json"
    run_all.write_data(data, path=str(out))
    reloaded = json.loads(out.read_text(encoding="utf-8"))
    assert reloaded["schemaVersion"] == common.SCHEMA_VERSION
    assert set(reloaded["providers"]) == {"clp", "towngas", "wsd"}


def test_manual_provider_with_value():
    manual = {
        "providers": {
            "clp": {"value": 200.0, "unit": "kWh", "period": "May 2026"}
        }
    }
    entry = run_all._manual_provider(manual, "clp")
    assert entry is not None
    assert entry["value"] == 200.0
    assert entry["source"] == "manual"
    assert entry["ok"] is True


def test_manual_provider_null_value_is_none():
    manual = {"providers": {"clp": {"value": None}}}
    assert run_all._manual_provider(manual, "clp") is None
