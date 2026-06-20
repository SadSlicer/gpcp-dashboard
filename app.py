"""GPCP — ETF Portfolio Dashboard.

A local Streamlit app that replaces the GPCP.xlsm workflow. Reads/writes
the workbook in place; fetches live prices from Yahoo Finance.
"""

from __future__ import annotations

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

if "theme" not in st.session_state:
    st.session_state.theme = "dark"

_T = va1theme.tokens_for(st.session_state.theme)
# Legacy aliases (kept so existing call-sites keep working — they map to the
# new VA1 tokens). Will be progressively replaced as we refactor each surface.
BG       = _T.BG_DEEP
PANEL    = _T.BG_ELEVATED
GRID     = _T.BORDER_2 if not _T.BORDER_2.startswith("rgba") else "#1F2730"
TEXT     = _T.TEXT_PRIMARY
MUTED    = _T.TEXT_MUTED
ACCENT   = _T.ACCENT      # brand orange (VA1 v3)
BRAND    = _T.BRAND       # = ACCENT now (orange)
GREEN    = _T.SUCCESS     # semantic green for positive returns — NEVER orange
RED      = _T.DANGER      # semantic red for negative returns

ETF_COLORS = va1theme.ETF_COLORS

# Inject the full VA1 CSS (fonts, tokens, animations, component styles)
st.markdown(va1theme.build_css(st.session_state.theme), unsafe_allow_html=True)

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
        return {}, "no data — click 🔄 Refresh & Save"
    last = price_history.iloc[-1]
    prices = {a: float(last[a]) for a in data.ASSETS if a in last.index and pd.notna(last[a])}
    label = f"sqlite snapshot · {last['date'].strftime('%d %b %Y')}"
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
        lbl = lbl.where(~df["is_buy"].fillna(False), lbl + " · achat")
    return lbl


def _auto_refresh_if_stale() -> str | None:
    """Option C: on first session load, if the DB is missing today's (or the
    most recent trading day's) close, fetch + save automatically. Idempotent —
    daily_update.run() is itself a no-op when nothing has moved."""
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


auto_msg = _auto_refresh_if_stale()

static, price_history, position_history, transactions_df = _load_all(_user_scope())

if "live_prices" not in st.session_state:
    prices_init, src_label = _initial_prices(static, price_history)
    st.session_state.live_prices = prices_init
    st.session_state.prices_source = src_label
    st.session_state.prices_fetched_at = None

if auto_msg:
    st.toast(auto_msg, icon="🔄")


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

# VA1 — Brand header (logo + name + status pills) + theme toggle in same row
header_col, theme_col = st.columns([9, 1])
with header_col:
    st.markdown(
        va1theme.header_html(
            pf_name=_active_pf['name'],
            pf_ccy=_pf_ccy,
            source=st.session_state.prices_source,
            version="VA1",
        ),
        unsafe_allow_html=True,
    )
with theme_col:
    new_theme = st.selectbox(
        "Theme",
        options=["dark", "light"],
        index=0 if st.session_state.theme == "dark" else 1,
        label_visibility="collapsed",
        key="theme_picker",
    )
    if new_theme != st.session_state.theme:
        st.session_state.theme = new_theme
        st.rerun()

# VA1 — Status bar (NAV, Daily, VL, source, last save)
st.markdown(
    va1theme.status_bar_html([
        ("NAV", euro(live_total), ""),
        ("Daily", f"{arrow} {euro(live_pnl_eur)} ({pct(live_pnl_pct)})", direction_cls),
        ("VL · base 100", f"{vl:,.4f}", ""),
        ("Source", st.session_state.prices_source, ""),
        ("Last update", _now_paris().strftime('%a %d %b · %H:%M'), ""),
    ]),
    unsafe_allow_html=True,
)

col_a, _ = st.columns([1.7, 8.3])
with col_a:
    if st.button("↻ Refresh & Save", width="stretch", type="primary",
                 help="Fetch latest Yahoo Finance quotes and upsert today's row in the database. "
                      "Single source of truth: every tab reads from this DB after the click. "
                      "Safe on weekends/holidays — Yahoo returns the last trading day and the "
                      "upsert is a no-op if that date is already saved."):
        with st.spinner("Fetching Yahoo Finance…"):
            try:
                # V13.1: first overwrite the last ~7 calendar days with the
                # official closes (kills any prior intraday snapshot).
                try:
                    data.refetch_recent_closes(days=7)
                except Exception:
                    pass
                quotes = prices.fetch_latest_with_date()
                if not quotes:
                    st.error("No prices returned. Check internet connectivity.")
                else:
                    trade_date = prices.most_common_trade_date(quotes)
                    price_map = {a: p for a, (_, p) in quotes.items()}
                    # Persist to DB (idempotent upsert — overwrites today's row if any)
                    res = data.save_today(price_map, static.shares, when=trade_date)
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


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab_overview, tab_positions, tab_allocation, tab_prices, tab_tx, tab_pro, tab_settings = st.tabs(
    ["Overview", "Positions", "Allocation", "Price History", "Transactions", "🧪 Pro", "⚙ Settings"]
)

# ============================================================================
# OVERVIEW — VA1 v3: NAV hero + KPI grid + chart + allocation breakdown
# ============================================================================
with tab_overview:
    inception_date = snapshot["inception_date"]
    total_return_pct = snapshot["total_return_pct"]
    net_invested = snapshot.get("net_invested", 0.0)
    cash_pnl_eur = snapshot.get("cash_pnl_eur", 0.0)

    # ---- VA1 NAV Hero (Overview-only) ----
    # Build a 30-day sparkline from the NAV history.
    _nav_for_spark = data.nav_series(price_history)
    _spark_pts: list[float] = []
    if not _nav_for_spark.empty:
        _tail = _nav_for_spark.tail(30)
        _spark_pts = [float(v) for v in _tail["nav"].tolist() if pd.notna(v)]
    _spark_svg = va1theme.sparkline_svg(_spark_pts, color=ACCENT) if len(_spark_pts) >= 2 else ""

    st.markdown(
        va1theme.hero_nav_html(
            nav_value=euro(live_total),
            daily=f"{arrow} {euro(live_pnl_eur)} ({pct(live_pnl_pct)})",
            daily_dir=direction_cls,
            vl=f"{vl:,.4f}",
            total_return=pct(total_return_pct),
            total_dir="up" if total_return_pct >= 0 else "down",
            sparkline_svg=_spark_svg,
        ),
        unsafe_allow_html=True,
    )

    # ---- KPI section ----
    st.markdown(va1theme.section_head("Performance instantanée",
                                        "Snapshot live · NAV, P&L, VL, frais pondérés"),
                unsafe_allow_html=True)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.markdown(kpi("Total Value", euro(live_total), live=True), unsafe_allow_html=True)
    c2.markdown(
        kpi(
            "Daily P&L",
            euro(live_pnl_eur),
            f"{'▲' if live_pnl_eur >= 0 else '▼'} {pct(live_pnl_pct)}",
            "up" if live_pnl_eur >= 0 else "down",
        ),
        unsafe_allow_html=True,
    )
    c3.markdown(
        kpi(
            "Total Return",
            pct(total_return_pct),
            f"VL {vl:,.4f} · time-weighted",
            "up" if total_return_pct >= 0 else "down",
        ),
        unsafe_allow_html=True,
    )
    c4.markdown(
        kpi(
            "Cash P&L",
            euro(cash_pnl_eur),
            "valeur − net investi",
            "up" if cash_pnl_eur >= 0 else "down",
        ),
        unsafe_allow_html=True,
    )
    c5.markdown(
        kpi(
            "Net Invested",
            euro(net_invested),
            f"{len(transactions_df)} tx · depuis {inception_date.strftime('%d %b %Y') if inception_date else '—'}",
        ),
        unsafe_allow_html=True,
    )

    # ---- VL chart (base 100, unitized — neutralizes flows) ----
    # VA6 (v2): switched from raw NAV (in €) to VL because raw NAV jumps
    # every time you buy / deposit. The VL is unitized so a new transaction
    # creates units, not performance — only real market moves shift the
    # curve. Reference baseline = 100 at inception.
    st.markdown(va1theme.section_head(
        "VL · Performance pure (base 100)",
        "Unitized (time-weighted) — neutralise dépôts, retraits et achats. "
        "Seule la perf marché bouge la courbe."),
        unsafe_allow_html=True)
    vl_series_df = data.compute_vl_series(price_history)
    if vl_series_df.empty:
        st.info("No history yet — click 🔄 Refresh & Save to record today's snapshot.")
    else:
        vl_df = vl_series_df[["date", "vl", "nav"]].copy()

        # Range selector control
        min_d = vl_df["date"].min().date()
        max_d = vl_df["date"].max().date()
        c_from, c_to, _ = st.columns([1, 1, 4])
        with c_from:
            nav_from = st.date_input("From", min_d, min_value=min_d, max_value=max_d, key="nav_from")
        with c_to:
            nav_to = st.date_input("To", max_d, min_value=min_d, max_value=max_d, key="nav_to")
        nav_view = vl_df[(vl_df["date"] >= pd.Timestamp(nav_from)) &
                          (vl_df["date"] <= pd.Timestamp(nav_to))]

        fig_nav_ov = go.Figure()
        fig_nav_ov.add_trace(
            go.Scatter(
                x=nav_view["date"], y=nav_view["vl"],
                mode="lines",
                line=dict(color=ACCENT, width=2.5),
                fill="tozeroy",
                fillcolor="rgba(255,136,0,0.08)",
                name="VL",
                customdata=nav_view["nav"],
                hovertemplate=(
                    "%{x|%a %d %b %Y}<br>"
                    "<b>VL %{y:.4f}</b><br>"
                    "NAV %{customdata:,.2f} €<extra></extra>"
                ),
            )
        )
        # Reference: base 100 at inception
        fig_nav_ov.add_hline(
            y=100.0,
            line=dict(color=MUTED, width=1, dash="dot"),
            annotation_text="Inception · base 100",
            annotation_position="top left",
            annotation_font_color=MUTED,
        )
        style_fig(fig_nav_ov, height=420, showlegend=False)
        fig_nav_ov.update_yaxes(title=None, tickformat=",.2f")
        # V12: hide weekends + market holidays on the date axis
        fig_nav_ov.update_xaxes(rangebreaks=data.trading_day_rangebreaks(
            price_history, nav_from, nav_to))
        # Tight y-axis: always include the 100 reference line
        if not nav_view.empty:
            lo, hi = float(nav_view["vl"].min()), float(nav_view["vl"].max())
            lo, hi = min(lo, 99.5), max(hi, 100.5)
            pad = max((hi - lo) * 0.18, 0.5)
            fig_nav_ov.update_yaxes(range=[lo - pad, hi + pad])
        st.plotly_chart(fig_nav_ov, width="stretch")

    # ---- Allocation + Daily Return breakdown ----
    st.markdown(va1theme.section_head(
        "Composition & performance par actif",
        f"Allocation donut · Daily return par actif "
        f"(perf stock pure — FX neutralisé ; voir Positions pour le {_pf_ccy} équivalent)"
    ), unsafe_allow_html=True)

    col_donut, col_bars = st.columns([1, 1])

    alloc_df = pd.DataFrame(
        [
            {
                "Asset": a,
                "Value": p["value"],
                "Allocation": p["allocation"],
            }
            for a, p in snapshot["positions"].items()
        ]
    )

    with col_donut:
        if not alloc_df.empty:
            # VA1 v4: build a full color map covering every current asset
            # (custom-added assets like AAPL/Nvidia/Coca aren't in ETF_COLORS
            # so fall back to color_for_asset which spreads them across a
            # diverse palette indexed by their position in data.ASSETS).
            _color_map = {
                a: va1theme.color_for_asset(a, i)
                for i, a in enumerate(alloc_df["Asset"].tolist())
            }
            fig = px.pie(
                alloc_df,
                values="Value",
                names="Asset",
                hole=0.62,
                color="Asset",
                color_discrete_map=_color_map,
            )
            fig.update_traces(
                textinfo="percent+label",
                textfont=dict(color=TEXT, size=11),
                hovertemplate="<b>%{label}</b><br>%{value:,.2f} €<br>%{percent}<extra></extra>",
                marker=dict(line=dict(color=BG, width=2)),
            )
            fig.add_annotation(
                text=f"<b>{euro(live_total, 0)}</b><br><span style='color:{MUTED};font-size:10px'>NAV</span>",
                showarrow=False,
                font=dict(color=TEXT, size=16),
            )
            style_fig(fig, height=380)
            st.plotly_chart(fig, width="stretch")

    with col_bars:
        rows = [
            {"Asset": a, "Return": snapshot["positions"][a].get("daily_return", 0.0) * 100.0}
            for a in data.ASSETS if a in snapshot["positions"]
        ]
        if not rows:
            st.info("Aucun actif dans ce portefeuille. Va dans **Transactions** "
                    "pour en ajouter (achat, ou ➕ Nouvel actif).")
        else:
            bar_df = pd.DataFrame(rows).sort_values("Return")
            fig = go.Figure()
            fig.add_bar(
                x=bar_df["Return"], y=bar_df["Asset"], orientation="h",
                marker=dict(
                    color=[GREEN if v >= 0 else RED for v in bar_df["Return"]],
                    line=dict(color=BG, width=1),
                ),
                hovertemplate="<b>%{y}</b><br>Daily Return: %{x:+.2f}%<extra></extra>",
                text=[f"{v:+.2f}%" for v in bar_df["Return"]],
                textposition="outside",
                textfont=dict(color=TEXT, size=11),
                cliponaxis=False,
            )
            style_fig(fig, height=380, showlegend=False)
            # Pad x-range so outside labels stay inside the plot frame
            _lo, _hi = float(bar_df["Return"].min()), float(bar_df["Return"].max())
            _span = max(abs(_lo), abs(_hi), 0.5)
            fig.update_xaxes(title=None, ticksuffix="%",
                              range=[_lo - _span * 0.30 - 0.5,
                                     _hi + _span * 0.30 + 0.5])
            fig.update_yaxes(title=None)
            st.plotly_chart(fig, width="stretch")


# ============================================================================
# POSITIONS
# ============================================================================
with tab_positions:
    _positions_empty = (not data.ASSETS and snapshot.get("cash_balance", 0) <= 0)
    if _positions_empty:
        st.info("Ce portefeuille est vide. Va dans **Transactions** pour acheter "
                "ton premier actif (ETF existant ou ➕ Nouvel actif), "
                "ou dans **Settings → Portefeuilles** pour changer de portefeuille.")
    rows = []
    # V12: Price displayed in NATIVE currency (per asset, with its own symbol);
    # Value displayed in portfolio currency.
    _pf_ccy_pos = data.current_portfolio_currency()
    _pf_sym_pos = data.CURRENCY_SYMBOL.get(_pf_ccy_pos, _pf_ccy_pos)
    _value_col = f"Value ({_pf_ccy_pos})"
    # VA1 v4: discreet dual display of Daily Return — pure stock perf for
    # ALL assets; when an asset's native currency differs from the
    # portfolio currency, append the FX-included value inline so the
    # discrepancy with Price History EUR values is self-explanatory.
    def _fmt_daily(stock: float | None, pf: float | None,
                    native_ccy: str, target_ccy: str) -> str:
        if stock is None or pd.isna(stock):
            return "—"
        # NB: −0.00% can show when value rounds to zero — preserve sign for UX
        stock_s = f"{stock:+.2%}"
        if (pf is None or pd.isna(pf)
                or native_ccy.upper() == target_ccy.upper()
                or abs(pf - stock) < 1e-6):
            return stock_s
        pf_s = f"{pf:+.2%}"
        return f"{stock_s}  ·  {pf_s} {target_ccy}"

    for asset in data.ASSETS:
        if asset not in snapshot["positions"]:
            continue  # fully-exited asset (0 shares)
        p = snapshot["positions"].get(asset, {})
        native_ccy = (p.get("currency") or _pf_ccy_pos).upper()
        native_sym = data.CURRENCY_SYMBOL.get(native_ccy, native_ccy)
        price_native = p.get("price")
        price_str = (f"{price_native:,.4f} {native_sym}"
                     if price_native is not None else "—")
        rows.append(
            {
                "Asset": asset,
                "ISIN": static.isins.get(asset, "—"),
                "Fund": static.funds.get(asset, "—"),
                "Shares": static.shares.get(asset, 0),
                "Price": price_str,
                _value_col: p.get("value"),
                "Allocation": p.get("allocation"),
                "Fees": static.fees.get(asset),
                "Daily Return": _fmt_daily(
                    p.get("daily_return"), p.get("daily_return_pf"),
                    native_ccy, _pf_ccy_pos,
                ),
                "Total Return": p.get("total_return"),
            }
        )
    # Cash line (PEA liquidity) when present
    if "Cash" in snapshot["positions"]:
        cp = snapshot["positions"]["Cash"]
        rows.append({
            "Asset": "Cash", "ISIN": "—", "Fund": "—", "Shares": None,
            "Price": "—", _value_col: cp.get("value"),
            "Allocation": cp.get("allocation"), "Fees": None,
            "Daily Return": "—", "Total Return": None,
        })
    pos_df = pd.DataFrame(rows)

    if not pos_df.empty:
        def color_signed(val):
            if pd.isna(val) or val == 0:
                return f"color: {TEXT}"
            return f"color: {GREEN}; font-weight:600" if val > 0 else f"color: {RED}; font-weight:600"

        # VA1 v4: Daily Return is now a pre-formatted string ("X% · Y% EUR"
        # for FX assets, just "X%" otherwise). Color by detecting the sign
        # character of the first (stock) value.
        def color_daily_str(val):
            if not isinstance(val, str) or val in ("—", ""):
                return f"color: {TEXT}"
            if val.startswith("+"):
                return f"color: {GREEN}; font-weight:600"
            if val.startswith(("-", "−")):
                return f"color: {RED}; font-weight:600"
            return f"color: {TEXT}"

        styled = (
            pos_df.style.format(
                {
                    _value_col: f"{{:,.2f}} {_pf_sym_pos}",
                    "Allocation": "{:.2%}",
                    "Fees": "{:.2%}",
                    "Total Return": "{:+.2%}",
                },
                na_rep="—",
            )
            .map(color_signed, subset=["Total Return"])
            .map(color_daily_str, subset=["Daily Return"])
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
        st.dataframe(styled, width="stretch", hide_index=True)

        # Footer totals — show portfolio-level %, not per-asset €.
        total_value = pos_df[_value_col].sum()
        weighted_fees = (pos_df["Fees"] * pos_df["Allocation"]).sum()
        c1, c2, c3, c4 = st.columns(4)
        c1.markdown(kpi("Σ Positions", euro(total_value)), unsafe_allow_html=True)
        c2.markdown(
            kpi(
                "Daily Return",
                pct(live_pnl_pct),
                f"{'▲' if live_pnl_eur >= 0 else '▼'} {euro(live_pnl_eur)}",
                "up" if live_pnl_eur >= 0 else "down",
            ),
            unsafe_allow_html=True,
        )
        _cash_pnl = snapshot.get("cash_pnl_eur", 0.0)
        c3.markdown(
            kpi(
                "Total Return",
                pct(total_return_pct),
                f"Cash P&L {euro(_cash_pnl)}",
                "up" if total_return_pct >= 0 else "down",
            ),
            unsafe_allow_html=True,
        )
        c4.markdown(kpi("Weighted Fees", f"{weighted_fees * 100:.2f} %"), unsafe_allow_html=True)


# ============================================================================
# ALLOCATION  — drift vs inception + stacked allocation evolution
# ============================================================================
with tab_allocation:
    if not data.ASSETS:
        st.info("Ce portefeuille est vide. Va dans **Transactions** pour acheter "
                "ton premier actif (ETF existant ou ➕ Nouvel actif via son ticker Yahoo).")
    elif price_history.empty:
        st.info("No price history saved yet. Click 🔄 Refresh & Save to record today.")
    else:
        # ---- 1) Drift vs Inception (point-in-time bar chart) -------------
        st.markdown(
            va1theme.section_head(
                "Allocation Drift vs Inception",
                "Écart en points de pourcentage entre allocation actuelle et "
                "inception. Positif = ETF surpondéré (à racheter), négatif = sous-pondéré."),
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
            st.info("Aucune position détenue actuellement (tout a été vendu — "
                    "le portefeuille n'est plus que du cash).")
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
                    "Actuelle : %{customdata[0]:.2f}%<br>"
                    "Cible    : %{customdata[1]:.2f}%<br>"
                    "Drift    : %{x:+.2f} pts<extra></extra>"
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
                            "somme des écarts absolus"),
                        unsafe_allow_html=True)
            c3.markdown(kpi("Inception date",
                            snapshot["inception_date"].strftime("%d %b %Y") if snapshot["inception_date"] else "—",
                            "référence cible"),
                        unsafe_allow_html=True)

        # ---- 2) Allocation evolution (stacked 100% area chart) ------------
        st.markdown(
            va1theme.section_head(
                "Évolution des allocations (% du portefeuille)",
                "Chaque bande = % du NAV occupé par un ETF. Les bandes qui "
                "s'élargissent = ETFs qui ont surperformé."),
            unsafe_allow_html=True,
        )

        alloc_min, alloc_max = price_history["date"].min().date(), price_history["date"].max().date()
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
        style_fig(fig_alloc, height=420)
        fig_alloc.update_yaxes(title="Allocation (%)", ticksuffix="%", range=[0, 100])
        fig_alloc.update_xaxes(rangebreaks=data.trading_day_rangebreaks(
            price_history, alloc_from, alloc_to))
        st.plotly_chart(fig_alloc, width="stretch")


# ============================================================================
# PRICE HISTORY
# ============================================================================
with tab_prices:
    if price_history.empty:
        st.info("No price history saved yet. Click 🔄 Refresh & Save to record today.")
    else:
        # V12: convert every asset price from its native currency to the
        # portfolio currency via FX at each date, so charts & tables are
        # internally consistent and the labels (e.g. €) match the values.
        pf_ccy = data.current_portfolio_currency()
        pf_sym = data.CURRENCY_SYMBOL.get(pf_ccy, pf_ccy)
        price_history_pf = _augmented_pf(price_history)

        min_d, max_d = price_history_pf["date"].min().date(), price_history_pf["date"].max().date()
        c1, c2, c3 = st.columns([2, 2, 3])
        with c1:
            start = st.date_input("From", min_d, min_value=min_d, max_value=max_d, key="ph_from")
        with c2:
            end = st.date_input("To", max_d, min_value=min_d, max_value=max_d, key="ph_to")
        with c3:
            selected = st.multiselect(
                "Tickers",
                options=data.ASSETS,
                default=data.ASSETS,
                key="ph_assets",
            )

        normalize = st.toggle("Normalize to 100 at start", value=False, key="ph_norm")

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
            if normalize:
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
                    hovertemplate=f"<b>{asset}</b><br>%{{x|%d %b %Y}}<br>%{{y:,.4f}} {pf_sym}<extra></extra>",
                )
            )
        style_fig(fig, height=520)
        fig.update_yaxes(title=("Indexed (100 = start)" if normalize else f"Price ({pf_sym})"))
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
            f"Prix journaliers par ETF ({pf_sym})",
            f"Prix convertis en {pf_ccy} au taux du jour. Total = NAV portefeuille (Σ prix × parts détenues ce jour-là).",
        )
        prices_tbl = base.copy()
        # Total = NAV = Σ price × shares_held_at_that_date (all in pf_ccy)
        _total_series = pd.Series([0.0] * len(prices_tbl))
        for a in data.ASSETS:
            _total_series = _total_series + (
                prices_tbl[a].astype(float).fillna(0).reset_index(drop=True)
                * _shares_col(a, _shares_by_date_slice)
            )
        prices_tbl["Cash"] = _cash_by_date_slice.values
        prices_tbl["Total"] = (_total_series + _cash_by_date_slice).values   # NAV = Σ actifs + cash
        prices_tbl.insert(0, "Date", _date_labels(prices_tbl))
        prices_tbl = prices_tbl.drop(columns=["date"])
        prices_tbl = prices_tbl[["Date", *data.ASSETS, "Cash", "Total"]]
        fmt = {a: f"{{:,.4f}} {pf_sym}" for a in data.ASSETS}
        fmt["Cash"] = f"{{:,.2f}} {pf_sym}"
        fmt["Total"] = f"{{:,.2f}} {pf_sym}"
        st.dataframe(_style_history(prices_tbl, fmt), width="stretch", hide_index=True)

        # ===================== Table 2: POSITION VALUES per ETF + Total NAV =====================
        _section_header(
            f"Valeur de position journalière par ETF ({pf_sym})",
            "Prix × parts détenues à cette date (time-varying). Total = NAV portefeuille.",
        )
        pos_tbl = base.copy().reset_index(drop=True)
        for a in data.ASSETS:
            pos_tbl[a] = (
                pos_tbl[a].astype(float).fillna(0).reset_index(drop=True)
                * _shares_col(a, _shares_by_date_slice)
            )
        pos_tbl["Cash"] = _cash_by_date_slice.values
        pos_tbl["Total"] = pos_tbl[data.ASSETS].sum(axis=1).values + _cash_by_date_slice.values  # NAV = Σ actifs + cash
        pos_tbl.insert(0, "Date", _date_labels(pos_tbl))
        pos_tbl = pos_tbl.drop(columns=["date"])
        pos_tbl = pos_tbl[["Date", *data.ASSETS, "Cash", "Total"]]
        fmt2 = {a: f"{{:,.2f}} {pf_sym}" for a in data.ASSETS}
        fmt2["Cash"] = f"{{:,.2f}} {pf_sym}"
        fmt2["Total"] = f"{{:,.2f}} {pf_sym}"
        st.dataframe(_style_history(pos_tbl, fmt2), width="stretch", hide_index=True)

        # ===================== Table 3: NAV (raw + VL base 100 + daily change) =====================
        _section_header(
            "Historique NAV portefeuille",
            f"Brute ({pf_sym}), VL (base 100 à l'inception), variation jour.",
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
                nav_full[a].astype(float).fillna(0).reset_index(drop=True)
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
        nav_view = nav_view.rename(columns={"Δ €": delta_col})
        nav_view = nav_view[["Date", "NAV", "Cash", "VL", delta_col, "Daily Change"]]
        fmt3 = {
            "NAV": f"{{:,.2f}} {pf_sym}",
            "Cash": f"{{:,.2f}} {pf_sym}",
            "VL": "{:,.4f}",
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
            a for a in data.ASSETS
            if (static.currencies.get(a) or pf_ccy).upper() != pf_ccy.upper()
        ]
        if _fx_assets:
            _section_header(
                "Détail multi-devises",
                f"native × taux de change = converti en {pf_ccy}. "
                f"Sélectionne un actif pour vérifier le calcul jour par jour.",
            )
            mc_col1, _ = st.columns([2, 6])
            with mc_col1:
                mc_asset = st.selectbox(
                    "Actif", _fx_assets, key="ph_multi_ccy_asset",
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
                    f"Prix natif ({mc_native_ccy})":
                        mc_slice[mc_asset].astype(float).values,
                    f"FX {mc_native_ccy}→{pf_ccy}": _rates.values,
                    f"Prix converti ({pf_ccy})":
                        mc_slice[mc_asset].astype(float).values * _rates.values,
                })
                mc_fmt = {
                    f"Prix natif ({mc_native_ccy})":
                        f"{{:,.4f}} {mc_native_sym}",
                    f"FX {mc_native_ccy}→{pf_ccy}": "{:,.6f}",
                    f"Prix converti ({pf_ccy})":
                        f"{{:,.4f}} {pf_sym}",
                }
                st.dataframe(
                    _style_history(mc_view, mc_fmt),
                    width="stretch", hide_index=True,
                )
            else:
                st.info(f"Pas de prix natifs enregistrés pour {mc_asset} "
                        f"sur la période sélectionnée.")


# ============================================================================
# TRANSACTIONS
# ============================================================================
with tab_tx:
    # ---- New transaction form ----
    st.markdown(
        va1theme.section_head(
            "Nouvelle transaction",
            "Achat · vente · dépôt · retrait — toutes les vues se recalculent automatiquement"),
        unsafe_allow_html=True,
    )

    NEW_ETF_LABEL = "➕ Nouvel actif…"
    TX_TYPES = ["Achat (BUY)", "Vente (SELL)", "Dépôt de cash", "Retrait de cash"]
    # NB: deliberately NOT a st.form — we want the Type/Asset selectboxes to
    # trigger a rerun so the right fields appear immediately.
    r1c1, r1c2, r1c3 = st.columns(3)
    with r1c1:
        tx_date = st.date_input("Date", dt.date.today(), key="ntx_date")
    with r1c2:
        tx_side = st.selectbox("Type", TX_TYPES, key="ntx_side")

    is_deposit = tx_side == "Dépôt de cash"
    is_withdraw = tx_side == "Retrait de cash"
    is_cash = is_deposit or is_withdraw

    asset_choice = None
    is_new = False
    new_name = new_isin = new_ticker = new_fund = ""
    new_fees = 0.0

    if not is_cash:
        with r1c3:
            asset_choice = st.selectbox("Asset", [*static.isins.keys(), NEW_ETF_LABEL], key="ntx_asset")
        is_new = asset_choice == NEW_ETF_LABEL
        if is_new:
            st.markdown(
                f"<div style='color:{ACCENT};font-size:11px;margin-bottom:2px'>"
                f"Nouvel actif — n'importe quelle action ou ETF. "
                f"Il suffit de son <b>nom</b> et de son <b>ticker Yahoo Finance</b> "
                f"(ex. AAPL, MC.PA, PSP5.PA). L'ISIN, le secteur et le pays "
                f"sont récupérés automatiquement via Yahoo si disponibles.</div>",
                unsafe_allow_html=True,
            )
            n1, n2, n3, n4, n5 = st.columns([3, 2, 2, 2, 2])
            with n1:
                new_name = st.text_input("Nom (requis)",
                                         placeholder="ex. Apple, LVMH, Bitcoin…",
                                         key="ntx_newname")
            with n2:
                new_ticker = st.text_input("Ticker Yahoo (requis)",
                                           placeholder="ex. AAPL, MC.PA",
                                           key="ntx_newticker")
            with n3:
                _pf_ccy_default = data.current_portfolio_currency()
                _ccy_options = data.COMMON_CURRENCIES.copy()
                if _pf_ccy_default in _ccy_options:
                    _ccy_options.remove(_pf_ccy_default)
                    _ccy_options.insert(0, _pf_ccy_default)
                new_currency = st.selectbox(
                    "Devise", options=_ccy_options, index=0,
                    key="ntx_newccy",
                    help="Devise de cotation de l'actif. AAPL=USD, MC.PA=EUR, etc. "
                         "Auto-détectée depuis Yahoo si laissée par défaut."
                )
            with n4:
                new_isin = st.text_input("ISIN (optionnel)",
                                         placeholder="auto si vide",
                                         key="ntx_newisin")
            with n5:
                new_fees = st.number_input("Frais (% annuel)", min_value=0.0,
                                           max_value=5.0, value=0.0, step=0.01,
                                           format="%.2f", key="ntx_newfees")
            new_fund = ""  # auto-filled from yfinance.info
    else:
        with r1c3:
            st.markdown(
                f"<div style='color:{MUTED};font-size:11px;letter-spacing:1px;"
                f"text-transform:uppercase;margin-bottom:4px'>Cash dispo</div>"
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
                f"Montant ({data.CURRENCY_SYMBOL.get(tx_currency, tx_currency)})",
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
        # VA2 — auto-fetch price by date toggle
        if "ntx_manual_price" not in st.session_state:
            st.session_state.ntx_manual_price = False
        r1d = st.columns([2, 6])
        with r1d[0]:
            tx_manual = st.checkbox(
                "Saisie manuelle du prix",
                value=st.session_state.ntx_manual_price,
                key="ntx_manual_price",
                help="Décoche pour que le dashboard utilise l'adjusted close "
                     "Yahoo de la date sélectionnée. Coche si tu veux entrer "
                     "un prix différent (OTC, prix limite, etc.).",
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
                    f"Prix unitaire <span style='color:{ACCENT};font-size:9px;"
                    f"padding:2px 6px;border-radius:4px;background:rgba(255,136,0,0.12);"
                    f"border:1px solid rgba(255,136,0,0.3);margin-left:6px'>"
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
                st.markdown(
                    f"<div style='color:{MUTED};font-size:11px;letter-spacing:.06em;"
                    f"text-transform:uppercase;margin-bottom:6px;font-weight:500'>"
                    f"Prix unitaire</div>"
                    f"<div style='font-family:JetBrains Mono,monospace;font-size:14px;"
                    f"padding:9px 12px;background:{PANEL};"
                    f"border:1px solid {RED};border-radius:6px;color:{RED}'>"
                    f"Aucun prix dispo. Coche « Saisie manuelle » ou change la date.</div>",
                    unsafe_allow_html=True,
                )
            else:
                tx_price = st.number_input(
                    "Prix unitaire", min_value=0.0, value=0.0,
                    step=0.01, format="%.4f", key="ntx_price",
                )
        with r2c2:
            tx_shares = st.number_input("Nombre de titres", min_value=0.0, value=0.0,
                                        step=1.0, format="%.4f", key="ntx_shares")
        with r2c3:
            tx_currency = st.selectbox(
                "Devise tx", options=_tx_ccy_options, index=0, key="ntx_currency",
                help="Devise dans laquelle le prix est exprimé (= devise débitée "
                     "sur ton compte espèces). Convertie automatiquement vers la "
                     "devise du portefeuille au taux de change du jour de la transaction.",
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
                               f"FX indisponible</div>")
            st.markdown(
                f"<div style='color:{MUTED};font-size:11px;letter-spacing:1px;"
                f"text-transform:uppercase;margin-bottom:4px'>Total ({pf_ccy})</div>"
                f"<div style='font-size:22px;font-weight:600;color:{TEXT};"
                f"font-variant-numeric:tabular-nums'>{total_str}</div>"
                f"{fx_note}",
                unsafe_allow_html=True,
            )

    if st.button("✓ Enregistrer la transaction", type="primary", key="ntx_submit"):
        try:
            if is_cash:
                kind = "DEPOSIT" if is_deposit else "WITHDRAW"
                if cash_amount <= 0:
                    st.error("Le montant doit être > 0.")
                else:
                    res = data.add_cash_movement(tx_date, kind, cash_amount)
                    _refresh_excel_cache()
                    label = "Dépôt" if kind == "DEPOSIT" else "Retrait"
                    st.success(f"✓ {label} de {euro(res['amount'])} · "
                               f"cash dispo : {euro(res['cash_after'])}")
                    st.rerun()
            else:
                side = "BUY" if tx_side.startswith("Achat") else "SELL"
                if tx_shares <= 0 or tx_price <= 0:
                    st.error("Prix et nombre de titres doivent être > 0.")
                elif is_new:
                    if not (new_name.strip() and new_ticker.strip()):
                        st.error("Nom et ticker Yahoo sont obligatoires.")
                    elif side == "SELL":
                        st.error("Un nouvel actif ne peut pas commencer par une vente.")
                    else:
                        import compositions_scraper as _cs
                        name = new_name.strip()
                        ticker = new_ticker.strip()
                        with st.spinner("Récupération auto des métadonnées Yahoo…"):
                            info = _cs.lookup_yfinance_info(ticker)
                        isin = (new_isin.strip() or info.get("isin") or "")
                        fund = info.get("fund") or "—"
                        # If user didn't override, prefer Yahoo's currency when
                        # known (it's authoritative); otherwise keep the dropdown.
                        auto_ccy = (info.get("currency") or "").upper().strip()
                        currency = auto_ccy or new_currency
                        data.register_asset(name, isin, ticker,
                                            fund=fund, fees=new_fees / 100.0,
                                            currency=currency)
                        res = data.add_transaction(tx_date, name, side,
                                                   tx_price, tx_shares, isin=isin or None,
                                                   currency=tx_currency)
                        # Try factsheet first, then yfinance.info (stock) fallback.
                        scrape_msg = ""
                        try:
                            with st.spinner("Récupération des expositions géo/secteur…"):
                                r = _cs.refresh_asset(name)
                                wrote_stock = False
                                if r.get("status") != "ok":
                                    wrote_stock = _cs.seed_stock_compositions(name, ticker)
                            if r.get("status") == "ok":
                                scrape_msg = f" · expo {r.get('source','')} récupérée"
                            elif wrote_stock:
                                scrape_msg = " · expo (stock) via yfinance.info"
                            else:
                                scrape_msg = " · expo non trouvée (réessai le 15)"
                        except Exception:
                            scrape_msg = ""
                        _refresh_excel_cache()
                        bf = f" · +{res['backfilled_days']}j de prix rétro-importés" if res.get("backfilled_days") else ""
                        st.success(f"✓ {name} créé ({ticker}) + {res['type']} "
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
                           f"parts détenues : {res['new_holding']:g}")
                    if side == "SELL":
                        msg += f" · cash dispo : {euro(data.cash_balance_as_of(dt.date.today()))}"
                    if res.get("backfilled_days"):
                        msg += f" · +{res['backfilled_days']} jours de prix rétro-importés"
                    st.success(msg)
                    st.rerun()
        except ValueError as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(f"Erreur : {exc}")

    # ---- History ----
    st.markdown(
        va1theme.section_head("Historique des transactions",
                                "Filtre par asset ou recherche par ISIN"),
        unsafe_allow_html=True,
    )
    if transactions_df.empty:
        st.info("Aucune transaction enregistrée.")
    else:
        c1, c2 = st.columns([3, 1])
        with c1:
            q = st.text_input("Rechercher (asset, ISIN)", "", key="tx_q").strip().lower()
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
        _sell_ret = {}
        _sfn = getattr(data, "sell_pnl_rows", None)
        if _sfn:
            for s in _sfn():
                if s.get("id") is not None and s.get("return_pct") is not None:
                    _sell_ret[int(s["id"])] = s["return_pct"]
        view_display["Return vente"] = view_display.apply(
            lambda r: (f"{_sell_ret[int(r['Id'])] * 100:+.2f} %"
                       if (str(r["Type"]) == "SELL" and pd.notna(r.get("Id"))
                           and int(r["Id"]) in _sell_ret) else "—"),
            axis=1,
        )
        view_display = view_display[[
            "Date", "Asset", "ISIN", "Type", "Price", "Shares",
            "Currency", f"Total ({pf_ccy_tx})", "Return vente",
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
        c1.markdown(kpi("Σ Achats", _money(buys)), unsafe_allow_html=True)
        c2.markdown(kpi("Σ Ventes", _money(sells)), unsafe_allow_html=True)
        c3.markdown(kpi("Net investi", _money(buys - sells)), unsafe_allow_html=True)
        c4.markdown(kpi("# Transactions", str(len(view))), unsafe_allow_html=True)

        # ---- Realized sells — P&L per sale (incl. partial sells) ----
        _sell_fn = getattr(data, "sell_pnl_rows", None)
        _sells = _sell_fn() if _sell_fn else []
        if _sells:
            st.markdown(
                va1theme.section_head(
                    "Ventes réalisées — P&L",
                    "Pour chaque vente : return et P&L réalisés vs le coût d'achat "
                    "moyen à la date de vente (ventes partielles incluses)."),
                unsafe_allow_html=True,
            )

            def _sym(c):
                return data.CURRENCY_SYMBOL.get(c, c)

            sell_tbl = pd.DataFrame([
                {
                    "Date": s["date"].strftime("%d %b %Y") if hasattr(s["date"], "strftime") else str(s["date"]),
                    "Asset": s["asset"],
                    "Parts vendues": f"{s['shares']:g}",
                    "Prix vente": f"{s['sell_price']:,.4f} {_sym(s['currency'])}",
                    "Coût moyen": (f"{s['avg_cost']:,.4f} {_sym(s['currency'])}"
                                   if s["avg_cost"] is not None else "—"),
                    "Return": (f"{s['return_pct'] * 100:+.2f} %"
                               if s["return_pct"] is not None else "—"),
                    "P&L réalisé": (f"{s['pnl']:+,.2f} {_sym(s['currency'])}"
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
                "Supprimer une transaction",
                "Action destructive — coche la confirmation avant de supprimer. "
                "Cash, parts et NAV se recalculent automatiquement."),
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
            st.info("Aucune transaction à supprimer dans la vue filtrée.")
        else:
            labels = [_tx_label(r) for _, r in view_for_select.iterrows()]
            id_by_label = dict(zip(labels, view_for_select["Id"].astype(int).tolist()))
            cdel1, cdel2, cdel3 = st.columns([5, 2, 2])
            with cdel1:
                chosen = st.selectbox("Transaction", labels, key="tx_del_sel",
                                       label_visibility="collapsed")
            with cdel2:
                confirm = st.checkbox("Je confirme", key="tx_del_confirm",
                                       value=False)
            with cdel3:
                if st.button("✕ Supprimer", key="tx_del_btn",
                             type="primary", disabled=not confirm,
                             width="stretch"):
                    try:
                        res = data.delete_transaction(id_by_label[chosen])
                        if res["deleted"]:
                            _refresh_excel_cache()
                            st.success(f"Transaction #{res['id']} supprimée. "
                                       f"Cash, parts et NAV recalculés.")
                            st.session_state.pop("tx_del_confirm", None)
                            st.rerun()
                        else:
                            st.warning(f"Transaction #{res['id']} introuvable "
                                       f"(déjà supprimée ?).")
                    except Exception as exc:
                        st.error(f"Erreur lors de la suppression : {exc}")

    # ----------------------------------------------------------------
    # VA2 — Excel / CSV bulk import (with preview)
    # ----------------------------------------------------------------
    st.markdown(
        va1theme.section_head(
            "Import en lot (Excel / CSV)",
            "Upload un fichier, vérifie la preview, puis valide. "
            "Colonnes : date, asset, type, shares, price (optionnel — "
            "auto-fetch sinon), currency (optionnel), amount (pour DEPOSIT/WITHDRAW)."),
        unsafe_allow_html=True,
    )

    imp_top_l, imp_top_r = st.columns([3, 1])
    with imp_top_l:
        uploaded = st.file_uploader(
            "Fichier", type=["xlsx", "xls", "csv"],
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
            st.error(f"Lecture du fichier échouée : {_e}")
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
                    return "⚠ date invalide"
                if t in ("DEPOSIT", "WITHDRAW"):
                    try:
                        amt = float(row.get("amount") or 0)
                    except Exception:
                        amt = 0
                    if amt <= 0:
                        return "⚠ amount > 0 requis"
                    return "✓ ok"
                if t in ("BUY", "SELL"):
                    asset = str(row.get("asset") or "").strip()
                    if asset not in data.ASSETS:
                        return f"⚠ asset inconnu : {asset!r}"
                    try:
                        sh = float(row.get("shares") or 0)
                    except Exception:
                        sh = 0
                    if sh <= 0:
                        return "⚠ shares > 0 requis"
                    return "✓ ok"
                return "⚠ type invalide"

            imp_df["status"] = imp_df.apply(_validate, axis=1)
            imp_df.insert(0, "import", imp_df["status"].str.startswith("✓"))

            st.markdown(
                f"<div style='color:{MUTED};font-size:12px;margin:14px 0 6px 0'>"
                f"<b style='color:{TEXT}'>{int(imp_df['import'].sum())}</b> "
                f"transaction(s) à importer sur {len(imp_df)} ligne(s). "
                f"Décoche celles que tu ne veux pas, ou corrige-les sur place."
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
                        "Importer", help="Coche pour inclure la ligne",
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
                    f"✓ Valider et enregistrer ({n_ready})",
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
                                f"✓ {res['inserted']} importées, "
                                f"{res['skipped']} échouées : "
                                + " · ".join(f"#{e['row']+1} {e['reason']}"
                                              for e in res["errors"][:3])
                                + (f" (+{len(res['errors'])-3} autres)"
                                   if len(res["errors"]) > 3 else "")
                            )
                        else:
                            st.success(
                                f"✓ {res['inserted']} transaction(s) "
                                f"enregistrée(s). NAV et cash recalculés.")
                        st.rerun()
                    except Exception as _e:
                        st.error(f"Import échoué : {_e}")
            with bcol2:
                if st.button("Reset", key="tx_bulk_reset"):
                    st.session_state.pop("tx_bulk_upload", None)
                    st.rerun()


# ============================================================================
# PRO — V2 advanced analytics
# ============================================================================
with tab_pro:
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
    st.markdown(
        va1theme.section_head(
            "Date de début du portefeuille (inception)",
            "Point de référence de toute la performance : VL = 100 à cette date. "
            "Changer cette date réajuste TOUT."),
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
        sessions_label = "aucun prix sauvegardé"
    else:
        sessions_label = f"du {ph_min.strftime('%d %b %Y')} au {ph_max.strftime('%d %b %Y')}"

    c1, c2 = st.columns([1, 2])
    with c1:
        chosen = st.date_input(
            "Date d'inception",
            value=current_inception,
            min_value=min_d, max_value=max_d,
            key="settings_inception",
        )
    with c2:
        st.markdown(
            f"<div style='background:{PANEL};border:1px solid {GRID};border-radius:10px;"
            f"padding:12px 16px;font-size:12px;color:{MUTED}'>"
            f"Actuelle : <b style='color:{TEXT}'>{current_inception.strftime('%d %b %Y')}</b><br>"
            f"Par défaut (1ère transaction) : <b style='color:{TEXT}'>{default_inception.strftime('%d %b %Y')}</b><br>"
            f"Séances disponibles : {sessions_label}"
            f"</div>",
            unsafe_allow_html=True,
        )

    b1, b2, b3, b4 = st.columns([1, 1, 2, 2])
    with b1:
        if st.button("✓ Appliquer", type="primary", key="settings_apply"):
            data.set_inception_date(chosen)
            _refresh_excel_cache()
            st.success(f"Date d'inception → {chosen.strftime('%d %b %Y')}. Tout est recalculé.")
            st.rerun()
    with b2:
        if st.button("↺ Réinitialiser", key="settings_reset"):
            data.set_inception_date(default_inception)
            _refresh_excel_cache()
            st.success(f"Date d'inception réinitialisée → {default_inception.strftime('%d %b %Y')}.")
            st.rerun()
    with b3:
        if st.button("⤓ Rétro-importer les prix manquants",
                     key="settings_backfill",
                     help="Va chercher chez Yahoo tous les prix journaliers manquants "
                          "entre la date d'inception et aujourd'hui, pour chaque actif "
                          "du portefeuille. Utile après un changement d'inception ou "
                          "pour un portefeuille créé avant l'auto-backfill."):
            with st.spinner("Récupération des prix manquants depuis Yahoo…"):
                try:
                    res = data.backfill_all_assets_to_inception()
                except Exception as exc:
                    st.error(f"Backfill échoué : {exc}")
                    res = None
            if res is not None:
                if res:
                    total = sum(res.values())
                    detail = ", ".join(f"{a} +{n}j" for a, n in res.items())
                    st.success(f"✓ {total} prix importés ({detail}).")
                else:
                    st.info("Tous les prix sont déjà à jour, rien à importer.")
                _refresh_excel_cache()
                st.rerun()
    with b4:
        if st.button("⟳ Re-télécharger TOUS les prix (adjusted close)",
                     key="settings_refetch_all",
                     help="V12 : vide entièrement la table des prix et la "
                          "refait depuis Yahoo avec auto_adjust=True "
                          "(split- et dividend-adjusted total return). "
                          "À utiliser une fois après le passage à la V12 "
                          "pour éliminer les anciens prix bruts incohérents."):
            with st.spinner("Re-téléchargement complet en cours…"):
                try:
                    res2 = data.refetch_all_prices_from_inception()
                except Exception as exc:
                    st.error(f"Re-téléchargement échoué : {exc}")
                    res2 = None
            if res2 is not None:
                total = sum(res2.values())
                detail = ", ".join(f"{a}={n}j" for a, n in res2.items() if n)
                st.success(f"✓ Table prix reconstruite : {total} lignes ({detail}).")
                _refresh_excel_cache()
                st.rerun()

    # ---- V10: Portfolios management ----
    st.markdown(
        va1theme.section_head(
            "Portefeuilles",
            "Gère plusieurs portefeuilles indépendants — chacun a ses propres "
            "transactions, prix et historiques."),
        unsafe_allow_html=True,
    )

    pfs = data.list_portfolios()
    cur_pf = data.current_portfolio()

    # Switch
    sw1, sw2 = st.columns([2, 4])
    with sw1:
        chosen_pid = st.selectbox(
            "Portefeuille actuel",
            options=[p["id"] for p in pfs],
            index=[p["id"] for p in pfs].index(cur_pf["id"]),
            format_func=lambda pid: next(p["name"] for p in pfs if p["id"] == pid),
            key="pf_switch",
        )
    with sw2:
        if chosen_pid != cur_pf["id"]:
            if st.button(f"➜ Basculer vers {next(p['name'] for p in pfs if p['id']==chosen_pid)}",
                         type="primary", key="pf_do_switch"):
                data.switch_portfolio(chosen_pid)
                _refresh_excel_cache()
                st.session_state.pop("live_prices", None)
                st.rerun()

    # Create
    st.markdown(f"<div style='color:{MUTED};font-size:11px;margin-top:14px;"
                f"letter-spacing:1px;text-transform:uppercase'>Créer un nouveau portefeuille</div>",
                unsafe_allow_html=True)
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        new_pf_name = st.text_input("Nom du portefeuille",
                                    placeholder="ex. Crypto, PEA Bourse Direct, Speculation…",
                                    key="pf_new_name",
                                    label_visibility="collapsed")
    with c2:
        new_pf_ccy = st.selectbox("Devise", options=data.COMMON_CURRENCIES,
                                  index=0, key="pf_new_ccy",
                                  label_visibility="collapsed")
    with c3:
        if st.button("➕ Créer (vide)", key="pf_create"):
            try:
                entry = data.create_portfolio(new_pf_name, currency=new_pf_ccy)
                data.switch_portfolio(entry["id"])
                _refresh_excel_cache()
                st.session_state.pop("live_prices", None)
                st.success(f"✓ Portefeuille « {entry['name']} » créé et activé (vide).")
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    # Rename + Delete current
    st.markdown(f"<div style='color:{MUTED};font-size:11px;margin-top:14px;"
                f"letter-spacing:1px;text-transform:uppercase'>"
                f"Renommer ou supprimer le portefeuille actuel ({cur_pf['name']})</div>",
                unsafe_allow_html=True)
    r1, r2, r3 = st.columns([2, 1, 1])
    with r1:
        rename_to = st.text_input("Nouveau nom", value=cur_pf["name"],
                                  key="pf_rename_to", label_visibility="collapsed")
    with r2:
        if st.button("✎ Renommer", key="pf_rename"):
            try:
                data.rename_portfolio(cur_pf["id"], rename_to)
                _refresh_excel_cache()
                st.success(f"✓ Renommé en « {rename_to.strip()} »")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
    with r3:
        if len(pfs) > 1:
            confirm_del = st.checkbox("Je confirme", key="pf_del_confirm",
                                      help="Coche puis clique Supprimer. Action irréversible.")
            if st.button("🗑 Supprimer", key="pf_delete",
                         disabled=not confirm_del,
                         help="Coche d'abord la case de confirmation."):
                try:
                    data.delete_portfolio(cur_pf["id"])
                    _refresh_excel_cache()
                    st.session_state.pop("live_prices", None)
                    st.success(f"✓ Portefeuille « {cur_pf['name']} » supprimé.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
        else:
            st.caption("Au moins 1 portefeuille requis.")

    # List
    st.markdown(f"<div style='color:{MUTED};font-size:11px;margin-top:14px;"
                f"letter-spacing:1px;text-transform:uppercase'>Tous les portefeuilles</div>",
                unsafe_allow_html=True)
    rows = [{"ID": p["id"], "Nom": p["name"],
             "Source": "Excel (GPCP)" if p.get("seed_from_workbook") else "Vide à la création",
             "Créé le": p.get("created_at","").split("T")[0],
             "Actif": "● actif" if p["id"] == cur_pf["id"] else ""}
            for p in pfs]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.caption(
        "ℹ️ Les données de chaque portefeuille vivent dans un fichier sqlite "
        "séparé sous `portfolios/portfolio_<id>.db`. Supprimer un portefeuille "
        "supprime son fichier — irréversible côté dashboard (le tag git le garde "
        "récupérable côté code, pas côté données utilisateur)."
    )
