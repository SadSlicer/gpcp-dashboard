"""GPCP — ETF Portfolio Dashboard.

A local Streamlit app that replaces the GPCP.xlsm workflow. Reads/writes
the workbook in place; fetches live prices from Yahoo Finance.
"""

from __future__ import annotations

import sys as _sys
# Boot markers (visible in Streamlit Cloud logs) so we can tell whether the LIVE
# app is running this build and, if it crashes, whether it dies DURING imports
# (native wheel segfault: numpy/pandas/plotly) or later. If BOOT-START prints but
# BOOT-IMPORTS-OK does not, the crash is an import-time native-lib segfault.
_sys.stderr.write("GPCP-BOOT-START build=skip-baremode-v5\n"); _sys.stderr.flush()

import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

# Portfolio timezone — Streamlit Cloud runs in UTC, so all user-facing times
# (last update, fetch time, the after-close cutoff) are rendered in Paris time.
PARIS_TZ = ZoneInfo("Europe/Paris")


def _now_paris() -> dt.datetime:
    return dt.datetime.now(PARIS_TZ)
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import data
import daily_update
import prices
import pro
import theme as va1theme

_sys.stderr.write("GPCP-BOOT-IMPORTS-OK\n"); _sys.stderr.flush()

# SAAS — gate access by code + Supabase Auth login if secrets are configured.
# In pure local dev (no secrets), this is a no-op and the dashboard runs
# exactly like V15.  When auth runs, it calls st.set_page_config(centered)
# itself for the gate / login screens, then st.stop()s; subsequent reruns
# (once logged in) skip auth instantly and fall through to the wide layout
# below.
import supabase_client as _saas_cfg
import auth as _saas_auth

if _saas_cfg.is_saas_mode():
    _saas_user = _saas_auth.require_auth()
else:
    _saas_user = None

st.set_page_config(
    page_title="GPCP — Portfolio Terminal",
    page_icon="●",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# VA1 theme — Linear-inspired premium dark + emerald accent.
# All tokens centralized in theme.py. Session-state theme toggle (dark/light).
# ---------------------------------------------------------------------------

def _active_theme() -> str:
    """The theme Streamlit is currently rendering ("dark" | "light").

    Drives Plotly (styled server-side) and seeds the CSS default block. Falls
    back to dark — the app's default — when the context isn't resolved yet
    (documented as possibly stale on a session's very first run).
    """
    try:
        return "light" if st.context.theme.type == "light" else "dark"
    except Exception:
        return va1theme.DEFAULT_THEME


st.session_state.theme = _active_theme()

_T = va1theme.tokens_for(st.session_state.theme)
# Legacy aliases (kept so existing call-sites keep working — they map to the
# new VA1 tokens). Will be progressively replaced as we refactor each surface.
BG       = _T.BG_DEEP
PANEL    = _T.BG_ELEVATED
GRID     = _T.GRID
TEXT     = _T.TEXT_PRIMARY
MUTED    = _T.TEXT_MUTED
ACCENT   = _T.ACCENT      # brand orange (VA1 v3)
BRAND    = _T.BRAND       # = ACCENT now (orange)
GREEN    = _T.SUCCESS     # semantic green for positive returns — NEVER orange
RED      = _T.DANGER      # semantic red for negative returns

ETF_COLORS = va1theme.ETF_COLORS
# Data series use the SERIES palette, never BRAND: on the dark ground
# BRAND is a near-white tint (it has to read as a logo/button fill), which
# draws a washed-out line. SERIES[0] is the saturated steel blue.
SERIES = va1theme.series_palette(st.session_state.theme)
LINE = SERIES[0]

# Inject the full VA1 CSS (fonts, tokens, animations, component styles)
st.markdown(va1theme.build_css(st.session_state.theme), unsafe_allow_html=True)

# Loading-spinner element. Its own node (not body::before/::after, which the
# animated background owns) so the ring stays crisp; CSS reveals it during a
# rerun via body:has([data-testid="stStatusWidget"]).
st.markdown('<div class="gpcp-loader" aria-hidden="true"></div>', unsafe_allow_html=True)


def _require_first_portfolio() -> None:
    """First run: force the user to create their first portfolio (name + currency)
    before the dashboard loads. Replaces the old silent auto-create. SaaS only;
    skipped in demo mode. Runs BEFORE any data.current_portfolio() call so the
    auto-create fallback never fires ahead of this screen."""
    if not _saas_cfg.is_saas_mode() or st.session_state.get("__demo_mode"):
        return
    try:
        if data.list_portfolios():
            return
    except Exception:
        return
    st.markdown(
        va1theme.section_head(
            "Welcome",
            "Create your first portfolio to get started — you can add more "
            "later."),
        unsafe_allow_html=True,
    )
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        name = st.text_input("Portfolio name", value="My portfolio",
                             max_chars=40, key="__first_pf_name")
        ccy = st.selectbox("Currency", options=data.COMMON_CURRENCIES, index=0,
                          key="__first_pf_ccy")
        if st.button("Create my portfolio", type="primary",
                    width="stretch", key="__first_pf_btn"):
            if name.strip():
                data.create_portfolio(name.strip(), ccy)
                st.rerun()
            else:
                st.error("Please give your portfolio a name.")
    st.stop()


_require_first_portfolio()

# Demo mode flag — read-only frozen portfolio. Drives the banner below + hides
# write controls (Refresh & Save, Settings); writes are also blocked data-side.
_DEMO = bool(st.session_state.get("__demo_mode"))
if _DEMO:
    _db1, _db2 = st.columns([6, 1])
    with _db1:
        st.markdown(
            "<div style='background:var(--accent-tint);border:1px solid "
            "var(--accent-border);border-radius:6px;padding:10px 16px;"
            "font-size:13px;color:var(--accent)'><b>Demo mode — fictitious "
            "portfolio.</b> Simulated data (8 index ETFs, ~1 year, EUR) shown "
            "for demonstration only — <b>not real holdings and not investment "
            "advice</b>. Read-only: no change is saved.</div>",
            unsafe_allow_html=True,
        )
    with _db2:
        if st.button("Exit demo", width="stretch", key="__exit_demo"):
            st.session_state.pop("__demo_mode", None)
            st.rerun()

# Legacy CUSTOM_CSS retained as a no-op for backward compatibility.
# All real styling now happens in theme.build_css() above. This variable will
# be removed once every surface uses the new tokens.
CUSTOM_CSS = """
<style>
  html, body, [data-testid="stAppViewContainer"] {{
    background-color: {BG};
    color: {TEXT};
    font-family: 'SF Mono', 'JetBrains Mono', Menlo, Consolas, monospace;
  }}
  [data-testid="stHeader"] {{ background: transparent; }}
  .block-container {{ padding-top: 1.5rem; padding-bottom: 3rem; max-width: 1500px; }}

  /* Tabs */
  .stTabs [data-baseweb="tab-list"] {{
    gap: 4px;
    background: {PANEL};
    border-radius: 10px;
    padding: 6px;
  }}
  .stTabs [data-baseweb="tab"] {{
    background: transparent;
    color: {MUTED};
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 600;
    letter-spacing: 0.5px;
    text-transform: uppercase;
    font-size: 12px;
  }}
  .stTabs [aria-selected="true"] {{
    background: {BG} !important;
    color: {ACCENT} !important;
    box-shadow: inset 0 -2px 0 {ACCENT};
  }}

  /* Cards */
  .kpi-card {{
    background: {PANEL};
    border: 1px solid {GRID};
    border-radius: 10px;
    padding: 18px 20px;
    height: 100%;
  }}
  .kpi-label {{
    color: {MUTED};
    font-size: 11px;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    margin-bottom: 6px;
  }}
  .kpi-value {{
    color: {TEXT};
    font-size: 28px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }}
  .kpi-delta {{
    margin-top: 4px;
    font-size: 13px;
    font-variant-numeric: tabular-nums;
  }}
  .kpi-delta.up   {{ color: {GREEN}; }}
  .kpi-delta.down {{ color: {RED};   }}

  /* Headline strip */
  .ticker-bar {{
    background: linear-gradient(90deg, {PANEL} 0%, {BG} 100%);
    border: 1px solid {GRID};
    border-radius: 10px;
    padding: 8px 14px;
    margin-bottom: 18px;
    font-size: 12px;
    color: {MUTED};
    font-variant-numeric: tabular-nums;
  }}
  .ticker-bar b {{ color: {TEXT}; }}
  .ticker-bar .up   {{ color: {GREEN}; }}
  .ticker-bar .down {{ color: {RED};   }}

  /* Brand */
  .brand {{
    display: flex; align-items: baseline; gap: 14px; margin-bottom: 8px;
  }}
  .brand-mark {{
    font-size: 26px; font-weight: 700; letter-spacing: 2px; color: {ACCENT};
  }}
  .brand-sub {{
    color: {MUTED}; font-size: 12px; letter-spacing: 1.5px; text-transform: uppercase;
  }}

  /* Buttons */
  .stButton > button {{
    background: {PANEL};
    color: {TEXT};
    border: 1px solid {GRID};
    border-radius: 8px;
    padding: 0.6rem 1.2rem;
    font-weight: 600;
    letter-spacing: 0.5px;
  }}
  .stButton > button:hover {{
    border-color: {ACCENT};
    color: {ACCENT};
  }}

  /* Dataframes */
  [data-testid="stDataFrame"] {{
    background: {PANEL};
    border-radius: 10px;
    border: 1px solid {GRID};
    padding: 6px;
  }}

  /* Legacy block intentionally empty — see theme.build_css() */
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Plotly defaults — delegate to the centralized VA1 theme
# ---------------------------------------------------------------------------

def style_fig(fig: go.Figure, *, height: int = 380, showlegend: bool = True) -> go.Figure:
    return va1theme.style_plotly(
        fig, theme=st.session_state.theme,
        height=height, showlegend=showlegend,
    )


def period_returns(ph: pd.DataFrame) -> dict[str, dict[str, float | None]]:
    """Per-asset MTD / YTD / 12-month return, read off the stored price history.

    Stored prices are already converted to the portfolio currency, so these are
    the returns actually experienced, FX included — they will differ from the
    "pure stock performance" daily figure, which neutralizes FX.

    The reference for a window is the last close AT OR BEFORE its start. When an
    asset was bought mid-window it has no such close, so the first quote after
    the start is used instead and the return runs from the purchase — never from
    a price the portfolio never held.
    """
    out: dict[str, dict[str, float | None]] = {}
    if ph is None or ph.empty or "date" not in ph.columns:
        return out
    ph = ph.sort_values("date")
    dates = pd.to_datetime(ph["date"])
    last_date = dates.iloc[-1]
    starts = {
        "MTD": last_date.normalize().replace(day=1),
        "YTD": last_date.normalize().replace(month=1, day=1),
        "12Mo": last_date.normalize() - pd.DateOffset(years=1),
    }
    for col in ph.columns:
        if col == "date":
            continue
        s = pd.to_numeric(ph[col], errors="coerce")
        valid = s.notna() & (s > 0)
        if not valid.any():
            continue
        last_val = float(s[valid].iloc[-1])
        res: dict[str, float | None] = {}
        for label, start in starts.items():
            before = valid & (dates <= start)
            after = valid & (dates > start)
            if before.any():
                base = float(s[before].iloc[-1])
            elif after.any():
                base = float(s[after].iloc[0])
            else:
                base = 0.0
            res[label] = (last_val / base - 1.0) if base > 0 else None
        out[col] = res
    return out


def vl_period_returns(ph: pd.DataFrame) -> dict[str, float | None]:
    """Portfolio-level MTD / YTD / 12Mo, time-weighted.

    Taken from the unit-value series, not from the NAV: the NAV jumps on every
    deposit, so a NAV-based "YTD" would count new money as performance.
    """
    empty = {"MTD": None, "YTD": None, "12Mo": None}
    try:
        vl_df = data.compute_vl_series(ph)
    except Exception:
        return empty
    if vl_df is None or vl_df.empty or "vl" not in vl_df.columns:
        return empty
    tmp = vl_df[["date", "vl"]].rename(columns={"vl": "_vl"})
    got = period_returns(tmp)
    return got.get("_vl", empty)


def rgba(hex_color: str, alpha: float) -> str:
    """"#0F2547" → "rgba(15, 37, 71, 0.06)".

    Area fills have to be derived from the line colour; hardcoding them is how
    a navy curve ended up with an orange fill left over from the old palette.
    """
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {alpha})"


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def euro(v, decimals: int = 2) -> str:
    if v is None or pd.isna(v):
        return "—"
    s = f"{v:,.{decimals}f}".replace(",", " ").replace(".", ",")
    return f"{s} €"


def pct(v, decimals: int = 2) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{v * 100:+.{decimals}f} %"


def kpi(label: str, value: str, delta: str | None = None,
        direction: str = "", live: bool = False) -> str:
    """Render a VA1 KPI card. `live=True` adds a pulsing "Live" badge."""
    return va1theme.kpi_card(label, value, delta=delta,
                              direction=direction, live=live)


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

def _initial_prices(static: data.PortfolioStatic, price_history: pd.DataFrame) -> tuple[dict[str, float], str]:
    """Pull the latest known prices from the history so the app loads
    something meaningful without a network call. Returns (prices, source_label)."""
    if price_history.empty:
        return {}, "no data — click Refresh & Save"
    # Each asset uses its OWN last adjusted close (last non-NaN value in its
    # column), i.e. "session closed → last adjusted close". Using the global last
    # ROW instead would drop any asset whose most recent session closed on a
    # different day than the others (US vs EU, a market holiday, a data lag) —
    # that asset would vanish from the NAV.
    prices: dict[str, float] = {}
    for a in data.ASSETS:
        if a in price_history.columns:
            col = price_history[a].dropna()
            if not col.empty:
                prices[a] = float(col.iloc[-1])
    last_date = price_history["date"].iloc[-1]
    label = f"sqlite snapshot · {last_date.strftime('%d %b %Y')}"
    return prices, label


def _user_scope() -> tuple[str, str]:
    """Per-user cache key for `_load_all`.

    `st.cache_data` is ONE cache shared by every session in the process (only
    `st.session_state` is per-session). With a no-arg `_load_all`, the first of
    several concurrent users to render populated that single entry and every
    other user was then served THAT user's portfolio — a crash (their per-session
    `data.ASSETS` no longer matched the cached `price_history` columns → the
    `astype`/index error in the allocation chart) and, worse, a cross-user data
    leak. Keying the cache on (user_id, portfolio_id) gives each user+portfolio
    its own entry so concurrent sessions stay fully isolated. Local sqlite mode
    has a single implicit user."""
    uid = "local"
    try:
        user = st.session_state.get("__saas_user")
        if user and user.get("id"):
            uid = str(user["id"])
    except Exception:
        pass
    try:
        pid = str(data.current_portfolio()["id"])
    except Exception:
        pid = "default"
    return uid, pid


@st.cache_data(show_spinner=False)
def _load_all(scope: tuple[str, str]):
    # `scope` = (user_id, portfolio_id). It is unused in the body but is what
    # keys the cache per user — DO NOT prefix it with "_" (Streamlit skips
    # underscore-prefixed args when hashing, which would re-introduce the
    # cross-user bug). See _user_scope().
    static = data.load_static()
    price_history = data.load_price_history()
    position_history = data.load_position_history()
    transactions = data.load_transactions()
    return static, price_history, position_history, transactions


def _refresh_excel_cache():
    # Clear only THIS user's entry so one user's write doesn't wipe everyone
    # else's cache (and force a reload storm). Fall back to a full clear on a
    # Streamlit too old to target a single entry (still correct, just broader).
    try:
        _load_all.clear(_user_scope())
    except Exception:
        _load_all.clear()


@st.cache_data(ttl=3600, show_spinner=False)
def _auto_price_for_new_ticker(ticker: str, when: dt.date):
    """Adjusted close for a not-yet-registered asset, by Yahoo ticker.

    Cached by (ticker, date) so typing in the new-asset form doesn't re-hit
    Yahoo on every Streamlit rerun. Returns None for invalid/non-public
    tickers → the form falls back to manual price entry.
    """
    return prices.fetch_adjusted_close_on(ticker, when)


def _augmented_pf(price_history):
    """Price history (in portfolio currency) with a purchase-price row per BUY,
    for the history tables + charts so each asset's series starts at the price
    PAID. Falls back to the plain close history if the active backend has no
    augmentation (local sqlite mode)."""
    aug = price_history
    # Guard: duplicate columns make the per-row augmentation emit non-scalar
    # (Series) cells, which later crash .astype(float) in the allocation chart.
    # Should never happen once data loads are per-user, but keep it bulletproof.
    if getattr(aug, "columns", None) is not None and aug.columns.duplicated().any():
        aug = aug.loc[:, ~aug.columns.duplicated()]
    fn = getattr(data, "augmented_price_history", None)
    if fn is not None:
        try:
            aug = fn(aug)
        except Exception:
            pass
    return data.price_history_in_portfolio_currency(aug)


def _date_labels(df) -> pd.Series:
    """Formatted dates for the history tables, marking purchase rows '· achat'."""
    lbl = df["date"].dt.strftime("%a %d %b %Y")
    if "is_buy" in df.columns:
        lbl = lbl.where(~df["is_buy"].fillna(False), lbl + " · buy")
    if "is_sell" in df.columns:
        lbl = lbl.where(~df["is_sell"].fillna(False), lbl + " · sell")
    return lbl


def _num_col(frame: pd.DataFrame, name: str) -> pd.Series:
    """Robust numeric extraction of column `name` for the history tables.

    Guards every shape that has crashed a plain .astype(float) here: a DUPLICATE
    column name (frame[name] returns a DataFrame), object dtype with stray
    strings, and non-scalar cells (e.g. an odd/leveraged asset whose augmented
    history left a Series in a cell). Non-numeric / missing → 0 so the NAV row
    still totals instead of taking down the whole page."""
    col = frame[name]
    if isinstance(col, pd.DataFrame):          # duplicate column name → take first
        col = col.iloc[:, 0]
    col = col.map(lambda x: x if pd.api.types.is_scalar(x) else float("nan"))
    return pd.to_numeric(col, errors="coerce").fillna(0.0).reset_index(drop=True)


def _has_script_ctx() -> bool:
    """True only for a REAL user script run. Streamlit Cloud periodically executes
    the whole app in 'bare mode' (health checks / file-watch reruns) with no
    ScriptRunContext — those must NOT do the heavy Yahoo-fetch + DB work, or two
    heavy runs (bare-mode + a real session) collide on the small free-tier
    container and segfault a native lib. Cheap and defensive."""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx() is not None
    except Exception:
        return True                      # unknown → behave as before (do the work)


def _auto_refresh_if_stale() -> str | None:
    """Option C: on first session load, if the DB is missing today's (or the
    most recent trading day's) close, fetch + save automatically. Idempotent —
    daily_update.run() is itself a no-op when nothing has moved."""
    if not prices.YAHOO_ENABLED:
        return None                      # Yahoo kill-switch: never fetch at boot
    if not _has_script_ctx():
        return None                      # bare-mode/health-check run → no heavy work
    if st.session_state.get("__demo_mode"):
        return None                      # demo is read-only — never fetch/save
    if st.session_state.get("auto_refresh_done"):
        return None
    st.session_state.auto_refresh_done = True

    latest = data.latest_price_date()
    today = dt.date.today()
    # Only attempt after the European close (≥ 17:30 Paris). Before that,
    # opening the dashboard mid-day shouldn't trigger writes — the cron at
    # 18:00 owns the daily save.
    now = _now_paris().time()
    after_close = now >= dt.time(17, 30)
    if latest is not None and latest >= today and not after_close:
        return None
    if latest is not None and latest >= today:
        return None

    try:
        rc = daily_update.run(force=False)
        if rc == 0 and (data.latest_price_date() or latest) != latest:
            _refresh_excel_cache()
            return "Auto-refresh: new prices saved from Yahoo Finance."
        return None
    except Exception as exc:
        return f"Auto-refresh skipped: {exc}"


def _heal_price_gaps_once() -> None:
    """Once per (session, portfolio): repair any asset whose stored price history
    has a hole up to today — otherwise the gap is forward-filled with a stale
    price and NAV/VL/charts silently break. Cloud backend only (no-op on local
    sqlite, which is kept fresh by the launchd cron). Best-effort."""
    if not prices.YAHOO_ENABLED:
        return                           # Yahoo kill-switch: never fetch at boot
    if not _has_script_ctx():
        return                           # bare-mode/health-check run → no heavy work
    fn = getattr(data, "heal_price_gaps", None)
    if fn is None:
        return
    try:
        pid = data.current_portfolio()["id"]
    except Exception:
        return
    healed = st.session_state.setdefault("price_heal_done", set())
    if pid in healed:
        return
    healed.add(pid)
    try:
        if fn() > 0:
            _refresh_excel_cache()          # new prices → drop the cached load
    except Exception:
        pass


_sys.stderr.write("GPCP-BOOT: before auto_refresh\n"); _sys.stderr.flush()
auto_msg = _auto_refresh_if_stale()
_sys.stderr.write("GPCP-BOOT: before heal\n"); _sys.stderr.flush()
_heal_price_gaps_once()
_sys.stderr.write("GPCP-BOOT: before load_all\n"); _sys.stderr.flush()

static, price_history, position_history, transactions_df = _load_all(_user_scope())
_sys.stderr.write("GPCP-BOOT: after load_all\n"); _sys.stderr.flush()

# Assets CURRENTLY held (shares > 0 today). A fully-sold asset keeps its
# transactions + realized P&L (archives) but must vanish from every "current
# holdings" view (Positions, Allocation drift, Price History, Pro correlation /
# attribution / sector-geo, the asset dropdowns). data.ASSETS still lists every
# traded asset — used only where the holding PERIOD matters (allocation
# evolution) or for the ledger.
_cur_shares = data.current_shares()
held_assets = [a for a in data.ASSETS if _cur_shares.get(a, 0) > 1e-9]

if "live_prices" not in st.session_state:
    prices_init, src_label = _initial_prices(static, price_history)
    st.session_state.live_prices = prices_init
    st.session_state.prices_source = src_label
    st.session_state.prices_fetched_at = None

if auto_msg:
    st.toast(auto_msg)


# ---------------------------------------------------------------------------
# Header / action bar
# ---------------------------------------------------------------------------

_active_pf = data.current_portfolio()
_pf_ccy = data.current_portfolio_currency()
_pf_sym = data.CURRENCY_SYMBOL.get(_pf_ccy, _pf_ccy)

# Snapshot has to be computed BEFORE the header (status bar reads it)
snapshot = data.compute_snapshot(static, st.session_state.live_prices, price_history)
live_total = snapshot["total_value"]
live_pnl_eur = snapshot["daily_pnl_eur"]
live_pnl_pct = snapshot["daily_pnl_pct"]
vl = snapshot["vl"]
arrow = "▲" if live_pnl_eur >= 0 else "▼"
direction_cls = "up" if live_pnl_eur >= 0 else "down"

# APP BAR — identity, freshness and the primary action on ONE row.
#
# This replaces the old stacked header + status strip. The status strip carried
# NAV / Daily / Unit value, which the KPI strip on the Dashboard already shows;
# repeating them above every tab cost a band of height on each screen for no new
# information. What stays here is what is NOT elsewhere: which portfolio, in
# which currency, how fresh the prices are.
#
# The theme picker that used to sit here is gone: it could only drive the CSS
# layer, never Streamlit's native chrome (dataframes render on a canvas and read
# .streamlit/config.toml), so choosing dark produced a dark page with light
# tables. The app is pinned dark in every layer instead.
_bar_left, _bar_right = st.columns([7, 2], vertical_alignment="center")
with _bar_left:
    st.markdown(
        va1theme.header_html(
            pf_name=_active_pf['name'],
            pf_ccy=_pf_ccy,
            source=(f"{st.session_state.prices_source} · "
                    f"{_now_paris().strftime('%a %d %b · %H:%M')}"),
            version="",
        ),
        unsafe_allow_html=True,
    )
with _bar_right:
    if not _DEMO and st.button("Refresh & Save", width="stretch", type="primary",
                 help="Fetch latest Yahoo Finance quotes and upsert today's row in the database. "
                      "Single source of truth: every tab reads from this DB after the click. "
                      "Safe on weekends/holidays — Yahoo returns the last trading day and the "
                      "upsert is a no-op if that date is already saved."):
        with st.spinner("Fetching Yahoo Finance…"):
            try:
                _sys.stderr.write("GPCP-REFRESH: start refetch_recent_closes\n"); _sys.stderr.flush()
                # V13.1: first overwrite the last ~7 calendar days with the
                # official closes (kills any prior intraday snapshot).
                try:
                    data.refetch_recent_closes(days=7)
                except Exception:
                    pass
                _sys.stderr.write("GPCP-REFRESH: before fetch_latest\n"); _sys.stderr.flush()
                quotes = prices.fetch_latest_with_date()
                _sys.stderr.write(f"GPCP-REFRESH: fetched {len(quotes)} quotes\n"); _sys.stderr.flush()
                if not quotes:
                    st.error("No prices returned. Check internet connectivity.")
                else:
                    trade_date = prices.most_common_trade_date(quotes)
                    price_map = {a: p for a, (_, p) in quotes.items()}
                    _sys.stderr.write("GPCP-REFRESH: before save_today\n"); _sys.stderr.flush()
                    # Persist to DB (idempotent upsert — overwrites today's row if any)
                    res = data.save_today(price_map, static.shares, when=trade_date)
                    _sys.stderr.write("GPCP-REFRESH: saved OK\n"); _sys.stderr.flush()
                    _refresh_excel_cache()
                    # Mirror into session so the page is instantly in sync
                    st.session_state.live_prices = price_map
                    st.session_state.live_trade_date = trade_date
                    st.session_state.prices_source = (
                        f"Yahoo Finance · trade {trade_date.strftime('%d %b %Y')}"
                    )
                    st.session_state.prices_fetched_at = _now_paris()
                    st.success(
                        f"✓ {len(quotes)} / {len(data.ASSETS)} prices saved · "
                        f"trade {trade_date.isoformat()} · NAV {euro(res['total_value'])}"
                    )
                    st.rerun()
            except Exception as exc:
                st.error(f"Refresh failed: {exc}")


def render_holdings(*, show_footer: bool = True) -> None:
    """The dense holdings table, as one panel.

    Shared by the Dashboard and by Holdings → Positions so the two can never
    show different columns or a different TOTAL. `show_footer` drops the KPI
    row on the Dashboard, where the same figures already sit in the strip at
    the top of the screen.
    """
    _positions_empty = (not data.ASSETS and snapshot.get("cash_balance", 0) <= 0)
    if _positions_empty:
        st.info("This portfolio is empty. Go to **History → Transactions** to buy "
                "your first asset (an existing asset or New asset), "
                "or to **Settings → Portfolios** to switch portfolio.")

    _pf_ccy_pos = data.current_portfolio_currency()
    _pf_sym_pos = data.CURRENCY_SYMBOL.get(_pf_ccy_pos, _pf_ccy_pos)
    _value_col = f"Value ({_pf_ccy_pos})"
    _pnl_col = f"P&L ({_pf_ccy_pos})"
    _cost_col = f"Cost basis ({_pf_ccy_pos})"

    _periods = period_returns(price_history)
    _tickers = getattr(data, "TICKER_BY_ASSET", {}) or {}

    # Daily return is shown as pure stock performance for every asset; when the
    # asset trades in another currency, the FX-included figure is appended so the
    # gap with the History tab's converted values explains itself.
    def _fmt_daily(stock: float | None, pf: float | None,
                   native_ccy: str, target_ccy: str) -> str:
        if stock is None or pd.isna(stock):
            return "—"
        stock_s = f"{stock:+.2%}"
        if (pf is None or pd.isna(pf)
                or native_ccy.upper() == target_ccy.upper()
                or abs(pf - stock) < 1e-6):
            return stock_s
        return f"{stock_s}  ·  {pf:+.2%} {target_ccy}"

    rows = []
    for asset in data.ASSETS:
        if asset not in snapshot["positions"]:
            continue  # fully-exited asset (0 shares)
        p = snapshot["positions"].get(asset, {})
        native_ccy = (p.get("currency") or _pf_ccy_pos).upper()
        native_sym = data.CURRENCY_SYMBOL.get(native_ccy, native_ccy)
        price_native = p.get("native_price", p.get("price"))
        _dr = p.get("daily_return")
        value = p.get("value")
        pnl = p.get("total_return_eur")
        # Cost basis is not stored: it is what the position is worth today minus
        # what it has earned. Only derivable when both are known.
        cost = (value - pnl) if (value is not None and pnl is not None) else None
        per = _periods.get(asset, {})
        rows.append({
            "Ticker": _tickers.get(asset) or "—",
            "Asset": asset,
            "ISIN": static.isins.get(asset, "—"),
            "Shares": f"{static.shares.get(asset, 0):,.0f}",
            "Last": (f"{price_native:,.4f} {native_sym}"
                     if price_native is not None else "—"),
            # Absolute move of the day, in the asset's own currency. Derived
            # from the return rather than stored: price − price/(1+r).
            "Chg": (f"{price_native - price_native / (1.0 + _dr):+,.4f}"
                    if (price_native is not None and _dr is not None
                        and pd.notna(_dr) and (1.0 + _dr) != 0) else "—"),
            _value_col: value,
            "Weight": p.get("allocation"),
            _cost_col: cost,
            _pnl_col: pnl,
            "P&L %": p.get("total_return"),
            "% Chg": _fmt_daily(p.get("daily_return"), p.get("daily_return_pf"),
                                native_ccy, _pf_ccy_pos),
            "MTD %": per.get("MTD"),
            "YTD %": per.get("YTD"),
            "12Mo %": per.get("12Mo"),
            "Fees": static.fees.get(asset),
        })

    # Cash line (PEA liquidity) when present
    if "Cash" in snapshot["positions"]:
        cp = snapshot["positions"]["Cash"]
        rows.append({
            "Ticker": "—", "Asset": "Cash", "ISIN": "—",
            "Shares": "—", "Last": "—", "Chg": "—",
            _value_col: cp.get("value"), "Weight": cp.get("allocation"),
            _cost_col: float("nan"), _pnl_col: float("nan"),
            "P&L %": float("nan"), "% Chg": "—", "MTD %": float("nan"),
            "YTD %": float("nan"), "12Mo %": float("nan"),
            "Fees": float("nan"),
        })

    pos_df = pd.DataFrame(rows)

    if not pos_df.empty:
        _panel = st.container(border=True)
        _panel.markdown(
            va1theme.panel_head(
                "Holdings",
                "prices in native currency · MTD / YTD / 12Mo include FX",
                right=va1theme.tag(_pf_ccy_pos) + " " + va1theme.tag(
                    f"{len(pos_df)} lines"),
            ),
            unsafe_allow_html=True,
        )

        # Portfolio line first, the way a terminal reads: the total, then what
        # composes it. MTD/YTD/12Mo come from the unit value (time-weighted), so
        # deposits don't show up as performance.
        _vl_per = vl_period_returns(price_history)
        _tot_value = pos_df[_value_col].sum(skipna=True)
        _tot_cost = pos_df[_cost_col].sum(skipna=True)
        _tot_pnl = pos_df[_pnl_col].sum(skipna=True)
        total_row = {
            "Ticker": "", "Asset": "TOTAL",
            "ISIN": f"{len(pos_df)} lines", "Shares": "—",
            "Last": "—", "Chg": "—",
            _value_col: _tot_value, "Weight": pos_df["Weight"].sum(skipna=True),
            _cost_col: _tot_cost, _pnl_col: _tot_pnl,
            "P&L %": total_return_pct,
            "% Chg": f"{live_pnl_pct:+.2%}",
            "MTD %": _vl_per.get("MTD"), "YTD %": _vl_per.get("YTD"),
            "12Mo %": _vl_per.get("12Mo"),
            "Fees": (pos_df["Fees"] * pos_df["Weight"]).sum(skipna=True),
        }
        # ---- Render ---------------------------------------------------
        # Hand-rendered HTML rather than st.dataframe: that widget paints to a
        # canvas, so its header casing, column alignment, typography and total
        # row can't be styled. This is also what finally killed the "None" the
        # grid printed for the empty TOTAL cells.
        def _tone(v) -> str:
            if v is None or (isinstance(v, float) and pd.isna(v)):
                return "muted"
            return "pos" if v > 0 else ("neg" if v < 0 else "")

        def _money(v) -> str:
            return "—" if v is None or pd.isna(v) else f"{v:,.2f} {_pf_sym_pos}"

        def _signed_money(v) -> str:
            return "—" if v is None or pd.isna(v) else f"{v:+,.2f} {_pf_sym_pos}"

        def _pctf(v) -> str:
            return "—" if v is None or pd.isna(v) else f"{v:+.2%}"

        def _pct_plain(v) -> str:
            return "—" if v is None or pd.isna(v) else f"{v:.2%}"

        def _str_tone(txt: str) -> str:
            if not isinstance(txt, str) or txt in ("—", ""):
                return "muted"
            if txt.startswith("+"):
                return "pos"
            if txt.startswith(("-", "\u2212")):
                return "neg"
            return ""

        # "Last" (native price) and "Chg" (absolute day move in the asset's own
        # currency) are dropped by request — % Chg and the % returns stay. The
        # underlying values are still computed above; they're just not shown.
        headers = ["Ticker", "Asset", "Shares",
                   f"Value ({_pf_ccy_pos})", "Weight",
                   f"Cost basis ({_pf_ccy_pos})", f"P&L ({_pf_ccy_pos})",
                   "P&L %", "% Chg", "MTD %", "YTD %", "12Mo %", "Fees"]
        num_cols = set(range(2, len(headers)))

        def _num(v):
            """Raw value for sorting; blank when missing so it sorts last."""
            return "" if v is None or (isinstance(v, float) and pd.isna(v)) else v

        def _txt_num(txt: str):
            """Sort key for the pre-formatted text columns (Shares, Chg)."""
            if not isinstance(txt, str):
                return ""
            cleaned = txt.replace("\u2212", "-").replace(",", "").replace("%", "")
            cleaned = cleaned.replace("+", "").strip()
            try:
                return float(cleaned)
            except ValueError:
                return ""

        def _row_cells(r: dict, *, is_total: bool) -> list:
            return [
                (r["Ticker"], "key" if not is_total else "", r["Ticker"]),
                (r["Asset"], "name", r["Asset"]),
                (r["Shares"], "", _txt_num(r["Shares"])),
                (_money(r[_value_col]), "", _num(r[_value_col])),
                (_pct_plain(r["Weight"]), "", _num(r["Weight"])),
                (_money(r[_cost_col]), "", _num(r[_cost_col])),
                (_signed_money(r[_pnl_col]), _tone(r[_pnl_col]), _num(r[_pnl_col])),
                (_pctf(r["P&L %"]), _tone(r["P&L %"]), _num(r["P&L %"])),
                (r["% Chg"], _str_tone(r["% Chg"]), _txt_num(r["% Chg"])),
                (_pctf(r["MTD %"]), _tone(r["MTD %"]), _num(r["MTD %"])),
                (_pctf(r["YTD %"]), _tone(r["YTD %"]), _num(r["YTD %"])),
                (_pctf(r["12Mo %"]), _tone(r["12Mo %"]), _num(r["12Mo %"])),
                (_pct_plain(r["Fees"]), "muted", _num(r["Fees"])),
            ]

        table_rows = [_row_cells(total_row, is_total=True)]
        table_rows[0][1] = (f"TOTAL · {len(pos_df)} lines", "name", "")
        table_rows += [_row_cells(r, is_total=False) for r in rows]

        _tbl_html, _tbl_h = va1theme.sortable_table(
            headers, table_rows, num_cols=num_cols, first_row_is_total=True,
            theme=st.session_state.theme,
        )
        with _panel:
            # st.iframe, not components.v1.html: the latter is deprecated and
            # already past its announced removal date.
            st.iframe(_tbl_html, height=_tbl_h)
        _panel.caption(
            "MTD / YTD / 12Mo are price returns per line, computed from the "
            "stored history in " + _pf_ccy_pos + " (FX included). The TOTAL row "
            "uses the unit value instead, so deposits and withdrawals are not "
            "counted as performance."
        )
        if show_footer:
            # ---- Footer KPIs ----
            weighted_fees = (pos_df["Fees"] * pos_df["Weight"]).sum(skipna=True)
            f1, f2, f3, f4 = st.columns(4)
            f1.markdown(kpi("Σ Positions", euro(_tot_value)), unsafe_allow_html=True)
            f2.markdown(
                kpi("Daily return", pct(live_pnl_pct),
                    f"{arrow} {euro(live_pnl_eur)}", direction_cls),
                unsafe_allow_html=True,
            )
            f3.markdown(
                kpi("Total return", pct(total_return_pct),
                    f"Cash P&L {euro(snapshot.get('cash_pnl_eur', 0.0))}",
                    "up" if total_return_pct >= 0 else "down"),
                unsafe_allow_html=True,
            )
            f4.markdown(kpi("Weighted fees", f"{weighted_fees * 100:.2f} %"),
                        unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

# Five top-level sections instead of seven flat ones. Positions/Allocation
# answer the same question (what I hold, in what proportion) and Price
# history/Transactions are both "what happened", so each pair becomes one
# section with sub-tabs.
#
# The sub-tabs are CREATED here, inside their parent's context, and consumed
# further down via `with sub_x:`. A Streamlit container is bound to the
# position where it was created, so the content lands inside the parent tab
# without needing to re-indent the existing blocks.
tab_dashboard, tab_holdings, tab_history, tab_analytics, tab_settings = st.tabs(
    ["Dashboard", "Holdings", "History", "Analytics", "Settings"]
)

with tab_holdings:
    sub_positions, sub_allocation = st.tabs(["Positions", "Allocation"])
with tab_history:
    sub_prices, sub_tx = st.tabs(["Price history", "Transactions"])

# ============================================================================
# OVERVIEW — VA1 v3: NAV hero + KPI grid + chart + allocation breakdown
# ============================================================================
with tab_dashboard:
    inception_date = snapshot["inception_date"]
    net_invested = snapshot.get("net_invested", 0.0)
    cash_pnl_eur = snapshot.get("cash_pnl_eur", 0.0)
    # Total Return = the REAL money gain on invested capital (money-weighted):
    # (current NAV − net invested) / net invested. Computed here from snapshot
    # fields so it's identical on every backend. Distinct from the VL / unit
    # value, which is the time-weighted, flow-neutralized performance.
    total_return_pct = (cash_pnl_eur / net_invested) if net_invested > 0 else 0.0

    # ---- KPI strip -------------------------------------------------------
    # Six figures, joined into one ruled grid. Annualized and Max drawdown are
    # pulled up from the Analytics tab: they are what you check daily, and they
    # cost nothing to surface here.
    _hs = pro.headline_stats(price_history)
    _ann, _mdd = _hs.get("ann_return"), _hs.get("max_dd")
    _since = inception_date.strftime("%d %b %Y") if inception_date else "—"
    _years = ((pd.Timestamp.today().normalize() - pd.Timestamp(inception_date)).days / 365.25
              if inception_date else None)

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.markdown(
        kpi("Net asset value", euro(live_total),
            f"{arrow} {euro(live_pnl_eur)}  {pct(live_pnl_pct)}", direction_cls,
            live=True),
        unsafe_allow_html=True,
    )
    k2.markdown(
        kpi("Unit value (base 100)", f"{vl:,.2f}", "time-weighted"),
        unsafe_allow_html=True,
    )
    k3.markdown(
        kpi("Total return", pct(total_return_pct), "money-weighted",
            "up" if total_return_pct >= 0 else "down"),
        unsafe_allow_html=True,
    )
    k4.markdown(
        kpi("Net invested", euro(net_invested),
            f"{len(transactions_df)} tx · since {_since}"),
        unsafe_allow_html=True,
    )
    k5.markdown(
        kpi("Annualized", pct(_ann) if _ann is not None else "—",
            (f"geometric, {_years:.1f}y" if _years else "geometric"),
            ("up" if (_ann or 0) >= 0 else "down") if _ann is not None else ""),
        unsafe_allow_html=True,
    )
    k6.markdown(
        kpi("Max drawdown", pct(_mdd) if _mdd is not None else "—",
            "worst peak-to-trough", "down" if _mdd else ""),
        unsafe_allow_html=True,
    )

    st.write("")

    # ---- Performance + allocation, two panels side by side ---------------
    col_chart, col_alloc = st.columns([1.9, 1])

    with col_chart:
        with st.container(border=True):
            st.markdown(
                va1theme.panel_head(
                    "Unit value", "base 100 at inception · time-weighted"),
                unsafe_allow_html=True,
            )
            vl_series_df = data.compute_vl_series(price_history)
            if vl_series_df.empty:
                st.info("No history yet — click Refresh & Save to record "
                        "today's snapshot.")
            else:
                vl_df = vl_series_df[["date", "vl", "nav"]].copy()
                max_d = vl_df["date"].max().date()
                # Start at the effective inception (Settings date, else 1st
                # transaction) — same rule as the Allocation and Price history
                # tabs, which already clamped and so disagreed with this chart.
                _data_min = vl_df["date"].min().date()
                _incept = data.get_inception_date()
                min_d = min(max(_data_min, _incept), max_d)

                # A price history that BEGINS AFTER the inception is a data gap,
                # not a display choice: no clamp can show a curve for months
                # that were never fetched. Say so, and point at the fix, rather
                # than silently drawing a shorter history than the KPIs claim.
                if _incept and _data_min > _incept:
                    st.caption(
                        f"Price history starts {_data_min.strftime('%d %b %Y')}, "
                        f"after the {_incept.strftime('%d %b %Y')} inception — "
                        "the months in between were never fetched. "
                        "**Settings → Re-download ALL prices** backfills them."
                    )

                # A range switch, not two date pickers: picking "YTD" is one
                # click instead of two calendar drills. The custom range stays
                # reachable through the last option.
                _rng = st.segmented_control(
                    "Range", ["1M", "6M", "YTD", "1Y", "5Y", "Max", "Custom"],
                    default="1Y", key="dash_range", label_visibility="collapsed",
                )
                _rng = _rng or "1Y"
                if _rng == "Custom":
                    cf, ct = st.columns(2)
                    with cf:
                        nav_from = st.date_input("From", min_d, min_value=min_d,
                                                 max_value=max_d, key="nav_from")
                    with ct:
                        nav_to = st.date_input("To", max_d, min_value=min_d,
                                               max_value=max_d, key="nav_to")
                else:
                    nav_to = max_d
                    if _rng == "YTD":
                        nav_from = max(min_d, max_d.replace(month=1, day=1))
                    elif _rng == "Max":
                        nav_from = min_d
                    else:
                        _off = {"1M": pd.DateOffset(months=1),
                                "6M": pd.DateOffset(months=6),
                                "1Y": pd.DateOffset(years=1),
                                "5Y": pd.DateOffset(years=5)}[_rng]
                        nav_from = max(min_d, (pd.Timestamp(max_d) - _off).date())

                nav_view = vl_df[(vl_df["date"] >= pd.Timestamp(nav_from)) &
                                 (vl_df["date"] <= pd.Timestamp(nav_to))]

                fig_nav_ov = go.Figure()
                fig_nav_ov.add_trace(
                    go.Scatter(
                        x=nav_view["date"], y=nav_view["vl"], mode="lines",
                        line=dict(color=LINE, width=2),
                        fill="tozeroy", fillcolor=rgba(LINE, 0.10),
                        name="Unit value", customdata=nav_view["nav"],
                        hovertemplate=("%{x|%a %d %b %Y}<br>"
                                       "<b>Unit value %{y:.4f}</b><br>"
                                       "NAV %{customdata:,.2f} €<extra></extra>"),
                    )
                )
                # Emphasised endpoint — where the portfolio stands today.
                if not nav_view.empty:
                    fig_nav_ov.add_trace(go.Scatter(
                        x=[nav_view["date"].iloc[-1]], y=[nav_view["vl"].iloc[-1]],
                        mode="markers", marker=dict(color=LINE, size=7),
                        hoverinfo="skip", showlegend=False,
                    ))
                style_fig(fig_nav_ov, height=372, showlegend=False)
                fig_nav_ov.update_yaxes(title=None, tickformat=",.2f")
                fig_nav_ov.update_xaxes(rangebreaks=data.trading_day_rangebreaks(
                    price_history, nav_from, nav_to))
                if not nav_view.empty:
                    lo = float(nav_view["vl"].min())
                    hi = float(nav_view["vl"].max())
                    span = hi - lo
                    if span < 1e-9:            # a single flat day
                        lo, hi = lo - 1.0, hi + 1.0
                        span = hi - lo
                    # The base-100 line is only pulled into view when the data
                    # is anywhere near it. Forcing it in unconditionally is what
                    # made the curve look FLAT: on a portfolio at 153 the axis
                    # ran 100→160, so the whole series lived in the top quarter
                    # of the frame.
                    show_base = (lo - span) <= 100.0 <= (hi + span)
                    if show_base:
                        lo, hi = min(lo, 100.0), max(hi, 100.0)
                        span = hi - lo
                        fig_nav_ov.add_hline(
                            y=100.0, line=dict(color=MUTED, width=1, dash="dot"),
                            annotation_text="base 100",
                            annotation_position="top left",
                            annotation_font_color=MUTED,
                        )
                    pad = max(span * 0.12, 0.25)
                    fig_nav_ov.update_yaxes(range=[lo - pad, hi + pad])
                    # Pin the x-axis to the window so the curve runs edge to
                    # edge; Plotly otherwise pads the range and leaves the plot
                    # trailing off before the right border.
                    fig_nav_ov.update_xaxes(
                        range=[pd.Timestamp(nav_from), pd.Timestamp(nav_to)])
                st.plotly_chart(fig_nav_ov, width="stretch",
                                config=va1theme.PLOTLY_CONFIG)

    with col_alloc:
        with st.container(border=True):
            _alloc_rows = sorted(
                ((a, p.get("allocation") or 0.0)
                 for a, p in snapshot["positions"].items()),
                key=lambda t: t[1], reverse=True,
            )
            st.markdown(
                va1theme.panel_head(
                    "Allocation", right=va1theme.tag(f"{len(_alloc_rows)} lines")),
                unsafe_allow_html=True,
            )
            if not _alloc_rows:
                st.info("No asset yet.")
            else:
                # Bars, not a donut: past ~5 slices a pie stops being readable,
                # and here the weights line up as a scannable column.
                _bars = [
                    (a, w, va1theme.color_for_asset(a, i))
                    for i, (a, w) in enumerate(_alloc_rows)
                ]
                st.markdown(va1theme.alloc_bars(_bars), unsafe_allow_html=True)

    st.write("")

    # ---- Holdings ---------------------------------------------------------
    # The per-asset daily-return bar chart that used to sit here answered one
    # question with a whole panel. The holdings table answers it — the % Chg
    # column — plus weight, P&L, MTD, YTD and 12Mo, in the same space.
    render_holdings(show_footer=False)


# ============================================================================
# POSITIONS
# ============================================================================
with sub_positions:
    render_holdings(show_footer=True)



# ============================================================================
# ALLOCATION  — drift vs inception + stacked allocation evolution
# ============================================================================
with sub_allocation:
    if not data.ASSETS:
        st.info("This portfolio is empty. Go to **History → Transactions** to buy "
                "your first asset (an existing asset or New asset via its Yahoo ticker).")
    elif price_history.empty:
        st.info("No price history saved yet. Click Refresh & Save to record today.")
    else:
        # ---- 1) Drift vs Inception (point-in-time bar chart) -------------
        st.markdown(
            va1theme.section_head(
                "Allocation Drift vs Inception",
                "Percentage-point gap between current allocation and "
                "inception. Positive = overweight asset (trim it), negative = underweight."),
            unsafe_allow_html=True,
        )

        _drift_rows = [
            {
                "Asset": a,
                "Current": snapshot["positions"][a].get("allocation", 0.0) * 100.0,
                "Target": snapshot["positions"][a].get("target_allocation", 0.0) * 100.0,
                "Drift": snapshot["positions"][a].get("drift", 0.0) * 100.0,
            }
            for a in data.ASSETS
            if a in snapshot["positions"]
        ]
        if not _drift_rows:
            st.info("No position currently held (everything was sold — "
                    "the portfolio is now all cash).")
        else:
            drift_df = pd.DataFrame(_drift_rows).sort_values("Drift")

            fig_drift = go.Figure()
            fig_drift.add_bar(
                x=drift_df["Drift"],
                y=drift_df["Asset"],
                orientation="h",
                marker=dict(
                    color=[GREEN if v >= 0 else RED for v in drift_df["Drift"]],
                    line=dict(color=BG, width=1),
                ),
                customdata=drift_df[["Current", "Target"]].values,
                hovertemplate=(
                    "<b>%{y}</b><br>"
                    "Current : %{customdata[0]:.2f}%<br>"
                    "Target  : %{customdata[1]:.2f}%<br>"
                    "Drift   : %{x:+.2f} pts<extra></extra>"
                ),
                text=[f"{v:+.2f} pts" for v in drift_df["Drift"]],
                textposition="outside",
                textfont=dict(color=TEXT, size=11),
                cliponaxis=False,
            )
            fig_drift.add_vline(x=0, line=dict(color=MUTED, width=1, dash="dot"))
            style_fig(fig_drift, height=400, showlegend=False)
            # Pad x-range so outside labels stay inside the plot frame
            _lo = float(drift_df["Drift"].min())
            _hi = float(drift_df["Drift"].max())
            _span = max(abs(_lo), abs(_hi), 0.5)
            fig_drift.update_xaxes(title=None, ticksuffix=" pts",
                                    range=[_lo - _span * 0.30 - 1.0,
                                           _hi + _span * 0.30 + 1.0])
            fig_drift.update_yaxes(title=None)
            st.plotly_chart(fig_drift, width="stretch")

            # Drift summary KPIs
            max_drift = drift_df["Drift"].abs().max()
            total_abs = drift_df["Drift"].abs().sum()
            worst = drift_df.loc[drift_df["Drift"].abs().idxmax()]
            c1, c2, c3 = st.columns(3)
            c1.markdown(kpi("Max |drift|", f"{max_drift:+.2f} pts",
                            f"on {worst['Asset']}"),
                        unsafe_allow_html=True)
            c2.markdown(kpi("Σ |drift|", f"{total_abs:.2f} pts",
                            "sum of absolute gaps"),
                        unsafe_allow_html=True)
            c3.markdown(kpi("Inception date",
                            snapshot["inception_date"].strftime("%d %b %Y") if snapshot["inception_date"] else "—",
                            "target baseline"),
                        unsafe_allow_html=True)

        # ---- 2) Allocation evolution (stacked 100% area chart) ------------
        st.markdown(
            va1theme.section_head(
                "Allocation evolution (% of portfolio)",
                "Each band = % of NAV held by an ETF. Widening bands = "
                "Assets that outperformed."),
            unsafe_allow_html=True,
        )

        # Start at the effective inception (Settings date, else 1st transaction),
        # never earlier than the raw price history (and never past the last date).
        alloc_max = price_history["date"].max().date()
        alloc_min = min(max(price_history["date"].min().date(),
                            data.get_inception_date()), alloc_max)
        ca, cb, cc = st.columns([2, 2, 3])
        with ca:
            alloc_from = st.date_input("From", alloc_min, min_value=alloc_min,
                                       max_value=alloc_max, key="alloc_from")
        with cb:
            alloc_to = st.date_input("To", alloc_max, min_value=alloc_min,
                                     max_value=alloc_max, key="alloc_to")
        with cc:
            alloc_selected = st.multiselect(
                "Tickers", options=data.ASSETS, default=data.ASSETS, key="alloc_assets",
            )

        # V12: convert to portfolio currency first so per-asset values are
        # comparable when summed across currencies.
        _alloc_ph_pf = _augmented_pf(price_history)
        alloc_mask = (_alloc_ph_pf["date"] >= pd.Timestamp(alloc_from)) & (
            _alloc_ph_pf["date"] <= pd.Timestamp(alloc_to)
        )
        alloc_slice = _alloc_ph_pf.loc[alloc_mask].copy().reset_index(drop=True)

        # VA6 v2: time-varying shares (shares_held_as_of per row), not current
        # shares — so adding/selling assets later doesn't rewrite the past.
        _alloc_shares_at = [
            data.shares_held_as_of(d.date() if hasattr(d, "date") else d)
            for d in alloc_slice["date"]
        ]
        # Defensive: drop any duplicate columns and coerce each asset column to
        # numeric (non-numeric → NaN → 0) so an unexpected data shape can never
        # crash the whole page. Only assets present as a single column participate.
        alloc_slice = alloc_slice.loc[:, ~alloc_slice.columns.duplicated()]
        _alloc_assets = [a for a in data.ASSETS if a in alloc_slice.columns]
        for a in _alloc_assets:
            shares_col = pd.Series([h.get(a, 0) for h in _alloc_shares_at],
                                   index=alloc_slice.index)
            col = pd.to_numeric(alloc_slice[a], errors="coerce").fillna(0.0)
            alloc_slice[a] = col * shares_col
        if _alloc_assets:
            nav_series = alloc_slice[_alloc_assets].sum(axis=1)
            nav_series = nav_series.where(nav_series > 0, other=1.0)  # avoid /0
            for a in _alloc_assets:
                alloc_slice[a] = (alloc_slice[a] / nav_series) * 100.0

        fig_alloc = go.Figure()
        for idx, asset in enumerate(_alloc_assets):
            if asset not in alloc_selected:
                continue
            _c = va1theme.color_for_asset(asset, idx)
            fig_alloc.add_trace(
                go.Scatter(
                    x=alloc_slice["date"],
                    y=alloc_slice[asset],
                    name=asset,
                    mode="lines",
                    stackgroup="alloc",
                    groupnorm="percent",
                    line=dict(width=0.5, color=_c),
                    fillcolor=_c,
                    hovertemplate=(
                        f"<b>{asset}</b><br>%{{x|%d %b %Y}}<br>%{{y:.2f}}%<extra></extra>"
                    ),
                )
            )
        style_fig(fig_alloc, height=460, showlegend=True)
        # A 100%-stacked area fills the whole frame, so the default in-plot
        # legend printed the asset names ON TOP of the coloured bands. Move it
        # OUT, below the chart, with bottom room for both the legend rows and
        # the date axis.
        fig_alloc.update_layout(
            legend=dict(
                orientation="h", yanchor="top", y=-0.16,
                xanchor="center", x=0.5,
                font=dict(size=11), bgcolor="rgba(0,0,0,0)",
            ),
            margin=dict(l=56, r=24, t=16, b=96),
        )
        fig_alloc.update_yaxes(title="Allocation (%)", ticksuffix="%", range=[0, 100])
        fig_alloc.update_xaxes(rangebreaks=data.trading_day_rangebreaks(
            price_history, alloc_from, alloc_to))
        st.plotly_chart(fig_alloc, width="stretch", config=va1theme.PLOTLY_CONFIG)


# ============================================================================
# PRICE HISTORY
# ============================================================================
with sub_prices:
    if price_history.empty:
        st.info("No price history saved yet. Click Refresh & Save to record today.")
    else:
        # V12: convert every asset price from its native currency to the
        # portfolio currency via FX at each date, so charts & tables are
        # internally consistent and the labels (e.g. €) match the values.
        pf_ccy = data.current_portfolio_currency()
        pf_sym = data.CURRENCY_SYMBOL.get(pf_ccy, pf_ccy)
        price_history_pf = _augmented_pf(price_history)

        st.caption(
            "All prices come from Yahoo Finance (**adjusted close** — "
            "split- and dividend-adjusted total return). For a past date they "
            "won't match the raw market price shown elsewhere: the adjustment "
            "back-prices dividends, so older quotes sit below the nominal price."
        )

        # Start at the effective inception (Settings date, else 1st transaction).
        max_d = price_history_pf["date"].max().date()
        min_d = min(max(price_history_pf["date"].min().date(),
                        data.get_inception_date()), max_d)
        c1, c2, c3 = st.columns([2, 2, 3])
        with c1:
            start = st.date_input("From", min_d, min_value=min_d, max_value=max_d, key="ph_from")
        with c2:
            end = st.date_input("To", max_d, min_value=min_d, max_value=max_d, key="ph_to")
        with c3:
            selected = st.multiselect(
                "Tickers",
                options=held_assets,
                default=held_assets,
                key="ph_assets",
            )

        # Le graphe d'évolution des prix est TOUJOURS en base 100 (100 au début
        # de la fenêtre, par actif) : on compare des trajectoires de performance,
        # pas des niveaux de prix en devise. Pas d'option pour le désactiver.
        mask = (price_history_pf["date"] >= pd.Timestamp(start)) & (
            price_history_pf["date"] <= pd.Timestamp(end)
        )
        slice_df = price_history_pf.loc[mask].copy()

        fig = go.Figure()
        _slice_by_date = slice_df.set_index("date")
        for asset in selected:
            if asset not in slice_df.columns:
                continue
            # dropna() keeps only the dates this asset actually has a price on
            # (a freshly-added asset has data from its acquisition date onward,
            # not from the chart's start). Index = those real dates, so the line
            # starts where the asset's data starts instead of being misaligned
            # to the first N dates of the window.
            series = _slice_by_date[asset].dropna()
            if series.empty:
                continue
            x = series.index
            y = series.values
            y = (y / y[0]) * 100.0   # 100 at the asset's first available point
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=y,
                    mode="lines",
                    name=asset,
                    line=dict(
                        color=va1theme.color_for_asset(
                            asset,
                            data.ASSETS.index(asset) if asset in data.ASSETS else 0,
                        ),
                        width=2,
                    ),
                    hovertemplate=f"<b>{asset}</b><br>%{{x|%d %b %Y}}<br>%{{y:,.2f}} (base 100)<extra></extra>",
                )
            )
        style_fig(fig, height=520)
        fig.update_yaxes(title="Base 100 (100 = start of the window)")
        fig.update_xaxes(rangebreaks=data.trading_day_rangebreaks(
            price_history_pf, start, end))
        st.plotly_chart(fig, width="stretch")

        # ===================================================================
        # Daily history tables — fed by Refresh & Save + the 18:00 cron.
        # All three tables share the same date range filter as the chart.
        # Most recent date on top.
        # ===================================================================

        def _section_header(title: str, subtitle: str = "") -> None:
            # VA1 v3: delegate to the centralized section_head (accent bar + divider)
            st.markdown(va1theme.section_head(title, subtitle or None),
                        unsafe_allow_html=True)

        def _style_history(df: pd.DataFrame, fmt: dict, signed_cols: list[str] | None = None):
            signed_cols = signed_cols or []
            sty = (
                df.style.format(fmt, na_rep="—")
                .set_properties(**{"background-color": PANEL, "color": TEXT,
                                    "font-family": "monospace"})
                .set_table_styles(
                    [
                        {"selector": "th", "props": [("background-color", BG), ("color", MUTED),
                                                      ("font-weight", "600"),
                                                      ("text-transform", "uppercase"),
                                                      ("font-size", "11px"),
                                                      ("letter-spacing", "1px"),
                                                      ("border-bottom", f"1px solid {GRID}")]},
                        {"selector": "td", "props": [("border-bottom", f"1px solid {GRID}"),
                                                      ("padding", "8px 12px"),
                                                      ("text-align", "right")]},
                        {"selector": "td:first-child", "props": [("text-align", "left"),
                                                                  ("color", MUTED)]},
                    ]
                )
            )
            if signed_cols:
                sty = sty.map(color_signed, subset=signed_cols)
            return sty

        def color_signed(val):
            if pd.isna(val) or val == 0:
                return f"color: {TEXT}"
            return (f"color: {GREEN}; font-weight:600" if val > 0
                    else f"color: {RED}; font-weight:600")

        shares_map = static.shares

        # --- prep base frame (sorted DESC, formatted Date) ---
        base = slice_df.sort_values("date", ascending=False).reset_index(drop=True)

        # VA6 v2: pre-compute time-varying shares per date for the slice
        # (so adding / selling assets later doesn't pretend the new quantity
        # was held forever). One call per date returns shares for all assets.
        _shares_by_date_slice = [
            data.shares_held_as_of(d.date() if hasattr(d, "date") else d)
            for d in base["date"]
        ]
        # Cash balance per row — NAV = Σ assets + cash (a sale's proceeds sit in
        # cash, so they must be counted in NAV).
        _cash_by_date_slice = pd.Series([
            data.cash_balance_as_of(d.date() if hasattr(d, "date") else d)
            for d in base["date"]
        ])

        def _shares_col(asset: str, shares_list: list[dict]) -> pd.Series:
            return pd.Series([h.get(asset, 0) for h in shares_list])

        # ===================== Table 1: PRICES per ETF + Total NAV =====================
        _section_header(
            f"Daily prices per asset ({pf_sym})",
            f"Prices converted to {pf_ccy} at the day's rate. Total = portfolio NAV "
            f"(Σ price × shares held that day). Price history goes back at most 5 years "
            f"— deeper history is too heavy to load.",
        )
        prices_tbl = base.copy()
        # Currently-held assets only (a fully-sold asset is gone from this view).
        _total_series = pd.Series([0.0] * len(prices_tbl))
        for a in held_assets:
            _total_series = _total_series + (
                _num_col(prices_tbl, a)
                * _shares_col(a, _shares_by_date_slice)
            )
        prices_tbl["Cash"] = _cash_by_date_slice.values
        prices_tbl["Total"] = (_total_series + _cash_by_date_slice).values
        prices_tbl.insert(0, "Date", _date_labels(prices_tbl))
        prices_tbl = prices_tbl.drop(columns=["date"])
        prices_tbl = prices_tbl[["Date", *held_assets, "Cash", "Total"]]
        fmt = {a: f"{{:,.4f}} {pf_sym}" for a in held_assets}
        fmt["Cash"] = f"{{:,.2f}} {pf_sym}"
        fmt["Total"] = f"{{:,.2f}} {pf_sym}"
        st.dataframe(_style_history(prices_tbl, fmt), width="stretch", hide_index=True)

        # ===================== Table 2: POSITION VALUES per ETF + Total NAV =====================
        _section_header(
            f"Daily position value per asset ({pf_sym})",
            "Price × shares held on that date (time-varying). Total = portfolio NAV.",
        )
        pos_tbl = base.copy().reset_index(drop=True)
        for a in held_assets:
            pos_tbl[a] = (
                _num_col(pos_tbl, a)
                * _shares_col(a, _shares_by_date_slice)
            )
        pos_tbl["Cash"] = _cash_by_date_slice.values
        pos_tbl["Total"] = pos_tbl[held_assets].sum(axis=1).values + _cash_by_date_slice.values
        pos_tbl.insert(0, "Date", _date_labels(pos_tbl))
        pos_tbl = pos_tbl.drop(columns=["date"])
        pos_tbl = pos_tbl[["Date", *held_assets, "Cash", "Total"]]
        fmt2 = {a: f"{{:,.2f}} {pf_sym}" for a in held_assets}
        fmt2["Cash"] = f"{{:,.2f}} {pf_sym}"
        fmt2["Total"] = f"{{:,.2f}} {pf_sym}"
        st.dataframe(_style_history(pos_tbl, fmt2), width="stretch", hide_index=True)

        # ===================== Table 3: NAV (raw + VL base 100 + daily change) =====================
        _section_header(
            "Portfolio NAV history",
            f"Raw ({pf_sym}), unit value (base 100 at inception), daily change.",
        )
        # VA6 v2: NAV uses time-varying shares per date too (build from full ph)
        nav_full = price_history_pf.copy().sort_values("date").reset_index(drop=True)
        _shares_by_date_full = [
            data.shares_held_as_of(d.date() if hasattr(d, "date") else d)
            for d in nav_full["date"]
        ]
        _nav_series = pd.Series([0.0] * len(nav_full))
        for a in data.ASSETS:
            _nav_series = _nav_series + (
                _num_col(nav_full, a)
                * _shares_col(a, _shares_by_date_full)
            )
        _cash_by_date_full = pd.Series([
            data.cash_balance_as_of(d.date() if hasattr(d, "date") else d)
            for d in nav_full["date"]
        ])
        nav_full["Cash"] = _cash_by_date_full.values
        nav_full["NAV"] = (_nav_series + _cash_by_date_full).values   # NAV = Σ actifs + cash
        # VA6 v2 fix: VL must come from the UNITIZED series (compute_vl_series),
        # NOT from a naive NAV/inception_NAV ratio. The naive ratio jumps on
        # every flow (deposit / new buy / withdraw) — which is exactly the bug
        # the unitized VL exists to prevent.
        # VL from the PURE close history (unique dates) — never the augmented
        # frame (its duplicate buy/close dates would corrupt the unitization).
        _vl_proper = data.compute_vl_series(price_history)
        if not _vl_proper.empty:
            _vl_map = dict(zip(_vl_proper["date"], _vl_proper["vl"]))
            nav_full["VL"] = nav_full["date"].map(_vl_map)
            # Forward-fill in case the source price_history_pf and the vl_series
            # have a tiny date misalignment (shouldn't, but safe).
            nav_full["VL"] = nav_full["VL"].ffill().bfill()
        else:
            nav_full["VL"] = 100.0
        # Daily Change = VL pct_change so it reflects PERF (not flows).
        # Δ € = NAV diff so it remains intuitive ("how much did my pocket value
        # change €-wise" — includes both perf and deposits).
        nav_full["Daily Change"] = nav_full["VL"].pct_change()
        nav_full["Δ €"] = nav_full["NAV"].diff()

        # Filter to selected range, descending
        nav_view = nav_full[
            (nav_full["date"] >= pd.Timestamp(start)) &
            (nav_full["date"] <= pd.Timestamp(end))
        ].sort_values("date", ascending=False).reset_index(drop=True)
        nav_view.insert(0, "Date", _date_labels(nav_view))
        delta_col = f"Δ {pf_sym}"
        nav_view = nav_view.rename(columns={"Δ €": delta_col, "VL": "Unit value"})
        nav_view = nav_view[["Date", "NAV", "Cash", "Unit value", delta_col, "Daily Change"]]
        fmt3 = {
            "NAV": f"{{:,.2f}} {pf_sym}",
            "Cash": f"{{:,.2f}} {pf_sym}",
            "Unit value": "{:,.4f}",
            delta_col: f"{{:+,.2f}} {pf_sym}",
            "Daily Change": "{:+.2%}",
        }
        st.dataframe(
            _style_history(nav_view, fmt3, signed_cols=[delta_col, "Daily Change"]),
            width="stretch",
            hide_index=True,
        )

        # ===================================================================
        # VA2 — Multi-currency detail (per asset: native | FX | converted)
        # Self-verification table for assets whose native ccy ≠ pf_ccy.
        # ===================================================================
        _fx_assets = [
            a for a in held_assets
            if (static.currencies.get(a) or pf_ccy).upper() != pf_ccy.upper()
        ]
        if _fx_assets:
            _section_header(
                "Multi-currency detail",
                f"native × exchange rate = converted to {pf_ccy}. "
                f"Pick an asset to check the day-by-day calculation.",
            )
            mc_col1, _ = st.columns([2, 6])
            with mc_col1:
                mc_asset = st.selectbox(
                    "Asset", _fx_assets, key="ph_multi_ccy_asset",
                )
            mc_native_ccy = (static.currencies.get(mc_asset) or pf_ccy).upper()
            mc_native_sym = data.CURRENCY_SYMBOL.get(mc_native_ccy, mc_native_ccy)
            # Use the NATIVE-currency price_history (avoid the conversion
            # helper that's already applied to slice_df). Pull from db.
            ph_native = data.load_price_history(full=False)
            mc_mask = (ph_native["date"] >= pd.Timestamp(start)) & (
                ph_native["date"] <= pd.Timestamp(end))
            mc_slice = ph_native.loc[mc_mask, ["date", mc_asset]].dropna(subset=[mc_asset])
            mc_slice = mc_slice.sort_values("date", ascending=False).reset_index(drop=True)
            # Compute FX rate per row + converted price
            if not mc_slice.empty:
                _rates = mc_slice["date"].apply(
                    lambda ts: data.fx_rate(
                        mc_native_ccy, pf_ccy,
                        ts.date() if hasattr(ts, "date") else ts,
                    )
                ).astype(float)
                mc_view = pd.DataFrame({
                    "Date": mc_slice["date"].dt.strftime("%a %d %b %Y"),
                    f"Native price ({mc_native_ccy})":
                        mc_slice[mc_asset].astype(float).values,
                    f"FX {mc_native_ccy}→{pf_ccy}": _rates.values,
                    f"Converted price ({pf_ccy})":
                        mc_slice[mc_asset].astype(float).values * _rates.values,
                })
                mc_fmt = {
                    f"Native price ({mc_native_ccy})":
                        f"{{:,.4f}} {mc_native_sym}",
                    f"FX {mc_native_ccy}→{pf_ccy}": "{:,.6f}",
                    f"Converted price ({pf_ccy})":
                        f"{{:,.4f}} {pf_sym}",
                }
                st.dataframe(
                    _style_history(mc_view, mc_fmt),
                    width="stretch", hide_index=True,
                )
            else:
                st.info(f"No native prices recorded for {mc_asset} "
                        f"over the selected period.")


# ============================================================================
# TRANSACTIONS
# ============================================================================
with sub_tx:
    # ---- New transaction form ----
    st.markdown(
        va1theme.section_head(
            "New transaction",
            "Buy · sell · deposit · withdrawal — every view recalculates automatically"),
        unsafe_allow_html=True,
    )

    # Price history is capped at 5 years, so the trade-date picker is blocked to
    # the last 5 years (day-for-day, recomputed every run → always exactly 5y back).
    _min_tx_date = dt.date.today() - prices.MAX_HISTORY
    st.warning(
        f"**Price history is limited to the last 5 years.** Trade dates before "
        f"**{_min_tx_date.strftime('%d %b %Y')}** are disabled — an older date "
        f"can't load prices from before the 5-year cutoff.")

    NEW_ETF_LABEL = "New asset…"
    TX_TYPES = ["Buy (BUY)", "Sell (SELL)", "Cash deposit", "Cash withdrawal"]
    # NB: deliberately NOT a st.form — we want the Type/Asset selectboxes to
    # trigger a rerun so the right fields appear immediately.
    r1c1, r1c2, r1c3 = st.columns(3)
    with r1c1:
        tx_date = st.date_input("Date", dt.date.today(),
                                min_value=_min_tx_date, max_value=dt.date.today(),
                                key="ntx_date")
    with r1c2:
        tx_side = st.selectbox("Type", TX_TYPES, key="ntx_side")

    is_deposit = tx_side == "Cash deposit"
    is_withdraw = tx_side == "Cash withdrawal"
    is_cash = is_deposit or is_withdraw

    asset_choice = None
    is_new = False
    new_name = new_isin = new_ticker = new_fund = new_geo_raw = ""
    new_fees = 0.0

    if not is_cash:
        with r1c3:
            asset_choice = st.selectbox("Asset", [*held_assets, NEW_ETF_LABEL], key="ntx_asset")
        is_new = asset_choice == NEW_ETF_LABEL
        if is_new:
            st.markdown(
                f"<div style='color:{ACCENT};font-size:11px;margin-bottom:2px'>"
                f"New asset — any stock or ETF. "
                f"Just its <b>name</b> and its <b>Yahoo Finance ticker</b> "
                f"(e.g. AAPL, MC.PA, PSP5.PA). ISIN, sector and country "
                f"are fetched automatically from Yahoo when available.</div>",
                unsafe_allow_html=True,
            )
            n1, n2, n3, n4, n5 = st.columns([3, 2, 2, 2, 2])
            with n1:
                new_name = st.text_input("Name (required)",
                                         placeholder="e.g. Apple, LVMH, Bitcoin…",
                                         key="ntx_newname")
            with n2:
                new_ticker = st.text_input("Yahoo ticker (required)",
                                           placeholder="e.g. AAPL, MC.PA",
                                           key="ntx_newticker")
            with n3:
                _pf_ccy_default = data.current_portfolio_currency()
                _ccy_options = data.COMMON_CURRENCIES.copy()
                if _pf_ccy_default in _ccy_options:
                    _ccy_options.remove(_pf_ccy_default)
                    _ccy_options.insert(0, _pf_ccy_default)
                new_currency = st.selectbox(
                    "Currency", options=_ccy_options, index=0,
                    key="ntx_newccy",
                    help="Asset's quotation currency. AAPL=USD, MC.PA=EUR, etc. "
                         "Auto-detected from Yahoo if left at default."
                )
            with n4:
                new_isin = st.text_input("ISIN (required)",
                                         placeholder="e.g. FR0011871128",
                                         key="ntx_newisin",
                                         help="Mandatory. The sector/geo "
                                              "exposure is sourced only from the "
                                              "official factsheet located by ISIN "
                                              "(JustETF → issuer PDF) — never Yahoo.")
            with n5:
                new_fees = st.number_input("Fees (% per year)", min_value=0.0,
                                           max_value=5.0, value=0.0, step=0.01,
                                           format="%.2f", key="ntx_newfees")
            new_fund = ""  # auto-filled from yfinance.info
            new_geo_raw = st.text_input(
                "Geographic exposure — optional",
                placeholder="e.g. United States: 60%, Europe: 30%, Japan: 10%",
                key="ntx_newgeo",
                help="Leave EMPTY to auto-detect the geography from the ISIN "
                     "factsheet. Fill this ONLY if you are certain of the "
                     "breakdown — it overrides the automatic geography (the "
                     "sector stays automatic). Format: Country: %, Country: %")
    else:
        with r1c3:
            st.markdown(
                f"<div style='color:{MUTED};font-size:11px;letter-spacing:1px;"
                f"text-transform:uppercase;margin-bottom:4px'>Available cash</div>"
                f"<div style='font-size:18px;font-weight:600;color:{TEXT};"
                f"font-variant-numeric:tabular-nums;margin-top:6px'>"
                f"{euro(data.cash_balance_as_of(dt.date.today()))}</div>",
                unsafe_allow_html=True,
            )

    tx_price = tx_shares = 0.0
    cash_amount = 0.0
    tx_currency = data.current_portfolio_currency()
    if is_cash:
        cc1, cc2 = st.columns([1, 2])
        with cc1:
            cash_amount = st.number_input(
                f"Amount ({data.CURRENCY_SYMBOL.get(tx_currency, tx_currency)})",
                min_value=0.0, value=0.0,
                step=100.0, format="%.2f", key="ntx_cash_amount",
            )
    else:
        # V12: per-transaction currency. Default = the asset's registered currency
        # (for an existing asset) or the new-asset's selected currency. The cash
        # amount is converted via FX(tx_ccy → pf_ccy, tx_date) by _cash_walk.
        pf_ccy = data.current_portfolio_currency()
        if is_new:
            default_tx_ccy = (new_currency or pf_ccy).upper()
        else:
            default_tx_ccy = (static.currencies.get(asset_choice) or pf_ccy).upper()
        _tx_ccy_options = data.COMMON_CURRENCIES.copy()
        if default_tx_ccy in _tx_ccy_options:
            _tx_ccy_options.remove(default_tx_ccy)
            _tx_ccy_options.insert(0, default_tx_ccy)
        # Manual price entry is allowed ONLY when the transaction is dated today.
        # For any past (or future) date the price MUST come from the automatic
        # Yahoo adjusted-close fetch, so a back-test transaction can never be
        # booked at an arbitrary hand-typed price that diverges from the price
        # series driving the NAV/VL. (Today is fine: the live close may not be
        # saved yet, and the user knows the real-time price they're trading at.)
        _is_today = (tx_date == dt.date.today())
        if "ntx_manual_price" not in st.session_state:
            st.session_state.ntx_manual_price = False
        if _is_today:
            r1d = st.columns([2, 6])
            with r1d[0]:
                tx_manual = st.checkbox(
                    "Enter price manually",
                    value=st.session_state.ntx_manual_price,
                    key="ntx_manual_price",
                    help="Uncheck to use Yahoo's adjusted close for the selected "
                         "date. Check to enter a different price (OTC, limit "
                         "price, etc.). Only available for a transaction dated "
                         "today.",
                )
        else:
            # Past/future date → force automatic price, ignore any sticky toggle.
            tx_manual = False
            st.caption(
                "Past date — price is fetched automatically (Yahoo adjusted "
                "close). Manual entry is only available for a transaction dated "
                "today."
            )

        # Determine auto-fetched price for the (asset, date) pair if not manual.
        # Existing asset → DB cache / Yahoo via data.price_on_date.
        # Brand-new asset → adjusted close on that date straight from the
        # entered Yahoo ticker (so the price auto-fills before the asset is
        # even registered). Falls back to manual entry if the ticker has no
        # data (e.g. a non-public name like SpaceX).
        _auto_price = None
        _auto_source = None
        _target_asset = None
        if not is_cash and not is_new:
            _target_asset = asset_choice
        if not is_cash and not tx_manual:
            if _target_asset:
                try:
                    _auto_price, _auto_source = data.price_on_date(_target_asset, tx_date)
                except Exception:
                    _auto_price, _auto_source = None, "error"
            elif is_new and new_ticker.strip():
                try:
                    _p = _auto_price_for_new_ticker(new_ticker.strip(), tx_date)
                except Exception:
                    _p = None
                if _p is not None:
                    _auto_price, _auto_source = _p, "yahoo_fetch"

        r2c1, r2c2, r2c3, r2c4 = st.columns([2, 2, 1, 2])
        with r2c1:
            if (not tx_manual) and _auto_price is not None:
                tx_price = float(_auto_price)
                # Read-only display
                _src_label = {
                    "db_cache": "DB cache",
                    "yahoo_fetch": "Yahoo · fetched",
                    "fallback_prev_close": "≈ prev close",
                    "not_found": "—",
                    "error": "error",
                }.get(_auto_source or "—", _auto_source or "—")
                st.markdown(
                    f"<div style='color:{MUTED};font-size:11px;letter-spacing:.06em;"
                    f"text-transform:uppercase;margin-bottom:6px;font-weight:500'>"
                    f"Unit price <span style='color:{ACCENT};font-size:9px;"
                    f"padding:2px 6px;border-radius:3px;background:var(--accent-tint);"
                    f"border:1px solid var(--accent-border);margin-left:6px'>"
                    f"AUTO · {_src_label}</span></div>"
                    f"<div style='font-family:JetBrains Mono,monospace;font-size:18px;"
                    f"font-weight:500;padding:9px 12px;background:{PANEL};"
                    f"border:1px solid {GRID};border-radius:6px;"
                    f"font-variant-numeric:tabular-nums;color:{TEXT}'>"
                    f"{tx_price:,.4f}</div>",
                    unsafe_allow_html=True,
                )
            elif (not tx_manual) and _target_asset and _auto_price is None:
                tx_price = 0.0
                _no_price_hint = ("Try another date." if not _is_today
                                  else "Check “Enter price manually” or change the date.")
                st.markdown(
                    f"<div style='color:{MUTED};font-size:11px;letter-spacing:.06em;"
                    f"text-transform:uppercase;margin-bottom:6px;font-weight:500'>"
                    f"Unit price</div>"
                    f"<div style='font-family:JetBrains Mono,monospace;font-size:14px;"
                    f"padding:9px 12px;background:{PANEL};"
                    f"border:1px solid {RED};border-radius:6px;color:{RED}'>"
                    f"No price available. {_no_price_hint}</div>",
                    unsafe_allow_html=True,
                )
            else:
                tx_price = st.number_input(
                    "Unit price", min_value=0.0, value=0.0,
                    step=0.01, format="%.4f", key="ntx_price",
                )
        with r2c2:
            tx_shares = st.number_input("Shares", min_value=0.0, value=0.0,
                                        step=1.0, format="%.4f", key="ntx_shares")
        with r2c3:
            tx_currency = st.selectbox(
                "Tx currency", options=_tx_ccy_options, index=0, key="ntx_currency",
                help="Currency the price is expressed in (= the currency debited "
                     "from your cash account). Automatically converted to the "
                     "portfolio currency at the transaction-day exchange rate.",
            )
        with r2c4:
            native_total = tx_price * tx_shares
            tx_sym = data.CURRENCY_SYMBOL.get(tx_currency, tx_currency)
            pf_sym = data.CURRENCY_SYMBOL.get(pf_ccy, pf_ccy)
            if tx_currency == pf_ccy or native_total == 0:
                total_str = f"{native_total:,.2f} {pf_sym}"
                fx_note = ""
            else:
                try:
                    rate = data.fx_rate(tx_currency, pf_ccy, tx_date)
                    pf_total = native_total * rate
                    total_str = f"{pf_total:,.2f} {pf_sym}"
                    fx_note = (f"<div style='color:{MUTED};font-size:10px'>"
                               f"{native_total:,.2f} {tx_sym} × {rate:.4f}</div>")
                except Exception:
                    total_str = f"{native_total:,.2f} {tx_sym}"
                    fx_note = (f"<div style='color:{MUTED};font-size:10px'>"
                               f"FX unavailable</div>")
            st.markdown(
                f"<div style='color:{MUTED};font-size:11px;letter-spacing:1px;"
                f"text-transform:uppercase;margin-bottom:4px'>Total ({pf_ccy})</div>"
                f"<div style='font-size:22px;font-weight:600;color:{TEXT};"
                f"font-variant-numeric:tabular-nums'>{total_str}</div>"
                f"{fx_note}",
                unsafe_allow_html=True,
            )

    if st.button("✓ Save transaction", type="primary", key="ntx_submit"):
        try:
            if is_cash:
                kind = "DEPOSIT" if is_deposit else "WITHDRAW"
                if cash_amount <= 0:
                    st.error("Amount must be > 0.")
                else:
                    res = data.add_cash_movement(tx_date, kind, cash_amount)
                    _refresh_excel_cache()
                    label = "Deposit" if kind == "DEPOSIT" else "Withdrawal"
                    st.success(f"✓ {label} of {euro(res['amount'])} · "
                               f"available cash: {euro(res['cash_after'])}")
                    st.rerun()
            else:
                side = "BUY" if tx_side.startswith("Buy") else "SELL"
                # Hard guard: a past/future-dated transaction must use the
                # automatic price — never a hand-typed one (keeps the booked
                # price on the same adjusted basis as the price series).
                if (not _is_today) and tx_manual:
                    st.error("Manual price is only allowed for a transaction "
                             "dated today. Use the automatic price for a past date.")
                elif tx_shares <= 0 or tx_price <= 0:
                    if (not _is_today):
                        st.error("No automatic price available for this past "
                                 "date — pick another date.")
                    else:
                        st.error("Price and shares must both be > 0.")
                elif is_new:
                    if not (new_name.strip() and new_ticker.strip()):
                        st.error("Name and Yahoo ticker are required.")
                    elif not new_isin.strip():
                        st.error("ISIN is required for a new asset — the "
                                 "sector/geo exposure is sourced from the "
                                 "official factsheet located by ISIN.")
                    elif side == "SELL":
                        st.error("A new asset cannot start with a sell.")
                    else:
                        import compositions_scraper as _cs
                        name = new_name.strip()
                        ticker = new_ticker.strip()
                        isin = new_isin.strip()          # mandatory (user-entered)
                        # Yahoo is used ONLY for price metadata (fund name /
                        # quotation currency), never for sector/geo.
                        with st.spinner("Auto-fetching price metadata…"):
                            info = _cs.lookup_yfinance_info(ticker)
                        fund = info.get("fund") or "—"
                        auto_ccy = (info.get("currency") or "").upper().strip()
                        currency = auto_ccy or new_currency
                        data.register_asset(name, isin, ticker,
                                            fund=fund, fees=new_fees / 100.0,
                                            currency=currency)
                        res = data.add_transaction(tx_date, name, side,
                                                   tx_price, tx_shares, isin=isin,
                                                   currency=tx_currency)
                        # Optional manual geography: overrides the automatic one
                        # (sector stays auto). Persisted per-user in Postgres so it
                        # survives a Cloud reboot (the JSON file is ephemeral there).
                        manual_geo = _cs._parse_geo_input(new_geo_raw)
                        # Sector/geo: fund → official factsheet by ISIN;
                        # a stock (no fund factsheet) → its sector + country
                        # resolved live from its listing.
                        scrape_msg = ""
                        try:
                            with st.spinner("Fetching sector/geo from the ISIN factsheet…"):
                                r = _cs.seed_from_isin(name, isin, ticker=ticker,
                                                       issuer=fund if fund != "—" else "",
                                                       manual_geo=manual_geo)
                            if manual_geo:
                                scrape_msg = " · geography set manually · sector auto"
                            elif r.get("status") == "ok":
                                scrape_msg = " · sector/geo fetched from ISIN factsheet"
                            else:
                                scrape_msg = (" · no fund factsheet — sector/geo will "
                                              "use the asset's listing (single stock)")
                        except Exception:
                            scrape_msg = ""
                        if manual_geo and hasattr(data, "set_manual_geo"):
                            try:
                                data.set_manual_geo(name, manual_geo)
                            except Exception:
                                pass
                        _refresh_excel_cache()
                        bf = f" · +{res['backfilled_days']}d of prices backfilled" if res.get("backfilled_days") else ""
                        st.success(f"✓ {name} created ({ticker}) + {res['type']} "
                                   f"{res['shares']:g} @ {euro(res['price'])} = {euro(res['amount'])}{scrape_msg}{bf}")
                        st.rerun()
                else:
                    isin = static.isins.get(asset_choice)
                    res = data.add_transaction(tx_date, asset_choice, side,
                                               tx_price, tx_shares, isin=isin,
                                               currency=tx_currency)
                    _refresh_excel_cache()
                    msg = (f"✓ {res['type']} {res['shares']:g} {asset_choice} @ "
                           f"{euro(res['price'])} = {euro(res['amount'])} · "
                           f"shares held: {res['new_holding']:g}")
                    if side == "SELL":
                        msg += f" · available cash: {euro(data.cash_balance_as_of(dt.date.today()))}"
                    if res.get("backfilled_days"):
                        msg += f" · +{res['backfilled_days']} days of prices backfilled"
                    st.success(msg)
                    st.rerun()
        except ValueError as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(f"Error: {exc}")

    # ---- History ----
    st.markdown(
        va1theme.section_head("Transaction history",
                                "Filter by asset or search by ISIN"),
        unsafe_allow_html=True,
    )
    if transactions_df.empty:
        st.info("No transaction recorded yet.")
    else:
        c1, c2 = st.columns([3, 1])
        with c1:
            q = st.text_input("Search (asset, ISIN)", "", key="tx_q").strip().lower()
        with c2:
            assets_filter = st.multiselect(
                "Asset", options=sorted(transactions_df["Asset"].dropna().unique().tolist()),
                key="tx_assets",
            )

        view = transactions_df.copy()
        if q:
            view = view[
                view["Asset"].fillna("").str.lower().str.contains(q)
                | view["ISIN"].fillna("").astype(str).str.lower().str.contains(q)
            ]
        if assets_filter:
            view = view[view["Asset"].isin(assets_filter)]

        # V12: convert each row's native Total to portfolio currency via FX
        # at its own trade date. Keep Price in its native currency for clarity
        # ("I bought at $78.42") but tag the row with the native currency.
        pf_ccy_tx = data.current_portfolio_currency()
        pf_sym_tx = data.CURRENCY_SYMBOL.get(pf_ccy_tx, pf_ccy_tx)

        def _row_fx(row):
            ccy = (row.get("Currency") or pf_ccy_tx).upper()
            if ccy == pf_ccy_tx:
                return 1.0
            try:
                return float(data.fx_rate(ccy, pf_ccy_tx, row["Date"].date()))
            except Exception:
                return 1.0

        view = view.copy()
        view["_fx"] = view.apply(_row_fx, axis=1)
        view[f"Total ({pf_ccy_tx})"] = view["Total"].astype(float) * view["_fx"]

        view_display = view.copy()
        view_display["Date"] = view_display["Date"].dt.strftime("%d %b %Y")
        # Format Price with native currency symbol per row
        view_display["Price"] = view_display.apply(
            lambda r: (f"{r['Price']:,.4f} "
                       f"{data.CURRENCY_SYMBOL.get((r.get('Currency') or pf_ccy_tx).upper(), r.get('Currency') or '')}")
            if pd.notna(r["Price"]) else "—",
            axis=1,
        )
        # Realized return shown ON each SELL line (— for buys / cash moves):
        # the return of the sold shares vs the weighted-average cost.
        # Two returns per SELL line:
        #   Réalisé = sell price / weighted-avg cost − 1   (the gain you locked in)
        #   Marché  = current price / same cost − 1         (where the asset is TODAY)
        # Same denominator → directly comparable: Marché > Réalisé ⇒ sold too early.
        _sell_realized: dict[int, float] = {}
        _sell_market: dict[int, float] = {}
        _live_now = st.session_state.get("live_prices", {})
        _sfn = getattr(data, "sell_pnl_rows", None)
        if _sfn:
            for s in _sfn():
                if s.get("id") is None:
                    continue
                sid = int(s["id"])
                if s.get("return_pct") is not None:
                    _sell_realized[sid] = s["return_pct"]
                ac, cur = s.get("avg_cost"), _live_now.get(s["asset"])
                if ac and cur:
                    _sell_market[sid] = cur / ac - 1.0

        def _ret_cell(r, table):
            if str(r["Type"]) != "SELL" or not pd.notna(r.get("Id")):
                return "—"
            v = table.get(int(r["Id"]))
            return f"{v * 100:+.2f} %" if v is not None else "—"

        view_display["Realized return"] = view_display.apply(lambda r: _ret_cell(r, _sell_realized), axis=1)
        view_display["Market return (today)"] = view_display.apply(lambda r: _ret_cell(r, _sell_market), axis=1)
        # Yahoo ticker per asset (— for cash moves / unknown). Resolve defensively
        # so a backend without TICKER_BY_ASSET can't crash the table.
        _ticker_by_asset = getattr(data, "TICKER_BY_ASSET", {}) or {}
        view_display["Ticker"] = view_display["Asset"].map(
            lambda a: (_ticker_by_asset.get(a) or "—") if a else "—")
        view_display = view_display[[
            "Date", "Asset", "Ticker", "ISIN", "Type", "Price", "Shares",
            "Currency", f"Total ({pf_ccy_tx})", "Realized return", "Market return (today)",
        ]]

        def _color_side(val):
            if val == "BUY":
                return f"color: {GREEN}; font-weight:600"
            if val == "SELL":
                return f"color: {RED}; font-weight:600"
            return f"color: {TEXT}"

        styled_tx = (
            view_display.style.format({
                "Shares": "{:g}",
                f"Total ({pf_ccy_tx})": f"{{:,.2f}} {pf_sym_tx}",
            }, na_rep="—")
            .map(_color_side, subset=["Type"])
            .set_properties(**{"background-color": PANEL, "color": TEXT, "font-family": "monospace"})
            .set_table_styles(
                [
                    {"selector": "th", "props": [("background-color", BG), ("color", MUTED),
                                                  ("font-weight", "600"), ("text-transform", "uppercase"),
                                                  ("font-size", "11px"), ("letter-spacing", "1px"),
                                                  ("border-bottom", f"1px solid {GRID}")]},
                    {"selector": "td", "props": [("border-bottom", f"1px solid {GRID}"), ("padding", "10px 14px")]},
                ]
            )
        )
        st.dataframe(styled_tx, width="stretch", hide_index=True)

        # KPIs in portfolio currency
        total_pf_col = view[f"Total ({pf_ccy_tx})"]
        buys = total_pf_col[view["Type"] == "BUY"].sum()
        sells = total_pf_col[view["Type"] == "SELL"].sum()
        def _money(v):
            return f"{v:,.2f} {pf_sym_tx}".replace(",", " ").replace(".", ",")
        c1, c2, c3, c4 = st.columns(4)
        c1.markdown(kpi("Σ Buys", _money(buys)), unsafe_allow_html=True)
        c2.markdown(kpi("Σ Sells", _money(sells)), unsafe_allow_html=True)
        # "Net investi" = real EXTERNAL capital put in (deposits − withdrawals,
        # incl. buy shortfalls), NOT Σachats − Σventes. The old formula subtracted
        # the FULL sale proceeds, so a sale at a profit counted the sold asset's
        # GAIN against your invested money — misleading. This now matches the
        # Overview header (snapshot["net_invested"]); reinvesting a sale's cash is
        # internal and leaves it unchanged — only fresh money in/out moves it.
        c3.markdown(kpi("Net invested", _money(snapshot["net_invested"])), unsafe_allow_html=True)
        c4.markdown(kpi("# Transactions", str(len(view))), unsafe_allow_html=True)

        # ---- Realized sells — P&L per sale (incl. partial sells) ----
        _sell_fn = getattr(data, "sell_pnl_rows", None)
        _sells = _sell_fn() if _sell_fn else []
        if _sells:
            st.markdown(
                va1theme.section_head(
                    "Realized sells — P&L",
                    "For each sale: realized return and P&L vs the weighted-average "
                    "cost at the sale date (partial sells included)."),
                unsafe_allow_html=True,
            )

            def _sym(c):
                return data.CURRENCY_SYMBOL.get(c, c)

            sell_tbl = pd.DataFrame([
                {
                    "Date": s["date"].strftime("%d %b %Y") if hasattr(s["date"], "strftime") else str(s["date"]),
                    "Asset": s["asset"],
                    "Shares sold": f"{s['shares']:g}",
                    "Sell price": f"{s['sell_price']:,.4f} {_sym(s['currency'])}",
                    "Avg cost": (f"{s['avg_cost']:,.4f} {_sym(s['currency'])}"
                                   if s["avg_cost"] is not None else "—"),
                    "Realized": (f"{s['return_pct'] * 100:+.2f} %"
                                if s["return_pct"] is not None else "—"),
                    "Market (today)": (
                        f"{(_live_now.get(s['asset']) / s['avg_cost'] - 1) * 100:+.2f} %"
                        if (s.get('avg_cost') and _live_now.get(s['asset'])) else "—"),
                    "Realized P&L": (f"{s['pnl']:+,.2f} {_sym(s['currency'])}"
                                    if s["pnl"] is not None else "—"),
                }
                for s in _sells
            ])
            st.dataframe(sell_tbl, width="stretch", hide_index=True)

        # ----------------------------------------------------------------
        # V15 — Delete a transaction (mistake recovery) — MOVED HERE
        # ----------------------------------------------------------------
        st.markdown(
            va1theme.section_head(
                "Delete a transaction",
                "Destructive action — tick the confirmation before deleting. "
                "Cash, shares and NAV recalculate automatically."),
            unsafe_allow_html=True,
        )

        def _tx_label(row) -> str:
            d = row["Date"].strftime("%d %b %Y") if pd.notna(row["Date"]) else "—"
            ccy = (row.get("Currency") or pf_ccy_tx).upper()
            sym = data.CURRENCY_SYMBOL.get(ccy, ccy)
            asset = row["Asset"] or "—"
            t = row["Type"]
            if t in ("DEPOSIT", "WITHDRAW"):
                return f"#{int(row['Id'])} · {d} · {t} · {float(row['Total']):,.2f} {sym}"
            shares_n = float(row["Shares"]) if pd.notna(row["Shares"]) else 0
            price_n = float(row["Price"]) if pd.notna(row["Price"]) else 0
            return (f"#{int(row['Id'])} · {d} · {asset} · {t} · "
                    f"{shares_n:g} × {price_n:,.4f} {sym}")

        view_for_select = view.sort_values("Date", ascending=False).reset_index(drop=True)
        if view_for_select.empty:
            st.info("No transaction to delete in the filtered view.")
        else:
            labels = [_tx_label(r) for _, r in view_for_select.iterrows()]
            id_by_label = dict(zip(labels, view_for_select["Id"].astype(int).tolist()))
            cdel1, cdel2, cdel3 = st.columns([5, 2, 2])
            with cdel1:
                chosen = st.selectbox("Transaction", labels, key="tx_del_sel",
                                       label_visibility="collapsed")
            with cdel2:
                confirm = st.checkbox("I confirm", key="tx_del_confirm",
                                       value=False)
            with cdel3:
                if st.button("✕ Delete", key="tx_del_btn",
                             type="primary", disabled=not confirm,
                             width="stretch"):
                    try:
                        res = data.delete_transaction(id_by_label[chosen])
                        if res["deleted"]:
                            _refresh_excel_cache()
                            st.success(f"Transaction #{res['id']} deleted. "
                                       f"Cash, shares and NAV recalculated.")
                            st.session_state.pop("tx_del_confirm", None)
                            st.rerun()
                        else:
                            st.warning(f"Transaction #{res['id']} not found "
                                       f"(already deleted?).")
                    except Exception as exc:
                        st.error(f"Error while deleting: {exc}")

    # ----------------------------------------------------------------
    # VA2 — Excel / CSV bulk import (with preview)
    # ----------------------------------------------------------------
    st.markdown(
        va1theme.section_head(
            "Bulk import (Excel / CSV)",
            "Upload a file, check the preview, then confirm. "
            "Columns: date, asset, type, shares, price (optional — "
            "auto-fetched otherwise), currency (optional), amount (for DEPOSIT/WITHDRAW)."),
        unsafe_allow_html=True,
    )

    imp_top_l, imp_top_r = st.columns([3, 1])
    with imp_top_l:
        uploaded = st.file_uploader(
            "File", type=["xlsx", "xls", "csv"],
            label_visibility="collapsed", key="tx_bulk_upload",
        )
    with imp_top_r:
        # Pre-filled .xlsx template download
        import io as _io
        try:
            import openpyxl as _oxl
            wb = _oxl.Workbook()
            ws = wb.active
            ws.title = "transactions"
            headers = ["date", "asset", "type", "shares", "price",
                       "currency", "amount"]
            ws.append(headers)
            # Pre-filled example rows
            ws.append(["2025-06-10", "Nvidia", "BUY", 1, 143.93, "USD", ""])
            ws.append(["2025-06-10", "Coca", "BUY", 1, 70.31, "USD", ""])
            ws.append(["2026-01-15", "Nvidia", "SELL", 0.5, "", "USD", ""])
            ws.append(["2026-02-01", "Cash", "DEPOSIT", "", "", "", 1000])
            ws.append(["2026-03-15", "Cash", "WITHDRAW", "", "", "", 200])
            buf = _io.BytesIO()
            wb.save(buf)
            tpl_bytes = buf.getvalue()
            st.download_button(
                "⤓ Template", data=tpl_bytes,
                file_name="gpcp_tx_template.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch", key="tx_bulk_tpl",
            )
        except Exception:
            st.button("⤓ Template (n/a)", disabled=True, width="stretch")

    if uploaded is not None:
        try:
            if uploaded.name.lower().endswith(".csv"):
                imp_df = pd.read_csv(uploaded)
            else:
                imp_df = pd.read_excel(uploaded)
        except Exception as _e:
            st.error(f"Could not read file: {_e}")
            imp_df = None

        if imp_df is not None and not imp_df.empty:
            # Normalize column names (case-insensitive) and accept FR aliases too
            colmap = {
                "date": "date", "actif": "asset", "asset": "asset",
                "type": "type", "shares": "shares", "titres": "shares",
                "price": "price", "prix": "price",
                "currency": "currency", "devise": "currency",
                "amount": "amount", "montant": "amount",
            }
            imp_df = imp_df.rename(
                columns={c: colmap.get(str(c).strip().lower(), c)
                          for c in imp_df.columns})
            # Ensure all columns exist
            for col in ["date", "asset", "type", "shares", "price",
                        "currency", "amount"]:
                if col not in imp_df.columns:
                    imp_df[col] = None
            imp_df = imp_df[["date", "asset", "type", "shares", "price",
                              "currency", "amount"]].copy()

            # Per-row validation
            def _validate(row):
                t = str(row.get("type") or "").strip().upper()
                try:
                    d = pd.to_datetime(row.get("date")).date()
                except Exception:
                    return "⚠ invalid date"
                if t in ("DEPOSIT", "WITHDRAW"):
                    try:
                        amt = float(row.get("amount") or 0)
                    except Exception:
                        amt = 0
                    if amt <= 0:
                        return "⚠ amount > 0 required"
                    return "✓ ok"
                if t in ("BUY", "SELL"):
                    asset = str(row.get("asset") or "").strip()
                    if asset not in data.ASSETS:
                        return f"⚠ unknown asset: {asset!r}"
                    try:
                        sh = float(row.get("shares") or 0)
                    except Exception:
                        sh = 0
                    if sh <= 0:
                        return "⚠ shares > 0 required"
                    return "✓ ok"
                return "⚠ invalid type"

            imp_df["status"] = imp_df.apply(_validate, axis=1)
            imp_df.insert(0, "import", imp_df["status"].str.startswith("✓"))

            st.markdown(
                f"<div style='color:{MUTED};font-size:12px;margin:14px 0 6px 0'>"
                f"<b style='color:{TEXT}'>{int(imp_df['import'].sum())}</b> "
                f"transaction(s) to import out of {len(imp_df)} row(s). "
                f"Uncheck the ones you don't want, or fix them in place."
                f"</div>",
                unsafe_allow_html=True,
            )
            edited = st.data_editor(
                imp_df,
                width="stretch",
                num_rows="dynamic",
                key="tx_bulk_editor",
                column_config={
                    "import": st.column_config.CheckboxColumn(
                        "Import", help="Check to include the row",
                        default=True,
                    ),
                    "status": st.column_config.TextColumn(
                        "Status", disabled=True),
                },
            )

            # Recompute status on edited rows
            edited["status"] = edited.apply(_validate, axis=1)
            n_ready = int(((edited["import"] == True)  # noqa: E712
                            & edited["status"].str.startswith("✓")).sum())

            bcol1, bcol2 = st.columns([1, 4])
            with bcol1:
                if st.button(
                    f"✓ Confirm and save ({n_ready})",
                    type="primary", disabled=(n_ready == 0),
                    key="tx_bulk_submit",
                ):
                    rows_to_insert = []
                    for _, r in edited.iterrows():
                        if not r.get("import"):
                            continue
                        if not str(r.get("status") or "").startswith("✓"):
                            continue
                        rows_to_insert.append({
                            "date": pd.to_datetime(r["date"]).date(),
                            "asset": str(r["asset"]).strip() if pd.notna(r["asset"]) else "",
                            "type": str(r["type"]).strip().upper(),
                            "shares": (float(r["shares"]) if pd.notna(r["shares"]) and r["shares"] != "" else None),
                            "price": (float(r["price"]) if pd.notna(r["price"]) and r["price"] != "" else None),
                            "currency": (str(r["currency"]).strip().upper() if pd.notna(r["currency"]) and r["currency"] != "" else None),
                            "amount": (float(r["amount"]) if pd.notna(r["amount"]) and r["amount"] != "" else None),
                        })
                    try:
                        res = data.add_transactions_bulk(rows_to_insert)
                        _refresh_excel_cache()
                        if res["errors"]:
                            st.warning(
                                f"✓ {res['inserted']} imported, "
                                f"{res['skipped']} failed: "
                                + " · ".join(f"#{e['row']+1} {e['reason']}"
                                              for e in res["errors"][:3])
                                + (f" (+{len(res['errors'])-3} more)"
                                   if len(res["errors"]) > 3 else "")
                            )
                        else:
                            st.success(
                                f"✓ {res['inserted']} transaction(s) "
                                f"saved. NAV and cash recalculated.")
                        st.rerun()
                    except Exception as _e:
                        st.error(f"Import failed: {_e}")
            with bcol2:
                if st.button("Reset", key="tx_bulk_reset"):
                    st.session_state.pop("tx_bulk_upload", None)
                    st.rerun()


# ============================================================================
# PRO — V2 advanced analytics
# ============================================================================
with tab_analytics:
    pro.render(
        static=static,
        price_history=price_history,
        snapshot=snapshot,
        palette=dict(BG=BG, PANEL=PANEL, GRID=GRID, TEXT=TEXT, MUTED=MUTED,
                     ACCENT=ACCENT, GREEN=GREEN, RED=RED),
    )


# ============================================================================
# SETTINGS
# ============================================================================
with tab_settings:
    if _DEMO:
        st.info("Demo mode — settings (transactions, prices, inception, "
                "portfolios) are disabled in read-only mode.")
        st.stop()
    st.markdown(
        va1theme.section_head(
            "Portfolio start date (inception)",
            "Reference point for all performance: unit value = 100 on this date. "
            "Changing this date re-adjusts EVERYTHING."),
        unsafe_allow_html=True,
    )

    current_inception = data.get_inception_date()
    default_inception = data.default_inception_date()

    # Robust bounds: include price history AND transaction dates AND today, so
    # the current inception value is always inside the allowed range (avoids
    # Streamlit's "default value must lie between min and max" crash when the
    # earliest transaction predates any saved price).
    ph_all = data.load_price_history(full=True)
    ph_min = ph_all["date"].min().date() if not ph_all.empty else None
    ph_max = ph_all["date"].max().date() if not ph_all.empty else None
    candidates_lo = [d for d in (current_inception, default_inception, ph_min) if d]
    candidates_hi = [d for d in (current_inception, ph_max, dt.date.today()) if d]
    min_d = min(candidates_lo)
    max_d = max(candidates_hi)
    if ph_min is None or ph_max is None:
        sessions_label = "no price saved"
    else:
        sessions_label = f"from {ph_min.strftime('%d %b %Y')} to {ph_max.strftime('%d %b %Y')}"

    c1, c2 = st.columns([1, 2])
    with c1:
        chosen = st.date_input(
            "Inception date",
            value=current_inception,
            min_value=min_d, max_value=max_d,
            key="settings_inception",
        )
    with c2:
        st.markdown(
            f"<div style='background:{PANEL};border:1px solid {GRID};border-radius:10px;"
            f"padding:12px 16px;font-size:12px;color:{MUTED}'>"
            f"Current: <b style='color:{TEXT}'>{current_inception.strftime('%d %b %Y')}</b><br>"
            f"Default (1st transaction): <b style='color:{TEXT}'>{default_inception.strftime('%d %b %Y')}</b><br>"
            f"Available sessions: {sessions_label}"
            f"</div>",
            unsafe_allow_html=True,
        )

    b1, b2, b3, b4 = st.columns([1, 1, 2, 2])
    with b1:
        if st.button("✓ Apply", type="primary", key="settings_apply"):
            data.set_inception_date(chosen)
            _refresh_excel_cache()
            st.success(f"Inception date → {chosen.strftime('%d %b %Y')}. Everything recalculated.")
            st.rerun()
    with b2:
        if st.button("↺ Reset", key="settings_reset"):
            data.set_inception_date(default_inception)
            _refresh_excel_cache()
            st.success(f"Inception date reset → {default_inception.strftime('%d %b %Y')}.")
            st.rerun()
    with b3:
        if st.button("⤓ Backfill missing prices",
                     key="settings_backfill",
                     help="Fetch from Yahoo every missing daily price between the "
                          "inception date and today, for each asset in the "
                          "portfolio. Useful after changing the inception date or "
                          "for a portfolio created before auto-backfill."):
            with st.spinner("Fetching missing prices from Yahoo…"):
                try:
                    res = data.backfill_all_assets_to_inception()
                except Exception as exc:
                    st.error(f"Backfill failed: {exc}")
                    res = None
            if res is not None:
                if res:
                    total = sum(res.values())
                    detail = ", ".join(f"{a} +{n}d" for a, n in res.items())
                    st.success(f"✓ {total} prices imported ({detail}).")
                else:
                    st.info("All prices are already up to date, nothing to import.")
                _refresh_excel_cache()
                st.session_state.pop("live_prices", None)   # re-read each asset's last close
                st.rerun()
    with b4:
        if st.button("⟳ Re-download ALL prices (adjusted close)",
                     key="settings_refetch_all",
                     help="Fully clears the price table and rebuilds it from "
                          "Yahoo with auto_adjust=True (split- and "
                          "dividend-adjusted total return). Use once to wipe out "
                          "old inconsistent raw prices."):
            with st.spinner("Full re-download in progress…"):
                try:
                    res2 = data.refetch_all_prices_from_inception()
                except Exception as exc:
                    st.error(f"Re-download failed: {exc}")
                    res2 = None
            if res2 is not None:
                n = int(res2.get("refetched", 0))
                err = res2.get("error")
                if err:
                    st.error(f"Re-download returned no data ({err}).")
                elif n:
                    mode = "replaced" if res2.get("wiped") else "merged (kept existing)"
                    st.success(f"✓ Price table rebuilt: {n} rows {mode}.")
                    _refresh_excel_cache()
                    st.session_state.pop("live_prices", None)   # re-read last close
                    st.rerun()
                else:
                    st.info("Nothing to re-download.")

    # ---- Diagnostic: what does Yahoo return for a ticker (local vs Cloud) ----
    with st.expander("Price-fetch diagnostic (read-only)"):
        st.caption("Measures exactly what Yahoo returns for one ticker from this "
                   "server's IP — window by window. Writes nothing to the DB. "
                   "Run it on the deployed app to see the real Cloud behaviour.")
        # Environment snapshot: which backend is live + the stored price span.
        try:
            _backend = data._active_backend_name()
        except Exception as _e:
            _backend = f"?({_e})"
        try:
            _lpd = data.latest_price_date()
        except Exception:
            _lpd = None
        try:
            _epd = data.earliest_price_date() if hasattr(data, "earliest_price_date") else None
        except Exception:
            _epd = None
        _ph_span = "—"
        if not price_history.empty and "date" in price_history.columns:
            _ph_span = (f"{price_history['date'].min().date()} → "
                        f"{price_history['date'].max().date()} "
                        f"({len(price_history)} rows)")
        st.write(f"**Backend:** `{_backend}` · **stored prices:** {_epd} → {_lpd} · "
                 f"**price_history in view:** {_ph_span}")
        st.write("**Assets → resolved Yahoo ticker:** " + (", ".join(
            f"{a}={(data.TICKER_BY_ASSET.get(a) or '?')}" for a in data.ASSETS) or "—"))
        dcol1, dcol2 = st.columns([2, 1])
        with dcol1:
            probe_tk = st.text_input("Yahoo ticker", key="diag_ticker",
                                     placeholder="e.g. 0P0000YWX8.F")
        with dcol2:
            probe_years = st.number_input("Years back", 1, 12, 5, key="diag_years")
        if st.button("Run diagnostic", key="diag_run") and probe_tk.strip():
            import datetime as _dt
            import prices as _prices
            start = _dt.date.today() - _dt.timedelta(days=int(probe_years) * 365)
            with st.spinner("Probing Yahoo…"):
                try:
                    rep = _prices.probe_ticker_fetch(probe_tk.strip(), start)
                except Exception as exc:
                    rep = {"error": str(exc)}
            if rep.get("error") and "windows" not in rep:
                st.error(f"Probe crashed: {rep['error']}")
            else:
                sf, r1 = rep["single_full"], rep["recent_1y"]
                st.write(f"**Single full shot** ({rep['range']}): "
                         f"{sf['n']} rows, first={sf['first']}, last={sf['last']}, "
                         f"{sf['secs']}s" + (f" — ERROR {sf['error']}" if sf['error'] else ""))
                st.write(f"**Recent 1-year window alone**: "
                         f"{r1['n']} rows, first={r1['first']}, last={r1['last']}, "
                         f"{r1['secs']}s" + (f" — ERROR {r1['error']}" if r1['error'] else ""))
                st.write(f"**Chunked oldest→newest** — stitched last date = "
                         f"**{rep['stitched_last']}**:")
                st.dataframe([
                    {"window": w["window"], "rows": w["n"], "first": w["first"],
                     "last": w["last"], "secs": w["secs"], "error": w["error"] or ""}
                    for w in rep["windows"]
                ], hide_index=True, use_container_width=True)

    # ---- V10: Portfolios management ----
    st.markdown(
        va1theme.section_head(
            "Portfolios",
            "Manage several independent portfolios — each has its own "
            "transactions, prices and history."),
        unsafe_allow_html=True,
    )

    pfs = data.list_portfolios()
    cur_pf = data.current_portfolio()

    # Switch
    sw1, sw2 = st.columns([2, 4])
    with sw1:
        chosen_pid = st.selectbox(
            "Current portfolio",
            options=[p["id"] for p in pfs],
            index=[p["id"] for p in pfs].index(cur_pf["id"]),
            format_func=lambda pid: next(p["name"] for p in pfs if p["id"] == pid),
            key="pf_switch",
        )
    with sw2:
        if chosen_pid != cur_pf["id"]:
            if st.button(f"➜ Switch to {next(p['name'] for p in pfs if p['id']==chosen_pid)}",
                         type="primary", key="pf_do_switch"):
                data.switch_portfolio(chosen_pid)
                _refresh_excel_cache()
                st.session_state.pop("live_prices", None)
                st.rerun()

    # Create
    st.markdown(f"<div style='color:{MUTED};font-size:11px;margin-top:14px;"
                f"letter-spacing:1px;text-transform:uppercase'>Create a new portfolio</div>",
                unsafe_allow_html=True)
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        new_pf_name = st.text_input("Portfolio name",
                                    placeholder="e.g. Crypto, PEA Bourse Direct, Speculation…",
                                    key="pf_new_name",
                                    label_visibility="collapsed")
    with c2:
        new_pf_ccy = st.selectbox("Currency", options=data.COMMON_CURRENCIES,
                                  index=0, key="pf_new_ccy",
                                  label_visibility="collapsed")
    with c3:
        if st.button("➕ Create (empty)", key="pf_create"):
            try:
                entry = data.create_portfolio(new_pf_name, currency=new_pf_ccy)
                data.switch_portfolio(entry["id"])
                _refresh_excel_cache()
                st.session_state.pop("live_prices", None)
                st.success(f"✓ Portfolio “{entry['name']}” created and activated (empty).")
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    # Rename + Delete current
    st.markdown(f"<div style='color:{MUTED};font-size:11px;margin-top:14px;"
                f"letter-spacing:1px;text-transform:uppercase'>"
                f"Rename or delete the current portfolio ({cur_pf['name']})</div>",
                unsafe_allow_html=True)
    r1, r2, r3 = st.columns([2, 1, 1])
    with r1:
        rename_to = st.text_input("New name", value=cur_pf["name"],
                                  key="pf_rename_to", label_visibility="collapsed")
    with r2:
        if st.button("✎ Rename", key="pf_rename"):
            try:
                data.rename_portfolio(cur_pf["id"], rename_to)
                _refresh_excel_cache()
                st.success(f"✓ Renamed to “{rename_to.strip()}”")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
    with r3:
        if len(pfs) > 1:
            confirm_del = st.checkbox("I confirm", key="pf_del_confirm",
                                      help="Check, then click Delete. Irreversible action.")
            if st.button("Delete", key="pf_delete",
                         disabled=not confirm_del,
                         help="Check the confirmation box first."):
                try:
                    data.delete_portfolio(cur_pf["id"])
                    _refresh_excel_cache()
                    st.session_state.pop("live_prices", None)
                    st.success(f"✓ Portfolio “{cur_pf['name']}” deleted.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
        else:
            st.caption("At least 1 portfolio required.")

    # List
    st.markdown(f"<div style='color:{MUTED};font-size:11px;margin-top:14px;"
                f"letter-spacing:1px;text-transform:uppercase'>All portfolios</div>",
                unsafe_allow_html=True)
    rows = [{"ID": p["id"], "Name": p["name"],
             "Source": "Excel (GPCP)" if p.get("seed_from_workbook") else "Empty at creation",
             "Created on": p.get("created_at","").split("T")[0],
             "Active": "● active" if p["id"] == cur_pf["id"] else ""}
            for p in pfs]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.caption(
        "ℹ️ Each portfolio's data lives in a separate sqlite file under "
        "`portfolios/portfolio_<id>.db`. Deleting a portfolio removes its file — "
        "irreversible on the dashboard side (the git tag keeps it recoverable "
        "code-side, not for user data)."
    )
