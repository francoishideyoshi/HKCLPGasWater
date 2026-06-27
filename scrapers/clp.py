"""CLP (China Light & Power) electricity consumption scraper.

BEST-EFFORT / UNVERIFIABLE
==========================
The exact CLP login flow and DOM cannot be confirmed without live credentials.
Crucially, since ~19 Sep 2025 CLP appears to use **passwordless login** (OTP to
phone/email, and/or iAM Smart). That very likely makes unattended headless
automation impossible. This scraper therefore:

  * Detects a non-password (OTP / iAM Smart) login screen and fails *gracefully*
    into a clear error message, so the orchestrator falls back to manual data.
  * Wraps everything in try/except and returns a structured result; it never
    crashes the run.

>>> YOU WILL ALMOST CERTAINLY NEED TO EDIT THE CONSTANTS BELOW <<<
On your first real run, log into CLP yourself, inspect the page, and update the
URLs / selectors. The parsing logic is isolated in :func:`parse_clp` so you can
unit-test it against a saved fixture without any network access.
"""

from __future__ import annotations

import re
from typing import Optional

from .common import (
    error_result,
    get_credentials,
    get_provider_mode,
    has_credentials,
    make_provider,
    now_iso,
)

# ---------------------------------------------------------------------------
# PORTAL CONSTANTS  --  EDIT THESE ON YOUR FIRST REAL RUN
# ---------------------------------------------------------------------------
# Best-guess URLs for the CLP "iAccount" online services portal.
LOGIN_URL = "https://services.clp.com.hk/en/login/index.aspx"
DASHBOARD_URL = "https://services.clp.com.hk/en/iaccount/index.aspx"

# Best-guess CSS selectors for a (legacy) username+password form. If CLP has
# fully removed password login these will simply not be found and we bail out
# into the manual fallback.
SEL_USERNAME = "input#username, input[name='username'], input[type='email']"
SEL_PASSWORD = "input#password, input[name='password'], input[type='password']"
SEL_SUBMIT = "button[type='submit'], input[type='submit']"

# Markers that indicate a passwordless / OTP / iAM Smart screen (no password
# field usable for automation). If any of these appear we fail gracefully.
OTP_MARKERS = (
    "one-time password",
    "one time password",
    "otp",
    "verification code",
    "iam smart",
    "passwordless",
    "send code",
)

# Selector(s) where the latest consumption figure is expected to render.
SEL_CONSUMPTION = ".consumption-value, .latest-usage, [data-usage]"

PROVIDER = "clp"


# ---------------------------------------------------------------------------
# Parsing (pure, network-free, unit-testable)
# ---------------------------------------------------------------------------
def parse_clp(html_or_text: str) -> dict:
    """Extract the latest consumption reading from CLP page content.

    This is intentionally tolerant: CLP's real markup is unknown, so we look for
    a kWh figure using a regex as a robust fallback. Replace / tighten this once
    you know the real DOM.

    Returns a dict with at least ``value`` (float) and ``unit``; raises
    ``ValueError`` if nothing parseable is found.
    """
    if not html_or_text:
        raise ValueError("empty page content")

    text = html_or_text

    # First, look for an explicit "NNN kWh" pattern (most reliable signal).
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*kWh", text, flags=re.IGNORECASE)
    if not m:
        # Fallback: a data attribute like data-usage="245.6"
        m = re.search(r"data-usage=[\"']([\d,]+(?:\.\d+)?)[\"']", text)
    if not m:
        raise ValueError("could not locate a kWh consumption value in page")

    value = float(m.group(1).replace(",", ""))

    # Try to pick up a period label, e.g. "May 2026" or "01 May - 31 May 2026".
    period = _extract_period(text)

    return {
        "value": value,
        "unit": "kWh",
        "period": period,
        "reading_type": "billed",
    }


def _extract_period(text: str) -> Optional[str]:
    """Best-effort extraction of a human-readable billing period label."""
    # e.g. "Billing period: 01 May 2026 - 31 May 2026"
    m = re.search(
        r"(\d{1,2}\s+\w+\s+\d{4}\s*[-–to]+\s*\d{1,2}\s+\w+\s+\d{4})",
        text,
    )
    if m:
        return m.group(1).strip()
    # e.g. "May 2026"
    m = re.search(r"([A-Z][a-z]+\s+\d{4})", text)
    if m:
        return m.group(1).strip()
    return None


# ---------------------------------------------------------------------------
# Network / login (best-effort; requires Playwright + live creds)
# ---------------------------------------------------------------------------
def scrape_clp(env: Optional[dict] = None) -> dict:
    """Attempt to log into CLP and fetch the latest electricity consumption.

    Returns a normalized provider dict (see scrapers.common). Never raises.
    """
    # Respect explicit manual mode -- do not even attempt to scrape.
    if get_provider_mode(env, PROVIDER) == "manual":
        return make_provider(
            PROVIDER,
            ok=False,
            source="manual",
            error="provider in manual mode; using manual_data.json",
        )

    # No creds -> nothing to do; fall back to manual.
    if not has_credentials(env, PROVIDER):
        return make_provider(
            PROVIDER,
            ok=False,
            source="manual",
            error="no CLP_USERNAME/CLP_PASSWORD set; using manual fallback",
        )

    username, password = get_credentials(env, PROVIDER)

    # Lazy import so the package imports fine (and tests run) without Playwright.
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001
        return error_result(
            PROVIDER, "playwright not installed; cannot scrape (run pip install -r requirements.txt)"
        )

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            page.set_default_timeout(30000)

            page.goto(LOGIN_URL, wait_until="domcontentloaded")
            body_text = (page.content() or "").lower()

            # --- Detect passwordless / OTP / iAM Smart screen -> graceful fail.
            if any(marker in body_text for marker in OTP_MARKERS):
                browser.close()
                return error_result(
                    PROVIDER,
                    "CLP login appears passwordless (OTP/iAM Smart); cannot automate. "
                    "Use manual_data.json for CLP.",
                )

            # --- Detect that no password field exists at all.
            if not page.query_selector(SEL_PASSWORD):
                browser.close()
                return error_result(
                    PROVIDER,
                    "no password field found on CLP login page (likely OTP-only); "
                    "use manual_data.json for CLP.",
                )

            # --- Attempt a classic username/password login.
            page.fill(SEL_USERNAME, username)
            page.fill(SEL_PASSWORD, password)
            page.click(SEL_SUBMIT)
            page.wait_for_load_state("networkidle")

            # Navigate to the dashboard/consumption page and read it.
            page.goto(DASHBOARD_URL, wait_until="networkidle")
            # If SEL_CONSUMPTION matches, parse just that element's text; else fall
            # back to the whole page. Editing SEL_CONSUMPTION above thus changes
            # what gets parsed.
            _el = page.query_selector(SEL_CONSUMPTION)
            html = _el.inner_text() if _el else page.content()
            browser.close()

        parsed = parse_clp(html)
        return make_provider(
            PROVIDER,
            ok=True,
            value=parsed["value"],
            unit=parsed.get("unit", "kWh"),
            period=parsed.get("period"),
            asOf=now_iso(),
            source="scrape",
            error=None,
            extra={"reading_type": parsed.get("reading_type")},
        )
    except Exception as exc:  # noqa: BLE001
        return error_result(PROVIDER, f"CLP scrape failed: {type(exc).__name__}: {exc}")
