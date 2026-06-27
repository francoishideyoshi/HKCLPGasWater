# HK Utilities Widget (CLP · Towngas · WSD)

An **iOS home-screen widget** that shows your latest Hong Kong utility
consumption — **CLP** (electricity), **Towngas** (gas), and **WSD** (water) — for
**free**, with **no Apple Developer account** and **no paid hosting**.

## 1. What this is

Two halves, decoupled by one public JSON file:

- **Data acquisition** runs in the cloud on a daily schedule (GitHub Actions).
  It logs into each portal (where possible), reads the latest consumption, and
  commits `public/data.json`.
- **Data display** runs on your iPhone (the free **Scriptable** app). The widget
  just fetches that JSON. **It never sees your credentials.**

```
   GitHub Secrets (encrypted creds)
            │
            ▼
   GitHub Actions (free daily cron)
   ┌───────────────────────────────────────────┐
   │ scrapers/run_all.py                        │
   │   clp.py  towngas.py  wsd.py  (best-effort)│
   │        │       │         │                 │
   │        ▼       ▼         ▼                 │
   │   merge with manual_data.json + last-known │
   │        │                                   │
   │        ▼  git commit                       │
   │   public/data.json                         │
   └────────┼──────────────────────────────────┘
            │  served via raw.githubusercontent.com (no auth)
            ▼
   iPhone — Scriptable widget (small / medium)
   fetches data.json, renders 3 rows
```

**Key property:** credentials live only in GitHub Actions Secrets. The phone and
the public JSON only ever contain consumption numbers.

## 2. Prerequisites

- A free **GitHub** account.
- An **iPhone** with the free **[Scriptable](https://apps.apple.com/app/scriptable/id1405459188)** app.
- Login credentials for whichever of CLP / Towngas / WSD you want to track.

## 3. Setup: get the repo

1. Create/fork this repo into **your own** GitHub account (e.g. `YOURNAME/HKCLPGasWater`).
   If you were handed the code, just push it to a new repo of your own.
2. Keep the repo **public** (this is the simplest free setup — see the Security
   note at the bottom; only consumption numbers, no PII, are exposed).
3. Open the **Actions** tab once and click **"I understand my workflows, enable them"**.

## 4. Add your credentials as Secrets

Go to **Settings → Secrets and variables → Actions → New repository secret** and
add (only for the providers you want to automate):

| Secret name | Value |
|---|---|
| `CLP_USERNAME` | your CLP login |
| `CLP_PASSWORD` | your CLP password |
| `TOWNGAS_USERNAME` | your Towngas eService login |
| `TOWNGAS_PASSWORD` | your Towngas password |
| `WSD_USERNAME` | your WSD e-Services login |
| `WSD_PASSWORD` | your WSD password |

Secrets are encrypted, injected only at run time, and never committed.

## 5. Set the mode per provider (optional)

By default every provider is already in **`auto`** (scrape) mode — you do **not**
need to add anything to keep a provider on auto. Only add a **Variable** to force
a provider into **manual** mode (recommended for CLP — see Troubleshooting):
**Settings → Secrets and variables → Actions → Variables tab → New repository
variable**:

| Variable name | Value | When to add |
|---|---|---|
| `CLP_PROVIDER_MODE` | `manual` | Recommended — CLP login is OTP-only, can't be scraped |
| `TOWNGAS_PROVIDER_MODE` | `manual` | Only if Towngas scraping doesn't work for you |
| `WSD_PROVIDER_MODE` | `manual` | Only if WSD scraping doesn't work for you |

Leave a provider's variable **unset** to keep it on auto. In `manual` mode the
scraper is skipped and the value comes from `manual_data.json` (see step 9).

## 6. Run the Action once, manually

1. **Actions** tab → **"Update utility data"** workflow → **Run workflow** button.
2. Wait ~1–2 minutes. Open the run and read the **"Run scrapers and build
   data.json"** step log. You'll see one line per provider, e.g.:
   ```
   - clp      status=error source=manual value=None ...
   - towngas  status=ok    source=scrape value=38.0 units
   - wsd      status=stale source=scrape value=21.0 m3
   ```
   - `status=ok` → scraped fine.
   - `status=error` → couldn't scrape (see the message; use manual fallback).
   - `status=stale` → showing the last-known value because this run failed.
3. The workflow commits `public/data.json` automatically if anything changed.

## 7. Get your data URL

Open this in a browser (replace `YOURNAME`):
```
https://raw.githubusercontent.com/YOURNAME/HKCLPGasWater/main/public/data.json
```
You should see the JSON. Copy this URL — it's your `RAW_URL`.

## 8. Install the widget

1. Open **Scriptable** → **+** (new script).
2. Paste the contents of [`widget/hk-utilities-widget.js`](widget/hk-utilities-widget.js).
3. At the top, set `RAW_URL` to **your** URL from step 7
   (replace `USER/REPO`). Give the script a name (e.g. "HK Utilities").
4. Tap ▶ to preview — you should see three rows render.
5. Go to the home screen → long-press → **+** → search **Scriptable** → pick a
   **small** or **medium** widget → add it.
6. Long-press the new widget → **Edit Widget** → set **Script** to "HK Utilities".

## 9. Manual fallback (for any provider you can't automate)

Some logins (especially **CLP's OTP / iAM Smart**) can't be automated. For those:

1. Set that provider to `manual` mode (step 5).
2. Edit **`manual_data.json`** in the repo (web UI: click the file → pencil icon).
   Fill in the latest number you read off the portal:
   ```jsonc
   "clp": { "value": 245.6, "unit": "kWh", "period": "May 2026",
            "asOf": "2026-06-01T00:00:00Z", "label": "CLP Electricity" }
   ```
   Only `value` is required. Set `value` to `null` to "blank" a provider.
3. Commit. The next Action run (or a manual run) will pick it up and write it
   into `public/data.json`.

You can also hand-edit `public/data.json` directly for a quick one-off.

## 10. Troubleshooting

- **CLP shows `error` / "passwordless (OTP/iAM Smart)".** Since Sep 2025 CLP
  login is OTP-to-phone/email or iAM Smart, which a headless robot can't pass.
  → Set `CLP_PROVIDER_MODE=manual` and use `manual_data.json` (step 9).
- **WSD 24-hour lockout.** WSD suspends the account for **24h after 5
  consecutive logon failures**. This scraper makes **exactly one** attempt and
  never retries — but if your `WSD_PASSWORD` is wrong, each daily run still
  counts as a failure. **Double-check WSD credentials before enabling it.** If
  WSD shows a login error, fix the secret or switch it to `manual`.
- **Geo / IP block.** GitHub runners are outside Hong Kong; a portal may block
  datacenter IPs. If a provider always errors despite correct creds, it's likely
  blocked → use the manual fallback, or run `python -m scrapers.run_all` on your
  own machine and commit the result.
- **A provider's value is wrong / `error` "could not locate ... value".** The
  portal's page layout differs from the built-in best guesses. Edit the clearly
  marked `# PORTAL CONSTANTS` block (URLs + selectors) and the `parse_*` regex at
  the top of `scrapers/clp.py` / `towngas.py` / `wsd.py`. The parsing functions
  have offline unit tests (`tests/test_parsers.py`) with fixtures you can update.
- **Widget shows "No data".** Check `RAW_URL` is correct and that the Action has
  run at least once. The widget caches the last good payload, so it still renders
  offline once it has fetched successfully.
- **Reading the data:** `status` dot/colour — green=live, amber=stale/manual,
  red=error.

## 11. Security note

- Credentials are stored **only** as GitHub Actions Secrets (encrypted, never
  committed, masked in logs). `.gitignore` blocks `.env`, cookie/session dumps,
  and `secrets*.json`.
- `public/data.json` contains **only consumption figures** — no account numbers,
  addresses, or names. The repo is public, so anyone with the raw URL can see
  those numbers; nothing else is exposed.
- Recommended: enable **2FA on your GitHub account**.

## Data schema

`public/data.json` (validated by `schema.json`, see `tests/`):

| Field | Type | Notes |
|---|---|---|
| `schemaVersion` | int | currently `1` |
| `updatedAt` | string | ISO-8601 UTC of the last run |
| `providers.<key>.provider` | string | `clp` / `towngas` / `wsd` |
| `providers.<key>.label` | string | display name |
| `providers.<key>.ok` | bool | true if a fresh value was obtained |
| `providers.<key>.value` | number\|null | consumption for the period |
| `providers.<key>.unit` | string | e.g. `kWh`, `units`, `m3` |
| `providers.<key>.period` | string\|null | human-readable billing period |
| `providers.<key>.asOf` | string\|null | when this value was obtained |
| `providers.<key>.source` | string | `scrape` or `manual` |
| `providers.<key>.stale` | bool | last-known value carried over |
| `providers.<key>.error` | string\|null | message when not ok |

## Local development

```bash
pip install -r requirements.txt
playwright install chromium        # only needed for live scraping
python -m scrapers.run_all         # runs offline; writes public/data.json
pytest -q                          # 32 offline tests, no creds needed
```

> **Best-effort disclaimer:** the exact login flow and page layout of each
> portal cannot be verified without live credentials, so the scrapers are
> written defensively (try/except, graceful manual fallback, easy-to-edit
> selectors). The offline pipeline (build + merge + widget + tests) is fully
> working; per-portal login automation must be confirmed against your own
> accounts and may require editing selectors or falling back to manual.
