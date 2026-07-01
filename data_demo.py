"""Read-only DEMO backend — a frozen, fictional US-stock portfolio.

Activated by the "Démo" button on the login page (sets
`st.session_state["__demo_mode"]`). The data dispatcher (`data.py`) then routes
here: `install()` feeds the FULL V15 engine (`data_sqlite`) with the frozen demo
dataset by replacing its data-access *leaves*, and blocks every write. So all the
real maths (snapshot, VL, Pro tabs) run unchanged — just over the demo data.

No Supabase, no sqlite file: everything comes from the bundled `demo_data.json`
(7 diversified index ETFs, ~1 year of real frozen closes — actual split-adjusted
prices, so they match Yahoo, EUR). A few pure
helpers that V15 sqlite never had (augmented_price_history, sell_pnl_rows,
avg_cost_by_asset…) are provided here too, so the demo shows the same buy/sell
markers and realized-P&L as the live cloud app.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd
import streamlit as st

import data_sqlite as _ds

_DEMO_PATH = Path(__file__).resolve().parent / "demo_data.json"

_INSTALLED = False
_PH: pd.DataFrame | None = None       # price history (date + one col per asset)
_TX: list[dict] = []                  # transactions (engine dict shape)
_ASSETS: list[str] = []
_CCY = "USD"
_INCEPTION: dt.date | None = None
_TICKERS: dict[str, str] = {}
_STATIC = None


def _demo_pf() -> dict:
    return {"id": "DEMO", "name": "Demo (read-only)",
            "currency": _CCY, "seed_from_workbook": False}


def _load() -> None:
    global _PH, _TX, _ASSETS, _CCY, _INCEPTION, _TICKERS, _STATIC
    d = json.loads(_DEMO_PATH.read_text(encoding="utf-8"))
    _ASSETS = list(d["assets"])
    _CCY = (d.get("currency") or "USD").upper()
    _TICKERS = dict(d.get("tickers", {}))

    ph = pd.DataFrame({"date": pd.to_datetime(d["dates"])})
    for a in _ASSETS:
        ph[a] = [float(x) for x in d["prices"][a]]
    _PH = ph

    _TX = [{
        "id": i,
        "date": dt.date.fromisoformat(t["date"]),
        "asset": t["asset"],
        "isin": "",
        "type": (t["type"] or "BUY").upper(),
        "price": float(t["price"]) if t.get("price") is not None else None,
        "shares": float(t.get("shares") or 0),
        "amount": float(t.get("amount") or 0),
        "currency": (t.get("currency") or "USD").upper(),
    } for i, t in enumerate(d["transactions"])]

    # Inception = first transaction (when the portfolio actually starts holding),
    # NOT the first price row — otherwise NAV is 0 before the first buy and the
    # unitized VL degenerates.
    _INCEPTION = min((t["date"] for t in _TX), default=dt.date.fromisoformat(d["inception"]))

    shares: dict[str, float] = {}
    for t in _TX:
        if t["type"] == "BUY":
            shares[t["asset"]] = shares.get(t["asset"], 0.0) + t["shares"]
        elif t["type"] == "SELL":
            shares[t["asset"]] = shares.get(t["asset"], 0.0) - t["shares"]
    shares = {a: s for a, s in shares.items() if abs(s) > 1e-9}

    _STATIC = _ds.PortfolioStatic(
        isins={a: "" for a in _ASSETS},
        funds={a: "—" for a in _ASSETS},
        fees={a: 0.0 for a in _ASSETS},
        shares=shares,
        tickers=dict(_TICKERS),
        currencies={a: _CCY for a in _ASSETS},
    )


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _live_tail(since_iso: str, tickers: tuple) -> dict:
    """Recent closes AFTER the frozen snapshot, for the demo tickers — cached 6h
    so the demo stays current (up to the latest trading day) without re-fetching
    on every rerun. Best-effort: any failure yields no tail (frozen base shown)."""
    import prices as _p
    since = dt.date.fromisoformat(since_iso)
    today = dt.date.today()
    out: dict[str, dict[str, float]] = {}
    for name, tk in tickers:
        try:
            s = _p.fetch_ticker_history(tk, since + dt.timedelta(days=1), today)
            out[name] = {d.isoformat(): float(p) for d, p in s if p is not None}
        except Exception:
            out[name] = {}
    return out


def _price_history(full: bool = False) -> pd.DataFrame:
    """Frozen ~1-year base + a live, cached tail → the demo shows current prices."""
    if _PH is None:
        return pd.DataFrame()
    base = _PH
    try:
        tail = _live_tail(base["date"].iloc[-1].date().isoformat(), tuple(_TICKERS.items()))
    except Exception:
        tail = {}
    per_asset = [set(tail.get(a, {})) for a in _ASSETS]
    new_dates = sorted(set.intersection(*per_asset)) if (per_asset and all(per_asset)) else []
    if not new_dates:
        return base.copy()
    rows = {"date": [pd.Timestamp(d) for d in new_dates]}
    for a in _ASSETS:
        rows[a] = [tail[a][d] for d in new_dates]
    return pd.concat([base, pd.DataFrame(rows)], ignore_index=True)


# ---- read helpers V15-sqlite never had (pure; operate on the frozen demo) ----

def _buys_by_asset() -> dict[str, list[tuple[dt.date, float]]]:
    out: dict[str, list[tuple[dt.date, float]]] = {}
    for t in _TX:
        if t["type"] == "BUY" and t.get("price"):
            out.setdefault(t["asset"], []).append((t["date"], float(t["price"])))
    for a in out:
        out[a].sort()
    return out


def first_buy_by_asset() -> dict[str, tuple[dt.date, float]]:
    return {a: lst[0] for a, lst in _buys_by_asset().items() if lst}


def avg_cost_by_asset() -> dict[str, tuple[dt.date, float]]:
    agg: dict[str, dict] = {}
    for t in _TX:
        if t["type"] == "BUY" and t.get("price") and t.get("shares"):
            d = agg.setdefault(t["asset"], {"amt": 0.0, "sh": 0.0, "first": t["date"]})
            d["amt"] += float(t["price"]) * float(t["shares"])
            d["sh"] += float(t["shares"])
            if t["date"] < d["first"]:
                d["first"] = t["date"]
    return {a: (d["first"], d["amt"] / d["sh"]) for a, d in agg.items() if d["sh"] > 0}


def sell_pnl_rows() -> list[dict]:
    out: list[dict] = []
    for t in _TX:
        if t["type"] != "SELL":
            continue
        asset, sale = t["asset"], t["date"]
        sp = float(t.get("price") or 0.0)
        ss = float(t.get("shares") or 0.0)
        amt = sh = 0.0
        for b in _TX:
            if (b["type"] == "BUY" and b["asset"] == asset and b["date"] <= sale
                    and b.get("price") and b.get("shares")):
                amt += float(b["price"]) * float(b["shares"])
                sh += float(b["shares"])
        ac = (amt / sh) if sh > 0 else None
        out.append({
            "id": t["id"], "date": sale, "asset": asset, "shares": ss,
            "sell_price": sp, "avg_cost": ac, "currency": t["currency"],
            "pnl": ((sp - ac) * ss) if ac is not None else None,
            "return_pct": ((sp / ac - 1.0) if (ac and ac > 0) else None),
        })
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


def augmented_price_history(price_history: pd.DataFrame | None = None) -> pd.DataFrame:
    ph = _price_history() if price_history is None else price_history.copy()
    cols = [c for c in ph.columns if c not in ("date", "is_buy", "is_sell")]
    if ph.empty:
        out = ph.copy()
        if "is_buy" not in out.columns:
            out.insert(1, "is_buy", pd.Series([], dtype=bool))
        if "is_sell" not in out.columns:
            out.insert(2, "is_sell", pd.Series([], dtype=bool))
        return out
    ph = ph.sort_values("date").reset_index(drop=True)
    buy_by_date: dict[dt.date, dict[str, float]] = {}
    for a, lst in _buys_by_asset().items():
        if a in cols:
            for d, p in lst:
                buy_by_date.setdefault(d, {})[a] = p
    sell_by_date: dict[dt.date, dict[str, float]] = {}
    for t in _TX:
        if t["type"] == "SELL" and t.get("price") and t["asset"] in cols:
            sell_by_date.setdefault(t["date"], {})[t["asset"]] = float(t["price"])

    def close_asof(d):
        prior = ph[ph["date"].dt.date <= d]
        src = prior.iloc[-1] if not prior.empty else None
        return {c: (src[c] if src is not None else float("nan")) for c in cols}

    events = [(r["date"], "", {c: r[c] for c in cols}) for _, r in ph.iterrows()]
    for d, amap in buy_by_date.items():
        v = close_asof(d); v.update(amap); events.append((pd.Timestamp(d), "buy", v))
    for d, amap in sell_by_date.items():
        v = close_asof(d); v.update(amap); events.append((pd.Timestamp(d), "sell", v))
    events.sort(key=lambda e: (e[0], 0 if e[1] else 1))
    rows = [{"date": ts, "is_buy": k == "buy", "is_sell": k == "sell", **v}
            for ts, k, v in events]
    return pd.DataFrame(rows)[["date", "is_buy", "is_sell", *cols]]


def _load_transactions() -> pd.DataFrame:
    if not _TX:
        return pd.DataFrame(columns=["Id", "Date", "Asset", "ISIN", "Type",
                                     "Price", "Shares", "Total", "Currency"])
    df = pd.DataFrame([{
        "Id": t["id"], "Date": t["date"], "Asset": t["asset"], "ISIN": "",
        "Type": t["type"], "Price": t["price"], "Shares": t["shares"],
        "Total": t["amount"], "Currency": t["currency"],
    } for t in _TX])
    df["Date"] = pd.to_datetime(df["Date"])
    return df.sort_values("Date", ascending=False).reset_index(drop=True)


def _blocked(*_a, **_k):
    raise RuntimeError("Demo portfolio — read-only (changes disabled).")


def install() -> None:
    """Point data_sqlite's leaves at the frozen demo data + block all writes. Idempotent."""
    global _INSTALLED
    if _INSTALLED:
        return
    _load()

    # ---- reads (data-access leaves the engine builds on) ----
    _ds.ASSETS[:] = _ASSETS                        # mutate the shared list in place
    _ds.TICKER_BY_ASSET = dict(_TICKERS)
    _ds.ISIN_BY_ASSET = {a: "" for a in _ASSETS}
    _ds._all_transactions = lambda: _TX
    _ds.load_transactions = _load_transactions
    _ds.load_price_history = _price_history
    _ds.load_position_history = _price_history
    _ds.load_static = lambda: _STATIC
    _ds.current_portfolio = _demo_pf
    _ds.current_portfolio_currency = lambda: _CCY
    _ds.list_portfolios = lambda: [_demo_pf()]
    _ds.get_inception_date = lambda: _INCEPTION
    _ds.default_inception_date = lambda: _INCEPTION
    _ds.latest_price_date = lambda: (_price_history()["date"].iloc[-1].date()
                                     if _PH is not None else None)
    _ds.last_save_at = lambda: None
    _ds.fx_rate = lambda a, b, when=None: 1.0          # all USD → no FX
    _ds.prefetch_fx_window = lambda *a, **k: None
    _ds.ensure_seeded = lambda: None
    # pure helpers V15 sqlite never had (so the demo shows buy/sell markers +P&L)
    _ds._buys_by_asset = _buys_by_asset
    _ds.first_buy_by_asset = first_buy_by_asset
    _ds.avg_cost_by_asset = avg_cost_by_asset
    _ds.sell_pnl_rows = sell_pnl_rows
    _ds.augmented_price_history = augmented_price_history

    # ---- writes (every mutation surfaces a friendly read-only error) ----
    for fn in ("add_transaction", "delete_transaction", "add_cash_movement",
               "add_transactions_bulk", "save_today", "backfill_prices",
               "register_asset", "create_portfolio", "switch_portfolio",
               "rename_portfolio", "delete_portfolio", "set_inception_date",
               "refetch_recent_closes", "refetch_all_prices_from_inception",
               "backfill_all_assets_to_inception"):
        setattr(_ds, fn, _blocked)

    _INSTALLED = True
