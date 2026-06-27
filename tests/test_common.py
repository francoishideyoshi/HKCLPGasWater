"""Tests for the shared schema / dataclass / env helpers and the data.json schema."""

import json
import os

import pytest

from scrapers import common

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_make_provider_defaults():
    d = common.make_provider("clp")
    assert d["provider"] == "clp"
    assert d["label"] == "CLP Electricity"
    assert d["unit"] == "kWh"
    assert d["ok"] is False
    assert d["value"] is None
    assert d["source"] == "manual"
    assert common.validate_provider_dict(d)


def test_make_provider_unknown_raises():
    with pytest.raises(ValueError):
        common.make_provider("nope")


def test_make_provider_ok_scrape():
    d = common.make_provider(
        "towngas", ok=True, value=38.0, unit="units", source="scrape", period="Apr-Jun"
    )
    assert d["ok"] is True
    assert d["value"] == 38.0
    assert d["source"] == "scrape"
    assert common.validate_provider_dict(d)


def test_error_result():
    d = common.error_result("wsd", "boom")
    assert d["ok"] is False
    assert d["error"] == "boom"
    assert d["source"] == "scrape"
    assert common.validate_provider_dict(d)


def test_validate_rejects_bad_source():
    d = common.make_provider("clp")
    d["source"] = "bogus"
    assert not common.validate_provider_dict(d)


def test_validate_rejects_string_value():
    d = common.make_provider("clp")
    d["value"] = "245"
    assert not common.validate_provider_dict(d)


def test_safe_run_catches_exception():
    def boom():
        raise RuntimeError("kaboom")

    d = common.safe_run("clp", boom)
    assert d["ok"] is False
    assert "error" in d and d["error"]
    assert common.validate_provider_dict(d)


def test_safe_run_passes_through_dict():
    good = common.make_provider("clp", ok=True, value=1.0, source="scrape")
    d = common.safe_run("clp", lambda: good)
    assert d == good


def test_env_helpers():
    env = {"CLP_USERNAME": "u", "CLP_PASSWORD": "p", "CLP_PROVIDER_MODE": "manual"}
    assert common.get_credentials(env, "clp") == ("u", "p")
    assert common.has_credentials(env, "clp")
    assert common.get_provider_mode(env, "clp") == "manual"
    # empty string treated as unset
    assert not common.has_credentials({"CLP_USERNAME": "", "CLP_PASSWORD": "x"}, "clp")
    # default mode
    assert common.get_provider_mode({}, "wsd") == "auto"


def test_timestamp_roundtrip():
    ts = common.now_iso()
    assert ts.endswith("Z")
    dt = common.parse_iso(ts)
    assert dt is not None
    assert common.parse_iso(None) is None
    assert common.parse_iso("garbage") is None


def test_seed_data_json_matches_schema():
    jsonschema = pytest.importorskip("jsonschema")
    with open(os.path.join(_ROOT, "schema.json"), encoding="utf-8") as fh:
        schema = json.load(fh)
    with open(os.path.join(_ROOT, "public", "data.json"), encoding="utf-8") as fh:
        data = json.load(fh)
    jsonschema.validate(data, schema)
