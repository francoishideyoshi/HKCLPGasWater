"""Unit tests for each scraper's PARSE function against saved fixtures.

These test parsing only -- no network, no login, no credentials. This isolates
"did the page layout change" from "did login break".
"""

import os

import pytest

from scrapers import clp, towngas, wsd

_FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _fixture(name):
    with open(os.path.join(_FIXTURES, name), encoding="utf-8") as fh:
        return fh.read()


def test_parse_clp():
    parsed = clp.parse_clp(_fixture("clp_dashboard.html"))
    assert parsed["value"] == 245.6
    assert parsed["unit"] == "kWh"
    assert parsed["period"] is not None
    assert "May 2026" in parsed["period"]


def test_parse_clp_empty_raises():
    with pytest.raises(ValueError):
        clp.parse_clp("")


def test_parse_clp_no_value_raises():
    with pytest.raises(ValueError):
        clp.parse_clp("<html>no numbers here</html>")


def test_clp_otp_markers_detected():
    # The OTP fixture must contain at least one configured OTP marker.
    text = _fixture("clp_otp_login.html").lower()
    assert any(marker in text for marker in clp.OTP_MARKERS)


def test_parse_towngas():
    parsed = towngas.parse_towngas(_fixture("towngas_usage.html"))
    assert parsed["value"] == 38.0
    assert parsed["unit"] == "units"
    assert parsed["period"] is not None


def test_parse_towngas_no_value_raises():
    with pytest.raises(ValueError):
        towngas.parse_towngas("<html>nothing</html>")


def test_parse_wsd():
    parsed = wsd.parse_wsd(_fixture("wsd_consumption.html"))
    assert parsed["value"] == 21.0
    assert parsed["unit"] == "m3"
    assert parsed["period"] is not None


def test_parse_wsd_cubic_metre_words():
    parsed = wsd.parse_wsd("<p>You used 33 cubic metres this period.</p>")
    assert parsed["value"] == 33.0


def test_parse_wsd_no_value_raises():
    with pytest.raises(ValueError):
        wsd.parse_wsd("<html>nope</html>")


def test_scrapers_manual_mode_skip(monkeypatch):
    # In manual mode each scraper must skip without touching the network.
    env = {
        "CLP_PROVIDER_MODE": "manual",
        "TOWNGAS_PROVIDER_MODE": "manual",
        "WSD_PROVIDER_MODE": "manual",
    }
    for fn in (clp.scrape_clp, towngas.scrape_towngas, wsd.scrape_wsd):
        result = fn(env)
        assert result["ok"] is False
        assert result["source"] == "manual"


def test_scrapers_no_creds_skip():
    # With no creds, scrapers fall back to manual without attempting login.
    for fn in (clp.scrape_clp, towngas.scrape_towngas, wsd.scrape_wsd):
        result = fn({})
        assert result["ok"] is False
        assert result["source"] == "manual"
