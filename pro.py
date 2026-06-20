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
            "Pas assez d'historique pour calculer des métriques de risque pertinentes. "
            "Il faut au moins une dizaine de jours de données. Patiente que le cron historise "
            "quelques séances et reviens ici."
        )
        st.metric("Jours d'historique disponibles", len(nav))
        return

    rets = _daily_returns(nav)

    # --- Inputs row ---
    c1, c2 = st.columns([1, 3])
    with c1:
        rf_pct = st.number_input(
            "Taux sans risque annuel (%)",
            min_value=0.0, max_value=10.0,
            value=DEFAULT_RF * 100, step=0.25,
            help="Sert au calcul du Sharpe / Sortino. Par défaut ≈ €STR ~ 3 %.",
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
            f"⚠️ Seulement {n} jours de returns disponibles. Les chiffres "
            "**annualisés** (rendement, volatilité, Sharpe, Sortino) sont des "
            "extrapolations peu fiables tant que l'historique est court — ils se "
            "stabiliseront avec quelques semaines de données. Le Max Drawdown, la "
            "VaR et la CVaR (non annualisés) restent lisibles dès maintenant."
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
             f"Calculé sur {n} returns daily ({nav.index[0].date()} → {nav.index[-1].date()}).")

    if n < 20:
        st.markdown(
            f"<div style='color:{palette['ACCENT']};font-size:11px;font-style:italic;"
            f"margin-bottom:8px'>⚠ Seulement {n} returns : les ratios ci-dessous sont "
            f"très bruités tant que l'historique est court (fiables à partir de ~30-60 jours).</div>",
            unsafe_allow_html=True,
        )

    r1c1, r1c2, r1c3, r1c4 = st.columns(4)
    r1c1.markdown(_kpi("Annualized Return", fmt_pct(ann_return),
                       tone="up" if ann_return >= 0 else "down",
                       delta=f"mean daily {fmt_pct(mean_d, 4)}", palette=palette),
                  unsafe_allow_html=True)
    r1c1.markdown(_expl(palette, "Rendement extrapolé sur 1 an. Repère actions : "
                        "<0 = perte · 0-7 % = modeste · 7-12 % = bon · >12 % = très bon."),
                  unsafe_allow_html=True)
    r1c2.markdown(_kpi("Annualized Volatility", fmt_pct(ann_vol),
                       delta=f"σ daily {fmt_pct(std_d, 4)}", palette=palette),
                  unsafe_allow_html=True)
    r1c2.markdown(_expl(palette, "Amplitude des variations (risque). "
                        "<10 % = faible · 10-20 % = modéré · >20 % = élevé."),
                  unsafe_allow_html=True)
    r1c3.markdown(_kpi("Sharpe Ratio", fmt_num(sharpe),
                       delta=f"vs rf {rf_pct:.2f} %",
                       tone="up" if (not pd.isna(sharpe) and sharpe > 1) else
                            ("down" if (not pd.isna(sharpe) and sharpe < 0) else ""),
                       palette=palette),
                  unsafe_allow_html=True)
    r1c3.markdown(_expl(palette, "Rendement par unité de risque total. "
                        "<0 = mauvais · 0-1 = moyen · 1-2 = bon · >2 = excellent."),
                  unsafe_allow_html=True)
    r1c4.markdown(_kpi("Sortino Ratio", fmt_num(sortino),
                       delta="downside-only σ",
                       tone="up" if (not pd.isna(sortino) and sortino > 1) else "",
                       palette=palette),
                  unsafe_allow_html=True)
    r1c4.markdown(_expl(palette, "Comme le Sharpe mais ne pénalise que la baisse "
                        "(ignore la volatilité à la hausse). >1 = bon · >2 = très bon."),
                  unsafe_allow_html=True)

    r2c1, r2c2, r2c3, r2c4 = st.columns(4)
    r2c1.markdown(_kpi("Max Drawdown", fmt_pct(max_dd),
                       delta=(f"{dd_duration_days} d "
                              f"{'(recovered)' if recovered else '(unrecovered)'}"),
                       tone="down" if max_dd and max_dd < 0 else "",
                       palette=palette),
                  unsafe_allow_html=True)
    r2c1.markdown(_expl(palette, "Pire chute depuis un sommet. "
                        ">-10 % = confortable · -10 à -30 % = normal en actions · <-40 % = sévère."),
                  unsafe_allow_html=True)
    r2c2.markdown(_kpi("Calmar Ratio", fmt_num(calmar),
                       delta="return / |max DD|", palette=palette),
                  unsafe_allow_html=True)
    r2c2.markdown(_expl(palette, "Rendement annualisé / pire chute. "
                        "<1 = faible · 1-3 = bon · >3 = excellent."),
                  unsafe_allow_html=True)
    r2c3.markdown(_kpi("VaR 95 % (1d)", fmt_pct(var95),
                       delta=f"CVaR 95 {fmt_pct(cvar95)}",
                       tone="down" if var95 and var95 < 0 else "",
                       palette=palette),
                  unsafe_allow_html=True)
    r2c3.markdown(_expl(palette, "Perte journalière dépassée ~1 jour sur 20 (cas défavorable). "
                        "Plus proche de 0 = mieux. CVaR = perte moyenne au-delà de ce seuil."),
                  unsafe_allow_html=True)
    r2c4.markdown(_kpi("VaR 99 % (1d)", fmt_pct(var99),
                       delta="historical quantile",
                       tone="down" if var99 and var99 < 0 else "",
                       palette=palette),
                  unsafe_allow_html=True)
    r2c4.markdown(_expl(palette, "Perte journalière dépassée ~1 jour sur 100 "
                        "(scénario extrême). Mesure le risque de queue."),
                  unsafe_allow_html=True)

    # --- Drawdown curve ---
    _section(palette, "Drawdown Curve",
             "Sous-performance vs précédent pic en %. Plus la courbe creuse, plus le portefeuille a saigné.")
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
             "Histogramme des returns quotidiens. Les queues épaisses ('fat tails') trahissent un risque non gaussien.")
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
        f"ℹ️ Beta vs benchmark sera disponible dans le sous-onglet « Benchmark Comparison » "
        f"une fois implémenté. Toutes les autres métriques sont prêtes à l'emploi."
    )


# ---------------------------------------------------------------------------
# Sub-tab 2 — Calendar heatmap of monthly returns
# ---------------------------------------------------------------------------

def _render_calendar_heatmap(static, price_history: pd.DataFrame, palette: dict) -> None:
    # VA6: VL so monthly returns reflect market perf, not flows
    nav = _portfolio_vl_series(price_history)
    if len(nav) < 2:
        st.info("Pas encore assez d'historique pour calculer des returns mensuels.")
        return

    # Monthly returns = NAV end-of-month vs NAV end-of-previous-month
    monthly = nav.resample("ME").last()
    m_ret = monthly.pct_change().dropna()
    if m_ret.empty:
        st.info(
            "Pas encore de mois clos dans l'historique. Le 1er mois complet apparaîtra ici "
            "dès que la DB couvrira deux fins de mois consécutives."
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
             "Returns calculés sur la NAV fin de mois. Vert = mois positif, rouge = mois négatif.")

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
        st.info("Pas assez d'historique pour calculer des corrélations significatives.")
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
        st.info("Returns non disponibles.")
        return

    # Pairwise correlation + observation count per pair (for hover tooltip)
    corr = rets.corr()
    valid = rets.notna().astype(int)
    n_obs = valid.T.dot(valid)   # symmetric N×N matrix of common observation counts

    max_obs = int(n_obs.values.max())
    _section(palette, "Correlation Matrix",
             f"Corrélation des returns daily — calculée paire par paire sur "
             f"leurs dates communes (jusqu'à {max_obs} séances). "
             f"+1 = parfaitement liés (vert), 0 = indépendants (jaune), "
             f"-1 = inversement liés (rouge).")

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
                     "Ces ETFs bougent ensemble — diversification limitée entre eux.")
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
                     "Ces ETFs apportent vraiment de la diversification au portefeuille.")
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
        f"= (1 − ρ̄ pondérée par les poids) × 100. Au-dessus de 60 = bonne diversification, "
        f"en dessous de 30 = portefeuille très corrélé.</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Sub-tab 3 — Performance Attribution
# ---------------------------------------------------------------------------

def _render_attribution(static, price_history: pd.DataFrame, palette: dict) -> None:
    if len(price_history) < 2:
        st.info("Pas assez d'historique pour calculer une attribution.")
        return

    # Work in PORTFOLIO currency so per-asset returns (and the NAV sums) include
    # FX moves and match the Positions tab / snapshot (no native-vs-PF mismatch).
    hist = data.price_history_in_portfolio_currency(price_history).sort_values("date").reset_index(drop=True)
    pf_ccy = data.current_portfolio_currency()
    min_d = hist["date"].min().date()
    max_d = hist["date"].max().date()

    _section(palette, "Performance Attribution",
             "Décomposition du return du portefeuille en contributions par ETF "
             "(contribution = poids initial × return de l'actif).")

    c1, c2 = st.columns(2)
    with c1:
        att_from = st.date_input("From", min_d, min_value=min_d, max_value=max_d, key="att_from")
    with c2:
        att_to = st.date_input("To", max_d, min_value=min_d, max_value=max_d, key="att_to")
    if att_from >= att_to:
        st.warning("La date de fin doit être strictement après la date de début.")
        return

    mask = (hist["date"].dt.date >= att_from) & (hist["date"].dt.date <= att_to)
    sub = hist.loc[mask]
    if len(sub) < 2:
        st.warning("La période sélectionnée doit contenir au moins 2 séances.")
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
        st.info("Aucun actif valorisable sur cette période — ajoute des transactions "
                "ou élargis la plage de dates.")
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
            "Poids début : %{customdata[0]:.2f} %<br>"
            "Return ETF  : %{customdata[1]:+.2f} %<br>"
            "Contribution: %{x:+.3f} pts<extra></extra>"
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
    fig.update_xaxes(title="Contribution au return total (points de %)",
                      ticksuffix=" pts",
                      range=[_lo / 100 - _span * 0.30 / 100 - 0.005,
                             _hi / 100 + _span * 0.30 / 100 + 0.005])
    fig.update_yaxes(title=None)
    st.plotly_chart(fig, width="stretch")

    # ---- Per-ETF performance over the period (vertical bars, % on top) ----
    _section(palette, "Performance par ETF sur la période",
             f"Return de chaque ETF entre {att_from} et {att_to} "
             f"(indépendant du poids — la pure performance de prix).")
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
        hovertemplate="<b>%{x}</b><br>Return période : %{y:+.2f}%<extra></extra>",
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
    _section(palette, "Tableau de détail")
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
        f"ℹ️ Σ contributions = {sum_contrib*100:+.4f} % · Return total = {total_ret*100:+.4f} % · "
        f"écart = {delta:.4f} pp (devrait être ≈ 0, légère différence due à la dérive des "
        f"poids dans la période)."
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
        st.info("Pas assez d'historique pour comparer à un benchmark.")
        return

    _section(palette, "Benchmark Comparison",
             "Compare ta NAV à un benchmark de référence. Indexées toutes deux à 100 à "
             "la première date d'historique pour une lecture directe.")

    bm_choice = st.selectbox(
        "Benchmark",
        options=list(BENCHMARKS.keys()),
        index=0,
        help="Choisis ton benchmark de référence.",
        key="bm_choice",
    )

    # VA6: VL = fair comparison vs benchmark (both reflect pure perf)
    nav = _portfolio_vl_series(price_history)
    if nav.empty:
        st.info("NAV indisponible.")
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
            st.error("Impossible de fetcher les composantes du benchmark 60/40.")
            return
        # Align both series, normalize to 100 at start, then weighted
        joined = pd.concat([world, bond], axis=1, keys=["world", "bond"]).ffill().dropna()
        joined = joined / joined.iloc[0] * 100
        bm = (0.6 * joined["world"] + 0.4 * joined["bond"]).rename(bm_info["label"])
    else:
        with st.spinner(f"Fetching {bm_info['ticker']}…"):
            bm = _fetch_benchmark(bm_info["ticker"], start_d, end_d)
        if bm.empty:
            st.error(f"Pas de données pour {bm_info['ticker']}.")
            return

    # Align dates with portfolio NAV
    common = nav.index.intersection(bm.index)
    if len(common) < 2:
        st.warning(
            f"Trop peu de dates communes entre ta NAV ({len(nav)} jours) et le benchmark "
            f"({len(bm)} jours). Réessaye quand l'historique sera plus long."
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

    _section(palette, "Statistiques de performance relative")
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
                     delta=f"sensibilité au {bm_info['label']}",
                     palette=palette), unsafe_allow_html=True)
    c6.markdown(_kpi("Correlation", fmt_num(corr),
                     delta=f"sur {len(common_rets)} returns daily",
                     palette=palette), unsafe_allow_html=True)

    # ---- Relative outperformance chart ----
    rel = (nav_idx - bm_idx)
    _section(palette, "Surperformance cumulée (points indexés)",
             "GPCP − Benchmark. Au-dessus de zéro = tu bats le marché, en-dessous = tu sous-performes.")
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
    fig_rel.update_yaxes(title="Écart cumulé (pts d'indice)")
    fig_rel.update_xaxes(rangebreaks=data.trading_day_rangebreaks(
        pd.DataFrame({"date": rel.index})))
    st.plotly_chart(fig_rel, width="stretch")


# ---------------------------------------------------------------------------
# Sub-tab 6 — Monte Carlo Simulator
# ---------------------------------------------------------------------------

def _render_monte_carlo(static, price_history: pd.DataFrame,
                          snapshot: dict, palette: dict) -> None:
    # VA6: calibrate GBM on VL returns (pure market perf, no flow contamination)
    # but START the simulation at the REAL CURRENT NAV in € so projected paths
    # are in real money. Otherwise "NAV de départ" would show ~100 (VL base).
    nav = _portfolio_vl_series(price_history)
    if len(nav) < 3:
        st.info(
            "Le Monte Carlo a besoin d'au moins une dizaine de séances pour calibrer "
            "vol et rendement historiques. Reviens dans 2-3 semaines."
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
             f"Simulation de N trajectoires GBM calibrées sur ton historique : μ = "
             f"{mu_a*100:.2f} %/an, σ = {sigma_a*100:.2f} %/an. "
             f"Départ : NAV actuelle = {nav_eur_now:,.0f} €. "
             f"Percentiles P10 / P50 / P90 et probabilité d'objectif.")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        horizon_y = st.selectbox("Horizon", options=[1, 3, 5, 10, 20], index=2,
                                  format_func=lambda x: f"{x} an" + ("s" if x > 1 else ""),
                                  key="mc_horizon")
    with c2:
        n_sims = st.selectbox("Nb simulations", options=[1000, 5000, 10000, 25000], index=2,
                              key="mc_n")
    with c3:
        contrib_monthly = st.number_input("Apport mensuel (€)", min_value=0, value=0, step=100,
                                          key="mc_contrib", help="Optionnel — simule du DCA.")
    with c4:
        target = st.number_input("Objectif NAV (€)", min_value=0,
                                 value=int(nav_eur_now * 2), step=1000,
                                 key="mc_target",
                                 help="Probabilité d'atteindre ce montant au terme.")

    n_steps = horizon_y * TRADING_DAYS

    # Vectorized GBM simulation — starts at current NAV in € (not VL ~100)
    nav0 = nav_eur_now
    contrib_daily = contrib_monthly * 12 / TRADING_DAYS  # smoothed daily

    rng = np.random.default_rng(42)
    # Geometric Brownian Motion: r_t = mu_d - 0.5*sigma_d^2 + sigma_d*Z_t
    drift = mu_d - 0.5 * sigma_d ** 2
    shocks = rng.normal(drift, sigma_d, size=(n_steps, n_sims))
    log_growth = np.cumsum(shocks, axis=0)
    growth = np.exp(log_growth)
    paths = nav0 * growth
    # Add daily contributions (smoothed) — gross approximation but fine for visualization
    if contrib_daily > 0:
        contrib_cum = np.cumsum(np.ones((n_steps, 1)) * contrib_daily * growth, axis=0)
        # NB: this isn't perfectly realistic; for a precise DCA simulation you'd
        # add €contrib at each step and let it grow. The approximation underweights
        # late contributions slightly — acceptable for indicative ranges.
        paths = paths + contrib_cum

    terminal = paths[-1, :]
    p10 = np.percentile(paths, 10, axis=1)
    p50 = np.percentile(paths, 50, axis=1)
    p90 = np.percentile(paths, 90, axis=1)

    # Build x-axis as future dates
    last_date = nav.index[-1]
    future_dates = pd.bdate_range(last_date + pd.Timedelta(days=1), periods=n_steps)

    fig = go.Figure()
    # Sample a few individual paths (faint) to give texture
    sample_idx = rng.choice(n_sims, size=min(40, n_sims), replace=False)
    for i in sample_idx:
        fig.add_trace(go.Scatter(
            x=future_dates, y=paths[:, i],
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
                      annotation_text=f"Objectif {target:,.0f} €",
                      annotation_position="top left",
                      annotation_font_color=palette["GREEN"])
    _style_fig(fig, palette, height=480)
    fig.update_yaxes(title="NAV simulée (€)", tickformat=",.0f", ticksuffix=" €")
    st.plotly_chart(fig, width="stretch")

    # KPI cards
    prob_target = float((terminal >= target).mean() * 100) if target > 0 else float("nan")
    prob_loss = float((terminal < nav0).mean() * 100)
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(_kpi(f"Median (P50) at {horizon_y}y",
                     f"{np.median(terminal):,.0f} €",
                     delta=f"× {np.median(terminal)/nav0:.2f}",
                     palette=palette), unsafe_allow_html=True)
    c2.markdown(_kpi("P10 (pessimiste)",
                     f"{np.percentile(terminal, 10):,.0f} €",
                     delta=f"× {np.percentile(terminal,10)/nav0:.2f}",
                     tone="down", palette=palette), unsafe_allow_html=True)
    c3.markdown(_kpi("P90 (optimiste)",
                     f"{np.percentile(terminal, 90):,.0f} €",
                     delta=f"× {np.percentile(terminal,90)/nav0:.2f}",
                     tone="up", palette=palette), unsafe_allow_html=True)
    c4.markdown(_kpi("P(atteint objectif)",
                     f"{prob_target:.1f} %" if not pd.isna(prob_target) else "—",
                     delta=f"P(perte vs aujourd'hui) {prob_loss:.1f} %",
                     tone="up" if (not pd.isna(prob_target) and prob_target > 50) else "",
                     palette=palette), unsafe_allow_html=True)

    # Terminal distribution histogram
    _section(palette, "Distribution finale", f"NAV après {horizon_y} an(s)")
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
                          annotation_text="Objectif", annotation_font_color=palette["GREEN"])
    _style_fig(fig_hist, palette, height=300, showlegend=False)
    fig_hist.update_xaxes(title="NAV terminale (€)", tickformat=",.0f", ticksuffix=" €")
    st.plotly_chart(fig_hist, width="stretch")

    st.caption(
        "ℹ️ Le modèle suppose des returns log-normaux i.i.d. — fiable pour la centrale mais "
        "sous-estime les krachs extrêmes (queues fines). C'est un ordre de grandeur, pas une prédiction."
    )

    # ---- Pedagogical explainer (collapsible) ----
    med = float(np.median(terminal))
    with st.expander("❓ Comment ça marche ? (données utilisées + méthode expliquée)"):
        st.markdown(
            f"""
**En une phrase :** on rejoue **{n_sims:,}** fois les {horizon_y} prochaines année(s)
de ton portefeuille, en tirant chaque jour un rendement au hasard *calibré sur ton
historique réel*, puis on regarde la distribution des résultats.

---

**1. Les données utilisées (mesurées sur ton historique)**

| Donnée | Valeur | D'où ça vient |
|---|---|---|
| Rendement moyen quotidien (μ) | {mu_d*100:.4f} % /jour | moyenne de tes returns journaliers |
| Volatilité quotidienne (σ) | {sigma_d*100:.4f} % /jour | écart-type de tes returns journaliers |
| → annualisés | μ ≈ {mu_a*100:.2f} % /an · σ ≈ {sigma_a*100:.2f} % /an | × 252 (et √252 pour σ) |
| NAV de départ | {nav0:,.0f} € | ta valeur actuelle |
| Apport mensuel simulé | {contrib_monthly:,} € | ton réglage (DCA) |
| Horizon | {horizon_y} an(s) = {n_steps} jours de bourse | ton réglage |

**2. La méthode : « Mouvement Brownien Géométrique » (GBM)**

C'est le modèle standard de la finance pour simuler un prix. Chaque jour :

```
rendement_du_jour  =  (μ − ½σ²)  +  σ × (tirage aléatoire gaussien)
                       └─ tendance ─┘   └──── le hasard du marché ────┘
```

- La **tendance** pousse doucement vers le haut (si μ>0).
- Le **tirage aléatoire** (une « loi normale ») ajoute le bruit quotidien : certains
  jours montent, d'autres descendent, avec une ampleur dictée par σ.
- On enchaîne {n_steps} jours → **une trajectoire**. On recommence {n_sims:,} fois →
  **{n_sims:,} trajectoires** toutes différentes.

**3. Lire le résultat**

Sur les {n_sims:,} fins de parcours, on classe les NAV finales et on prend :
- **P10** = le 10ᵉ percentile → seulement 10 % des scénarios font pire (cas pessimiste).
- **P50** (médiane) = la moitié font mieux, la moitié pire → **{med:,.0f} €**.
- **P90** = cas optimiste (10 % font mieux).
- **P(atteint objectif)** = part des trajectoires qui finissent ≥ ton objectif.

**4. Limites à garder en tête**
- Le modèle suppose que μ et σ futurs ressemblent au passé — faux lors d'un changement de régime.
- Il **sous-estime les krachs extrêmes** (les vraies bourses ont des « queues épaisses »).
- Avec peu d'historique, μ et σ sont mal estimés → résultats à prendre avec des pincettes.

👉 **C'est un éventail de possibles, pas une prédiction.** L'intérêt : visualiser le
*risque* (écart P10↔P90), pas deviner un chiffre exact.
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
def _live_geo_sector(ticker: str):
    """Sector + country for ANY asset — straight from Yahoo Finance, cached a day.

    - ETF → real sector look-through via `funds_data.sector_weightings`
      (multi-bucket). Yahoo exposes no clean country breakdown for funds, so geo
      is left to the curated factsheet JSON for the tracked ETFs.
    - Stock → its single sector + country, each a 100 % bucket.

    Returns (geo_dict, sector_dict), either possibly empty. No file writes →
    works on the cloud where etf_compositions.json is read-only/ephemeral, and
    auto-covers any newly added asset (incl. a brand-new ETF) with no scraper."""
    ticker = (ticker or "").strip()
    if not ticker:
        return {}, {}
    import compositions_scraper as _cs
    geo: dict[str, float] = {}
    sec: dict[str, float] = {}
    # ETF sector breakdown (non-empty only for funds)
    try:
        import yfinance as yf
        raw = yf.Ticker(ticker).funds_data.sector_weightings or {}
        for k, v in raw.items():
            try:
                name = _cs._YF_SECTOR_MAP.get(k, "Other")
                sec[name] = sec.get(name, 0.0) + float(v) * 100.0
            except (TypeError, ValueError):
                continue
    except Exception:
        pass
    is_fund = bool(sec)
    # Stock fallback: single sector + country buckets from .info
    try:
        info = _cs.lookup_yfinance_info(ticker)
    except Exception:
        info = {}
    if not sec and info.get("sector"):
        sec = {info["sector"]: 100.0}
    # Country only for a single stock (a fund's .info country = domicile, not
    # its holdings' geography — misleading, so skip it for ETFs).
    if not is_fund and info.get("country"):
        geo = {info["country"]: 100.0}
    return geo, sec


def _render_sector_geo(static, price_history: pd.DataFrame, snapshot: dict, palette: dict) -> None:
    compositions = _load_compositions()

    _section(palette, "Sector / Geographic Exposure",
             "Look-through : décomposition de tes positions à travers les compositions "
             "publiques de chacun des 7 ETFs. Les chiffres sont scrapés automatiquement "
             "le 15 de chaque mois depuis les factsheets officielles (Amundi / BNP) — "
             "clique sur ↗ factsheet pour cross-checker.")

    # Build the aggregated exposures
    total_value = sum(p["value"] for p in snapshot["positions"].values())
    if total_value <= 0:
        st.info("NAV nulle — pas d'exposition à afficher.")
        return

    def _eff_comp(asset: str) -> dict:
        """Effective geo/sector for an asset: the curated ETF JSON breakdown
        when available, otherwise a live Yahoo lookup — so stocks (and ETFs not
        in the JSON) get a sector/country too."""
        entry = compositions.get(asset, {}) or {}
        geo = entry.get("geo") or {}
        sec = entry.get("sector") or {}
        if geo and sec:
            return entry
        tk = data.TICKER_BY_ASSET.get(asset) or entry.get("ticker") or ""
        lg, ls = _live_geo_sector(tk)
        return {**entry, "geo": (geo or lg), "sector": (sec or ls)}

    def aggregate(key: str) -> dict:
        """Weight per-asset breakdowns by current portfolio value."""
        agg: dict[str, float] = {}
        for asset, p in snapshot["positions"].items():
            value = p["value"]   # = current_price × shares — drifts daily with the market
            weights = _eff_comp(asset).get(key, {})
            for cat, pct in weights.items():
                agg[cat] = agg.get(cat, 0.0) + value * pct / 100.0
        return agg

    geo = aggregate("geo")
    sec = aggregate("sector")

    # Still nothing (e.g. Yahoo unreachable for every holding). Bail cleanly.
    if not geo and not sec:
        st.info("Pas de données de composition pour les actifs détenus "
                "(secteur/pays indisponibles sur Yahoo pour ces tickers).")
        return

    def to_df(agg: dict, total: float, col_name: str) -> pd.DataFrame:
        if not agg:
            return pd.DataFrame(columns=[col_name, "€", "%"])
        df = pd.DataFrame(
            [{col_name: k, "€": v, "%": v / total * 100} for k, v in agg.items()]
        )
        return df.sort_values("€", ascending=False).reset_index(drop=True)

    geo_df = to_df(geo, total_value, "Pays / Région")
    sec_df = to_df(sec, total_value, "Secteur")

    # Plot side-by-side
    col_g, col_s = st.columns(2)
    with col_g:
        st.markdown(
            f"<div style='color:{palette['ACCENT']};font-size:13px;font-weight:600;"
            f"letter-spacing:1.5px;text-transform:uppercase;margin-bottom:8px'>"
            f"Exposition géographique</div>", unsafe_allow_html=True,
        )
        fig_g = go.Figure(go.Bar(
            x=geo_df["%"], y=geo_df["Pays / Région"], orientation="h",
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
            f"Exposition sectorielle</div>", unsafe_allow_html=True,
        )
        fig_s = go.Figure(go.Bar(
            x=sec_df["%"], y=sec_df["Secteur"], orientation="h",
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
            f"⚠️ Concentration géographique élevée : **{geo_df.iloc[0]['Pays / Région']}** = "
            f"**{geo_df.iloc[0]['%']:.1f} %** du portefeuille."
        )
    if not sec_df.empty and sec_df.iloc[0]["%"] > 30:
        insights.append(
            f"⚠️ Concentration sectorielle : **{sec_df.iloc[0]['Secteur']}** = "
            f"**{sec_df.iloc[0]['%']:.1f} %**."
        )
    # Currency proxy: USA + UK + most of EM is USD-denominated for the underlyings
    usd_share = geo.get("USA", 0) / total_value * 100
    if usd_share > 30:
        insights.append(
            f"💱 Exposition USD (sous-jacents US) : **{usd_share:.1f} %**. "
            f"Tu portes ce risque de change même si tes ETFs sont libellés EUR."
        )

    if not insights:
        insights.append("✓ Pas de concentration excessive détectée.")
    for ins in insights:
        st.markdown(ins)

    # Aggregated tables (always visible)
    _section(palette, "Tableaux agrégés (look-through portefeuille)")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"<div style='color:{palette['MUTED']};font-size:11px;"
                    f"letter-spacing:1px;text-transform:uppercase'>Géographique</div>",
                    unsafe_allow_html=True)
        tbl_g = geo_df.copy()
        tbl_g["€"] = tbl_g["€"].map(lambda v: f"{v:,.2f} €")
        tbl_g["%"] = tbl_g["%"].map(lambda v: f"{v:.2f} %")
        st.dataframe(tbl_g, width="stretch", hide_index=True)
    with c2:
        st.markdown(f"<div style='color:{palette['MUTED']};font-size:11px;"
                    f"letter-spacing:1px;text-transform:uppercase'>Sectorielle</div>",
                    unsafe_allow_html=True)
        tbl_s = sec_df.copy()
        tbl_s["€"] = tbl_s["€"].map(lambda v: f"{v:,.2f} €")
        tbl_s["%"] = tbl_s["%"].map(lambda v: f"{v:.2f} %")
        st.dataframe(tbl_s, width="stretch", hide_index=True)

    # Per-ETF tables — one block per ETF showing its own geo + sector breakdown
    _section(palette, "Détail par ETF",
             "Composition publique de chaque ETF (factsheet émetteur). "
             "Le pastille de droite indique la fraîcheur des données. "
             "Le poids du portefeuille s'applique automatiquement au calcul agrégé ci-dessus.")

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
                    f"font-style:italic'>MàJ {auto_ts} · {auto_src}</span>")

        st.markdown(
            f"<div style='background:{p_panel};border:1px solid {p_grid};"
            f"border-radius:10px;padding:14px 18px;margin-top:14px;margin-bottom:6px'>"
            f"<div style='display:flex;justify-content:space-between;align-items:baseline'>"
            f"<div><b style='color:{p_text};font-size:14px'>{asset}</b>"
            f" <span style='color:{p_muted};font-size:11px;font-family:monospace'>"
            f"{isin} · {issuer}</span>{prov}</div>"
            f"<div style='font-size:11px'>"
            f"<span style='color:{p_muted}'>poids: "
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

        geo_e_df = _comp_df(geo_e, "Pays / Région")
        sec_e_df = _comp_df(sec_e, "Secteur")

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
        f"ℹ️ Calcul agrégé : pour chaque ETF, ses % géo/secteur sont multipliés par "
        f"sa **valeur actuelle en €** dans le portefeuille (= prix×parts du jour), "
        f"puis sommés. Quand un ETF surperforme, son influence sur les expos agrégées "
        f"monte automatiquement. Σ poids = {sum_check:.2f} %."
    )


# ---------------------------------------------------------------------------
# Sub-tab 7 — Monthly PDF Export
# ---------------------------------------------------------------------------

REPORTS_DIR = data.ROOT / "reports"


def _render_pdf_export(static, price_history: pd.DataFrame, snapshot: dict, palette: dict) -> None:
    _section(palette, "Monthly PDF Export",
             "Génère un rapport stylé d'une page récapitulant l'état du portefeuille. "
             "Le fichier est sauvegardé dans le dossier reports/ — tu peux l'envoyer "
             "par email ou archiver à la main. Pas de SMTP requis (sécurité).")

    REPORTS_DIR.mkdir(exist_ok=True)

    # List existing reports
    existing = sorted(REPORTS_DIR.glob("GPCP_*.pdf"), reverse=True)
    if existing:
        st.markdown("**📂 Rapports déjà générés :**")
        for f in existing[:10]:
            size_kb = f.stat().st_size / 1024
            st.markdown(
                f"<div style='font-family:monospace;font-size:12px;color:{palette['MUTED']}'>"
                f"  {f.name} <span style='float:right'>{size_kb:.1f} KB</span></div>",
                unsafe_allow_html=True,
            )

    c1, c2 = st.columns([1, 3])
    with c1:
        period = st.selectbox("Période", options=["This month", "Last month", "YTD", "All-time"],
                               key="pdf_period")

    if st.button("📄 Générer le rapport", type="primary"):
        try:
            with st.spinner("Generating PDF…"):
                pdf_path = _generate_pdf_report(static, price_history, snapshot, period)
            st.success(f"✓ Rapport généré : `{pdf_path.name}` ({pdf_path.stat().st_size/1024:.1f} KB)")
            # Offer download via Streamlit
            with open(pdf_path, "rb") as f:
                st.download_button(
                    label=f"⬇ Télécharger {pdf_path.name}",
                    data=f.read(),
                    file_name=pdf_path.name,
                    mime="application/pdf",
                )
            st.caption(f"📁 Fichier également disponible localement : {pdf_path}")
        except Exception as exc:
            st.error(f"Erreur génération : {exc}")
            import traceback
            st.code(traceback.format_exc())


def _generate_pdf_report(static, price_history: pd.DataFrame, snapshot: dict, period: str):
    """Generate a one-page PDF report and return its path."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    )

    today = dt.date.today()
    fname = f"GPCP_{today.strftime('%Y-%m')}_{period.replace(' ', '_').lower()}.pdf"
    path = REPORTS_DIR / fname

    doc = SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "T", parent=styles["Title"], fontSize=20, leading=24,
        textColor=colors.HexColor("#FF8800"), spaceAfter=4,
    )
    sub_style = ParagraphStyle(
        "S", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#8B95A1"),
        spaceAfter=14, alignment=0,
    )
    h2 = ParagraphStyle(
        "H2", parent=styles["Heading2"], fontSize=12,
        textColor=colors.HexColor("#1A1D21"), spaceBefore=10, spaceAfter=6,
    )
    body = ParagraphStyle("B", parent=styles["Normal"], fontSize=9, leading=12)

    story = []
    story.append(Paragraph("GPCP — Portfolio Report", title_style))
    story.append(Paragraph(
        f"Période : <b>{period}</b> · Date du rapport : {today.strftime('%d %B %Y')} · "
        f"Inception : {snapshot['inception_date'].strftime('%d %b %Y') if snapshot.get('inception_date') else '—'}",
        sub_style,
    ))

    # ----- KPI block -----
    story.append(Paragraph("Headline KPIs", h2))
    kpi_data = [
        ["Métrique", "Valeur"],
        ["NAV", f"{snapshot['total_value']:,.2f} €"],
        ["Daily P&L", f"{snapshot['daily_pnl_eur']:+,.2f} € ({snapshot['daily_pnl_pct']*100:+.2f} %)"],
        ["Total Return", f"{snapshot['total_return_eur']:+,.2f} € ({snapshot['total_return_pct']*100:+.2f} %)"],
        ["VL (base 100)", f"{snapshot['vl']:.4f}"],
        ["Nb ETFs", f"{len(snapshot['positions'])}"],
    ]
    t = Table(kpi_data, colWidths=[60 * mm, 110 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#161A1F")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E1E5EA")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.whitesmoke, colors.HexColor("#F7F8FA")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t)
    story.append(Spacer(1, 6 * mm))

    # ----- Positions table -----
    story.append(Paragraph("Positions", h2))
    pos_data = [["ETF", "Parts", "Prix (€)", "Valeur (€)", "Alloc", "Daily", "Total Ret"]]
    for asset in data.ASSETS:
        p = snapshot["positions"].get(asset, {})
        pos_data.append([
            asset,
            str(static.shares.get(asset, 0)),
            f"{p.get('price', 0):.4f}",
            f"{p.get('value', 0):,.2f}",
            f"{p.get('allocation', 0)*100:.2f} %",
            f"{p.get('daily_return', 0)*100:+.2f} %",
            f"{p.get('total_return', 0)*100:+.2f} %",
        ])
    pos_data.append([
        "TOTAL", "", "", f"{snapshot['total_value']:,.2f}", "100.00 %",
        f"{snapshot['daily_pnl_pct']*100:+.2f} %",
        f"{snapshot['total_return_pct']*100:+.2f} %",
    ])
    pt = Table(pos_data, colWidths=[28 * mm, 14 * mm, 22 * mm, 26 * mm,
                                     20 * mm, 22 * mm, 22 * mm])
    pt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#161A1F")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E1E5EA")),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E1E5EA")),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2),
         [colors.whitesmoke, colors.HexColor("#F7F8FA")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(pt)
    story.append(Spacer(1, 6 * mm))

    # ----- Top movers / drift -----
    story.append(Paragraph("Top movers", h2))
    movers = sorted(
        [(a, snapshot["positions"][a]) for a in data.ASSETS if a in snapshot["positions"]],
        key=lambda kv: kv[1].get("daily_return", 0),
        reverse=True,
    )
    best = movers[:3]
    worst = movers[-3:][::-1]
    mover_data = [["📈 Top 3 (daily)", "", "📉 Bottom 3 (daily)", ""]]
    for i in range(3):
        l_asset, l_p = best[i] if i < len(best) else ("", {})
        r_asset, r_p = worst[i] if i < len(worst) else ("", {})
        mover_data.append([
            l_asset, f"{l_p.get('daily_return', 0)*100:+.2f} %" if l_asset else "",
            r_asset, f"{r_p.get('daily_return', 0)*100:+.2f} %" if r_asset else "",
        ])
    mt = Table(mover_data, colWidths=[38 * mm, 22 * mm, 38 * mm, 22 * mm])
    mt.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (1, 1), (1, -1), "RIGHT"),
        ("ALIGN", (3, 1), (3, -1), "RIGHT"),
        ("TEXTCOLOR", (1, 1), (1, -1), colors.HexColor("#16855B")),
        ("TEXTCOLOR", (3, 1), (3, -1), colors.HexColor("#C9302C")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(mt)
    story.append(Spacer(1, 6 * mm))

    # ----- Footer -----
    story.append(Paragraph(
        "<i>Rapport généré automatiquement par GPCP Dashboard. "
        "Données issues de Yahoo Finance.</i>",
        ParagraphStyle("F", parent=body, fontSize=7,
                       textColor=colors.HexColor("#8B95A1"), alignment=1),
    ))

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
