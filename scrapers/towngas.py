"""Towngas (The Hong Kong and China Gas Company) gas consumption scraper.

BEST-EFFORT / UNVERIFIABLE
==========================
The exact Towngas eService login flow and DOM cannot be confirmed without live
credentials. Towngas' eService Centre appears to support a classic
username+password login (verify on first run). If a second factor / CAPTCHA is
encountered, this scraper fails gracefully into the manual fallback.

Parsing is isolated in :func:`parse_towngas` for offline unit-testing.

>>> EDIT THE CONSTANTS BELOW ON YOUR FIRST REAL RUN <<<
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
LOGIN_URL = "https://eservice.towngas.com/"
USAGE_URL = "https://eservice.towngas.com/Account/GasConsumption"

SEL_USERNAME = "input#username, input[name='username'], input[name='LoginId'], input[type='email']"
SEL_PASSWORD = "input#password, input[name='password'], input[name='Password'], input[type='password']"
SEL_SUBMIT = "button[type='submit'], input[type='submit'], button#login"

# Markers that indicate a second factor / CAPTCHA we can't pass headlessly.
BLOCK_MARKERS = (
    "captcha",
    "verification code",
    "one-time password",
    "otp",
    "iam smart",
)

SEL_CONSUMPTION = ".gas-usage, .consumption, [data-units]"

PROVIDER = "towngas"


# ---------------------------------------------------------------------------
# Parsing (pure, network-free, unit-testable)
# ---------------------------------------------------------------------------
def parse_towngas(html_or_text: str) -> dict:
    """Extract the latest gas consumption (in Towngas "units") from page content.

    Tolerant regex-based extraction; tighten once the real DOM is known.
    Raises ``ValueError`` if nothing parseable is found.
    """
    if not html_or_text:
        raise ValueError("empty page content")

    text = html_or_text

    # Towngas bills in "units". Look for "NN units" or "NN unit".
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*units?\b", text, flags=re.IGNORECASE)
    if not m:
        m = re.search(r"data-units=[\"']([\d,]+(?:\.\d+)?)[\"']", text)
    if not m:
        raise ValueError("could not locate a 'units' gas consumption value in page")

    value = float(m.group(1).replace(",", ""))
    period = _extract_period(text)

    return {
        "value": value,
        "unit": "units",
        "period": period,
        "reading_type": "billed",
    }


def _extract_period(text: str) -> Optional[str]:
    m = re.search(
        r"(\d{1,2}\s+\w+\s+\d{4}\s*[-–to]+\s*\d{1,2}\s+\w+\s+\d{4})",
        text,
    )
    if m:
        return m.group(1).strip()
    m = re.search(r"([A-Z][a-z]+\s*[-–]\s*[A-Z][a-z]+\s+\d{4})", text)
    if m:
        return m.group(1).strip()
    return None


# ---------------------------------------------------------------------------
# Network / login (best-effort)
# ---------------------------------------------------------------------------
def scrape_towngas(env: Optional[dict] = None) -> dict:
    """Attempt to log into Towngas eService and fetch the latest gas usage.

    Returns a normalized provider dict. Never raises.
    """
    if get_provider_mode(env, PROVIDER) == "manual":
        return make_provider(
            PROVIDER,
            ok=False,
            source="manual",
            error="provider in manual mode; using manual_data.json",
        )

    if not has_credentials(env, PROVIDER):
        return make_provider(
            PROVIDER,
            ok=False,
            source="manual",
            error="no TOWNGAS_USERNAME/TOWNGAS_PASSWORD set; using manual fallback",
        )

    username, password = get_credentials(env, PROVIDER)

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

            if any(marker in body_text for marker in BLOCK_MARKERS):
                browser.close()
                return error_result(
                    PROVIDER,
                    "Towngas login shows a second factor / CAPTCHA; cannot automate. "
                    "Use manual_data.json for Towngas.",
                )

            if not page.query_selector(SEL_PASSWORD):
                browser.close()
                return error_result(
                    PROVIDER,
                    "no password field found on Towngas login page; use manual_data.json.",
                )

            page.fill(SEL_USERNAME, username)
            page.fill(SEL_PASSWORD, password)
            page.click(SEL_SUBMIT)
            page.wait_for_load_state("networkidle")

            page.goto(USAGE_URL, wait_until="networkidle")
            # If SEL_CONSUMPTION matches, parse just that element's text; else fall
            # back to the whole page. Editing SEL_CONSUMPTION above thus changes
            # what gets parsed.
            _el = page.query_selector(SEL_CONSUMPTION)
            html = _el.inner_text() if _el else page.content()
            browser.close()

        parsed = parse_towngas(html)
        return make_provider(
            PROVIDER,
            ok=True,
            value=parsed["value"],
            unit=parsed.get("unit", "units"),
            period=parsed.get("period"),
            asOf=now_iso(),
            source="scrape",
            error=None,
            extra={"reading_type": parsed.get("reading_type")},
        )
    except Exception as exc:  # noqa: BLE001
        return error_result(PROVIDER, f"Towngas scrape failed: {type(exc).__name__}: {exc}")
