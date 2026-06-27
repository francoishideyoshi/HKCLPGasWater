"""WSD (Water Supplies Department) water consumption scraper.

BEST-EFFORT / UNVERIFIABLE
==========================
The exact WSD e-Services login flow and DOM cannot be confirmed without live
credentials. WSD's electronic services show consumption + payment history for
e-bill customers.

>>> CRITICAL SAFETY NOTE <<<
WSD **suspends an account for 24 hours after 5 consecutive logon failures**.
Therefore this scraper makes **exactly one** login attempt per run and NEVER
retries on a bad credential / failed login. A failed login returns an error
result and the run moves on. Do not add retry loops here.

Parsing is isolated in :func:`parse_wsd` for offline unit-testing.

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
LOGIN_URL = "https://www.esd.wsd.gov.hk/"
CONSUMPTION_URL = "https://www.esd.wsd.gov.hk/Account/Consumption"

SEL_USERNAME = "input#username, input[name='username'], input[name='UserId'], input[type='email']"
SEL_PASSWORD = "input#password, input[name='password'], input[name='Password'], input[type='password']"
SEL_SUBMIT = "button[type='submit'], input[type='submit'], button#login"

# Markers that indicate iAM Smart / second factor we can't pass headlessly.
BLOCK_MARKERS = (
    "iam smart",
    "captcha",
    "one-time password",
    "otp",
    "verification code",
)

SEL_CONSUMPTION = ".water-consumption, .consumption, [data-m3]"

PROVIDER = "wsd"


# ---------------------------------------------------------------------------
# Parsing (pure, network-free, unit-testable)
# ---------------------------------------------------------------------------
def parse_wsd(html_or_text: str) -> dict:
    """Extract the latest water consumption (cubic metres) from page content.

    Tolerant regex-based extraction; tighten once the real DOM is known.
    Raises ``ValueError`` if nothing parseable is found.
    """
    if not html_or_text:
        raise ValueError("empty page content")

    text = html_or_text

    # Water is billed in cubic metres. Accept "m3", "m³", "cubic metre(s)".
    m = re.search(
        r"([\d,]+(?:\.\d+)?)\s*(?:m\xb3|m3|cubic\s+met(?:re|er)s?)\b",
        text,
        flags=re.IGNORECASE,
    )
    if not m:
        m = re.search(r"data-m3=[\"']([\d,]+(?:\.\d+)?)[\"']", text)
    if not m:
        raise ValueError("could not locate an m3 water consumption value in page")

    value = float(m.group(1).replace(",", ""))
    period = _extract_period(text)

    return {
        "value": value,
        "unit": "m3",
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
# Network / login (best-effort; SINGLE attempt, no retry)
# ---------------------------------------------------------------------------
def scrape_wsd(env: Optional[dict] = None) -> dict:
    """Attempt ONE login to WSD e-Services and fetch latest water consumption.

    Returns a normalized provider dict. Never raises. Never retries (24h lockout
    risk after 5 consecutive failures).
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
            error="no WSD_USERNAME/WSD_PASSWORD set; using manual fallback",
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
                    "WSD login shows iAM Smart / second factor; cannot automate. "
                    "Use manual_data.json for WSD.",
                )

            if not page.query_selector(SEL_PASSWORD):
                browser.close()
                return error_result(
                    PROVIDER,
                    "no password field found on WSD login page; use manual_data.json.",
                )

            # SINGLE attempt only -- do NOT loop / retry (24h lockout risk).
            page.fill(SEL_USERNAME, username)
            page.fill(SEL_PASSWORD, password)
            page.click(SEL_SUBMIT)
            page.wait_for_load_state("networkidle")

            page.goto(CONSUMPTION_URL, wait_until="networkidle")
            # If SEL_CONSUMPTION matches, parse just that element's text; else fall
            # back to the whole page. Editing SEL_CONSUMPTION above thus changes
            # what gets parsed.
            _el = page.query_selector(SEL_CONSUMPTION)
            html = _el.inner_text() if _el else page.content()
            browser.close()

        parsed = parse_wsd(html)
        return make_provider(
            PROVIDER,
            ok=True,
            value=parsed["value"],
            unit=parsed.get("unit", "m3"),
            period=parsed.get("period"),
            asOf=now_iso(),
            source="scrape",
            error=None,
            extra={"reading_type": parsed.get("reading_type")},
        )
    except Exception as exc:  # noqa: BLE001
        return error_result(PROVIDER, f"WSD scrape failed (no retry): {type(exc).__name__}: {exc}")
