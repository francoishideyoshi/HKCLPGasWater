// HK Utilities Widget for Scriptable (iOS)
// ----------------------------------------------------------------------------
// Shows the latest CLP (electricity), Towngas (gas) and WSD (water) consumption
// by fetching a public data.json committed by your GitHub Action.
//
// SETUP (do this once):
//   1. Open the free Scriptable app -> create a new script -> paste this file.
//   2. Replace USER/REPO in RAW_URL below with your GitHub username and repo
//      name. The default branch is assumed to be "main".
//   3. Run the script once inside Scriptable to confirm it renders.
//   4. Long-press the home screen -> add a Scriptable widget (small or medium)
//      -> choose this script.
//
// It caches the last successful payload on-device, so the widget still renders
// the last-known values when offline.
// ----------------------------------------------------------------------------

// >>> EDIT THIS: replace USER and REPO with your own. <<<
const RAW_URL =
  "https://raw.githubusercontent.com/USER/REPO/main/public/data.json";

// How many days old before we visually flag a reading as stale (matches builder).
const STALE_AFTER_DAYS = 2;

// ---- Theme ----------------------------------------------------------------
const COLORS = {
  bg1: new Color("#0f2027"),
  bg2: new Color("#203a43"),
  text: new Color("#ffffff"),
  sub: new Color("#9fb3c8"),
  ok: new Color("#7ee787"),
  warn: new Color("#f0c674"),
  err: new Color("#ff7b72"),
};

// Per-provider display config (icon = SF Symbol name, accent color).
const PROVIDER_META = {
  clp: { icon: "bolt.fill", color: new Color("#ffd166") },
  towngas: { icon: "flame.fill", color: new Color("#ff8c42") },
  wsd: { icon: "drop.fill", color: new Color("#4cc9f0") },
};

const ORDER = ["clp", "towngas", "wsd"];

// ---- Data loading with on-device cache ------------------------------------
function cacheFile() {
  const fm = FileManager.local();
  return fm.joinPath(fm.cacheDirectory(), "hk_utilities_cache.json");
}

function readCache() {
  try {
    const fm = FileManager.local();
    const path = cacheFile();
    if (fm.fileExists(path)) {
      return JSON.parse(fm.readString(path));
    }
  } catch (e) {
    // ignore corrupt cache
  }
  return null;
}

function writeCache(data) {
  try {
    const fm = FileManager.local();
    fm.writeString(cacheFile(), JSON.stringify(data));
  } catch (e) {
    // best-effort cache; ignore failures
  }
}

async function loadData() {
  try {
    const req = new Request(RAW_URL);
    req.timeoutInterval = 15;
    const data = await req.loadJSON();
    if (data && data.providers) {
      writeCache(data);
      return { data, fromCache: false };
    }
  } catch (e) {
    // fall through to cache
  }
  const cached = readCache();
  if (cached) return { data: cached, fromCache: true };
  return { data: null, fromCache: false };
}

// ---- Helpers --------------------------------------------------------------
function daysSince(iso) {
  if (!iso) return Infinity;
  const t = Date.parse(iso.replace("Z", "+00:00"));
  if (isNaN(t)) return Infinity;
  return (Date.now() - t) / 86400000;
}

function statusOf(entry) {
  // Returns { tag, color } for the small indicator.
  if (!entry || entry.value === null || entry.value === undefined) {
    return { tag: "no data", color: COLORS.err };
  }
  if (entry.error && !entry.ok && !entry.stale) {
    return { tag: "error", color: COLORS.err };
  }
  if (entry.stale || daysSince(entry.asOf) > STALE_AFTER_DAYS) {
    return { tag: "stale", color: COLORS.warn };
  }
  if (entry.source === "manual") {
    return { tag: "manual", color: COLORS.warn };
  }
  return { tag: "live", color: COLORS.ok };
}

function fmtValue(entry) {
  if (entry.value === null || entry.value === undefined) return "--";
  const n = entry.value;
  const num = Number.isInteger(n) ? n.toString() : n.toFixed(1);
  return `${num} ${entry.unit || ""}`.trim();
}

function fmtUpdated(iso) {
  if (!iso) return "never";
  const d = new Date(Date.parse(iso.replace("Z", "+00:00")));
  if (isNaN(d.getTime())) return iso;
  const df = new DateFormatter();
  df.dateFormat = "d MMM HH:mm";
  return df.string(d);
}

// ---- Rendering ------------------------------------------------------------
function applyBackground(widget) {
  const g = new LinearGradient();
  g.colors = [COLORS.bg1, COLORS.bg2];
  g.locations = [0, 1];
  widget.backgroundGradient = g;
}

function addHeader(widget, data, fromCache) {
  const header = widget.addStack();
  header.centerAlignContent();
  const title = header.addText("HK Utilities");
  title.font = Font.semiboldSystemFont(13);
  title.textColor = COLORS.text;
  header.addSpacer();
  const upd = header.addText(
    (fromCache ? "cached " : "") + fmtUpdated(data && data.updatedAt)
  );
  upd.font = Font.systemFont(9);
  upd.textColor = COLORS.sub;
}

function addRow(widget, key, entry, medium) {
  const meta = PROVIDER_META[key];
  const row = widget.addStack();
  row.centerAlignContent();
  row.spacing = 6;

  // Icon
  const sym = SFSymbol.named(meta.icon);
  if (sym) {
    const img = row.addImage(sym.image);
    img.imageSize = new Size(medium ? 18 : 14, medium ? 18 : 14);
    img.tintColor = meta.color;
  }

  // Label
  const label = row.addText(entry && entry.label ? entry.label : key.toUpperCase());
  label.font = Font.mediumSystemFont(medium ? 13 : 11);
  label.textColor = COLORS.text;
  label.lineLimit = 1;

  row.addSpacer();

  // Value
  const value = row.addText(entry ? fmtValue(entry) : "--");
  value.font = Font.semiboldSystemFont(medium ? 14 : 11);
  value.textColor = COLORS.text;
  value.lineLimit = 1;

  // Status dot + tag
  const st = statusOf(entry || {});
  const dot = row.addText(" ●");
  dot.font = Font.systemFont(medium ? 11 : 9);
  dot.textColor = st.color;

  if (medium) {
    const tag = row.addText(st.tag);
    tag.font = Font.systemFont(9);
    tag.textColor = st.color;
  }
}

function addErrorState(widget, message) {
  applyBackground(widget);
  const t = widget.addText("HK Utilities");
  t.font = Font.semiboldSystemFont(14);
  t.textColor = COLORS.text;
  widget.addSpacer(6);
  const m = widget.addText(message);
  m.font = Font.systemFont(11);
  m.textColor = COLORS.err;
}

async function createWidget() {
  const widget = new ListWidget();
  widget.setPadding(12, 12, 12, 12);

  const family = config.widgetFamily || "medium";
  const medium = family !== "small";

  const { data, fromCache } = await loadData();

  if (!data || !data.providers) {
    addErrorState(
      widget,
      "No data. Check RAW_URL and that the Action has run."
    );
    return widget;
  }

  applyBackground(widget);
  addHeader(widget, data, fromCache);
  widget.addSpacer(medium ? 8 : 6);

  for (const key of ORDER) {
    addRow(widget, key, data.providers[key], medium);
    widget.addSpacer(medium ? 6 : 4);
  }

  widget.addSpacer();
  // Refresh roughly daily; the underlying data only changes per billing cycle.
  widget.refreshAfterDate = new Date(Date.now() + 6 * 3600 * 1000);
  return widget;
}

// ---- Entry point ----------------------------------------------------------
const widget = await createWidget();
if (config.runsInWidget) {
  Script.setWidget(widget);
} else {
  // Preview when run inside the Scriptable app.
  await widget.presentMedium();
}
Script.complete();
