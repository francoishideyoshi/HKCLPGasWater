"""Shared helpers for the HK utility scrapers.

This module deliberately contains *no* provider-specific logic. It defines:

- The normalized result schema (:class:`ProviderResult` + :func:`make_provider`).
- Env-var helpers for reading credentials / per-provider mode.
- Timestamp utilities (everything is UTC, ISO-8601, ``Z`` suffixed).
- A :func:`safe_run` wrapper so a single scraper crashing can never take down
  the whole run.

Everything here is import-safe and works with zero environment variables, so
the offline / no-credentials path (used by CI and the unit tests) is fully
exercisable.
"""

from __future__ import annotations

import os
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Optional

# The schema version baked into data.json. Bump when the shape changes so the
# widget can refuse / adapt to incompatible payloads.
SCHEMA_VERSION = 1

# Valid provider keys (order matters: this is the display order in the widget).
PROVIDERS = ("clp", "towngas", "wsd")

# Human-friendly default labels per provider.
DEFAULT_LABELS = {
    "clp": "CLP Electricity",
    "towngas": "Towngas",
    "wsd": "Water (WSD)",
}

# Default display unit per provider (best guess; the portal value wins when scraped).
DEFAULT_UNITS = {
    "clp": "kWh",
    "towngas": "units",
    "wsd": "m3",
}


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------
def now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with a ``Z`` suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp (``Z`` or offset) into an aware datetime.

    Returns ``None`` for falsy / unparseable input instead of raising, so it is
    safe to call on possibly-missing fields.
    """
    if not value:
        return None
    try:
        # Accept the trailing 'Z' that fromisoformat historically disliked.
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Environment / credential helpers
# ---------------------------------------------------------------------------
def get_env(env: Optional[dict], key: str, default: Optional[str] = None) -> Optional[str]:
    """Read ``key`` from the supplied ``env`` mapping, falling back to os.environ.

    Passing an explicit ``env`` dict makes scrapers easy to unit-test without
    touching the real process environment.
    """
    source = env if env is not None else os.environ
    val = source.get(key, default)
    # Treat empty / whitespace-only strings as "not set".
    if val is not None and str(val).strip() == "":
        return default
    return val


def get_credentials(env: Optional[dict], provider: str) -> tuple[Optional[str], Optional[str]]:
    """Return ``(username, password)`` for a provider from env vars.

    Env var names follow the convention ``<PROVIDER>_USERNAME`` /
    ``<PROVIDER>_PASSWORD`` (e.g. ``CLP_USERNAME``).
    """
    prefix = provider.upper()
    username = get_env(env, f"{prefix}_USERNAME")
    password = get_env(env, f"{prefix}_PASSWORD")
    return username, password


def get_provider_mode(env: Optional[dict], provider: str) -> str:
    """Return the run mode for a provider: ``"auto"`` or ``"manual"``.

    Controlled by ``<PROVIDER>_PROVIDER_MODE`` (e.g. ``CLP_PROVIDER_MODE=manual``).
    Defaults to ``"auto"``. In ``manual`` mode the scraper is skipped entirely and
    the orchestrator uses manual_data.json / last-known values.
    """
    prefix = provider.upper()
    mode = (get_env(env, f"{prefix}_PROVIDER_MODE", "auto") or "auto").strip().lower()
    return "manual" if mode == "manual" else "auto"


def has_credentials(env: Optional[dict], provider: str) -> bool:
    """True only if both username and password are present for the provider."""
    username, password = get_credentials(env, provider)
    return bool(username) and bool(password)


# ---------------------------------------------------------------------------
# Normalized result schema
# ---------------------------------------------------------------------------
@dataclass
class ProviderResult:
    """Normalized per-provider result.

    This is the single source of truth for the per-provider object written into
    data.json. The dataclass keeps construction type-safe; :meth:`to_dict`
    produces the plain dict that is serialized.
    """

    provider: str
    label: str
    ok: bool = False
    value: Optional[float] = None
    unit: str = ""
    period: Optional[str] = None
    asOf: Optional[str] = None
    source: str = "manual"  # "scrape" | "manual"
    stale: bool = False
    error: Optional[str] = None
    # Extra parsed detail kept for debugging / future use; not required by the
    # widget but harmless to carry.
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        # Drop the empty extra blob to keep data.json tidy.
        if not d.get("extra"):
            d.pop("extra", None)
        return d


def make_provider(
    provider: str,
    *,
    ok: bool = False,
    value: Optional[float] = None,
    unit: Optional[str] = None,
    period: Optional[str] = None,
    asOf: Optional[str] = None,
    source: str = "manual",
    stale: bool = False,
    error: Optional[str] = None,
    label: Optional[str] = None,
    extra: Optional[dict] = None,
) -> dict:
    """Convenience constructor returning a schema-valid provider dict.

    Fills in sensible defaults (label, unit) from the provider key.
    """
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider: {provider!r}")
    result = ProviderResult(
        provider=provider,
        label=label or DEFAULT_LABELS[provider],
        ok=ok,
        value=value,
        unit=unit if unit is not None else DEFAULT_UNITS[provider],
        period=period,
        asOf=asOf or now_iso(),
        source=source,
        stale=stale,
        error=error,
        extra=extra or {},
    )
    return result.to_dict()


def error_result(provider: str, message: str, *, source: str = "scrape") -> dict:
    """Shorthand for a failed (ok=false) provider result."""
    return make_provider(
        provider,
        ok=False,
        value=None,
        source=source,
        stale=False,
        error=message,
    )


# ---------------------------------------------------------------------------
# Safe-run wrapper
# ---------------------------------------------------------------------------
def safe_run(provider: str, fn: Callable[[], dict]) -> dict:
    """Run ``fn`` and guarantee a schema-valid dict back, never an exception.

    Any exception is captured and turned into an ``ok=false`` error result, so
    one provider failing can never crash the whole run.
    """
    try:
        result = fn()
        if not isinstance(result, dict):
            return error_result(provider, "scraper returned non-dict result")
        return result
    except Exception as exc:  # noqa: BLE001 - we intentionally catch everything
        # Keep the message short and free of any sensitive request detail.
        tb = traceback.format_exc(limit=1).strip().splitlines()
        detail = tb[-1] if tb else str(exc)
        return error_result(provider, f"unhandled error: {detail}")


def validate_provider_dict(d: Any) -> bool:
    """Lightweight structural check used by tests and the orchestrator.

    Returns True if ``d`` has the required keys with the right primitive types.
    (A full jsonschema check lives in tests/test_common.py.)
    """
    if not isinstance(d, dict):
        return False
    required = {
        "provider": str,
        "label": str,
        "ok": bool,
        "unit": str,
        "source": str,
        "stale": bool,
    }
    for key, typ in required.items():
        if key not in d or not isinstance(d[key], typ):
            return False
    if d["provider"] not in PROVIDERS:
        return False
    if d["source"] not in ("scrape", "manual"):
        return False
    # value may be None or a number
    if d.get("value") is not None and not isinstance(d["value"], (int, float)):
        return False
    return True
