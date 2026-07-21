"""GPCP design system — "Ledger" (fintech premium, data-dense).

Direction: trust navy + premium gold, on neutral grounds with a slight blue
bias. Light is the reference theme; dark is a strict transposition of it.

Hard rules this file enforces (a deliberate break from the previous VA1 look,
which read as generic/AI-generated):
  - Opaque surfaces only. NO glassmorphism (no translucent + backdrop-filter
    as a content surface).
  - 1px hairline borders as the primary separator, not shadows.
  - NO glow, NO coloured shadows, NO gradient text, NO decorative ambient
    gradients, NO permanently animated background (that was continuous GPU
    compositing on a 1-CPU container).
  - Tabular numerals everywhere digits line up in a column.
  - Accent used sparingly (~5% of surface), never as a large fill.

Performance / accessibility contract:
  - Motion is limited to short state transitions; `prefers-reduced-motion`
    is respected globally.
  - Both themes target WCAG AA (4.5:1 text, 3:1 UI).
  - Positive/negative are never signalled by colour alone — call sites pair
    them with a sign or an arrow (see `TREND_UP` / `TREND_DOWN`).

⚠️ LOAD-BEARING — see SAAS/ALPHA_REBUILD.md fix #6: the tab CSS below targets
BOTH the legacy `[data-baseweb="tab"]` attribute AND the stable ARIA roles, and
hard-hides inactive panels. Streamlit is pinned to 1.57.0; a DOM change in a
newer version previously broke the layout (tiny tabs / stacked panels). The
appearance may change freely, that robustness may not.
"""

from dataclasses import dataclass

import plotly.graph_objects as go


# ----------------------------------------------------------------------
# Tokens
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class Tokens:
    BG_DEEP: str          # page ground
    BG_BASE: str          # recessed surface
    BG_ELEVATED: str      # raised surface (cards, panels)
    BG_INPUT: str
    SURFACE_1: str        # default panel fill
    SURFACE_2: str        # subtle alternate fill (table headers, totals)
    SURFACE_HOVER: str
    BORDER_1: str         # hairline, default
    BORDER_2: str         # hairline, emphasised
    BORDER_3: str         # strong (focus, active outline)
    TEXT_PRIMARY: str
    TEXT_SECONDARY: str
    TEXT_MUTED: str
    TEXT_FAINT: str
    TEXT_DISABLED: str
    ACCENT: str           # gold — selection / active state, used sparingly
    ACCENT_SOFT: str
    ACCENT_DEEP: str
    ACCENT_TINT: str
    ACCENT_BORDER: str
    ACCENT_ON: str        # text colour ON an accent fill
    BRAND: str            # navy — primary buttons, logo mark
    BRAND_ON: str
    DANGER: str           # negative performance / destructive
    DANGER_TINT: str
    SUCCESS: str          # positive performance (teal-leaning, deutan-safe)
    SUCCESS_TINT: str
    INFO: str
    GRID: str             # chart gridlines / table row separators


LIGHT = Tokens(
    BG_DEEP        = "#F4F7FA",
    BG_BASE        = "#FAFCFE",
    BG_ELEVATED    = "#FFFFFF",
    BG_INPUT       = "#FFFFFF",
    SURFACE_1      = "#FFFFFF",
    SURFACE_2      = "#F7FAFC",
    SURFACE_HOVER  = "#F1F5F9",
    BORDER_1       = "#E2E8F0",
    BORDER_2       = "#CBD5E1",
    BORDER_3       = "#94A3B8",
    TEXT_PRIMARY   = "#0B1220",
    TEXT_SECONDARY = "#4A5A70",
    TEXT_MUTED     = "#8496AC",
    TEXT_FAINT     = "#AEBDCC",
    TEXT_DISABLED  = "#CBD5E1",
    ACCENT         = "#A16207",
    ACCENT_SOFT    = "#B8730C",
    ACCENT_DEEP    = "#82500A",
    ACCENT_TINT    = "#FBF3E4",
    ACCENT_BORDER  = "#E3CB9A",
    ACCENT_ON      = "#FFFFFF",
    BRAND          = "#0F2547",
    BRAND_ON       = "#FFFFFF",
    DANGER         = "#B3261E",
    DANGER_TINT    = "#FBEAE8",
    SUCCESS        = "#0F766E",
    SUCCESS_TINT   = "#E6F4F1",
    INFO           = "#0369A1",
    GRID           = "#EDF1F6",
)

DARK = Tokens(
    BG_DEEP        = "#0A0E14",
    BG_BASE        = "#0F141C",
    BG_ELEVATED    = "#121821",
    BG_INPUT       = "#0F141C",
    SURFACE_1      = "#121821",
    SURFACE_2      = "#171F2A",
    SURFACE_HOVER  = "#1C2531",
    BORDER_1       = "#232D3B",
    BORDER_2       = "#33404F",
    BORDER_3       = "#4A5A6B",
    TEXT_PRIMARY   = "#E9EEF5",
    TEXT_SECONDARY = "#94A6BC",
    TEXT_MUTED     = "#647689",
    TEXT_FAINT     = "#4A5868",
    TEXT_DISABLED  = "#333F4D",
    ACCENT         = "#D9A441",
    ACCENT_SOFT    = "#E5B75F",
    ACCENT_DEEP    = "#B8862E",
    ACCENT_TINT    = "#241D0E",
    ACCENT_BORDER  = "#4A3A19",
    ACCENT_ON      = "#0A0E14",
    BRAND          = "#C9D8EC",
    BRAND_ON       = "#0A0E14",
    DANGER         = "#EF6B62",
    DANGER_TINT    = "#25130F",
    SUCCESS        = "#35C2A5",
    SUCCESS_TINT   = "#0E241F",
    INFO           = "#7FA8D9",
    GRID           = "#1C2531",
)


# The app FOLLOWS THE VISITOR'S OS preference (light or dark), and the user can
# override it from the ⋮ → Settings menu — both are Streamlit-native behaviours,
# available because config.toml defines both [theme.light] and [theme.dark].
# When indeterminate, it falls back to light (config base). That same native
# resolution drives the st.dataframe canvas chrome AND, through
# st.context.theme.type, the single palette this module emits and Plotly's
# colours — so every layer stays in lockstep. An in-app CSS-only toggle can't
# do that (it would leave the canvas tables on the old palette).
DEFAULT_THEME = "light"


def tokens_for(theme: str) -> Tokens:
    return LIGHT if theme == "light" else DARK


# Direction glyphs — colour is never the only carrier of meaning (WCAG 1.4.1).
TREND_UP = "▲"     # ▲
TREND_DOWN = "▼"   # ▼


# ----------------------------------------------------------------------
# Series palette — for charts and allocation breakdowns.
#
# Ordered so that adjacent series stay distinguishable in greyscale and for
# deutan/protan vision: navy → teal → gold → steel → violet → clay. Hue AND
# lightness both vary, so series never rely on hue alone.
# ----------------------------------------------------------------------

_SERIES_LIGHT = ["#0F2547", "#0F766E", "#A16207", "#5B7FA6",
                 "#7A5C9E", "#B0705A", "#3E7C59", "#8A5A7A"]
_SERIES_DARK  = ["#7FA8D9", "#35C2A5", "#D9A441", "#9BB4CE",
                 "#A98BC9", "#CE8E76", "#6FB58C", "#C08BA6"]


def series_palette(theme: str = "light") -> list[str]:
    return list(_SERIES_LIGHT if theme == "light" else _SERIES_DARK)


# Named ETFs keep a stable colour across the app so the same fund is always
# the same colour, chart to chart.
ETF_COLORS = {
    "S&P 500":      "#0F2547",
    "NASDAQ":       "#0F766E",
    "Stoxx 600":    "#A16207",
    "Russel 2000":  "#5B7FA6",
    "Emerging ESG": "#7A5C9E",
    "IBEX":         "#B0705A",
    "TOPIX":        "#3E7C59",
    "Cash":         "#8496AC",
}


def color_for_asset(asset: str, idx: int = 0) -> str:
    if asset in ETF_COLORS:
        return ETF_COLORS[asset]
    return _SERIES_LIGHT[idx % len(_SERIES_LIGHT)]


# ----------------------------------------------------------------------
# CSS
# ----------------------------------------------------------------------

def _palette_vars(t: Tokens, shadow_rgb: str) -> str:
    """The colour half of the token block — emitted once per theme."""
    return f"""
    --bg-deep:        {t.BG_DEEP};
    --bg-base:        {t.BG_BASE};
    --bg-elevated:    {t.BG_ELEVATED};
    --bg-input:       {t.BG_INPUT};
    --surface-1:      {t.SURFACE_1};
    --surface-2:      {t.SURFACE_2};
    --surface-hover:  {t.SURFACE_HOVER};
    --border-1:       {t.BORDER_1};
    --border-2:       {t.BORDER_2};
    --border-3:       {t.BORDER_3};
    --text-primary:   {t.TEXT_PRIMARY};
    --text-secondary: {t.TEXT_SECONDARY};
    --text-muted:     {t.TEXT_MUTED};
    --text-faint:     {t.TEXT_FAINT};
    --text-disabled:  {t.TEXT_DISABLED};
    --accent:         {t.ACCENT};
    --accent-soft:    {t.ACCENT_SOFT};
    --accent-deep:    {t.ACCENT_DEEP};
    --accent-tint:    {t.ACCENT_TINT};
    --accent-border:  {t.ACCENT_BORDER};
    --accent-on:      {t.ACCENT_ON};
    --brand:          {t.BRAND};
    --brand-on:       {t.BRAND_ON};
    --danger:         {t.DANGER};
    --danger-tint:    {t.DANGER_TINT};
    --success:        {t.SUCCESS};
    --success-tint:   {t.SUCCESS_TINT};
    --info:           {t.INFO};
    --grid:           {t.GRID};
    --shadow-1: 0 1px 2px rgba({shadow_rgb}, 0.06);
    --shadow-2: 0 2px 8px rgba({shadow_rgb}, 0.08);
    --shadow-3: 0 8px 24px rgba({shadow_rgb}, 0.12);
    --focus-ring: 0 0 0 2px {t.BG_DEEP}, 0 0 0 4px {t.ACCENT};"""


def build_css(active: str | None = None) -> str:
    """The stylesheet for the ACTIVE palette (one per render).

    `active` is the theme Streamlit is rendering, read from st.context.theme.type
    (which follows the OS preference and the ⋮ → Settings choice). Emitting a
    single palette per render — rather than both and switching client-side — is
    what keeps this CSS in step with the st.dataframe canvas, whose colours come
    from config.toml and which no CSS selector can reach. On a theme change
    Streamlit reruns, the context updates, and this re-emits to match.

    Streamlit exposes no stable theme selector on the DOM (no data-theme, no
    CSS var), so a client-side switch here is impossible — verified in-browser.
    """
    active = active or DEFAULT_THEME
    palette = _palette_vars(tokens_for(active),
                            "11, 18, 32" if active == "light" else "0, 0, 0")

    return f"""
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

  :root {{
{palette}

    --font-sans: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, sans-serif;
    --font-mono: 'IBM Plex Mono', 'SF Mono', Menlo, monospace;

    --r-xs: 3px; --r-sm: 4px; --r-md: 6px; --r-lg: 8px; --r-xl: 10px;
    --ease: cubic-bezier(0.2, 0, 0.2, 1);
    --t-fast: 120ms; --t-base: 180ms;
    color-scheme: {'dark' if active == 'dark' else 'light'};
  }}

  html, body {{
    background: var(--bg-deep) !important;
    color: var(--text-primary);
    font-family: var(--font-sans);
    font-size: 14px; line-height: 1.5;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }}
  [data-testid="stAppViewContainer"], .stApp {{
    background: var(--bg-deep) !important;
    color: var(--text-primary);
  }}
  ::selection {{ background: var(--accent-tint); color: var(--text-primary); }}

  /* Every figure in the app aligns in its column. */
  .kpi-value, .kpi-delta, .kpi-sub,
  .va1-status-value, .va1-hero-nav, .va1-hero-pill-value,
  [data-testid="stMetricValue"],
  [data-testid="stDataFrame"] td, [data-testid="stTable"] td {{
    font-variant-numeric: tabular-nums;
    font-feature-settings: "tnum" 1;
  }}

  /* Keep the ⋮ menu reachable — it holds the light/dark switch, the only
     control that repaints BOTH the CSS and the dataframe canvas at once. Hide
     only the noise around it (footer, the Deploy/status toolbar). */
  footer {{ visibility: hidden; height: 0; }}
  [data-testid="stHeader"] {{
    background: transparent;
    height: auto; pointer-events: none;
  }}
  [data-testid="stHeader"] #MainMenu {{ pointer-events: auto; }}
  [data-testid="stToolbarActions"], [data-testid="stStatusWidget"] {{
    visibility: hidden;
  }}

  .block-container {{
    padding-top: 1.1rem !important;
    padding-bottom: 3rem !important;
    max-width: 1600px !important;
  }}

  /* Rerun indicator — a small determinate-looking ring, no page dim. */
  .gpcp-loader {{
    display: none;
    position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
    z-index: 99999; width: 64px; height: 64px;
    align-items: center; justify-content: center;
    background: var(--bg-elevated);
    border: 1px solid var(--border-2);
    border-radius: var(--r-lg);
    box-shadow: var(--shadow-3);
    pointer-events: none;
  }}
  body:has([data-testid="stStatusWidget"]) .gpcp-loader {{ display: flex; }}
  [data-testid="stMarkdown"]:has(.gpcp-loader) {{ height: 0; margin: 0; }}
  .gpcp-loader::after {{
    content: ""; width: 26px; height: 26px;
    border: 2px solid var(--border-2);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: gp-spin 0.7s linear infinite;
  }}
  @keyframes gp-spin {{ to {{ transform: rotate(360deg); }} }}

  /* ============================================================
     HEADER
     ============================================================ */
  .va1-header {{
    display: flex; justify-content: space-between; align-items: center;
    gap: 16px; flex-wrap: wrap;
    padding: 12px 0 14px 0;
    margin-bottom: 4px;
    border-bottom: 1px solid var(--border-1);
  }}
  .va1-brand {{ display: flex; align-items: center; gap: 10px; }}
  .va1-brand-logo {{
    width: 26px; height: 26px; border-radius: var(--r-sm);
    background: var(--brand); color: var(--brand-on);
    display: grid; place-items: center;
    font-weight: 700; font-size: 11px; letter-spacing: 0.02em;
  }}
  .va1-brand-name {{
    font-size: 15px; font-weight: 600;
    letter-spacing: -0.01em; color: var(--text-primary);
  }}
  .va1-brand-divider {{ width: 1px; height: 16px; background: var(--border-2); margin: 0 4px; }}
  .va1-brand-tag {{ font-size: 12px; color: var(--text-secondary); font-weight: 400; }}
  .va1-pill {{
    display: inline-flex; align-items: center; gap: 6px;
    padding: 4px 9px; border-radius: 999px;
    background: var(--surface-2); border: 1px solid var(--border-1);
    font-size: 11px; color: var(--text-secondary); font-weight: 500;
  }}
  .va1-pill-dot {{
    width: 6px; height: 6px; border-radius: 50%;
    background: var(--success); flex: none;
  }}

  /* ============================================================
     STATUS BAR
     ============================================================ */
  .va1-status {{
    display: flex; gap: 24px; align-items: center;
    padding: 12px 2px 16px 2px;
    flex-wrap: wrap;
  }}
  .va1-status-item {{ display: flex; flex-direction: column; gap: 2px; }}
  .va1-status-label {{
    font-size: 10px; color: var(--text-muted);
    text-transform: uppercase; letter-spacing: 0.07em; font-weight: 600;
  }}
  .va1-status-value {{
    font-family: var(--font-mono);
    font-size: 14px; color: var(--text-primary); font-weight: 500;
  }}
  .va1-status-value.up   {{ color: var(--success); }}
  .va1-status-value.down {{ color: var(--danger); }}
  .va1-status-sep {{ width: 1px; height: 26px; background: var(--border-1); }}

  /* ============================================================
     NAV HERO (Overview)
     ============================================================ */
  .va1-hero {{
    display: grid; grid-template-columns: 1fr auto; gap: 24px;
    align-items: center;
    padding: 20px 24px;
    margin-bottom: 20px;
    background: var(--surface-1);
    border: 1px solid var(--border-1);
    border-radius: var(--r-lg);
  }}
  .va1-hero-label {{
    font-size: 10px; font-weight: 600; letter-spacing: 0.08em;
    color: var(--text-muted); text-transform: uppercase;
    margin-bottom: 8px;
  }}
  .va1-hero-nav {{
    font-family: var(--font-mono);
    font-size: 38px; font-weight: 600;
    line-height: 1.05; letter-spacing: -0.02em;
    color: var(--text-primary);
  }}
  .va1-hero-meta {{
    display: flex; gap: 1px; margin-top: 16px; align-items: stretch;
    flex-wrap: wrap;
    background: var(--border-1);
    border: 1px solid var(--border-1);
    border-radius: var(--r-md);
    overflow: hidden;
  }}
  .va1-hero-pill {{
    display: inline-flex; flex-direction: column; gap: 2px;
    padding: 8px 14px;
    background: var(--surface-1);
    flex: 1 1 auto;
  }}
  .va1-hero-pill-label {{
    font-size: 10px; color: var(--text-muted);
    text-transform: uppercase; letter-spacing: 0.07em; font-weight: 600;
  }}
  .va1-hero-pill-value {{
    font-family: var(--font-mono);
    font-size: 14px; color: var(--text-primary); font-weight: 500;
  }}
  .va1-hero-pill-value.up   {{ color: var(--success); }}
  .va1-hero-pill-value.down {{ color: var(--danger); }}
  .va1-hero-spark {{ width: 260px; height: 76px; }}

  /* ============================================================
     CARDS
     ============================================================ */
  .va1-card {{
    background: var(--surface-1);
    border: 1px solid var(--border-1);
    border-radius: var(--r-lg);
    padding: 18px 20px;
    margin-bottom: 20px;
  }}
  .va1-card-elevated {{
    background: var(--bg-elevated);
    border: 1px solid var(--border-1);
    border-radius: var(--r-lg);
    padding: 18px 20px;
    margin-bottom: 20px;
    box-shadow: var(--shadow-1);
  }}
  .va1-card-inset {{
    background: var(--surface-2);
    border: 1px solid var(--border-1);
    border-radius: var(--r-lg);
    padding: 16px 18px;
    margin-bottom: 20px;
  }}

  /* ============================================================
     SECTION HEAD
     ============================================================ */
  .va1-section-head {{
    display: flex; align-items: baseline; gap: 10px;
    margin: 26px 0 8px 0; flex-wrap: wrap;
  }}
  .va1-section-head:first-child {{ margin-top: 4px; }}
  .va1-section-bar {{ display: none; }}
  .va1-section-text {{ display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }}
  .va1-section-title {{
    font-size: 11px; font-weight: 600;
    color: var(--text-primary);
    text-transform: uppercase; letter-spacing: 0.08em;
  }}
  .va1-section-sub {{ font-size: 12px; color: var(--text-muted); font-weight: 400; }}
  .va1-divider {{
    height: 1px; border: none; background: var(--border-1);
    margin: 0 0 16px 0;
  }}

  /* ============================================================
     KPI STRIP — a joined grid, not floating cards
     ============================================================ */
  .kpi-card {{
    position: relative;
    padding: 12px 14px;
    background: var(--surface-1);
    border: 1px solid var(--border-1);
    border-radius: var(--r-md);
    height: 100%;
    transition: border-color var(--t-base) var(--ease),
                background-color var(--t-base) var(--ease);
  }}
  .kpi-card:hover {{
    background: var(--surface-2);
    border-color: var(--border-2);
  }}
  .kpi-label {{
    display: flex; justify-content: space-between; align-items: center;
    gap: 8px;
    font-size: 10px; font-weight: 600; color: var(--text-muted);
    text-transform: uppercase; letter-spacing: 0.07em;
    margin-bottom: 8px;
  }}
  .kpi-badge-live {{
    display: inline-flex; gap: 5px; align-items: center;
    font-size: 9px; font-weight: 600; letter-spacing: 0.05em;
    padding: 1px 6px; border-radius: 3px;
    background: var(--success-tint); color: var(--success);
    border: 1px solid var(--success);
    text-transform: uppercase;
  }}
  .kpi-value {{
    font-family: var(--font-mono);
    font-size: 21px; font-weight: 600;
    letter-spacing: -0.02em; line-height: 1.15;
    color: var(--text-primary);
  }}
  /* Solid colour — never gradient-clipped text. */
  .kpi-value.up   {{ color: var(--success); }}
  .kpi-value.down {{ color: var(--danger); }}
  .kpi-delta, .kpi-sub {{
    font-family: var(--font-mono); font-size: 11.5px;
    color: var(--text-muted); margin-top: 4px;
  }}
  .kpi-delta.up   {{ color: var(--success); }}
  .kpi-delta.down {{ color: var(--danger); }}

  /* ============================================================
     TABS
     ⚠️ LOAD-BEARING (ALPHA_REBUILD fix #6) — dual selectors
     (legacy BaseWeb attribute + stable ARIA role) and the
     hard-hide of inactive panels. Restyle freely, do not narrow.
     ============================================================ */
  /* Top-level tabs read as a NAV: pills on a rule, active one outlined —
     not an underlined tab strip. Nested tabs stay a quieter underline so the
     two levels never look alike. */
  .stTabs [data-baseweb="tab-list"], .stTabs [role="tablist"] {{
    gap: 4px;
    background: transparent;
    border-bottom: 1px solid var(--border-1);
    padding: 0 0 8px 0;
    border-radius: 0;
    margin-bottom: 18px;
  }}
  .stTabs [data-baseweb="tab"], .stTabs [role="tab"] {{
    background: transparent !important;
    color: var(--text-secondary) !important;
    padding: 8px 14px !important;
    font-weight: 500 !important;
    font-size: 13.5px !important;
    letter-spacing: 0 !important;
    text-transform: none !important;
    border-radius: var(--r-md) !important;
    border: 1px solid transparent !important;
    transition: color var(--t-base) var(--ease),
                border-color var(--t-base) var(--ease),
                background var(--t-base) var(--ease) !important;
    min-height: 36px !important;
  }}
  .stTabs [data-baseweb="tab"]:hover, .stTabs [role="tab"]:hover {{
    color: var(--text-primary) !important;
    background: var(--surface-hover) !important;
  }}
  .stTabs [aria-selected="true"] {{
    background: var(--surface-2) !important;
    color: var(--text-primary) !important;
    font-weight: 600 !important;
    border-color: var(--accent-border) !important;
  }}
  /* Nested (second-level) tabs — quieter, underline only. */
  .stTabs .stTabs [data-baseweb="tab-list"],
  .stTabs .stTabs [role="tablist"] {{ padding-bottom: 0; margin-bottom: 14px; }}
  .stTabs .stTabs [data-baseweb="tab"], .stTabs .stTabs [role="tab"] {{
    border-radius: 0 !important;
    border: none !important;
    border-bottom: 2px solid transparent !important;
    padding: 8px 12px !important;
    font-size: 13px !important;
  }}
  .stTabs .stTabs [aria-selected="true"] {{
    background: transparent !important;
    border-bottom-color: var(--accent) !important;
  }}

  /* ============================================================
     PANEL — a bordered card with its own header row.
     st.container(border=True) provides the box; this gives it the
     chrome (title + actions on a ruled header, flush body).
     ============================================================ */
  [data-testid="stVerticalBlockBorderWrapper"]:has(> div > div > div > .gp-panel-head) {{
    background: var(--surface-1);
    border: 1px solid var(--border-1) !important;
    border-radius: var(--r-md) !important;
    padding: 0 !important;
    overflow: hidden;
  }}
  .gp-panel-head {{
    display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
    padding: 10px 14px;
    margin: 0 0 4px 0;
    border-bottom: 1px solid var(--border-1);
    background: var(--surface-1);
  }}
  .gp-panel-title {{
    font-size: 13px; font-weight: 600; letter-spacing: -0.01em;
    color: var(--text-primary);
  }}
  .gp-panel-sub {{ font-size: 11.5px; color: var(--text-muted); }}
  .gp-panel-spacer {{ flex: 1; }}
  .gp-tag {{
    display: inline-block; padding: 1px 7px; border-radius: 3px;
    font-family: var(--font-mono); font-size: 10px; font-weight: 500;
    border: 1px solid var(--border-1); color: var(--text-secondary);
    background: var(--surface-2);
  }}
  /* Body padding for the widgets Streamlit drops inside the panel. */
  [data-testid="stVerticalBlockBorderWrapper"]:has(.gp-panel-head)
    [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"]:not(:has(.gp-panel-head)) {{
    padding-left: 14px; padding-right: 14px;
  }}

  /* ============================================================
     DATA TABLE — hand-rendered, because st.dataframe draws on a
     canvas: its headers, alignment, typography and total row are
     out of CSS's reach. This gives the terminal look (uppercase
     ruled header, tabular figures, right-aligned numbers, a bold
     total line) at the cost of built-in sorting.
     ============================================================ */
  .gp-tbl-wrap {{ overflow-x: auto; }}
  table.gp-tbl {{
    width: 100%; border-collapse: collapse;
    font-family: var(--font-mono); font-variant-numeric: tabular-nums;
    font-size: 12px;
  }}
  table.gp-tbl thead th {{
    position: sticky; top: 0; z-index: 1;
    background: var(--surface-2);
    color: var(--text-muted);
    font-family: var(--font-sans);
    font-size: 9.5px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.07em;
    text-align: left; white-space: nowrap;
    padding: 9px 12px;
    border-bottom: 1px solid var(--border-2);
  }}
  table.gp-tbl th.num, table.gp-tbl td.num {{ text-align: right; }}
  table.gp-tbl tbody td {{
    padding: 8px 12px; white-space: nowrap;
    border-bottom: 1px solid var(--grid);
    color: var(--text-secondary);
  }}
  table.gp-tbl tbody tr:last-child td {{ border-bottom: none; }}
  table.gp-tbl tbody tr:hover td {{ background: var(--surface-hover); }}
  table.gp-tbl td.key {{ color: var(--text-primary); font-weight: 600; }}
  table.gp-tbl td.name {{ font-family: var(--font-sans); }}
  table.gp-tbl td.pos {{ color: var(--success); }}
  table.gp-tbl td.neg {{ color: var(--danger); }}
  table.gp-tbl td.muted {{ color: var(--text-muted); }}
  table.gp-tbl tr.total td {{
    background: var(--surface-2);
    color: var(--text-primary); font-weight: 700;
    border-bottom: 1px solid var(--border-2);
  }}
  table.gp-tbl tr.total td.pos {{ color: var(--success); }}
  table.gp-tbl tr.total td.neg {{ color: var(--danger); }}

  /* ============================================================
     ALLOCATION BARS — replaces the donut: readable past 5 lines,
     and the weights line up as a column instead of a wheel.
     ============================================================ */
  .gp-alloc {{ display: flex; flex-direction: column; gap: 11px; padding: 12px 14px 14px; }}
  .gp-alloc-row {{ display: grid; grid-template-columns: 1fr auto; gap: 6px 10px; align-items: baseline; }}
  .gp-alloc-name {{
    display: flex; align-items: center; gap: 8px; min-width: 0;
    font-size: 12.5px; color: var(--text-secondary);
  }}
  .gp-alloc-name span.lbl {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .gp-swatch {{ width: 9px; height: 9px; border-radius: 2px; flex: none; }}
  .gp-alloc-val {{
    font-family: var(--font-mono); font-variant-numeric: tabular-nums;
    font-size: 12.5px; font-weight: 600; color: var(--text-primary);
  }}
  .gp-alloc-track {{
    grid-column: 1 / -1; height: 5px; border-radius: 2px;
    background: var(--grid); overflow: hidden;
  }}
  .gp-alloc-fill {{ display: block; height: 100%; border-radius: 2px; }}

  /* Hard-hide INACTIVE panels regardless of which attribute the running
     Streamlit uses. Purely additive: it can only hide, never reveal.
     Without this, a DOM change stacks every tab's content on one page. */
  .stTabs [data-baseweb="tab-panel"][hidden],
  .stTabs [role="tabpanel"][hidden],
  .stTabs [role="tabpanel"][aria-hidden="true"],
  [data-testid="stTabs"] [role="tabpanel"][hidden],
  [data-testid="stTabs"] [role="tabpanel"][aria-hidden="true"] {{
    display: none !important;
    visibility: hidden !important;
  }}

  /* ============================================================
     BUTTONS
     ============================================================ */
  .stButton > button {{
    background: var(--surface-1);
    color: var(--text-primary);
    border: 1px solid var(--border-2);
    border-radius: var(--r-sm);
    padding: 8px 14px;
    font-weight: 500; font-size: 13px;
    font-family: var(--font-sans);
    cursor: pointer;
    min-height: 38px;
    transition: background-color var(--t-base) var(--ease),
                border-color var(--t-base) var(--ease);
  }}
  .stButton > button:hover {{
    background: var(--surface-hover);
    border-color: var(--border-3);
  }}
  .stButton > button:active {{ background: var(--surface-2); }}
  .stButton > button:focus-visible {{
    outline: none; box-shadow: var(--focus-ring);
  }}

  .stButton > button[kind="primary"],
  .stButton > button[data-testid="baseButton-primary"] {{
    background: var(--brand) !important;
    color: var(--brand-on) !important;
    border-color: var(--brand) !important;
    font-weight: 600;
  }}
  .stButton > button[kind="primary"]:hover,
  .stButton > button[data-testid="baseButton-primary"]:hover {{
    background: var(--brand) !important;
    border-color: var(--brand) !important;
    opacity: 0.88;
  }}

  /* ============================================================
     INPUTS
     ============================================================ */
  /* Streamlit nests three elements per field (root → base-input → input).
     Only the ROOT carries the border/background; the inner two go transparent,
     otherwise they stack into a heavy triple border. Targeting the root also
     means the dark theme works regardless of the native base in config.toml. */
  [data-testid="stTextInputRootElement"],
  [data-testid="stNumberInputContainer"],
  [data-baseweb="select"] > div {{
    background: var(--bg-input) !important;
    border: 1px solid var(--border-2) !important;
    border-radius: var(--r-sm) !important;
    transition: border-color var(--t-base) var(--ease),
                box-shadow var(--t-base) var(--ease);
  }}
  [data-testid="stTextInputRootElement"]:hover,
  [data-testid="stNumberInputContainer"]:hover,
  [data-baseweb="select"] > div:hover {{
    border-color: var(--border-3) !important;
  }}
  [data-testid="stTextInputRootElement"]:focus-within,
  [data-testid="stNumberInputContainer"]:focus-within,
  [data-baseweb="select"] > div:focus-within {{
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px var(--accent-tint) !important;
  }}
  [data-baseweb="base-input"] {{
    background: transparent !important;
    border: none !important;
  }}
  .stTextInput input, .stNumberInput input, .stDateInput input {{
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    outline: none !important;
    color: var(--text-primary) !important;
    font-family: var(--font-sans) !important;
    font-size: 13px !important;
  }}
  /* Figures stay monospaced so they align; free text does not. */
  .stNumberInput input, .stDateInput input {{ font-family: var(--font-mono) !important; }}
  /* Password reveal / step buttons inherit the field, not a dark block. */
  [data-testid="stTextInputRootElement"] button,
  [data-testid="stNumberInputContainer"] button {{
    background: transparent !important;
    border: none !important;
    color: var(--text-muted) !important;
  }}
  [data-testid="stTextInputRootElement"] button:hover,
  [data-testid="stNumberInputContainer"] button:hover {{
    color: var(--text-primary) !important;
    background: var(--surface-hover) !important;
  }}
  /* 16px on mobile stops iOS auto-zooming the whole page on focus. */
  @media (max-width: 640px) {{
    .stTextInput input, .stNumberInput input, .stDateInput input {{
      font-size: 16px !important;
    }}
  }}

  label, .stTextInput label, .stNumberInput label, .stSelectbox label,
  .stDateInput label, .stMultiSelect label, .stRadio label, .stCheckbox label {{
    color: var(--text-secondary) !important;
    font-size: 11px !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.06em !important;
  }}

  [data-baseweb="select"] {{ font-family: var(--font-sans) !important; }}
  [data-baseweb="select"] > div {{ background: var(--bg-input) !important; }}

  /* ============================================================
     DATA SURFACES
     ============================================================ */
  [data-testid="stDataFrame"], [data-testid="stTable"] {{
    background: var(--surface-1);
    border-radius: var(--r-md);
    border: 1px solid var(--border-1);
    overflow: hidden;
  }}
  [data-testid="stDataFrame"] td, [data-testid="stTable"] td {{
    font-family: var(--font-mono);
  }}

  .stPlotlyChart {{
    background: var(--surface-1);
    border: 1px solid var(--border-1);
    border-radius: var(--r-md);
    padding: 4px 4px 8px 4px;
    overflow: visible;
    min-width: 0;
  }}
  .stPlotlyChart > div {{ width: 100% !important; min-width: 0 !important; }}
  .js-plotly-plot, .js-plotly-plot .plotly {{ width: 100% !important; }}
  .js-plotly-plot svg {{ shape-rendering: geometricPrecision; }}
  [data-testid="StyledFullScreenButton"] {{
    background: var(--surface-1) !important;
    border: 1px solid var(--border-2) !important;
    color: var(--text-secondary) !important;
    border-radius: var(--r-sm) !important;
  }}

  [data-testid="stMetric"] {{
    background: var(--surface-1);
    border: 1px solid var(--border-1);
    border-radius: var(--r-md);
    padding: 12px 14px;
  }}
  [data-testid="stMetricLabel"] {{
    color: var(--text-muted) !important;
    font-size: 10px !important; font-weight: 600 !important;
    text-transform: uppercase; letter-spacing: 0.07em;
  }}
  [data-testid="stMetricValue"] {{
    font-family: var(--font-mono) !important;
    color: var(--text-primary) !important;
  }}

  .stAlert {{ border-radius: var(--r-md); border: 1px solid var(--border-1); }}
  [data-testid="stToast"] {{
    background: var(--bg-elevated); border: 1px solid var(--border-2);
    border-radius: var(--r-md); box-shadow: var(--shadow-2);
  }}

  .stMarkdown p, .stMarkdown li {{ color: var(--text-secondary); font-size: 13.5px; }}
  .stMarkdown h1, .stMarkdown h2, .stMarkdown h3, .stMarkdown h4 {{
    color: var(--text-primary); letter-spacing: -0.015em;
    font-family: var(--font-sans); text-wrap: balance;
  }}
  a {{ color: var(--info); }}

  /* Expanders */
  [data-testid="stExpander"] {{
    border: 1px solid var(--border-1) !important;
    border-radius: var(--r-md) !important;
    background: var(--surface-1);
  }}

  /* ============================================================
     RESPONSIVE
     Wide data keeps its density and scrolls inside its own
     container; the page body never scrolls sideways.
     ============================================================ */
  [data-testid="stDataFrame"] {{ overflow-x: auto; }}

  @media (max-width: 1024px) {{
    .block-container {{ padding-left: 1.2rem !important; padding-right: 1.2rem !important; }}
    .va1-hero {{ grid-template-columns: 1fr; }}
    .va1-hero-spark {{ width: 100%; }}
  }}

  @media (max-width: 768px) {{
    .block-container {{ padding-left: 0.8rem !important; padding-right: 0.8rem !important; }}
    .va1-hero {{ padding: 16px; }}
    .va1-hero-nav {{ font-size: 30px; }}
    .va1-hero-meta {{ flex-direction: column; }}
    .kpi-value {{ font-size: 18px; }}
    .va1-status {{ gap: 14px; }}
    .va1-status-sep {{ display: none; }}
    /* Streamlit columns stack natively below 640px; keep the gap tight. */
    [data-testid="stHorizontalBlock"] {{ gap: 8px !important; }}
    .stTabs [data-baseweb="tab"], .stTabs [role="tab"] {{
      padding: 10px 12px !important;
      font-size: 13px !important;
      min-height: 44px !important;   /* touch target */
    }}
    .stTabs [data-baseweb="tab-list"], .stTabs [role="tablist"] {{
      overflow-x: auto; flex-wrap: nowrap;
      scrollbar-width: none;
    }}
    .stTabs [data-baseweb="tab-list"]::-webkit-scrollbar {{ display: none; }}
    .stButton > button {{ min-height: 44px; width: 100%; }}
  }}

  /* ============================================================
     MOTION — short, purposeful, and fully opt-out
     ============================================================ */
  @media (prefers-reduced-motion: reduce) {{
    *, *::before, *::after {{
      animation-duration: 0.01ms !important;
      animation-iteration-count: 1 !important;
      transition-duration: 0.01ms !important;
      scroll-behavior: auto !important;
    }}
  }}
</style>
"""


# ----------------------------------------------------------------------
# Plotly theme
# ----------------------------------------------------------------------

def style_plotly(fig: go.Figure, *, theme: str = "light",
                 height: int = 360, showlegend: bool = True,
                 legend_pos: str = "top-right") -> go.Figure:
    """Apply the GPCP theme to a Plotly figure.

    Every colour is resolved from the active theme's tokens — previously the
    grid and hover colours were hardcoded for dark, which washed out in light.
    """
    t = tokens_for(theme)

    if legend_pos == "top-right":
        legend = dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(color=t.TEXT_SECONDARY, size=11,
                      family="IBM Plex Sans, sans-serif"),
            orientation="h", yanchor="bottom", y=1.02,
            xanchor="right", x=1,
        )
    elif legend_pos == "bottom":
        legend = dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(color=t.TEXT_SECONDARY, size=11,
                      family="IBM Plex Sans, sans-serif"),
            orientation="h", yanchor="top", y=-0.18,
        )
    else:
        legend = dict(visible=False)
        showlegend = False

    fig.update_layout(
        autosize=True,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        colorway=series_palette(theme),
        font=dict(color=t.TEXT_SECONDARY,
                  family="IBM Plex Sans, -apple-system, sans-serif", size=12),
        margin=dict(
            l=52, r=24,
            t=48 if showlegend and legend_pos == "top-right" else 28,
            b=56, pad=0,
        ),
        height=height,
        showlegend=showlegend,
        legend=legend,
        hoverlabel=dict(
            bgcolor=t.BG_ELEVATED,
            bordercolor=t.BORDER_2,
            font=dict(color=t.TEXT_PRIMARY, family="IBM Plex Mono", size=12),
        ),
    )
    axis_common = dict(
        gridcolor=t.GRID,
        zeroline=False,
        linecolor=t.BORDER_1,
        tickcolor="rgba(0,0,0,0)",
        tickfont=dict(color=t.TEXT_MUTED, size=11, family="IBM Plex Mono"),
        automargin=True,
    )
    fig.update_xaxes(showspikes=False, **axis_common)
    fig.update_yaxes(**axis_common)
    return fig


PLOTLY_CONFIG = {
    "displayModeBar": False,
    "displaylogo": False,
    "toImageButtonOptions": {"scale": 2, "format": "png"},
    "responsive": True,
}


# ----------------------------------------------------------------------
# Component HTML helpers
# ----------------------------------------------------------------------

def panel_head(title: str, sub: str = "", right: str = "") -> str:
    """Header row for a panel. Drop it as the first element inside a
    `st.container(border=True)` — the CSS keys off it to turn that container
    into a panel (flush header, ruled, padded body)."""
    sub_html = f'<span class="gp-panel-sub">{sub}</span>' if sub else ""
    right_html = f'<div class="gp-panel-spacer"></div>{right}' if right else ""
    return (
        f'<div class="gp-panel-head">'
        f'<span class="gp-panel-title">{title}</span>{sub_html}{right_html}'
        f'</div>'
    )


def tag(text: str) -> str:
    """Small monospace chip — currency, count, unit."""
    return f'<span class="gp-tag">{text}</span>'


def data_table(headers: list[str],
               rows: list[list[tuple[str, str]]],
               *, num_cols: set[int] | None = None,
               first_row_is_total: bool = False) -> str:
    """Render a dense table as HTML.

    `rows` holds (text, tone) per cell — tone is "" or one of the CSS classes
    (`pos`, `neg`, `key`, `name`, `muted`). Text is escaped here, so callers
    pass plain values (asset names contain "&").

    Hand-rendered rather than st.dataframe: that widget paints to a canvas,
    which puts its header casing, alignment, typography and total row beyond
    CSS. The trade-off is that sorting and column resizing are lost.
    """
    from html import escape

    num_cols = num_cols or set()
    head = "".join(
        f'<th class="{"num" if i in num_cols else ""}">{escape(str(h))}</th>'
        for i, h in enumerate(headers)
    )
    body = []
    for r, row in enumerate(rows):
        tr_cls = ' class="total"' if (first_row_is_total and r == 0) else ""
        tds = []
        for i, cell in enumerate(row):
            text, tone = cell if isinstance(cell, tuple) else (cell, "")
            cls = " ".join(c for c in (("num" if i in num_cols else ""), tone) if c)
            tds.append(f'<td class="{cls}">{escape(str(text))}</td>')
        body.append(f"<tr{tr_cls}>{''.join(tds)}</tr>")
    return (
        '<div class="gp-tbl-wrap"><table class="gp-tbl">'
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )


def sortable_table(headers: list[str],
                   rows: list[list[tuple]],
                   *, num_cols: set[int] | None = None,
                   first_row_is_total: bool = False,
                   theme: str = "dark") -> tuple[str, int]:
    """A click-to-sort version of `data_table`, as a standalone HTML document.

    Returns (html, height) for `st.components.v1.html`. It has to be a full
    document with the palette inlined: st.markdown strips <script>, so sorting
    can only run inside a component iframe, which sees none of the page's CSS
    variables.

    Cells are (text, tone) or (text, tone, sort_key). `sort_key` is the raw
    value — sorting on the DISPLAYED text would order "+1,038.15 €" as a
    string and put 9 after 1,038. Blank keys always sort last, in both
    directions, so empty cells never masquerade as the smallest value.

    The total row is pinned: it describes the whole table, so it must not be
    dragged into the middle of the ordering.
    """
    from html import escape

    t = tokens_for(theme)
    num_cols = num_cols or set()

    head = "".join(
        f'<th class="{"num" if i in num_cols else ""}" data-idx="{i}" '
        f'title="Sort by {escape(str(h))}">{escape(str(h))}</th>'
        for i, h in enumerate(headers)
    )
    body = []
    for r, row in enumerate(rows):
        tr_cls = ' class="total"' if (first_row_is_total and r == 0) else ""
        tds = []
        for i, cell in enumerate(row):
            text, tone = cell[0], (cell[1] if len(cell) > 1 else "")
            sort_key = cell[2] if len(cell) > 2 else None
            if sort_key is None:
                sort_key = ""
            cls = " ".join(c for c in (("num" if i in num_cols else ""), tone) if c)
            tds.append(
                f'<td class="{cls}" data-sort="{escape(str(sort_key))}">'
                f"{escape(str(text))}</td>"
            )
        body.append(f"<tr{tr_cls}>{''.join(tds)}</tr>")

    height = 46 + 33 * len(rows) + 16

    doc = f"""<!doctype html><html><head><meta charset="utf-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; background: {t.SURFACE_1}; }}
  .wrap {{ overflow-x: auto; }}
  table {{
    width: 100%; border-collapse: collapse;
    font-family: 'IBM Plex Mono', monospace; font-variant-numeric: tabular-nums;
    font-size: 12px; color: {t.TEXT_SECONDARY};
  }}
  thead th {{
    position: sticky; top: 0; z-index: 1;
    background: {t.SURFACE_2}; color: {t.TEXT_MUTED};
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 9.5px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.07em;
    text-align: left; white-space: nowrap;
    padding: 9px 12px; border-bottom: 1px solid {t.BORDER_2};
    cursor: pointer; user-select: none;
  }}
  thead th:hover {{ color: {t.TEXT_PRIMARY}; background: {t.SURFACE_HOVER}; }}
  thead th.num {{ text-align: right; }}
  thead th::after {{ content: ""; opacity: 0; margin-left: 5px; }}
  thead th.asc::after  {{ content: "\\25B2"; opacity: 1; color: {t.ACCENT}; }}
  thead th.desc::after {{ content: "\\25BC"; opacity: 1; color: {t.ACCENT}; }}
  tbody td {{
    padding: 8px 12px; white-space: nowrap;
    border-bottom: 1px solid {t.GRID};
  }}
  tbody td.num {{ text-align: right; }}
  tbody tr:last-child td {{ border-bottom: none; }}
  tbody tr:hover td {{ background: {t.SURFACE_HOVER}; }}
  td.key {{ color: {t.TEXT_PRIMARY}; font-weight: 600; }}
  td.name {{ font-family: 'IBM Plex Sans', sans-serif; }}
  td.pos {{ color: {t.SUCCESS}; }}
  td.neg {{ color: {t.DANGER}; }}
  td.muted {{ color: {t.TEXT_MUTED}; }}
  tr.total td {{
    background: {t.SURFACE_2}; color: {t.TEXT_PRIMARY}; font-weight: 700;
    border-bottom: 1px solid {t.BORDER_2};
  }}
  tr.total td.pos {{ color: {t.SUCCESS}; }}
  tr.total td.neg {{ color: {t.DANGER}; }}
  @media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important; }} }}
</style></head><body>
<div class="wrap"><table>
<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody>
</table></div>
<script>
(function () {{
  var table = document.querySelector('table');
  var tbody = table.tBodies[0];
  var ths = Array.prototype.slice.call(table.querySelectorAll('thead th'));

  function keyOf(tr, idx) {{
    var cell = tr.children[idx];
    return cell ? (cell.getAttribute('data-sort') || '') : '';
  }}

  ths.forEach(function (th, idx) {{
    th.addEventListener('click', function () {{
      var dir = th.classList.contains('asc') ? 'desc' : 'asc';
      ths.forEach(function (h) {{ h.classList.remove('asc', 'desc'); }});
      th.classList.add(dir);

      var rows = Array.prototype.slice.call(
        tbody.querySelectorAll('tr:not(.total)'));
      rows.sort(function (a, b) {{
        var av = keyOf(a, idx), bv = keyOf(b, idx);
        var an = parseFloat(av), bn = parseFloat(bv);
        var aEmpty = (av === '' || isNaN(an)) && av === '';
        var bEmpty = (bv === '' || isNaN(bn)) && bv === '';
        // Blanks last whichever way the column is sorted.
        if (aEmpty && bEmpty) return 0;
        if (aEmpty) return 1;
        if (bEmpty) return -1;
        var cmp;
        if (!isNaN(an) && !isNaN(bn)) cmp = an - bn;
        else cmp = String(av).localeCompare(String(bv));
        return dir === 'asc' ? cmp : -cmp;
      }});
      rows.forEach(function (r) {{ tbody.appendChild(r); }});
    }});
  }});
}})();
</script></body></html>"""
    return doc, height


def alloc_bars(rows: list[tuple[str, float, str]]) -> str:
    """Allocation as labelled horizontal bars.

    `rows` = [(label, weight_0_to_1, colour)], already sorted by the caller.
    Chosen over a donut: past ~5 slices a pie stops being readable, and here
    the weights line up as a scannable column.
    """
    if not rows:
        return ""
    parts = []
    for label, weight, colour in rows:
        pct_txt = f"{weight * 100:.1f}%"
        width = max(0.0, min(1.0, weight)) * 100.0
        parts.append(
            f'<div class="gp-alloc-row">'
            f'<div class="gp-alloc-name">'
            f'<span class="gp-swatch" style="background:{colour}"></span>'
            f'<span class="lbl">{label}</span></div>'
            f'<div class="gp-alloc-val">{pct_txt}</div>'
            f'<div class="gp-alloc-track">'
            f'<span class="gp-alloc-fill" style="width:{width:.2f}%;'
            f'background:{colour}"></span></div>'
            f'</div>'
        )
    return f'<div class="gp-alloc">{"".join(parts)}</div>'


def kpi_card(label: str, value: str,
             delta: str | None = None,
             direction: str = "",
             live: bool = False) -> str:
    badge = '<span class="kpi-badge-live">Live</span>' if live else ""
    value_cls = "up" if direction == "up" else ("down" if direction == "down" else "")
    delta_html = ""
    if delta:
        # NOTE: call sites already prefix the arrow (and `pct()` emits a signed
        # value), so direction survives colour blindness without adding one
        # here — doing so would double the glyph.
        delta_html = f'<div class="kpi-delta {value_cls}">{delta}</div>'
    return (
        f'<div class="kpi-card">'
        f'<div class="kpi-label">{label}{badge}</div>'
        f'<div class="kpi-value {value_cls}">{value}</div>'
        f'{delta_html}'
        f'</div>'
    )


def header_html(pf_name: str, pf_ccy: str, source: str, version: str = "") -> str:
    version_pill = f'<span class="va1-pill">{version}</span>' if version else ""
    return (
        f'<div class="va1-header">'
        f'  <div class="va1-brand">'
        f'    <div class="va1-brand-logo">GP</div>'
        f'    <span class="va1-brand-name">{pf_name}</span>'
        f'    <span class="va1-brand-divider"></span>'
        f'    <span class="va1-brand-tag">{pf_ccy}</span>'
        f'  </div>'
        f'  <div style="display:flex;gap:8px;align-items:center">'
        f'    <span class="va1-pill"><span class="va1-pill-dot"></span>{source}</span>'
        f'    {version_pill}'
        f'  </div>'
        f'</div>'
    )


def status_bar_html(items: list[tuple[str, str, str]]) -> str:
    parts = []
    for i, (label, value, cls) in enumerate(items):
        if i:
            parts.append('<div class="va1-status-sep"></div>')
        parts.append(
            f'<div class="va1-status-item">'
            f'<div class="va1-status-label">{label}</div>'
            f'<div class="va1-status-value {cls}">{value}</div>'
            f'</div>'
        )
    return f'<div class="va1-status">{"".join(parts)}</div>'


def section_head(title: str, sub: str | None = None) -> str:
    """Section header: uppercase label, optional sub, hairline rule."""
    sub_html = f'<div class="va1-section-sub">{sub}</div>' if sub else ""
    return (
        f'<div class="va1-section-head">'
        f'<div class="va1-section-text">'
        f'<div class="va1-section-title">{title}</div>'
        f'{sub_html}'
        f'</div></div>'
        f'<hr class="va1-divider" />'
    )


def hero_nav_html(nav_value: str, daily: str, daily_dir: str,
                  vl: str, total_return: str, total_dir: str,
                  sparkline_svg: str = "") -> str:
    """NAV hero for the Overview tab. `sparkline_svg` is an inline <svg>.

    `daily` / `total_return` arrive already prefixed with their arrow by the
    call site — this helper must not add one.
    """
    return (
        f'<div class="va1-hero">'
        f'  <div>'
        f'    <div class="va1-hero-label">Net Asset Value</div>'
        f'    <div class="va1-hero-nav">{nav_value}</div>'
        f'    <div class="va1-hero-meta">'
        f'      <div class="va1-hero-pill">'
        f'        <div class="va1-hero-pill-label">Daily</div>'
        f'        <div class="va1-hero-pill-value {daily_dir}">{daily}</div>'
        f'      </div>'
        f'      <div class="va1-hero-pill">'
        f'        <div class="va1-hero-pill-label">Unit value · base 100</div>'
        f'        <div class="va1-hero-pill-value">{vl}</div>'
        f'      </div>'
        f'      <div class="va1-hero-pill">'
        f'        <div class="va1-hero-pill-label">Total Return</div>'
        f'        <div class="va1-hero-pill-value {total_dir}">{total_return}</div>'
        f'      </div>'
        f'    </div>'
        f'  </div>'
        f'  <div class="va1-hero-spark">{sparkline_svg}</div>'
        f'</div>'
    )


def sparkline_svg(points: list[float], color: str = "#0F2547",
                  width: int = 260, height: int = 76) -> str:
    """Tiny SVG sparkline with a faint area fill and an emphasised endpoint."""
    if not points or len(points) < 2:
        return ""
    mn, mx = min(points), max(points)
    rng = (mx - mn) or 1.0
    step = width / (len(points) - 1)
    coords = []
    for i, v in enumerate(points):
        x = i * step
        y = height - ((v - mn) / rng) * (height * 0.85) - (height * 0.075)
        coords.append((x, y))
    path = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    area_path = path + f" L {width:.1f},{height:.1f} L 0,{height:.1f} Z"
    last_x, last_y = coords[-1]
    return (
        f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" '
        f'style="width:100%;height:100%;display:block" aria-hidden="true">'
        f'<defs><linearGradient id="gpspark" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{color}" stop-opacity="0.14"/>'
        f'<stop offset="100%" stop-color="{color}" stop-opacity="0"/>'
        f'</linearGradient></defs>'
        f'<path d="{area_path}" fill="url(#gpspark)"/>'
        f'<path d="{path}" fill="none" stroke="{color}" '
        f'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="2.5" fill="{color}"/>'
        f'</svg>'
    )
