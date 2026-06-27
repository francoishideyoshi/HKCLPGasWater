"""Orchestrator: run all scrapers, merge with manual data, write public/data.json.

Merge priority for each provider (highest wins):

  1. A successful scrape (``ok=true``, source ``scrape``).
  2. A manual value from ``manual_data.json`` (source ``manual``) -- used when
     the provider is in manual mode, has no creds, or scraping failed.
  3. The last-known value from the existing ``public/data.json`` -- carried over
     and marked ``stale=true`` so the widget still shows *something*.
  4. A plain error placeholder (``ok=false``, no value).

This module is runnable with ZERO environment variables / credentials and will
still produce a valid data.json (every provider ok=false / manual). That keeps
CI and the unit tests green without secrets.

Run with:  python -m scrapers.run_all
"""

from __future__ import annotations

import json
import os
from typing import Optional

from . import clp, towngas, wsd
from .common import (
    PROVIDERS,
    SCHEMA_VERSION,
    make_provider,
    now_iso,
    safe_run,
    validate_provider_dict,
)

# Repo-root-relative paths.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
DATA_PATH = os.path.join(_ROOT, "public", "data.json")
MANUAL_PATH = os.path.join(_ROOT, "manual_data.json")

# Map provider key -> its scrape function.
SCRAPERS = {
    "clp": clp.scrape_clp,
    "towngas": towngas.scrape_towngas,
    "wsd": wsd.scrape_wsd,
}


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------
def _load_json(path: str) -> Optional[dict]:
    """Load a JSON file, returning None if missing / unreadable / invalid."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _manual_provider(manual: Optional[dict], provider: str) -> Optional[dict]:
    """Return a normalized provider dict from manual_data.json, or None.

    manual_data.json is intentionally lenient: the user only needs to supply
    ``value`` (and optionally unit / period). Missing fields are filled in.
    """
    if not manual:
        return None
    entry = (manual.get("providers") or {}).get(provider)
    if not isinstance(entry, dict):
        return None
    if entry.get("value") is None:
        return None
    return make_provider(
        provider,
        ok=True,
        value=entry.get("value"),
        unit=entry.get("unit"),
        period=entry.get("period"),
        asOf=entry.get("asOf") or now_iso(),
        source="manual",
        stale=False,
        error=None,
        label=entry.get("label"),
    )


def _previous_provider(previous: Optional[dict], provider: str) -> Optional[dict]:
    """Return the last-known provider dict from a prior data.json, or None."""
    if not previous:
        return None
    entry = (previous.get("providers") or {}).get(provider)
    if not isinstance(entry, dict):
        return None
    if entry.get("value") is None:
        return None
    return entry


# ---------------------------------------------------------------------------
# Merge logic for a single provider
# ---------------------------------------------------------------------------
def merge_provider(
    provider: str,
    scraped: dict,
    manual: Optional[dict],
    previous: Optional[dict],
) -> dict:
    """Decide the final provider entry given scrape result + manual + previous."""
    # 1. Successful scrape always wins.
    if scraped.get("ok"):
        return scraped

    # 2. Manual value (explicit user-provided number).
    manual_entry = _manual_provider(manual, provider)
    if manual_entry is not None:
        # Surface why scraping was not used, if there was a scrape error.
        if scraped.get("error") and scraped.get("source") == "scrape":
            manual_entry["error"] = f"using manual value (scrape: {scraped['error']})"
        return manual_entry

    # 3. Carry over last-known value, marked stale.
    prev = _previous_provider(previous, provider)
    if prev is not None:
        carried = dict(prev)
        carried["stale"] = True
        carried["ok"] = False
        carried["error"] = scraped.get("error") or "scrape failed; showing last-known value"
        return carried

    # 4. Nothing available -- return the scrape error placeholder as-is.
    return scraped


# ---------------------------------------------------------------------------
# Top-level build
# ---------------------------------------------------------------------------
def build_data(env: Optional[dict] = None) -> dict:
    """Run every scraper, merge, and return the full data.json object (no write)."""
    env = env if env is not None else dict(os.environ)
    manual = _load_json(MANUAL_PATH)
    previous = _load_json(DATA_PATH)

    providers: dict[str, dict] = {}
    for provider in PROVIDERS:
        scrape_fn = SCRAPERS[provider]
        # safe_run guarantees a dict even if the scraper explodes.
        scraped = safe_run(provider, lambda fn=scrape_fn: fn(env))
        merged = merge_provider(provider, scraped, manual, previous)

        # NOTE: explicit manual values are authoritative and never auto-staled --
        # if you enter a value in manual_data.json it shows live regardless of its
        # asOf. Carried-over previous scrapes are already marked stale in
        # merge_provider step 3. The widget still applies its own STALE_AFTER_DAYS
        # check against asOf for display.
        if not validate_provider_dict(merged):
            # Last-resort fallback so output is always schema-valid.
            merged = make_provider(provider, ok=False, error="internal merge produced invalid entry")
        providers[provider] = merged

    return {
        "schemaVersion": SCHEMA_VERSION,
        "updatedAt": now_iso(),
        "providers": providers,
    }


def write_data(data: dict, path: str = DATA_PATH) -> None:
    """Write the data object to ``path`` as pretty JSON with a trailing newline."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def main() -> int:
    data = build_data()
    write_data(data)
    # Print a concise per-provider summary (no secrets, safe for CI logs).
    print(f"Wrote {DATA_PATH} (schemaVersion={data['schemaVersion']}, updatedAt={data['updatedAt']})")
    for provider, entry in data["providers"].items():
        status = "ok" if entry.get("ok") else ("stale" if entry.get("stale") else "error")
        print(
            f"  - {provider:8s} status={status:5s} source={entry.get('source'):6s} "
            f"value={entry.get('value')} {entry.get('unit')}"
            + (f"  ({entry.get('error')})" if entry.get("error") else "")
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
