"""GPCP Dashboard — V2 'Pro' tab.

Contains 8 sub-tabs of pro-grade analytics. This module is intentionally
isolated from app.py so it can be deleted / disabled without touching V1
features. Rendering is driven by `render(static, price_history, snapshot,
palette)` where `palette` carries the theme colors so charts match dark
or light mode.

Sub-tabs implemented in this iteration:
  1. Risk Metrics
  2. Calendar Heatmap (monthly returns)
  3. Correlation Matrix

Stubbed placeholders (built in a follow-up iteration):
  4. Performance Attribution
  5. Benchmark Comparison
  6. Monte Carlo Simulator
  7. Monthly PDF Export
  8. Sector / Geographic Exposure
"""

from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import data

COMPOSITIONS_PATH = Path(__file__).parent / "etf_compositions.json"

# VA1 v4 — colors centralized in theme.py. ETF_COLORS kept as a legacy
# alias for any direct .get() lookups; color_for_asset() is the canonical
# helper that handles fallback for custom assets (Coca, Nvidia, AAPL…).
import theme as va1theme
ETF_COLORS = va1theme.ETF_COLORS
color_for_asset = va1theme.color_for_asset

# Trading days in a year — used to annualize daily stats
TRADING_DAYS = 252
# Risk-free rate proxy for Sharpe — €STR ~ 3 % is a reasonable Euro default
DEFAULT_RF = 0.03

# Benchmark presets — well-known € or EUR-hedged ETFs trading on Euronext / Xetra
BENCHMARKS = {
    "MSCI World (IWDA.AS)":   {"ticker": "IWDA.AS", "label": "MSCI World"},
    "MSCI ACWI (IUSQ.DE)":    {"ticker": "IUSQ.DE", "label": "MSCI ACWI"},
    "FTSE Developed (VWCE.DE)": {"ticker": "VWCE.DE", "label": "FTSE All-World"},
    "60/40 mix (custom)":     {"ticker": None,     "label": "60% World / 40% AGG"},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _portfolio_nav_series(static, price_history: pd.DataFrame) -> pd.Series:
    """Return a single time-series of portfolio NAV (€) indexed by date.

    Uses data.nav_series() so it reflects TIME-VARYING shares + the cash balance
    (PEA liquidity), consistent with the Overview NAV and the snapshot.
    """
    nv = data.nav_series(price_history)
    if nv.empty:
        return pd.Series(dtype=float)
    return nv.set_index("date")["nav"].rename("NAV")


def _daily_returns(series: pd.Series) -> pd.Series:
    return series.pct_change().dropna()


def _portfolio_vl_series(price_history: pd.DataFrame) -> pd.Series:
    """VA6: VL (unitized, base 100) series indexed by date.

    Used for ALL performance / risk metrics so external flows (deposits,
    withdraws, implicit deposits on buys) don't contaminate the daily
    returns with fake "performance" spikes. VL is built so that only
    market moves change it.
    """
    vl = data.compute_vl_series(price_history)
    if vl.empty:
        return pd.Series(dtype=float)
    return vl.set_index("date")["vl"].rename("VL")


def _style_fig(fig: go.Figure, palette: dict, *, height: int = 380, showlegend: bool = True) -> go.Figure:
    fig.update_layout(
        paper_bgcolor=palette["BG"],
        plot_bgcolor=palette["BG"],
        font=dict(color=palette["TEXT"], family="SF Mono, JetBrains Mono, Menlo, monospace", size=12),
        margin=dict(l=10, r=10, t=30, b=10),
        height=height,
        showlegend=showlegend,
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=palette["MUTED"]),
                    orientation="h", y=-0.18),
        hoverlabel=dict(bgcolor=palette["PANEL"], bordercolor=palette["GRID"],
                        font=dict(color=palette["TEXT"])),
    )
    fig.update_xaxes(gridcolor=palette["GRID"], zeroline=False,
                     linecolor=palette["GRID"], tickcolor=palette["GRID"])
    fig.update_yaxes(gridcolor=palette["GRID"], zeroline=False,
                     linecolor=palette["GRID"], tickcolor=palette["GRID"])
    return fig


def _kpi(label: str, value: str, delta: str | None = None, *, palette: dict, tone: str = "") -> str:
    color = palette["TEXT"]
    if tone == "up":
        color = palette["GREEN"]
    elif tone == "down":
        color = palette["RED"]
    delta_html = f'<div style="font-size:13px;color:{color};margin-top:4px">{delta}</div>' if delta else ""
    return (
        f'<div style="background:{palette["PANEL"]};border:1px solid {palette["GRID"]};'
        f'border-radius:10px;padding:16px 20px;height:100%">'
        f'<div style="color:{palette["MUTED"]};font-size:11px;letter-spacing:1.2px;'
        f'text-transform:uppercase;margin-bottom:6px">{label}</div>'
        f'<div style="color:{palette["TEXT"]};font-size:24px;font-weight:600;'
        f'font-variant-numeric:tabular-nums">{value}</div>'
        f'{delta_html}</div>'
    )


def _expl(palette: dict, text: str) -> str:
    """Tiny discrete explanatory caption rendered under a KPI card."""
    return (f'<div style="color:{palette["MUTED"]};font-size:10px;line-height:1.35;'
            f'font-style:italic;margin:4px 2px 10px 2px">{text}</div>')


def _section(palette: dict, title: str, subtitle: str = "") -> None:
    sub = f'<div style="color:{palette["MUTED"]};font-size:11px;font-style:italic">{subtitle}</div>' if subtitle else ""
    st.markdown(
        f'<div style="margin:8px 0 14px 0">'
        f'<div style="color:{palette["ACCENT"]};font-size:13px;font-weight:600;'
        f'letter-spacing:1.5px;text-transform:uppercase">{title}</div>{sub}'
        f'</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Sub-tab 1 — Risk Metrics
# ---------------------------------------------------------------------------

def _render_risk_metrics(static, price_history: pd.DataFrame, palette: dict) -> None:
    # VA6: use VL (unitized) instead of raw NAV — deposits/buys don't
    # contaminate returns with fake spikes that inflate vol & skew Sharpe.
    nav = _portfolio_vl_series(price_history)
    if len(nav) < 3:
        st.info(
            "Not enough history to compute meaningful risk metrics. "
            "At least ten or so days of data are needed. Wait for a few more "
            "sessions to be recorded and come back here."
        )
        st.metric("Days of history available", len(nav))
        return

    rets = _daily_returns(nav)

    # --- Inputs row ---
    c1, c2 = st.columns([1, 3])
    with c1:
        rf_pct = st.number_input(
            "Annual risk-free rate (%)",
            min_value=0.0, max_value=10.0,
            value=DEFAULT_RF * 100, step=0.25,
            help="Used for the Sharpe / Sortino calculation. Default ≈ €STR ~ 3%.",
            key="pro_rf",
        )
    rf = rf_pct / 100.0

    # --- Core stats ---
    n = len(rets)
    mean_d = rets.mean()
    std_d = rets.std(ddof=1)
    # Annualized return via EAR on the mean daily return: (1 + r̄)^252 − 1.
    # Compounds the average daily return over a trading year (the effective
    # annual rate), consistent with the EDR used for the risk-free rate below.
    ann_return = ((1.0 + mean_d) ** TRADING_DAYS - 1.0) if (n > 0 and pd.notna(mean_d)) else 0.0
    ann_vol = std_d * math.sqrt(TRADING_DAYS) if std_d > 0 else 0.0
    # EDR — effective DAILY risk-free rate via geometric compounding,
    # (1+rf)^(1/252) − 1, NOT the naive rf/252 (which ignores compounding).
    rf_d = (1.0 + rf) ** (1.0 / TRADING_DAYS) - 1.0
    excess_d = rets - rf_d
    # Sharpe / Sortino: annualize the MEAN daily excess return via EAR
    # (geometric), (1+r̄)^252 − 1, then divide by annualized risk. Volatility
    # always annualizes as σ·√252 — variance is additive in time, there is no
    # "EAR" for a standard deviation.
    ann_excess = (1.0 + excess_d.mean()) ** TRADING_DAYS - 1.0
    sharpe = (ann_excess / ann_vol) if ann_vol > 0 else float("nan")
    # Sortino: same EAR numerator, denominator = annualized DOWNSIDE DEVIATION
    # = sqrt(mean(min(r - rf_d, 0)^2)) · √252 (penalises only downside).
    below = np.minimum(excess_d.values, 0.0)
    downside_dev = math.sqrt(float(np.mean(below ** 2))) if len(excess_d) else 0.0
    ann_downside = downside_dev * math.sqrt(TRADING_DAYS)
    sortino = (ann_excess / ann_downside) if ann_downside > 0 else float("nan")

    # Drawdown
    cum_max = nav.cummax()
    drawdown = nav / cum_max - 1.0
    max_dd = drawdown.min()
    # Find the date of max drawdown trough and duration to recovery
    trough_date = drawdown.idxmin() if not drawdown.empty else None
    if trough_date is not None and pd.notna(max_dd) and max_dd < 0:
        peak_before = nav.loc[:trough_date].idxmax()
        # Recovery: first date AFTER trough where NAV >= peak_before's NAV
        after = nav.loc[trough_date:]
        peak_value = nav.loc[peak_before]
        rec = after[after >= peak_value]
        rec_date = rec.index[0] if not rec.empty else None
        dd_duration_days = ((rec_date or nav.index[-1]) - peak_before).days
        recovered = rec_date is not None
    else:
        peak_before = trough_date
        rec_date = None
        dd_duration_days = 0
        recovered = True

    # VaR — historical method (no normality assumption). Computable from ≥2
    # returns; noisy until there are more, but no longer left blank.
    var95 = float(np.quantile(rets, 0.05)) if n >= 2 else float("nan")
    var99 = float(np.quantile(rets, 0.01)) if n >= 2 else float("nan")
    # Conditional VaR (expected shortfall) at 95
    tail = rets[rets <= var95] if not np.isnan(var95) else rets.iloc[0:0]
    cvar95 = float(tail.mean()) if len(tail) else var95

    # Calmar (annualized return / |max DD|)
    calmar = (ann_return / abs(max_dd)) if max_dd and abs(max_dd) > 1e-9 else float("nan")

    # Small-sample caution: annualization (×√252, ^(252/n)) extrapolates a few
    # days to a full year, so with little history the annualized figures are
    # mathematically correct but statistically very noisy / inflated.
    if n < 20:
        st.warning(
            f"⚠️ Only {n} days of returns available. The **annualized** figures "
            "(return, volatility, Sharpe, Sortino) are unreliable extrapolations "
            "while history is short — they will stabilize after a few weeks of "
            "data. Max Drawdown, VaR and CVaR (not annualized) are already "
            "meaningful."
        )

    # --- KPI grid (2 rows of 4 cards each) ---
    def fmt_pct(v, d=2):
        if v is None or pd.isna(v) or (isinstance(v, float) and math.isinf(v)):
            return "—"
        return f"{v * 100:+.{d}f} %"

    def fmt_num(v, d=2):
        if v is None or pd.isna(v) or (isinstance(v, float) and math.isinf(v)):
            return "—"
        return f"{v:.{d}f}"

    _section(palette, "Risk Metrics",
             f"Computed over {n} daily returns ({nav.index[0].date()} → {nav.index[-1].date()}).")

    if n < 20:
        st.markdown(
            f"<div style='color:{palette['ACCENT']};font-size:11px;font-style:italic;"
            f"margin-bottom:8px'>⚠ Only {n} returns: the ratios below are "
            f"very noisy while history is short (reliable from ~30-60 days).</div>",
            unsafe_allow_html=True,
        )

    r1c1, r1c2, r1c3, r1c4 = st.columns(4)
    r1c1.markdown(_kpi("Annualized Return", fmt_pct(ann_return),
                       tone="up" if ann_return >= 0 else "down",
                       delta=f"mean daily {fmt_pct(mean_d, 4)}", palette=palette),
                  unsafe_allow_html=True)
    r1c1.markdown(_expl(palette, "Return extrapolated to 1 year. Equity benchmark: "
                        "<0 = loss · 0-7% = modest · 7-12% = good · >12% = very good."),
                  unsafe_allow_html=True)
    r1c2.markdown(_kpi("Annualized Volatility", fmt_pct(ann_vol),
                       delta=f"σ daily {fmt_pct(std_d, 4)}", palette=palette),
                  unsafe_allow_html=True)
    r1c2.markdown(_expl(palette, "Size of the swings (risk). "
                        "<10% = low · 10-20% = moderate · >20% = high."),
                  unsafe_allow_html=True)
    r1c3.markdown(_kpi("Sharpe Ratio", fmt_num(sharpe),
                       delta=f"vs rf {rf_pct:.2f} %",
                       tone="up" if (not pd.isna(sharpe) and sharpe > 1) else
                            ("down" if (not pd.isna(sharpe) and sharpe < 0) else ""),
                       palette=palette),
                  unsafe_allow_html=True)
    r1c3.markdown(_expl(palette, "Return per unit of total risk. "
                        "<0 = poor · 0-1 = average · 1-2 = good · >2 = excellent."),
                  unsafe_allow_html=True)
    r1c4.markdown(_kpi("Sortino Ratio", fmt_num(sortino),
                       delta="downside-only σ",
                       tone="up" if (not pd.isna(sortino) and sortino > 1) else "",
                       palette=palette),
                  unsafe_allow_html=True)
    r1c4.markdown(_expl(palette, "Like the Sharpe but penalizes only the downside "
                        "(ignores upside volatility). >1 = good · >2 = very good."),
                  unsafe_allow_html=True)

    r2c1, r2c2, r2c3, r2c4 = st.columns(4)
    r2c1.markdown(_kpi("Max Drawdown", fmt_pct(max_dd),
                       delta=(f"{dd_duration_days} d "
                              f"{'(recovered)' if recovered else '(unrecovered)'}"),
                       tone="down" if max_dd and max_dd < 0 else "",
                       palette=palette),
                  unsafe_allow_html=True)
    r2c1.markdown(_expl(palette, "Worst drop from a peak. "
                        ">-10% = comfortable · -10 to -30% = normal for equities · <-40% = severe."),
                  unsafe_allow_html=True)
    r2c2.markdown(_kpi("Calmar Ratio", fmt_num(calmar),
                       delta="return / |max DD|", palette=palette),
                  unsafe_allow_html=True)
    r2c2.markdown(_expl(palette, "Annualized return / worst drop. "
                        "<1 = weak · 1-3 = good · >3 = excellent."),
                  unsafe_allow_html=True)
    r2c3.markdown(_kpi("VaR 95 % (1d)", fmt_pct(var95),
                       delta=f"CVaR 95 {fmt_pct(cvar95)}",
                       tone="down" if var95 and var95 < 0 else "",
                       palette=palette),
                  unsafe_allow_html=True)
    r2c3.markdown(_expl(palette, "Daily loss exceeded ~1 day in 20 (adverse case). "
                        "Closer to 0 = better. CVaR = average loss beyond that threshold."),
                  unsafe_allow_html=True)
    r2c4.markdown(_kpi("VaR 99 % (1d)", fmt_pct(var99),
                       delta="historical quantile",
                       tone="down" if var99 and var99 < 0 else "",
                       palette=palette),
                  unsafe_allow_html=True)
    r2c4.markdown(_expl(palette, "Daily loss exceeded ~1 day in 100 "
                        "(extreme scenario). Measures tail risk."),
                  unsafe_allow_html=True)

    # --- Drawdown curve ---
    _section(palette, "Drawdown Curve",
             "Underperformance vs the previous peak, in %. The deeper the curve, the more the portfolio bled.")
    fig_dd = go.Figure()
    fig_dd.add_trace(go.Scatter(
        x=drawdown.index, y=drawdown.values * 100,
        mode="lines", line=dict(color=palette["RED"], width=1.5),
        fill="tozeroy", fillcolor="rgba(239,83,80,0.18)",
        hovertemplate="%{x|%d %b %Y}<br>%{y:.2f}%<extra></extra>",
    ))
    if trough_date is not None and max_dd < 0:
        # add_vline's annotation positioner can't handle date axes under
        # plotly+pandas 3.0, so draw the line bare and add a separate
        # annotation with explicit coordinates.
        td = pd.Timestamp(trough_date).isoformat()
        fig_dd.add_shape(type="line", x0=td, x1=td, yref="paper", y0=0, y1=1,
                         line=dict(color=palette["MUTED"], width=1, dash="dot"))
        fig_dd.add_annotation(x=td, yref="paper", y=1.0,
                              text=f"Trough {pd.Timestamp(trough_date).date()}",
                              showarrow=False, yshift=8,
                              font=dict(color=palette["MUTED"], size=10))
    _style_fig(fig_dd, palette, height=320, showlegend=False)
    fig_dd.update_yaxes(title="Drawdown (%)", ticksuffix="%")
    fig_dd.update_xaxes(rangebreaks=data.trading_day_rangebreaks(
        pd.DataFrame({"date": drawdown.index})))
    st.plotly_chart(fig_dd, width="stretch")

    # --- Returns distribution histogram ---
    _section(palette, "Distribution of Daily Returns",
             "Histogram of daily returns. Fat tails reveal non-Gaussian risk.")
    fig_hist = go.Figure()
    fig_hist.add_trace(go.Histogram(
        x=rets.values * 100,
        nbinsx=max(20, int(math.sqrt(n))),
        marker=dict(color=palette["ACCENT"], line=dict(color=palette["BG"], width=1)),
        hovertemplate="%{x:.2f} %<br>count %{y}<extra></extra>",
        name="Daily returns",
    ))
    # Markers for VaR
    if not pd.isna(var95):
        fig_hist.add_vline(x=var95 * 100,
                           line=dict(color=palette["RED"], width=1, dash="dash"),
                           annotation_text=f"VaR 95 {var95*100:.2f}%",
                           annotation_position="top",
                           annotation_font_color=palette["RED"])
    if not pd.isna(var99):
        fig_hist.add_vline(x=var99 * 100,
                           line=dict(color=palette["RED"], width=1.5, dash="dot"),
                           annotation_text=f"VaR 99 {var99*100:.2f}%",
                           annotation_position="bottom",
                           annotation_font_color=palette["RED"])
    _style_fig(fig_hist, palette, height=300, showlegend=False)
    fig_hist.update_xaxes(title="Daily return (%)", ticksuffix="%")
    fig_hist.update_yaxes(title="Count")
    st.plotly_chart(fig_hist, width="stretch")

    st.caption(
        "ℹ️ Beta vs benchmark is available in the “Benchmark Comparison” sub-tab. "
        "All other metrics are ready to use."
    )


# ---------------------------------------------------------------------------
# Sub-tab 2 — Calendar heatmap of monthly returns
# ---------------------------------------------------------------------------

def _render_calendar_heatmap(static, price_history: pd.DataFrame, palette: dict) -> None:
    # VA6: VL so monthly returns reflect market perf, not flows
    nav = _portfolio_vl_series(price_history)
    if len(nav) < 2:
        st.info("Not enough history yet to compute monthly returns.")
        return

    # Monthly returns = NAV end-of-month vs NAV end-of-previous-month
    monthly = nav.resample("ME").last()
    m_ret = monthly.pct_change().dropna()
    if m_ret.empty:
        st.info(
            "No closed month in the history yet. The first full month will appear here "
            "as soon as the DB covers two consecutive month-ends."
        )
        return

    df = m_ret.to_frame("ret")
    df["Year"] = df.index.year
    df["Month"] = df.index.month

    pivot = df.pivot(index="Year", columns="Month", values="ret").sort_index(ascending=False)
    # Ensure all 12 month columns exist
    for m in range(1, 13):
        if m not in pivot.columns:
            pivot[m] = np.nan
    pivot = pivot[list(range(1, 13))]

    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    _section(palette, "Calendar Heatmap — Monthly Returns",
             "Returns computed on end-of-month NAV. Green = positive month, red = negative month.")

    # Build text annotations
    text = pivot.map(lambda v: "" if pd.isna(v) else f"{v*100:+.2f}%").values

    fig = go.Figure(data=go.Heatmap(
        z=pivot.values * 100,
        x=month_names,
        y=[str(y) for y in pivot.index],
        colorscale=[[0.0, palette["RED"]], [0.5, palette["PANEL"]], [1.0, palette["GREEN"]]],
        zmid=0,
        text=text,
        texttemplate="%{text}",
        textfont=dict(size=13, color=palette["TEXT"]),
        hovertemplate="%{y} %{x}<br><b>%{z:+.2f}%</b><extra></extra>",
        colorbar=dict(title="%", tickfont=dict(color=palette["MUTED"])),
    ))
    _style_fig(fig, palette, height=max(220, 60 * len(pivot)), showlegend=False)
    fig.update_xaxes(side="top")
    st.plotly_chart(fig, width="stretch")

    # Year-level summary
    yearly = (1 + df["ret"]).groupby(df["Year"]).prod() - 1
    if not yearly.empty:
        _section(palette, "Yearly Returns")
        cols = st.columns(min(len(yearly), 6))
        for i, (year, val) in enumerate(yearly.items()):
            tone = "up" if val >= 0 else "down"
            cols[i % len(cols)].markdown(
                _kpi(str(year), f"{val*100:+.2f} %", tone=tone, palette=palette),
                unsafe_allow_html=True,
            )

    # Best / worst month
    if len(m_ret) >= 1:
        best = m_ret.idxmax()
        worst = m_ret.idxmin()
        b1, b2 = st.columns(2)
        b1.markdown(_kpi("Best Month", f"{m_ret.max()*100:+.2f} %",
                         delta=best.strftime("%B %Y"), tone="up", palette=palette),
                    unsafe_allow_html=True)
        b2.markdown(_kpi("Worst Month", f"{m_ret.min()*100:+.2f} %",
                         delta=worst.strftime("%B %Y"), tone="down", palette=palette),
                    unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Sub-tab 4 — Correlation matrix
# ---------------------------------------------------------------------------

def _render_correlation(static, price_history: pd.DataFrame, snapshot: dict, palette: dict) -> None:
    if len(price_history) < 3:
        st.info("Not enough history to compute meaningful correlations.")
        return

    # Pct_change with NaN preserved (no global dropna) → pandas.corr() does
    # PAIRWISE-complete-obs by default: each (i,j) cell uses the rows where
    # both i AND j have valid data, independent of the other assets.
    # → Asset A bought in 2020 vs Asset B bought in 2025 : the (A,B) cell
    #   uses their ~1 year of common dates, while (A, longstanding_etf)
    #   keeps using all 6 years.
    df = price_history.sort_values("date").set_index("date")[list(data.ASSETS)]
    rets = df.pct_change()
    if rets.dropna(how="all").empty:
        st.info("Returns unavailable.")
        return

    # Pairwise correlation + observation count per pair (for hover tooltip)
    corr = rets.corr()
    valid = rets.notna().astype(int)
    n_obs = valid.T.dot(valid)   # symmetric N×N matrix of common observation counts

    max_obs = int(n_obs.values.max())
    _section(palette, "Correlation Matrix",
             f"Daily-return correlation — computed pairwise over each pair's "
             f"common dates (up to {max_obs} sessions). "
             f"+1 = perfectly linked (green), 0 = independent (yellow), "
             f"-1 = inversely linked (red).")

    # Text labels (NaN → em-dash for unavailable pairs)
    text = corr.map(lambda v: f"{v:.2f}" if pd.notna(v) else "—").values

    # VA3 — Excel-style red → yellow → green colorscale (matches user's reference)
    corr_colorscale = [
        [0.0,  "#F8696B"],   # z=-1.0 → Excel red
        [0.25, "#FBA075"],   # z=-0.5 → peach
        [0.5,  "#FFEB84"],   # z= 0.0 → Excel yellow
        [0.75, "#A4D080"],   # z=+0.5 → light green
        [1.0,  "#63BE7B"],   # z=+1.0 → Excel green
    ]
    fig = go.Figure(data=go.Heatmap(
        z=corr.values,
        x=list(corr.columns),
        y=list(corr.index),
        colorscale=corr_colorscale,
        zmid=0, zmin=-1, zmax=1,
        text=text,
        texttemplate="%{text}",
        textfont=dict(size=13, color="#0B0C0F"),
        customdata=n_obs.values,
        hovertemplate=(
            "<b>%{y} ↔ %{x}</b><br>"
            "ρ = %{z:.3f}<br>"
            "n = %{customdata} obs<extra></extra>"
        ),
        colorbar=dict(title="ρ", tickfont=dict(color=palette["MUTED"])),
    ))
    _style_fig(fig, palette, height=520, showlegend=False)
    st.plotly_chart(fig, width="stretch")

    # Highlight notable pairs
    pairs = []
    for i, a in enumerate(corr.index):
        for j, b in enumerate(corr.columns):
            if j > i:
                pairs.append((a, b, float(corr.iloc[i, j])))
    pairs.sort(key=lambda x: -x[2])

    if pairs:
        top_pos = pairs[:3]
        top_neg = sorted(pairs, key=lambda x: x[2])[:3]

        # Pre-extract colors to avoid escaping inside f-strings
        p_panel = palette["PANEL"]
        p_grid = palette["GRID"]
        p_text = palette["TEXT"]
        p_muted = palette["MUTED"]
        p_green = palette["GREEN"]
        p_red = palette["RED"]

        c1, c2 = st.columns(2)
        with c1:
            _section(palette, "Most correlated pairs",
                     "These assets move together — limited diversification between them.")
            for a, b, v in top_pos:
                st.markdown(
                    f"<div style='background:{p_panel};border:1px solid {p_grid};"
                    f"border-radius:8px;padding:10px 14px;margin-bottom:6px;"
                    f"font-variant-numeric:tabular-nums'>"
                    f"<b style='color:{p_text}'>{a}</b> "
                    f"<span style='color:{p_muted}'> ↔ </span>"
                    f"<b style='color:{p_text}'>{b}</b>"
                    f"<span style='float:right;color:{p_green};font-weight:600'>"
                    f"ρ = {v:.3f}</span></div>",
                    unsafe_allow_html=True,
                )
        with c2:
            _section(palette, "Least correlated pairs",
                     "These assets genuinely add diversification to the portfolio.")
            for a, b, v in top_neg:
                color = p_red if v < 0 else p_text
                st.markdown(
                    f"<div style='background:{p_panel};border:1px solid {p_grid};"
                    f"border-radius:8px;padding:10px 14px;margin-bottom:6px;"
                    f"font-variant-numeric:tabular-nums'>"
                    f"<b style='color:{p_text}'>{a}</b> "
                    f"<span style='color:{p_muted}'> ↔ </span>"
                    f"<b style='color:{p_text}'>{b}</b>"
                    f"<span style='float:right;color:{color};font-weight:600'>"
                    f"ρ = {v:.3f}</span></div>",
                    unsafe_allow_html=True,
                )

    # Diversification score = (1 − weighted average pairwise correlation) × 100.
    # The average is WEIGHTED by each pair's portfolio weights (wᵢ·wⱼ): a big
    # position's co-movements matter more than a tiny one's. ρ̄ = Σ wᵢwⱼρᵢⱼ / Σ wᵢwⱼ
    # over distinct pairs (a simple unweighted mean would be meaningless here).
    _w = {a: float((snapshot.get("positions", {}).get(a, {}) or {}).get("allocation", 0.0) or 0.0)
          for a in corr.index}
    _num = _den = 0.0
    for a, b, rho in pairs:
        if pd.notna(rho):
            wab = _w.get(a, 0.0) * _w.get(b, 0.0)
            _num += wab * rho
            _den += wab
    if _den > 0:
        avg = _num / _den
    else:   # no weights available (e.g. snapshot empty) → fall back to plain mean
        valid = [v for _, _, v in pairs if pd.notna(v)]
        avg = (sum(valid) / len(valid)) if valid else float("nan")
    score = (1 - avg) * 100  # 0 = all moves together, 100 = all uncorrelated
    st.markdown(
        f"<div style='margin-top:14px;background:{palette['PANEL']};"
        f"border:1px solid {palette['GRID']};border-radius:10px;padding:14px 18px'>"
        f"<div style='color:{palette['MUTED']};font-size:11px;letter-spacing:1.2px;"
        f"text-transform:uppercase'>Diversification Score</div>"
        f"<div style='color:{palette['TEXT']};font-size:24px;font-weight:600;"
        f"font-variant-numeric:tabular-nums'>{score:.1f} / 100</div>"
        f"<div style='color:{palette['MUTED']};font-size:11px;font-style:italic'>"
        f"= (1 − weight-weighted ρ̄) × 100. Above 60 = good diversification, "
        f"below 30 = highly correlated portfolio.</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Sub-tab 3 — Performance Attribution
# ---------------------------------------------------------------------------

def _render_attribution(static, price_history: pd.DataFrame, palette: dict) -> None:
    if len(price_history) < 2:
        st.info("Not enough history to compute an attribution.")
        return

    # Work in PORTFOLIO currency so per-asset returns (and the NAV sums) include
    # FX moves and match the Positions tab / snapshot (no native-vs-PF mismatch).
    hist = data.price_history_in_portfolio_currency(price_history).sort_values("date").reset_index(drop=True)
    pf_ccy = data.current_portfolio_currency()
    min_d = hist["date"].min().date()
    max_d = hist["date"].max().date()

    _section(palette, "Performance Attribution",
             "Breakdown of the portfolio return into per-ETF contributions "
             "(contribution = initial weight × asset return).")

    c1, c2 = st.columns(2)
    with c1:
        att_from = st.date_input("From", min_d, min_value=min_d, max_value=max_d, key="att_from")
    with c2:
        att_to = st.date_input("To", max_d, min_value=min_d, max_value=max_d, key="att_to")
    if att_from >= att_to:
        st.warning("The end date must be strictly after the start date.")
        return

    mask = (hist["date"].dt.date >= att_from) & (hist["date"].dt.date <= att_to)
    sub = hist.loc[mask]
    if len(sub) < 2:
        st.warning("The selected period must contain at least 2 sessions.")
        return

    last = sub.iloc[-1]

    # Base price per asset, consistent with the rest of the app:
    #  - acquired WITHIN the period → its EXACT purchase price (real perf since buy)
    #  - held coming into the period → the first close inside the window
    # (An asset with no price at att_from used to be dropped entirely; here it
    # still appears, measured from its own start.)
    cost_map = getattr(data, "avg_cost_by_asset", lambda: {})()   # {asset: (date, avg cost)}
    per_start: dict[str, float] = {}
    for a in data.ASSETS:
        if a not in sub.columns or pd.isna(last[a]):
            continue
        col_valid = sub[a].dropna()
        if col_valid.empty:
            continue
        cb = cost_map.get(a)
        if cb and att_from <= cb[0] <= att_to:
            # weighted-average cost, converted to portfolio currency at the buy
            # date so it's comparable to the PF-converted closes in `sub`.
            a_ccy = (static.currencies.get(a) or pf_ccy).upper()
            rate = 1.0 if a_ccy == pf_ccy else data.fx_rate(a_ccy, pf_ccy, cb[0])
            per_start[a] = float(cb[1]) * rate
        else:
            per_start[a] = float(col_valid.iloc[0])  # first close in the window (already PF)
    period_assets = list(per_start.keys())

    nav_start = sum(per_start[a] * static.shares.get(a, 0) for a in period_assets)
    nav_end = sum(float(last[a]) * static.shares.get(a, 0) for a in period_assets)
    total_ret = (nav_end / nav_start) - 1.0 if nav_start else 0.0

    rows = []
    for a in period_assets:
        p0 = per_start[a]; p1 = float(last[a]); sh = static.shares.get(a, 0)
        w0 = (p0 * sh) / nav_start if nav_start else 0.0
        r = (p1 / p0 - 1.0) if p0 else 0.0
        contrib = w0 * r
        rows.append({
            "Asset": a, "Start €": p0 * sh, "End €": p1 * sh,
            "Weight start": w0, "Return": r, "Contribution": contrib,
        })
    if not rows:
        st.info("No valuable asset over this period — add transactions "
                "or widen the date range.")
        return
    att = pd.DataFrame(rows).sort_values("Contribution", ascending=True)

    # KPI row
    days_in_period = (att_to - att_from).days
    k1, k2, k3 = st.columns(3)
    tone = "up" if total_ret >= 0 else "down"
    k1.markdown(_kpi("Total Return (period)", f"{total_ret*100:+.2f} %",
                     delta=f"{days_in_period} days calendar", tone=tone, palette=palette),
                unsafe_allow_html=True)
    k2.markdown(_kpi("NAV Start", f"{nav_start:,.2f} €",
                     delta=str(att_from), palette=palette), unsafe_allow_html=True)
    k3.markdown(_kpi("NAV End", f"{nav_end:,.2f} €",
                     delta=str(att_to), palette=palette), unsafe_allow_html=True)

    # Contribution bar chart
    fig = go.Figure()
    fig.add_bar(
        x=att["Contribution"] * 100,
        y=att["Asset"],
        orientation="h",
        marker=dict(
            color=[palette["GREEN"] if v >= 0 else palette["RED"] for v in att["Contribution"]],
            line=dict(color=palette["BG"], width=1),
        ),
        customdata=att[["Weight start", "Return"]].values * 100,
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Start weight : %{customdata[0]:.2f} %<br>"
            "Asset return : %{customdata[1]:+.2f} %<br>"
            "Contribution : %{x:+.3f} pts<extra></extra>"
        ),
        text=[f"{v*100:+.3f} pts" for v in att["Contribution"]],
        textposition="outside",
        textfont=dict(color=palette["TEXT"], size=11),
        cliponaxis=False,
    )
    fig.add_vline(x=0, line=dict(color=palette["MUTED"], width=1, dash="dot"))
    _style_fig(fig, palette, height=420, showlegend=False)
    # Pad x-range so outside labels stay inside the plot frame
    _vals = (att["Contribution"] * 100).tolist()
    _lo = min(min(_vals), 0.0); _hi = max(max(_vals), 0.0)
    _span = max(abs(_lo), abs(_hi), 0.5)
    fig.update_xaxes(title="Contribution to total return (percentage points)",
                      ticksuffix=" pts",
                      range=[_lo / 100 - _span * 0.30 / 100 - 0.005,
                             _hi / 100 + _span * 0.30 / 100 + 0.005])
    fig.update_yaxes(title=None)
    st.plotly_chart(fig, width="stretch")

    # ---- Per-asset performance over the period (vertical bars, % on top) ----
    _section(palette, "Per-asset performance over the period",
             f"Return of each asset between {att_from} and {att_to} "
             f"(weight-independent — pure price performance).")
    perf = att.sort_values("Return", ascending=False)
    fig_perf = go.Figure()
    fig_perf.add_bar(
        x=perf["Asset"],
        y=perf["Return"] * 100,
        marker=dict(
            color=[color_for_asset(a, i) for i, a in enumerate(perf["Asset"])],
            line=dict(color=palette["BG"], width=1),
        ),
        text=[f"{v*100:+.2f}%" for v in perf["Return"]],
        textposition="outside",
        textfont=dict(color=palette["TEXT"], size=12),
        hovertemplate="<b>%{x}</b><br>Period return: %{y:+.2f}%<extra></extra>",
        cliponaxis=False,
    )
    fig_perf.add_hline(y=0, line=dict(color=palette["MUTED"], width=1, dash="dot"))
    _style_fig(fig_perf, palette, height=420, showlegend=False)
    fig_perf.update_xaxes(title=None, tickangle=-30)
    fig_perf.update_yaxes(title="Performance (%)", ticksuffix="%")
    # headroom for the outside labels — generous padding so % labels stay visible
    if not perf.empty:
        lo = min(0.0, float((perf["Return"] * 100).min()))
        hi = max(0.0, float((perf["Return"] * 100).max()))
        pad = max((hi - lo) * 0.30, 1.0)
        fig_perf.update_yaxes(range=[lo - pad, hi + pad])
    st.plotly_chart(fig_perf, width="stretch")

    # Detail table
    _section(palette, "Detail table")
    tbl = att.sort_values("Contribution", ascending=False).copy()
    tbl["Start €"] = tbl["Start €"].map(lambda v: f"{v:,.2f} €")
    tbl["End €"] = tbl["End €"].map(lambda v: f"{v:,.2f} €")
    tbl["Weight start"] = tbl["Weight start"].map(lambda v: f"{v*100:.2f} %")
    tbl["Return"] = tbl["Return"].map(lambda v: f"{v*100:+.2f} %")
    tbl["Contribution"] = tbl["Contribution"].map(lambda v: f"{v*100:+.3f} pts")
    st.dataframe(tbl, width="stretch", hide_index=True)

    # Identity check
    sum_contrib = att["Contribution"].sum()
    delta = abs(sum_contrib - total_ret) * 100
    st.caption(
        f"ℹ️ Σ contributions = {sum_contrib*100:+.4f} % · Total return = {total_ret*100:+.4f} % · "
        f"gap = {delta:.4f} pp (should be ≈ 0; small difference due to weight "
        f"drift over the period)."
    )


# ---------------------------------------------------------------------------
# Sub-tab 5 — Benchmark Comparison
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False, ttl=3600)
def _fetch_benchmark(ticker: str, start: dt.date, end: dt.date) -> pd.Series:
    """Fetch a benchmark price series and cache it for an hour."""
    import yfinance as yf
    end_excl = end + dt.timedelta(days=1)
    try:
        hist = yf.Ticker(ticker).history(
            start=start.isoformat(), end=end_excl.isoformat(),
            interval="1d", auto_adjust=True,
        )
        if hist.empty:
            return pd.Series(dtype=float)
        series = hist["Close"].dropna()
        series.index = pd.to_datetime(series.index).tz_localize(None)
        return series
    except Exception:
        return pd.Series(dtype=float)


def _render_benchmark(static, price_history: pd.DataFrame, palette: dict) -> None:
    if len(price_history) < 2:
        st.info("Not enough history to compare against a benchmark.")
        return

    _section(palette, "Benchmark Comparison",
             "Compare your NAV against a reference benchmark. Both indexed to 100 on "
             "the first history date for a direct read.")

    bm_choice = st.selectbox(
        "Benchmark",
        options=list(BENCHMARKS.keys()),
        index=0,
        help="Choose your reference benchmark.",
        key="bm_choice",
    )

    # VA6: VL = fair comparison vs benchmark (both reflect pure perf)
    nav = _portfolio_vl_series(price_history)
    if nav.empty:
        st.info("NAV unavailable.")
        return

    bm_info = BENCHMARKS[bm_choice]
    start_d = nav.index[0].date()
    end_d = nav.index[-1].date()

    if bm_info["ticker"] is None:
        # 60/40 custom mix — World 60% + Bond AGG 40%
        with st.spinner("Fetching benchmark components…"):
            world = _fetch_benchmark("IWDA.AS", start_d, end_d)
            bond = _fetch_benchmark("AGGH.AS", start_d, end_d)
        if world.empty or bond.empty:
            st.error("Could not fetch the 60/40 benchmark components.")
            return
        # Align both series, normalize to 100 at start, then weighted
        joined = pd.concat([world, bond], axis=1, keys=["world", "bond"]).ffill().dropna()
        joined = joined / joined.iloc[0] * 100
        bm = (0.6 * joined["world"] + 0.4 * joined["bond"]).rename(bm_info["label"])
    else:
        with st.spinner(f"Fetching {bm_info['ticker']}…"):
            bm = _fetch_benchmark(bm_info["ticker"], start_d, end_d)
        if bm.empty:
            st.error(f"No data for {bm_info['ticker']}.")
            return

    # Align dates with portfolio NAV
    common = nav.index.intersection(bm.index)
    if len(common) < 2:
        st.warning(
            f"Too few common dates between your NAV ({len(nav)} days) and the benchmark "
            f"({len(bm)} days). Try again when the history is longer."
        )
        return

    nav_a = nav.loc[common]
    bm_a = bm.loc[common]

    # Normalize both to 100 at start
    nav_idx = nav_a / nav_a.iloc[0] * 100
    bm_idx = bm_a / bm_a.iloc[0] * 100

    # ---- Indexed performance chart ----
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=nav_idx.index, y=nav_idx.values, mode="lines",
        line=dict(color=palette["ACCENT"], width=2.5),
        name="GPCP", hovertemplate="%{x|%d %b %Y}<br><b>%{y:.2f}</b><extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=bm_idx.index, y=bm_idx.values, mode="lines",
        line=dict(color=palette["MUTED"], width=2, dash="dot"),
        name=bm_info["label"], hovertemplate="%{x|%d %b %Y}<br><b>%{y:.2f}</b><extra></extra>",
    ))
    _style_fig(fig, palette, height=380)
    fig.update_yaxes(title="Indexed (100 = start)")
    fig.update_xaxes(rangebreaks=data.trading_day_rangebreaks(
        pd.DataFrame({"date": nav_idx.index})))
    st.plotly_chart(fig, width="stretch")

    # ---- Stats ----
    nav_rets = nav_a.pct_change().dropna()
    bm_rets = bm_a.pct_change().dropna()
    common_rets = nav_rets.index.intersection(bm_rets.index)
    nav_rets = nav_rets.loc[common_rets]
    bm_rets = bm_rets.loc[common_rets]
    excess = nav_rets - bm_rets

    # Annualized alpha = mean(excess) * 252
    alpha = excess.mean() * TRADING_DAYS if len(excess) else float("nan")
    # Tracking error = std(excess) * sqrt(252)
    te = excess.std(ddof=1) * math.sqrt(TRADING_DAYS) if len(excess) > 1 else float("nan")
    ir = (alpha / te) if te and te > 0 else float("nan")
    # Beta vs benchmark
    if len(common_rets) >= 2 and bm_rets.var() > 0:
        beta = float(np.cov(nav_rets, bm_rets, ddof=1)[0, 1] / bm_rets.var(ddof=1))
    else:
        beta = float("nan")
    # Correlation
    corr = float(nav_rets.corr(bm_rets)) if len(common_rets) >= 2 else float("nan")

    # Total returns over the common window
    nav_tot = nav_a.iloc[-1] / nav_a.iloc[0] - 1
    bm_tot = bm_a.iloc[-1] / bm_a.iloc[0] - 1
    outperf = nav_tot - bm_tot

    def fmt_pct(v, d=2):
        if v is None or pd.isna(v) or (isinstance(v, float) and math.isinf(v)):
            return "—"
        return f"{v*100:+.{d}f} %"

    def fmt_num(v, d=2):
        if v is None or pd.isna(v) or (isinstance(v, float) and math.isinf(v)):
            return "—"
        return f"{v:.{d}f}"

    _section(palette, "Relative performance statistics")
    c1, c2, c3, c4 = st.columns(4)
    tone = "up" if outperf >= 0 else "down"
    c1.markdown(_kpi("Outperformance", fmt_pct(outperf),
                     delta=f"GPCP {fmt_pct(nav_tot)} vs BM {fmt_pct(bm_tot)}",
                     tone=tone, palette=palette), unsafe_allow_html=True)
    c2.markdown(_kpi("Alpha (annualized)", fmt_pct(alpha),
                     delta="mean(excess) × 252",
                     tone="up" if alpha > 0 else "down", palette=palette),
                unsafe_allow_html=True)
    c3.markdown(_kpi("Tracking Error", fmt_pct(te),
                     delta="σ(excess) × √252", palette=palette),
                unsafe_allow_html=True)
    c4.markdown(_kpi("Information Ratio", fmt_num(ir),
                     delta="alpha / TE",
                     tone="up" if (not pd.isna(ir) and ir > 0.5) else "",
                     palette=palette), unsafe_allow_html=True)

    c5, c6 = st.columns(2)
    c5.markdown(_kpi("Beta", fmt_num(beta),
                     delta=f"sensitivity to {bm_info['label']}",
                     palette=palette), unsafe_allow_html=True)
    c6.markdown(_kpi("Correlation", fmt_num(corr),
                     delta=f"over {len(common_rets)} daily returns",
                     palette=palette), unsafe_allow_html=True)

    # ---- Relative outperformance chart ----
    rel = (nav_idx - bm_idx)
    _section(palette, "Cumulative outperformance (index points)",
             "GPCP − Benchmark. Above zero = you beat the market, below = you underperform.")
    fig_rel = go.Figure()
    fig_rel.add_trace(go.Scatter(
        x=rel.index, y=rel.values, mode="lines",
        line=dict(color=palette["ACCENT"], width=1.8),
        fill="tozeroy",
        fillcolor=("rgba(38,166,154,0.18)" if rel.iloc[-1] >= 0 else "rgba(239,83,80,0.18)"),
        hovertemplate="%{x|%d %b %Y}<br><b>%{y:+.2f}</b> pts<extra></extra>",
    ))
    fig_rel.add_hline(y=0, line=dict(color=palette["MUTED"], width=1, dash="dot"))
    _style_fig(fig_rel, palette, height=280, showlegend=False)
    fig_rel.update_yaxes(title="Cumulative gap (index pts)")
    fig_rel.update_xaxes(rangebreaks=data.trading_day_rangebreaks(
        pd.DataFrame({"date": rel.index})))
    st.plotly_chart(fig_rel, width="stretch")


# ---------------------------------------------------------------------------
# Sub-tab 6 — Monte Carlo Simulator
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def _mc_simulate(nav0: float, mu_d: float, sigma_d: float, n_steps: int,
                 n_sims: int, contrib_daily: float, n_sample: int = 40):
    """Vectorized GBM Monte Carlo — the heavy part of the simulator.

    Fixed seed → deterministic, so it's safe to cache: identical inputs return
    the identical result instead of re-running tens of millions of draws on every
    Streamlit rerun (st.tabs re-executes this whole tab each time). Returns the
    P10/P50/P90 bands, terminal NAVs, and a small sample of paths (fan chart)."""
    rng = np.random.default_rng(42)
    drift = mu_d - 0.5 * sigma_d ** 2
    shocks = rng.normal(drift, sigma_d, size=(n_steps, n_sims))
    growth = np.exp(np.cumsum(shocks, axis=0))
    paths = nav0 * growth
    if contrib_daily > 0:
        paths = paths + np.cumsum(np.ones((n_steps, 1)) * contrib_daily * growth, axis=0)
    terminal = paths[-1, :]
    p10 = np.percentile(paths, 10, axis=1)
    p50 = np.percentile(paths, 50, axis=1)
    p90 = np.percentile(paths, 90, axis=1)
    sample_idx = rng.choice(n_sims, size=min(n_sample, n_sims), replace=False)
    return p10, p50, p90, terminal, paths[:, sample_idx]


def _render_monte_carlo(static, price_history: pd.DataFrame,
                          snapshot: dict, palette: dict) -> None:
    # VA6: calibrate GBM on VL returns (pure market perf, no flow contamination)
    # but START the simulation at the REAL CURRENT NAV in € so projected paths
    # are in real money. Otherwise "NAV de départ" would show ~100 (VL base).
    nav = _portfolio_vl_series(price_history)
    if len(nav) < 3:
        st.info(
            "Monte Carlo needs at least ten or so sessions to calibrate historical "
            "volatility and return. Come back in 2-3 weeks."
        )
        return

    rets = _daily_returns(nav)
    mu_d = rets.mean()
    sigma_d = rets.std(ddof=1)
    mu_a = mu_d * TRADING_DAYS
    sigma_a = sigma_d * math.sqrt(TRADING_DAYS) if sigma_d > 0 else 0.0

    # Real-money starting point — current portfolio NAV in pf_ccy
    nav_eur_now = float(snapshot.get("total_value") or 0.0)
    if nav_eur_now <= 0:
        # Fallback if snapshot empty: use VL last value (rare edge case)
        nav_eur_now = float(nav.iloc[-1])

    _section(palette, "Monte Carlo Simulator",
             f"Simulation of N GBM paths calibrated on your history: μ = "
             f"{mu_a*100:.2f} %/yr, σ = {sigma_a*100:.2f} %/yr. "
             f"Start: current NAV = {nav_eur_now:,.0f} €. "
             f"P10 / P50 / P90 percentiles and probability of reaching a target.")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        horizon_y = st.selectbox("Horizon", options=[1, 3, 5, 10, 20], index=2,
                                  format_func=lambda x: f"{x} year" + ("s" if x > 1 else ""),
                                  key="mc_horizon")
    with c2:
        n_sims = st.selectbox("Simulations", options=[1000, 5000, 10000, 25000], index=2,
                              key="mc_n")
    with c3:
        contrib_monthly = st.number_input("Monthly contribution (€)", min_value=0, value=0, step=100,
                                          key="mc_contrib", help="Optional — simulates DCA.")
    with c4:
        target = st.number_input("NAV target (€)", min_value=0,
                                 value=int(nav_eur_now * 2), step=1000,
                                 key="mc_target",
                                 help="Probability of reaching this amount at the horizon.")

    n_steps = horizon_y * TRADING_DAYS

    # Vectorized GBM simulation — starts at current NAV in € (not VL ~100)
    nav0 = nav_eur_now
    contrib_daily = contrib_monthly * 12 / TRADING_DAYS  # smoothed daily

    # Heavy GBM sim is cached (fixed seed → deterministic) so it doesn't re-run
    # on every Streamlit rerun. Contributions smoothed daily (DCA approximation).
    p10, p50, p90, terminal, samples = _mc_simulate(
        nav0, mu_d, sigma_d, n_steps, n_sims, contrib_daily)

    # Build x-axis as future dates
    last_date = nav.index[-1]
    future_dates = pd.bdate_range(last_date + pd.Timedelta(days=1), periods=n_steps)

    fig = go.Figure()
    # Sample a few individual paths (faint) to give texture
    for i in range(samples.shape[1]):
        fig.add_trace(go.Scatter(
            x=future_dates, y=samples[:, i],
            mode="lines", line=dict(color=palette["MUTED"], width=0.5),
            opacity=0.15, hoverinfo="skip", showlegend=False,
        ))
    # P10 / P90 fan
    fig.add_trace(go.Scatter(
        x=future_dates, y=p90, mode="lines", line=dict(width=0),
        name="P90", hovertemplate="%{x|%d %b %Y}<br>P90: %{y:,.0f} €<extra></extra>",
        showlegend=False,
    ))
    fig.add_trace(go.Scatter(
        x=future_dates, y=p10, mode="lines", line=dict(width=0),
        fill="tonexty", fillcolor="rgba(255,136,0,0.15)",
        name="P10–P90 range",
        hovertemplate="%{x|%d %b %Y}<br>P10: %{y:,.0f} €<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=future_dates, y=p50, mode="lines",
        line=dict(color=palette["ACCENT"], width=2.5),
        name="Median (P50)",
        hovertemplate="%{x|%d %b %Y}<br>P50: %{y:,.0f} €<extra></extra>",
    ))
    # Starting point
    fig.add_hline(y=nav0, line=dict(color=palette["MUTED"], width=1, dash="dot"),
                  annotation_text=f"NAV today {nav0:,.0f} €",
                  annotation_position="bottom left",
                  annotation_font_color=palette["MUTED"])
    if target > 0:
        fig.add_hline(y=target, line=dict(color=palette["GREEN"], width=1.2, dash="dash"),
                      annotation_text=f"Target {target:,.0f} €",
                      annotation_position="top left",
                      annotation_font_color=palette["GREEN"])
    _style_fig(fig, palette, height=480)
    fig.update_yaxes(title="Simulated NAV (€)", tickformat=",.0f", ticksuffix=" €")
    st.plotly_chart(fig, width="stretch")

    # KPI cards
    prob_target = float((terminal >= target).mean() * 100) if target > 0 else float("nan")
    prob_loss = float((terminal < nav0).mean() * 100)
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(_kpi(f"Median (P50) at {horizon_y}y",
                     f"{np.median(terminal):,.0f} €",
                     delta=f"× {np.median(terminal)/nav0:.2f}",
                     palette=palette), unsafe_allow_html=True)
    c2.markdown(_kpi("P10 (pessimistic)",
                     f"{np.percentile(terminal, 10):,.0f} €",
                     delta=f"× {np.percentile(terminal,10)/nav0:.2f}",
                     tone="down", palette=palette), unsafe_allow_html=True)
    c3.markdown(_kpi("P90 (optimistic)",
                     f"{np.percentile(terminal, 90):,.0f} €",
                     delta=f"× {np.percentile(terminal,90)/nav0:.2f}",
                     tone="up", palette=palette), unsafe_allow_html=True)
    c4.markdown(_kpi("P(target reached)",
                     f"{prob_target:.1f} %" if not pd.isna(prob_target) else "—",
                     delta=f"P(loss vs today) {prob_loss:.1f} %",
                     tone="up" if (not pd.isna(prob_target) and prob_target > 50) else "",
                     palette=palette), unsafe_allow_html=True)

    # Terminal distribution histogram
    _section(palette, "Terminal distribution", f"NAV after {horizon_y} year(s)")
    fig_hist = go.Figure()
    fig_hist.add_trace(go.Histogram(
        x=terminal, nbinsx=60,
        marker=dict(color=palette["ACCENT"], line=dict(color=palette["BG"], width=1)),
        hovertemplate="%{x:,.0f} €<br>count %{y}<extra></extra>",
    ))
    fig_hist.add_vline(x=nav0, line=dict(color=palette["MUTED"], width=1, dash="dot"),
                      annotation_text="NAV today", annotation_font_color=palette["MUTED"])
    if target > 0:
        fig_hist.add_vline(x=target, line=dict(color=palette["GREEN"], width=1.2, dash="dash"),
                          annotation_text="Target", annotation_font_color=palette["GREEN"])
    _style_fig(fig_hist, palette, height=300, showlegend=False)
    fig_hist.update_xaxes(title="Terminal NAV (€)", tickformat=",.0f", ticksuffix=" €")
    st.plotly_chart(fig_hist, width="stretch")

    st.caption(
        "ℹ️ The model assumes i.i.d. log-normal returns — reliable around the center but "
        "underestimates extreme crashes (thin tails). It's an order of magnitude, not a prediction."
    )

    # ---- Pedagogical explainer (collapsible) ----
    med = float(np.median(terminal))
    with st.expander("❓ How does it work? (data used + method explained)"):
        st.markdown(
            f"""
**In one sentence:** we replay the next {horizon_y} year(s) of your portfolio
**{n_sims:,}** times, drawing a random daily return each day *calibrated on your
real history*, then we look at the distribution of outcomes.

---

**1. The data used (measured on your history)**

| Data | Value | Where it comes from |
|---|---|---|
| Mean daily return (μ) | {mu_d*100:.4f} % /day | average of your daily returns |
| Daily volatility (σ) | {sigma_d*100:.4f} % /day | standard deviation of your daily returns |
| → annualized | μ ≈ {mu_a*100:.2f} % /yr · σ ≈ {sigma_a*100:.2f} % /yr | × 252 (and √252 for σ) |
| Starting NAV | {nav0:,.0f} € | your current value |
| Simulated monthly contribution | {contrib_monthly:,} € | your setting (DCA) |
| Horizon | {horizon_y} year(s) = {n_steps} trading days | your setting |

**2. The method: "Geometric Brownian Motion" (GBM)**

It's finance's standard model for simulating a price. Each day:

```
daily_return  =  (μ − ½σ²)  +  σ × (random Gaussian draw)
                  └─ drift ─┘   └──── market randomness ────┘
```

- The **drift** nudges gently upward (if μ>0).
- The **random draw** (a "normal distribution") adds the daily noise: some days
  go up, others down, with a magnitude set by σ.
- We chain {n_steps} days → **one path**. We repeat {n_sims:,} times →
  **{n_sims:,} paths**, all different.

**3. Reading the result**

Over the {n_sims:,} path endings, we rank the final NAVs and take:
- **P10** = the 10th percentile → only 10% of scenarios do worse (pessimistic case).
- **P50** (median) = half do better, half worse → **{med:,.0f} €**.
- **P90** = optimistic case (10% do better).
- **P(target reached)** = share of paths ending ≥ your target.

**4. Limitations to keep in mind**
- The model assumes future μ and σ resemble the past — wrong during a regime change.
- It **underestimates extreme crashes** (real markets have "fat tails").
- With little history, μ and σ are poorly estimated → take results with a pinch of salt.

👉 **It's a range of possibilities, not a prediction.** The point: to visualize
*risk* (P10↔P90 spread), not to guess an exact figure.
            """
        )


# ---------------------------------------------------------------------------
# Sub-tab 8 — Sector / Geographic Exposure
# ---------------------------------------------------------------------------

def _load_compositions() -> dict:
    """Read etf_compositions.json — the per-ETF geo + sector breakdowns."""
    if not COMPOSITIONS_PATH.exists():
        return {}
    with open(COMPOSITIONS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@st.cache_data(ttl=86400, show_spinner=False)
def _live_geo_sector(ticker: str, isin: str = ""):
    """Geography + sector for an asset, cached a day.

    Source priority:
      1. FUND → the official issuer factsheet located by ISIN (JustETF profile
         → fundinfo Monthly-Report PDF, parsed by compositions_scraper). This is
         the accurate holdings-weighted breakdown.
      2. STOCK → its single sector + country from Yahoo `.info` (only for an
         EQUITY; a fund's `.info` country is its domicile, not its holdings'
         geography, so Yahoo is never used for funds).
    Falls back to {"Unknown": 100.0} when neither yields data. Returns
    (geo_dict, sector_dict)."""
    isin = (isin or "").strip()
    ticker = (ticker or "").strip()
    import compositions_scraper as _cs
    geo: dict[str, float] = {}
    sec: dict[str, float] = {}

    # 1) FUND → official factsheet located by ISIN (JustETF → fundinfo PDF),
    #    then the JustETF profile-page HTML tables when the PDF renders its
    #    breakdowns as chart images (iShares / Vanguard / SPDR / Xtrackers).
    if isin:
        try:
            url = _cs.find_monthly_report_url(isin)
            if url:
                g, s = _cs.parse_factsheet_pdf(_cs._http_get(url, timeout=20))
                if _cs._validate(g, "geo")[0]:
                    geo = _cs._normalize_100(g)
                if _cs._validate(s, "sector")[0]:
                    sec = _cs._normalize_100(s)
        except Exception:
            pass
        if not geo or not sec:
            try:
                jg, js = _cs.find_justetf_exposure(isin)
                if not geo and _cs._validate(jg, "geo")[0]:
                    geo = _cs._normalize_100(jg)
                if not sec and _cs._validate(js, "sector")[0]:
                    sec = _cs._normalize_100(js)
            except Exception:
                pass

    # 2) STOCK → best available single sector + country from Yahoo .info. Only
    #    for an EQUITY (never a fund: a fund's .info country is its domicile,
    #    not its holdings' geography). Used when the ISIN factsheet gave nothing
    #    (missing geo AND sector) — i.e. an individual stock.
    if not geo and not sec and ticker:
        try:
            info = _cs.lookup_yfinance_info(ticker)
            if info.get("quote_type") == "EQUITY":
                if info.get("sector"):
                    sec = {_canon_cat(info["sector"], "sector"): 100.0}
                if info.get("country"):
                    geo = {_canon_cat(info["country"], "geo"): 100.0}
        except Exception:
            pass

    if not geo:
        geo = {"Unknown": 100.0}
    if not sec:
        sec = {"Unknown": 100.0}
    return geo, sec


# Canonical bucket names — different data sources label the same country/sector
# differently (Yahoo stock .info "Technology" / "United States" vs curated ETF
# factsheets "Tech" / "USA" vs Yahoo fund keys). Collapse them so the aggregate
# look-through never shows one thing twice (e.g. "USA" AND "United States").
_SECTOR_CANON = {
    "tech": "Tech", "technology": "Tech", "information technology": "Tech", "it": "Tech",
    "financials": "Financials", "financial services": "Financials",
    "financial": "Financials", "finance": "Financials",
    "healthcare": "Healthcare", "health care": "Healthcare", "health": "Healthcare",
    "consumer disc.": "Consumer Disc.", "consumer disc": "Consumer Disc.",
    "consumer discretionary": "Consumer Disc.", "consumer cyclical": "Consumer Disc.",
    "consumer staples": "Consumer Staples", "consumer defensive": "Consumer Staples",
    "communication": "Communication", "communication services": "Communication",
    "communications": "Communication",
    "industrials": "Industrials", "industrial": "Industrials",
    "materials": "Materials", "basic materials": "Materials",
    "energy": "Energy", "utilities": "Utilities",
    "real estate": "Real Estate", "realestate": "Real Estate",
}
_GEO_CANON = {
    "usa": "USA", "us": "USA", "u.s.": "USA", "u.s.a.": "USA", "america": "USA",
    "united states": "USA", "united states of america": "USA",
    "uk": "United Kingdom", "u.k.": "United Kingdom", "great britain": "United Kingdom",
    "britain": "United Kingdom", "united kingdom": "United Kingdom",
    "south korea": "South Korea", "korea": "South Korea",
    "republic of korea": "South Korea", "korea, south": "South Korea",
    "korea (south)": "South Korea", "taiwan": "Taiwan", "chinese taipei": "Taiwan",
    "hong kong": "Hong Kong", "hong kong sar": "Hong Kong",
    "china": "China", "people's republic of china": "China", "mainland china": "China",
    "uae": "UAE", "united arab emirates": "UAE",
    "russia": "Russia", "russian federation": "Russia",
    "czech republic": "Czech Republic", "czechia": "Czech Republic",
    "netherlands": "Netherlands", "the netherlands": "Netherlands",
}


def _canon_cat(name: str, kind: str) -> str:
    """Canonical bucket name for a geo/sector category so the same country or
    sector from different sources always merges into ONE bucket. Idempotent;
    unknown values are returned trimmed (never dropped)."""
    raw = (name or "").strip()
    if not raw:
        return "Unknown"
    table = _GEO_CANON if kind == "geo" else _SECTOR_CANON
    return table.get(raw.lower()) or raw


def _render_sector_geo(static, price_history: pd.DataFrame, snapshot: dict, palette: dict) -> None:
    compositions = _load_compositions()

    _section(palette, "Sector / Geographic Exposure",
             "Look-through: breakdown of your positions through the public "
             "compositions of each asset. Funds are sourced from the official "
             "issuer factsheet located by ISIN (JustETF → issuer PDF); individual "
             "stocks use their single sector + country. Click ↗ factsheet to "
             "cross-check.")

    # Build the aggregated exposures
    total_value = sum(p["value"] for p in snapshot["positions"].values())
    if total_value <= 0:
        st.info("NAV is zero — no exposure to display.")
        return

    def _eff_comp(asset: str) -> dict:
        """Effective geo/sector for an asset: the curated ETF JSON breakdown
        when available, otherwise a live Yahoo lookup — so stocks (and ETFs not
        in the JSON) get a sector/country too."""
        entry = compositions.get(asset, {}) or {}
        geo = entry.get("geo") or {}
        sec = entry.get("sector") or {}
        _isin = entry.get("isin") or data.ISIN_BY_ASSET.get(asset) or ""
        if geo and sec:
            out = dict(entry)
        else:
            tk = data.TICKER_BY_ASSET.get(asset) or entry.get("ticker") or ""
            lg, ls = _live_geo_sector(tk, _isin)
            out = {**entry, "geo": (geo or lg), "sector": (sec or ls)}
        # A newly-added ETF isn't in the curated JSON — surface its ISIN and a
        # JustETF factsheet link (built from the ISIN) so it shows a clickable
        # "↗ factsheet" exactly like the curated ETFs, to verify the numbers.
        if _isin:
            out.setdefault("isin", _isin)
            if not out.get("factsheet_url"):
                out["factsheet_url"] = (
                    f"https://www.justetf.com/fr/etf-profile.html?isin={_isin}")
        return out

    def aggregate(key: str) -> dict:
        """Weight per-asset breakdowns by current portfolio value."""
        agg: dict[str, float] = {}
        for asset, p in snapshot["positions"].items():
            value = p["value"]   # = current_price × shares — drifts daily with the market
            weights = _eff_comp(asset).get(key, {})
            for cat, pct in weights.items():
                c = _canon_cat(cat, key)
                agg[c] = agg.get(c, 0.0) + value * pct / 100.0
        return agg

    geo = aggregate("geo")
    sec = aggregate("sector")

    # Still nothing (e.g. Yahoo unreachable for every holding). Bail cleanly.
    if not geo and not sec:
        st.info("No composition data for the held assets "
                "(sector/country unavailable on Yahoo for these tickers).")
        return

    def to_df(agg: dict, total: float, col_name: str) -> pd.DataFrame:
        if not agg:
            return pd.DataFrame(columns=[col_name, "€", "%"])
        df = pd.DataFrame(
            [{col_name: k, "€": v, "%": v / total * 100} for k, v in agg.items()]
        )
        return df.sort_values("€", ascending=False).reset_index(drop=True)

    geo_df = to_df(geo, total_value, "Country / Region")
    sec_df = to_df(sec, total_value, "Sector")

    # Plot side-by-side
    col_g, col_s = st.columns(2)
    with col_g:
        st.markdown(
            f"<div style='color:{palette['ACCENT']};font-size:13px;font-weight:600;"
            f"letter-spacing:1.5px;text-transform:uppercase;margin-bottom:8px'>"
            f"Geographic exposure</div>", unsafe_allow_html=True,
        )
        fig_g = go.Figure(go.Bar(
            x=geo_df["%"], y=geo_df["Country / Region"], orientation="h",
            marker=dict(color=palette["ACCENT"], line=dict(color=palette["BG"], width=1)),
            customdata=geo_df["€"].values,
            hovertemplate="<b>%{y}</b><br>%{x:.2f} %<br>%{customdata:,.2f} €<extra></extra>",
            text=[f"{v:.1f}%" for v in geo_df["%"]],
            textposition="outside",
            textfont=dict(color=palette["TEXT"], size=11),
            cliponaxis=False,
        ))
        _style_fig(fig_g, palette, height=460, showlegend=False)
        _max_g = float(geo_df["%"].max()) if not geo_df.empty else 100
        fig_g.update_xaxes(ticksuffix=" %", title=None,
                            range=[0, _max_g * 1.20])
        fig_g.update_yaxes(title=None, autorange="reversed")
        st.plotly_chart(fig_g, width="stretch")

    with col_s:
        st.markdown(
            f"<div style='color:{palette['ACCENT']};font-size:13px;font-weight:600;"
            f"letter-spacing:1.5px;text-transform:uppercase;margin-bottom:8px'>"
            f"Sector exposure</div>", unsafe_allow_html=True,
        )
        fig_s = go.Figure(go.Bar(
            x=sec_df["%"], y=sec_df["Sector"], orientation="h",
            marker=dict(color=palette["GREEN"], line=dict(color=palette["BG"], width=1)),
            customdata=sec_df["€"].values,
            hovertemplate="<b>%{y}</b><br>%{x:.2f} %<br>%{customdata:,.2f} €<extra></extra>",
            text=[f"{v:.1f}%" for v in sec_df["%"]],
            textposition="outside",
            textfont=dict(color=palette["TEXT"], size=11),
            cliponaxis=False,
        ))
        _style_fig(fig_s, palette, height=460, showlegend=False)
        _max_s = float(sec_df["%"].max()) if not sec_df.empty else 100
        fig_s.update_xaxes(ticksuffix=" %", title=None,
                            range=[0, _max_s * 1.20])
        fig_s.update_yaxes(title=None, autorange="reversed")
        st.plotly_chart(fig_s, width="stretch")

    # Concentration warnings
    _section(palette, "Concentration & insights")
    insights = []
    if not geo_df.empty and geo_df.iloc[0]["%"] > 50:
        insights.append(
            f"⚠️ High geographic concentration: **{geo_df.iloc[0]['Country / Region']}** = "
            f"**{geo_df.iloc[0]['%']:.1f} %** of the portfolio."
        )
    if not sec_df.empty and sec_df.iloc[0]["%"] > 30:
        insights.append(
            f"⚠️ Sector concentration: **{sec_df.iloc[0]['Sector']}** = "
            f"**{sec_df.iloc[0]['%']:.1f} %**."
        )
    # Currency proxy: USA + UK + most of EM is USD-denominated for the underlyings
    usd_share = geo.get("USA", 0) / total_value * 100
    if usd_share > 30:
        insights.append(
            f"💱 USD exposure (US underlyings): **{usd_share:.1f} %**. "
            f"You carry this FX risk even if your assets are EUR-denominated."
        )

    if not insights:
        insights.append("✓ No excessive concentration detected.")
    for ins in insights:
        st.markdown(ins)

    # Aggregated tables (always visible)
    _section(palette, "Aggregated tables (portfolio look-through)")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"<div style='color:{palette['MUTED']};font-size:11px;"
                    f"letter-spacing:1px;text-transform:uppercase'>Geographic</div>",
                    unsafe_allow_html=True)
        tbl_g = geo_df.copy()
        tbl_g["€"] = tbl_g["€"].map(lambda v: f"{v:,.2f} €")
        tbl_g["%"] = tbl_g["%"].map(lambda v: f"{v:.2f} %")
        st.dataframe(tbl_g, width="stretch", hide_index=True)
    with c2:
        st.markdown(f"<div style='color:{palette['MUTED']};font-size:11px;"
                    f"letter-spacing:1px;text-transform:uppercase'>Sector</div>",
                    unsafe_allow_html=True)
        tbl_s = sec_df.copy()
        tbl_s["€"] = tbl_s["€"].map(lambda v: f"{v:,.2f} €")
        tbl_s["%"] = tbl_s["%"].map(lambda v: f"{v:.2f} %")
        st.dataframe(tbl_s, width="stretch", hide_index=True)

    # Per-ETF tables — one block per ETF showing its own geo + sector breakdown
    _section(palette, "Detail per asset",
             "Public composition of each asset (issuer factsheet). "
             "The dot on the right shows how fresh the data is. "
             "The portfolio weight is automatically applied to the aggregate above.")

    # Extract once to avoid f-string escape headaches
    p_panel = palette["PANEL"]; p_grid = palette["GRID"]
    p_text = palette["TEXT"]; p_muted = palette["MUTED"]; p_accent = palette["ACCENT"]

    for asset in data.ASSETS:
        comp = _eff_comp(asset)
        if not (comp.get("geo") or comp.get("sector")):
            continue
        p = snapshot["positions"].get(asset, {})
        weight_pct = p.get("allocation", 0) * 100

        isin = comp.get("isin", "—")
        issuer = comp.get("issuer", "—")
        url = comp.get("factsheet_url", "")
        link = (f'<a href="{url}" target="_blank" '
                f'style="color:{p_accent};text-decoration:none">↗ factsheet</a>'
                if url else "")
        # Plain data-provenance line (no color logic) — when + from where
        auto_ts = comp.get("last_auto_refresh", "")
        auto_src = comp.get("last_auto_refresh_source", "")
        prov = ""
        if auto_ts:
            prov = (f"<span style='color:{p_muted};font-size:10px;margin-left:8px;"
                    f"font-style:italic'>Updated {auto_ts} · {auto_src}</span>")

        st.markdown(
            f"<div style='background:{p_panel};border:1px solid {p_grid};"
            f"border-radius:10px;padding:14px 18px;margin-top:14px;margin-bottom:6px'>"
            f"<div style='display:flex;justify-content:space-between;align-items:baseline'>"
            f"<div><b style='color:{p_text};font-size:14px'>{asset}</b>"
            f" <span style='color:{p_muted};font-size:11px;font-family:monospace'>"
            f"{isin} · {issuer}</span>{prov}</div>"
            f"<div style='font-size:11px'>"
            f"<span style='color:{p_muted}'>weight: "
            f"<b style='color:{p_text}'>{weight_pct:.2f} %</b></span>"
            f" &nbsp;|&nbsp; {link}"
            f"</div></div></div>",
            unsafe_allow_html=True,
        )

        geo_e = comp.get("geo", {})
        sec_e = comp.get("sector", {})

        def _comp_df(d: dict, col: str) -> pd.DataFrame:
            # Single-stock entries (AAPL, CAT, …) may have an empty geo or
            # sector dict — guard so sort_values doesn't KeyError on no columns.
            if not d:
                return pd.DataFrame(columns=[col, "%"])
            return (pd.DataFrame([{col: k, "%": v} for k, v in d.items()])
                    .sort_values("%", ascending=False).reset_index(drop=True))

        geo_e_df = _comp_df(geo_e, "Country / Region")
        sec_e_df = _comp_df(sec_e, "Sector")

        # Add "Contribution portefeuille" column = weight_etf × pct_in_etf / 100
        geo_e_df["Contribution portfolio"] = geo_e_df["%"] * weight_pct / 100
        sec_e_df["Contribution portfolio"] = sec_e_df["%"] * weight_pct / 100

        geo_e_df["%"] = geo_e_df["%"].map(lambda v: f"{v:.2f} %")
        geo_e_df["Contribution portfolio"] = geo_e_df["Contribution portfolio"].map(lambda v: f"{v:.3f} pp")
        sec_e_df["%"] = sec_e_df["%"].map(lambda v: f"{v:.2f} %")
        sec_e_df["Contribution portfolio"] = sec_e_df["Contribution portfolio"].map(lambda v: f"{v:.3f} pp")

        cge, cse = st.columns(2)
        with cge:
            st.dataframe(geo_e_df, width="stretch", hide_index=True)
        with cse:
            st.dataframe(sec_e_df, width="stretch", hide_index=True)

    # Footer note
    sum_check = sum(p.get("allocation", 0) for p in snapshot["positions"].values()) * 100
    st.caption(
        f"ℹ️ Aggregate calculation: for each ETF, its geo/sector % are multiplied by "
        f"its **current € value** in the portfolio (= today's price×shares), then "
        f"summed. When an asset outperforms, its influence on the aggregate exposures "
        f"rises automatically. Σ weights = {sum_check:.2f} %."
    )


# ---------------------------------------------------------------------------
# Sub-tab 7 — Monthly PDF Export
# ---------------------------------------------------------------------------

REPORTS_DIR = data.ROOT / "reports"


def _render_pdf_export(static, price_history: pd.DataFrame, snapshot: dict, palette: dict) -> None:
    _section(palette, "Monthly PDF Export",
             "Generates a styled one-page report summarizing the portfolio's state. "
             "The file is saved in the reports/ folder — you can email it or archive "
             "it by hand. No SMTP required (security).")

    REPORTS_DIR.mkdir(exist_ok=True)

    # List existing reports
    existing = sorted(REPORTS_DIR.glob("GPCP_*.pdf"), reverse=True)
    if existing:
        st.markdown("**📂 Already generated reports:**")
        for f in existing[:10]:
            size_kb = f.stat().st_size / 1024
            st.markdown(
                f"<div style='font-family:monospace;font-size:12px;color:{palette['MUTED']}'>"
                f"  {f.name} <span style='float:right'>{size_kb:.1f} KB</span></div>",
                unsafe_allow_html=True,
            )

    c1, c2 = st.columns([1, 3])
    with c1:
        period = st.selectbox("Period", options=["This month", "Last month", "YTD", "All-time"],
                               key="pdf_period")

    if st.button("📄 Generate report", type="primary"):
        try:
            with st.spinner("Generating PDF…"):
                pdf_path = _generate_pdf_report(static, price_history, snapshot, period)
            st.success(f"✓ Report generated: `{pdf_path.name}` ({pdf_path.stat().st_size/1024:.1f} KB)")
            # Offer download via Streamlit
            with open(pdf_path, "rb") as f:
                st.download_button(
                    label=f"⬇ Download {pdf_path.name}",
                    data=f.read(),
                    file_name=pdf_path.name,
                    mime="application/pdf",
                )
            st.caption(f"📁 File also available locally: {pdf_path}")
        except Exception as exc:
            st.error(f"Generation error: {exc}")
            import traceback
            st.code(traceback.format_exc())


def _generate_pdf_report(static, price_history: pd.DataFrame, snapshot: dict, period: str):
    """Generate a professional, multi-section PDF report and return its path.

    Sections: cover + key data · multi-period performance (MTD / YTD / 1Y /
    since inception / annualized) vs an MSCI World benchmark · unit-value chart
    (base 100, portfolio vs benchmark) · risk indicators (vol, Sharpe, Sortino,
    max drawdown, VaR, tracking error, beta, information ratio) · sector & geo
    look-through · top positions · per-asset detail · realized P&L · disclaimer.
    Charts are drawn natively with reportlab.graphics (no image backend needed).
    """
    import math
    import numpy as np
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
        HRFlowable, KeepTogether
    )
    from reportlab.graphics.shapes import Drawing, String, Rect
    from reportlab.graphics.charts.lineplots import LinePlot

    today = dt.date.today()
    pf_ccy = data.current_portfolio_currency()
    sym = data.CURRENCY_SYMBOL.get(pf_ccy, pf_ccy)
    inception = snapshot.get("inception_date")
    positions = snapshot.get("positions", {})

    # ---- palette (premium fintech: monochrome ink + institutional blue accent,
    #      zinc neutrals — ui-ux-pro-max "Accessible & Ethical" / fintech) ----
    ACC = colors.HexColor("#2563EB")    # institutional blue (accent / portfolio line)
    DARK = colors.HexColor("#18181B")   # near-black ink (headers, bands)
    INK = colors.HexColor("#27272A")    # primary body text (zinc-800)
    GREY = colors.HexColor("#71717A")   # muted captions / labels (zinc-500)
    GRID = colors.HexColor("#E4E4E7")   # hairline borders (zinc-200)
    ZEBRA = colors.HexColor("#FAFAFA")  # table zebra (zinc-50)
    SOFT = colors.HexColor("#F4F4F5")   # soft surface (zinc-100)
    POS = colors.HexColor("#059669")    # emerald-600
    NEG = colors.HexColor("#DC2626")    # red-600
    WHITE = colors.white

    # ---- formatters ----
    def _bad(v):
        return v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))

    def mny(v, signed=False):
        return "—" if _bad(v) else f"{v:{'+' if signed else ''},.2f} {sym}"

    def pct(v, d=2):
        return "—" if _bad(v) else f"{v * 100:+.{d}f} %"

    def num(v, d=2):
        return "—" if _bad(v) else f"{v:.{d}f}"

    # ---- portfolio unit-value series (base 100) ----
    try:
        vlf = data.compute_vl_series(price_history)
    except Exception:
        vlf = None
    if vlf is not None and not vlf.empty:
        vser = pd.Series(vlf["vl"].astype(float).values,
                         index=pd.to_datetime(vlf["date"])).sort_index()
    else:
        vser = pd.Series(dtype=float)

    # ---- MSCI World benchmark, indexed to 100 over the common dates ----
    bench_label = "MSCI World"
    bser = pd.Series(dtype=float)
    if not vser.empty:
        try:
            raw = _fetch_benchmark("IWDA.AS", vser.index[0].date(), vser.index[-1].date())
            if raw is not None and not raw.empty:
                common = vser.index.intersection(raw.index)
                if len(common) >= 2:
                    bser = raw.loc[common] / float(raw.loc[common].iloc[0]) * 100.0
        except Exception:
            bser = pd.Series(dtype=float)

    # ---- multi-period returns from an indexed (base-100) series ----
    def _asof_ret(series, ref_ts):
        if series.empty:
            return None
        s = series[series.index <= ref_ts]
        if s.empty:
            return None
        base = float(s.iloc[-1])
        return (float(series.iloc[-1]) / base - 1.0) if base else None

    def _periods(series):
        if series.empty:
            return {}
        last, first = series.index[-1], series.index[0]
        si = float(series.iloc[-1]) / float(series.iloc[0]) - 1.0
        ndays = max((last - first).days, 1)
        ann = (float(series.iloc[-1]) / float(series.iloc[0])) ** (365.25 / ndays) - 1.0
        mtd_ref = pd.Timestamp(last.year, last.month, 1) - pd.Timedelta(days=1)
        ytd_ref = pd.Timestamp(last.year - 1, 12, 31)
        y1_ref = last - pd.DateOffset(years=1)
        return {
            "MTD": _asof_ret(series, mtd_ref) if mtd_ref >= first else si,
            "YTD": _asof_ret(series, ytd_ref) if ytd_ref >= first else si,
            "1Y": _asof_ret(series, y1_ref) if y1_ref >= first else None,
            "SI": si,
            "ANN": ann,
        }

    pp = _periods(vser)
    bp = _periods(bser) if not bser.empty else {}

    # ---- risk indicators ----
    rr = vser.pct_change().dropna() if not vser.empty else pd.Series(dtype=float)
    nret = len(rr)
    vol = float(rr.std(ddof=1) * math.sqrt(252)) if nret > 1 else None
    rf_d = (1.03) ** (1 / 252) - 1
    ann_ex = (1 + (rr - rf_d).mean()) ** 252 - 1 if nret else None
    sharpe = (ann_ex / vol) if (vol and vol > 0 and ann_ex is not None) else None
    downside = math.sqrt(float((np.minimum(rr.values - rf_d, 0) ** 2).mean())) if nret else 0.0
    sortino = (ann_ex / (downside * math.sqrt(252))) if (downside > 0 and ann_ex is not None) else None
    if not vser.empty:
        dd = vser / vser.cummax() - 1.0
        maxdd = float(dd.min())
    else:
        maxdd = None
    var95 = float(np.quantile(rr, 0.05)) if nret >= 2 else None
    te = beta = ir = None
    if not bser.empty:
        br = bser.pct_change().dropna()
        cidx = rr.index.intersection(br.index)
        if len(cidx) >= 2:
            ex = rr.loc[cidx] - br.loc[cidx]
            te = float(ex.std(ddof=1) * math.sqrt(252))
            alpha = float(ex.mean() * 252)
            ir = (alpha / te) if (te and te > 0) else None
            bvar = float(br.loc[cidx].var(ddof=1))
            if bvar > 0:
                beta = float(np.cov(rr.loc[cidx], br.loc[cidx], ddof=1)[0, 1] / bvar)

    # ---- sector / geo look-through (same logic as the Pro tab) ----
    try:
        _comp = _load_compositions()
    except Exception:
        _comp = {}

    def _eff(asset):
        e = _comp.get(asset, {}) or {}
        geo, sec = e.get("geo") or {}, e.get("sector") or {}
        if geo and sec:
            return geo, sec
        isin = e.get("isin") or data.ISIN_BY_ASSET.get(asset) or ""
        tk = data.TICKER_BY_ASSET.get(asset) or e.get("ticker") or ""
        try:
            lg, ls = _live_geo_sector(tk, isin)
        except Exception:
            lg, ls = {}, {}
        return (geo or lg), (sec or ls)

    geo_agg, sec_agg = {}, {}
    inv_total = sum(p.get("value", 0) for a, p in positions.items() if a != "Cash") or 1.0
    for a, p in positions.items():
        if a == "Cash":
            continue
        g, s = _eff(a)
        for k, v in (g or {}).items():
            ck = _canon_cat(k, "geo")
            geo_agg[ck] = geo_agg.get(ck, 0.0) + p.get("value", 0) * v / 100.0
        for k, v in (s or {}).items():
            ck = _canon_cat(k, "sector")
            sec_agg[ck] = sec_agg.get(ck, 0.0) + p.get("value", 0) * v / 100.0

    # ====================================================================
    # Build the document
    # ====================================================================
    fname = f"GPCP_{today.strftime('%Y-%m')}_{period.replace(' ', '_').lower()}.pdf"
    path = REPORTS_DIR / fname
    doc = SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=14 * mm, bottomMargin=14 * mm,
        title="GPCP — Portfolio Report",
    )
    CONTENT_W = 180 * mm   # A4 width (210) − 2×15 margins
    styles = getSampleStyleSheet()
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=10.5, leading=13,
                        fontName="Helvetica-Bold", textColor=DARK,
                        spaceBefore=2, spaceAfter=1)
    body = ParagraphStyle("B", parent=styles["Normal"], fontSize=8.5, leading=12,
                          textColor=INK)
    foot = ParagraphStyle("F", parent=body, fontSize=7, textColor=GREY, alignment=1,
                          leading=9)

    def _sec(title):
        """Section header: bold uppercase ink title + thin accent rule."""
        story.append(Spacer(1, 3.5 * mm))
        story.append(Paragraph(title.upper(), h2))
        story.append(HRFlowable(width="100%", thickness=1.1, color=ACC,
                                spaceBefore=1.5, spaceAfter=5, lineCap="round"))

    def _table(rows, widths, *, total_row=False, right_from=1, color_cells=None):
        """Generic premium table: dark ink header, hairline grid, zebra body."""
        t = Table(rows, colWidths=widths)
        st_ = [
            ("BACKGROUND", (0, 0), (-1, 0), DARK),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 7.5),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("TEXTCOLOR", (0, 1), (-1, -1), INK),
            ("LINEBELOW", (0, 0), (-1, -2), 0.25, GRID),
            ("LINEAFTER", (0, 0), (-2, -1), 0.25, GRID),
            ("BOX", (0, 0), (-1, -1), 0.4, GRID),
            ("ALIGN", (right_from, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1 if not total_row else -2), [WHITE, ZEBRA]),
        ]
        if total_row:
            st_ += [("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                    ("BACKGROUND", (0, -1), (-1, -1), SOFT),
                    ("LINEABOVE", (0, -1), (-1, -1), 0.6, DARK)]
        for (c, r, v) in (color_cells or []):
            if not _bad(v) and v != 0:
                st_.append(("TEXTCOLOR", (c, r), (c, r), POS if v > 0 else NEG))
        t.setStyle(TableStyle(st_))
        return t

    story = []

    # ---------- Header band (dark, full-width) ----------
    inc_str = inception.strftime("%d %b %Y") if inception else "—"
    band_cell = Paragraph(
        "<font size=8 color='#93C5FD'><b>GPCP &nbsp;·&nbsp; PORTFOLIO REPORTING</b></font>"
        "<br/><font size=21 color='#FFFFFF'><b>Portfolio Report</b></font>",
        ParagraphStyle("band", parent=body, leading=24, textColor=WHITE))
    band_meta = Paragraph(
        f"<font size=8 color='#A1A1AA'>{today.strftime('%d %B %Y')}<br/>"
        f"Period · {period}</font>",
        ParagraphStyle("bm", parent=body, leading=12, alignment=2))
    band = Table([[band_cell, band_meta]], colWidths=[CONTENT_W * 0.66, CONTENT_W * 0.34])
    band.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), DARK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 11), ("RIGHTPADDING", (-1, 0), (-1, 0), 11),
        ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    story.append(band)
    # meta strip
    meta = Table([[Paragraph(
        f"<font color='#71717A' size=8>Inception <b>{inc_str}</b> &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"Base currency <b>{pf_ccy}</b> &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"Benchmark <b>{bench_label}</b> &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"Source <b>Yahoo Finance (adjusted close)</b></font>", body)]],
        colWidths=[CONTENT_W])
    meta.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SOFT), ("LEFTPADDING", (0, 0), (-1, -1), 11),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, GRID),
    ]))
    story.append(meta)
    story.append(Spacer(1, 4 * mm))

    # ---------- Headline KPI tiles ----------
    cash = 0.0
    try:
        cash = float(data.cash_balance_as_of(today))
    except Exception:
        cash = float(positions.get("Cash", {}).get("value", 0) or 0)
    n_pos = len([a for a in positions if a != "Cash"])

    def _tile(label, value, hexcol="#27272A"):
        return Paragraph(
            f"<font size=6.5 color='#71717A'><b>{label.upper()}</b></font><br/>"
            f"<font size=13.5 color='{hexcol}'><b>{value}</b></font>",
            ParagraphStyle("tile", parent=body, leading=17))

    def _sign_hex(v):
        return "#27272A" if _bad(v) else ("#059669" if v >= 0 else "#DC2626")

    tr = snapshot.get("total_return_pct")
    tiles = [
        _tile("Net asset value", mny(snapshot.get("total_value"))),
        _tile("Total return", pct(tr), _sign_hex(tr)),
        _tile("1-Year", pct(pp.get("1Y")), _sign_hex(pp.get("1Y"))),
        _tile("Sharpe ratio", num(sharpe)),
        _tile("Max drawdown", pct(maxdd), "#DC2626" if not _bad(maxdd) else "#27272A"),
    ]
    tw = CONTENT_W / 5.0
    tile_tbl = Table([tiles], colWidths=[tw] * 5)
    tile_tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, GRID),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, GRID),
        ("BACKGROUND", (0, 0), (-1, -1), WHITE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(tile_tbl)

    # ---------- Key data ----------
    _sec("Key data")
    kd = [
        ["Net invested capital", mny(snapshot.get("net_invested")),
         "Unit value (base 100)", num(snapshot.get("vl"), 4)],
        ["Total P&L", f"{mny(snapshot.get('total_return_eur'), True)} "
                      f"({pct(snapshot.get('total_return_pct'))})",
         "Daily P&L", f"{mny(snapshot.get('daily_pnl_eur'), True)} "
                      f"({pct(snapshot.get('daily_pnl_pct'))})"],
        ["Cash", mny(cash), "Number of positions", str(n_pos)],
    ]
    kt = Table(kd, colWidths=[42 * mm, 48 * mm, 42 * mm, 48 * mm])
    kt.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
        ("FONTNAME", (3, 0), (3, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), GREY), ("TEXTCOLOR", (2, 0), (2, -1), GREY),
        ("TEXTCOLOR", (1, 0), (1, -1), INK), ("TEXTCOLOR", (3, 0), (3, -1), INK),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, GRID),
        ("BOX", (0, 0), (-1, -1), 0.4, GRID),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(kt)

    # ---------- Performance (multi-period) ----------
    _sec("Performance")
    perf_rows = [["", "MTD", "YTD", "1 Year", "Since incept.", "Annualized"]]
    color_cells = []
    keys = ["MTD", "YTD", "1Y", "SI", "ANN"]
    perf_rows.append(["Portfolio"] + [pct(pp.get(k)) for k in keys])
    for j, k in enumerate(keys, start=1):
        color_cells.append((j, 1, pp.get(k)))
    if bp:
        perf_rows.append([bench_label] + [pct(bp.get(k)) for k in keys])
        exc = ["Excess vs benchmark"]
        for k in keys:
            a, b = pp.get(k), bp.get(k)
            exc.append(pct(a - b) if (not _bad(a) and not _bad(b)) else "—")
        perf_rows.append(exc)
        for j, k in enumerate(keys, start=1):
            a, b = pp.get(k), bp.get(k)
            color_cells.append((j, 3, (a - b) if (not _bad(a) and not _bad(b)) else None))
    story.append(_table(perf_rows, [40 * mm, 26 * mm, 26 * mm, 26 * mm, 28 * mm, 26 * mm],
                        color_cells=color_cells))
    story.append(Spacer(1, 3 * mm))

    # ---------- Unit-value chart (base 100, portfolio vs benchmark) ----------
    if not vser.empty:
        try:
            xs = list(range(len(vser)))
            port_pts = list(zip(xs, [float(v) for v in vser.values]))
            series_data = [port_pts]
            bench_pts = []
            if not bser.empty:
                bb = bser.reindex(vser.index).ffill().bfill()
                bench_pts = list(zip(xs, [float(v) for v in bb.values]))
                series_data.append(bench_pts)
            allv = [y for _, y in port_pts] + [y for _, y in bench_pts]
            lo, hi = min(allv), max(allv)
            dw = Drawing(500, 200)
            lp = LinePlot()
            lp.x, lp.y, lp.width, lp.height = 34, 26, 452, 158
            lp.data = series_data
            lp.lines[0].strokeColor = ACC; lp.lines[0].strokeWidth = 1.8
            if bench_pts:
                lp.lines[1].strokeColor = colors.HexColor("#A1A1AA")
                lp.lines[1].strokeWidth = 1.1
                lp.lines[1].strokeDashArray = (3, 2)
            lp.xValueAxis.valueMin = 0
            lp.xValueAxis.valueMax = max(len(xs) - 1, 1)
            lp.xValueAxis.visibleLabels = 0
            lp.xValueAxis.visibleTicks = 0
            lp.xValueAxis.strokeColor = GRID
            pad = max((hi - lo) * 0.08, 1.0)
            lp.yValueAxis.valueMin = math.floor((lo - pad) / 5) * 5
            lp.yValueAxis.valueMax = math.ceil((hi + pad) / 5) * 5
            lp.yValueAxis.strokeColor = GRID
            lp.yValueAxis.gridStrokeColor = GRID
            lp.yValueAxis.visibleGrid = 1
            dw.add(lp)
            dw.add(String(34, 12, vser.index[0].strftime("%d %b %Y"),
                          fontSize=7, fillColor=GREY))
            dw.add(String(486, 12, vser.index[-1].strftime("%d %b %Y"),
                          fontSize=7, fillColor=GREY, textAnchor="end"))
            legend = "<font color='#2563EB'><b>—— Portfolio</b></font>"
            if bench_pts:
                legend += f" &nbsp;&nbsp;&nbsp; <font color='#A1A1AA'><b>- - {bench_label}</b></font>"
            story.append(Paragraph(
                "<font color='#71717A' size=8>UNIT VALUE — base 100 at inception "
                "(total return)</font>", body))
            story.append(Spacer(1, 1 * mm))
            story.append(dw)
            story.append(Paragraph(legend, ParagraphStyle(
                "lg", parent=body, fontSize=8, alignment=1)))
        except Exception:
            pass

    # ---------- Risk indicators ----------
    _sec("Risk indicators")
    risk_rows = [
        ["Volatility (annualized)", pct(vol), "Max drawdown", pct(maxdd)],
        ["Sharpe ratio", num(sharpe), "VaR 95% (1d)", pct(var95)],
        ["Sortino ratio", num(sortino), "Tracking error vs bench.", pct(te)],
        ["Beta vs benchmark", num(beta), "Information ratio", num(ir)],
    ]
    rt = Table(risk_rows, colWidths=[48 * mm, 42 * mm, 48 * mm, 42 * mm])
    rt.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
        ("FONTNAME", (3, 0), (3, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), GREY), ("TEXTCOLOR", (2, 0), (2, -1), GREY),
        ("TEXTCOLOR", (1, 0), (1, -1), INK), ("TEXTCOLOR", (3, 0), (3, -1), INK),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("ALIGN", (3, 0), (3, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, GRID),
        ("BOX", (0, 0), (-1, -1), 0.4, GRID),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [WHITE, ZEBRA]),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(rt)
    story.append(Paragraph(
        f"Risk computed on {nret} daily unit-value returns · risk-free 3.00% · "
        f"benchmark: {bench_label} (IWDA). Annualized figures are noisy on short "
        f"histories.", foot))

    # ====================== Page 2 — allocations & positions ============
    story.append(PageBreak())

    def _bar(frac):
        """Thin horizontal progress bar (reportlab Drawing) for a table cell."""
        w, h = 40 * mm, 4.5
        d = Drawing(w, h + 3)
        d.add(Rect(0, 1.5, w, h, fillColor=SOFT, strokeColor=None, rx=1.5, ry=1.5))
        fw = max(min(frac, 1.0), 0.0) * w
        if fw > 0:
            d.add(Rect(0, 1.5, max(fw, 1.0), h, fillColor=ACC, strokeColor=None, rx=1.5, ry=1.5))
        return d

    def _expo_table(title, agg):
        _sec(title)
        if not agg:
            story.append(Paragraph("No breakdown available.", body))
            return
        items = sorted(agg.items(), key=lambda kv: -kv[1])
        vmax = items[0][1] if items else 1.0
        rows = [["Bucket", "", "Weight", sym]]
        for k, v in items:
            share = v / inv_total * 100
            rows.append([k, _bar(v / vmax if vmax else 0), f"{share:.2f} %", f"{v:,.0f} {sym}"])
        t = Table(rows, colWidths=[52 * mm, 44 * mm, 34 * mm, 40 * mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), DARK),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 7.5), ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("TEXTCOLOR", (0, 1), (-1, -1), INK),
            ("ALIGN", (2, 0), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW", (0, 0), (-1, -2), 0.25, GRID), ("BOX", (0, 0), (-1, -1), 0.4, GRID),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, ZEBRA]),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ]))
        story.append(t)
        story.append(Spacer(1, 3 * mm))

    _expo_table("Geographic exposure (look-through)", geo_agg)
    _expo_table("Sector exposure (look-through)", sec_agg)

    # ---------- Top positions ----------
    _sec("Top positions")
    held = [(a, p) for a, p in positions.items()
            if a != "Cash" and p.get("value", 0) > 0]
    held.sort(key=lambda kv: kv[1].get("value", 0), reverse=True)
    tp_rows = [["Asset", "Ticker", "Weight", f"Value ({sym})", "Total return"]]
    tp_colors = []
    for i, (a, p) in enumerate(held[:12], start=1):
        tk = (getattr(data, "TICKER_BY_ASSET", {}) or {}).get(a, "—") or "—"
        tr = p.get("total_return")
        tp_rows.append([a, tk, f"{p.get('allocation', 0) * 100:.2f} %",
                        f"{p.get('value', 0):,.2f}", pct(tr)])
        tp_colors.append((4, i, tr))
    story.append(_table(tp_rows, [46 * mm, 24 * mm, 24 * mm, 40 * mm, 32 * mm],
                        right_from=2, color_cells=tp_colors))

    # ====================== Page 3 — detail & realized P&L ==============
    story.append(PageBreak())
    _sec("Per-asset detail")
    det_rows = [["Asset", "Shares", f"Price ({sym})", f"Value ({sym})",
                 "Weight", "Daily", "Total ret."]]
    det_colors = []
    for i, asset in enumerate(data.ASSETS, start=1):
        p = positions.get(asset, {})
        dr_ = p.get("daily_return"); tr = p.get("total_return")
        det_rows.append([
            asset, f"{static.shares.get(asset, 0):g}",
            f"{p.get('price', 0):,.4f}", f"{p.get('value', 0):,.2f}",
            f"{p.get('allocation', 0) * 100:.2f} %", pct(dr_), pct(tr),
        ])
        det_colors.append((5, i, dr_)); det_colors.append((6, i, tr))
    det_rows.append(["TOTAL", "", "", f"{snapshot.get('total_value', 0):,.2f}", "100.00 %",
                     pct(snapshot.get("daily_pnl_pct")), pct(snapshot.get("total_return_pct"))])
    story.append(_table(det_rows,
                        [38 * mm, 18 * mm, 24 * mm, 28 * mm, 20 * mm, 22 * mm, 22 * mm],
                        total_row=True, color_cells=det_colors))
    story.append(Spacer(1, 5 * mm))

    # ---------- Realized P&L ----------
    _sec("Realized sells — P&L")
    sells = []
    try:
        _sfn = getattr(data, "sell_pnl_rows", None)
        sells = _sfn() if _sfn else []
    except Exception:
        sells = []
    if sells:
        sp_rows = [["Date", "Asset", "Shares", "Sell price", "Avg cost", "Return", "Realized P&L"]]
        sp_colors = []
        for i, s in enumerate(sells, start=1):
            csym = data.CURRENCY_SYMBOL.get(s.get("currency", pf_ccy), s.get("currency", ""))
            d_ = s["date"].strftime("%d %b %Y") if hasattr(s.get("date"), "strftime") else str(s.get("date"))
            sp_rows.append([
                d_, s.get("asset", ""), f"{s.get('shares', 0):g}",
                f"{s.get('sell_price', 0):,.2f} {csym}",
                (f"{s['avg_cost']:,.2f} {csym}" if s.get("avg_cost") is not None else "—"),
                pct(s.get("return_pct")),
                (f"{s['pnl']:+,.2f} {csym}" if s.get("pnl") is not None else "—"),
            ])
            sp_colors.append((5, i, s.get("return_pct"))); sp_colors.append((6, i, s.get("pnl")))
        story.append(_table(sp_rows,
                            [24 * mm, 30 * mm, 18 * mm, 28 * mm, 28 * mm, 22 * mm, 30 * mm],
                            right_from=2, color_cells=sp_colors))
    else:
        story.append(Paragraph("No realized sell over the period.", body))

    # ---------- Disclaimer / footer ----------
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(
        "<i>This report is generated automatically by GPCP Dashboard for "
        "information only. Prices are sourced from Yahoo Finance (adjusted "
        "close — split- and dividend-adjusted total return); figures may differ "
        "from a custodian statement. Past performance does not guarantee future "
        "results. This is not investment advice.</i>", foot))

    doc.build(story)
    return path


# ---------------------------------------------------------------------------
# Main render entry point
# ---------------------------------------------------------------------------

def render(static, price_history: pd.DataFrame, snapshot: dict, palette: dict) -> None:
    """Render the entire Pro tab. Called from app.py."""
    sub_labels = [
        "Risk Metrics",
        "Calendar Heatmap",
        "Performance Attribution",
        "Correlation Matrix",
        "Benchmark Comparison",
        "Monte Carlo",
        "PDF Export",
        "Sector / Geo Exposure",
    ]
    subs = st.tabs(sub_labels)

    with subs[0]:
        _render_risk_metrics(static, price_history, palette)
    with subs[1]:
        _render_calendar_heatmap(static, price_history, palette)
    with subs[2]:
        _render_attribution(static, price_history, palette)
    with subs[3]:
        _render_correlation(static, price_history, snapshot, palette)
    with subs[4]:
        _render_benchmark(static, price_history, palette)
    with subs[5]:
        _render_monte_carlo(static, price_history, snapshot, palette)
    with subs[6]:
        _render_pdf_export(static, price_history, snapshot, palette)
    with subs[7]:
        _render_sector_geo(static, price_history, snapshot, palette)
