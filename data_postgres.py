"""Supabase Postgres backend — multi-tenant implementation of the data API.

Same public surface as `data_sqlite.py` so the dispatcher in `data.py`
can swap them transparently. Every query is scoped to the current
authenticated user via `_user_id()` which reads `st.session_state`
populated by `auth.require_auth()`.

Row-Level Security on the Postgres side enforces the same isolation at
the database level — so even if a query forgot the user filter, RLS
would block cross-user reads. Belt + suspenders.
"""

from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import pandas as pd

# Streamlit Cloud runs in UTC — stamp saved timestamps in Paris time so the
# UI ("last save", "last update") matches the owner's wall clock.
PARIS_TZ = ZoneInfo("Europe/Paris")

import supabase_client


# ----------------------------------------------------------------------
# Module-level globals re-exported from data_sqlite
# (constants, currency helpers — pure values, not touched by backend choice)
# ----------------------------------------------------------------------

import data_sqlite as _ds

# Constants — verbatim from sqlite backend
ROOT = _ds.ROOT                                  # repo root Path (pure constant)
DEFAULT_INCEPTION = _ds.DEFAULT_INCEPTION if hasattr(_ds, "DEFAULT_INCEPTION") else dt.date(2025, 1, 1)
TRADING_DAYS = getattr(_ds, "TRADING_DAYS", 252)
CURRENCY_SYMBOL = _ds.CURRENCY_SYMBOL
COMMON_CURRENCIES = _ds.COMMON_CURRENCIES

# Pure helpers — no DB I/O, re-exported as-is
trading_day_rangebreaks = _ds.trading_day_rangebreaks
PortfolioStatic = _ds.PortfolioStatic
# NOTE: price_history_in_portfolio_currency is NOT re-exported — its body
# references current_portfolio_currency()/load_static()/ASSETS as module
# name lookups, which would bind to data_sqlite's globals (reading sqlite
# data). It is re-implemented cloud-natively in the FX section below.

# Per-session asset state — ASSETS / ISIN_BY_ASSET / TICKER_BY_ASSET /
# YF_TICKER_BY_ISIN.
#
# These MUST NOT be plain module globals: Streamlit Cloud runs every user's
# session in the SAME process, so a shared global list would let one user's
# _sync_module_globals() clobber another user's asset list mid-render →
# crashes and cross-user data mixing. We back them with st.session_state (which
# Streamlit isolates per session) via thin proxies, so all existing
# `data.ASSETS` / `ASSETS.clear()` / `MAP.get(...)` call sites work unchanged
# while each session sees only its own data. Outside a session (cron, tests)
# they fall back to a process-local container.

class _SessionProxy:
    """Common base: resolve the per-session backing container (or a fallback)."""
    def __init__(self, key, factory):
        object.__setattr__(self, "_key", key)
        object.__setattr__(self, "_factory", factory)
        object.__setattr__(self, "_fallback", factory())

    def _store(self):
        try:
            from streamlit.runtime.scriptrunner import get_script_run_ctx
            if get_script_run_ctx() is None:
                return self._fallback          # no session (cron / tests)
            import streamlit as st
            ss = st.session_state
            if self._key not in ss:
                ss[self._key] = self._factory()
            return ss[self._key]
        except Exception:
            return self._fallback

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._store(), name)   # delegate clear/extend/get/update/…

    def __iter__(self):
        return iter(self._store())

    def __len__(self):
        return len(self._store())

    def __contains__(self, x):
        return x in self._store()

    def __getitem__(self, k):
        return self._store()[k]

    def __bool__(self):
        return bool(self._store())

    def __repr__(self):
        return repr(self._store())


class _ListProxy(_SessionProxy):
    def __init__(self, key):
        super().__init__(key, list)


class _DictProxy(_SessionProxy):
    def __init__(self, key, factory=dict):
        super().__init__(key, factory)

    def __setitem__(self, k, v):
        self._store()[k] = v


ASSETS = _ListProxy("_dp_assets")
ISIN_BY_ASSET = _DictProxy("_dp_isin_by_asset")
TICKER_BY_ASSET = _DictProxy("_dp_ticker_by_asset")
YF_TICKER_BY_ISIN = _DictProxy(
    "_dp_yf_ticker_by_isin",
    factory=lambda: dict(getattr(_ds, "_SEED_TICKER_BY_ISIN", {})),
)


# ----------------------------------------------------------------------
# Session / user / portfolio helpers
# ----------------------------------------------------------------------

def _user_id() -> str:
    """Current authenticated user_id from streamlit session_state."""
    import streamlit as st
    user = st.session_state.get("__saas_user")
    if not user or not user.get("id"):
        raise RuntimeError("No authenticated user — cloud backend used outside auth flow.")
    return user["id"]


def _sb():
    """User-scoped Supabase client — carries the logged-in user's JWT so
    Row-Level Security returns that user's rows. NEVER use the anon
    get_client() here: it has no session, so RLS would yield zero rows."""
    return supabase_client.get_user_client()


_PAGE = 1000  # PostgREST caps a single response at 1000 rows (Supabase default)


def _select_all(build_query, page_size: int = _PAGE) -> list[dict]:
    """Fetch EVERY row of a query, paging past PostgREST's 1000-row response cap.

    Without this, `.select(...).execute()` on a large table (prices, fx_rates)
    silently returns only the first `page_size` rows — for prices ordered by date
    that's the OLDEST ~1000 rows (≈4 years for one asset), which is exactly why
    the dashboard froze mid-2022 while newer prices sat unread in Postgres.

    `build_query` must return a FRESH, fully-filtered-and-ORDERED query on each
    call (a PostgREST builder can't be reused after `.range()/.execute()`). The
    ordering MUST be deterministic (unique key) or rows can shift across page
    boundaries — callers order by a unique tuple (date + asset / pair / id)."""
    rows: list[dict] = []
    start = 0
    while True:
        res = build_query().range(start, start + page_size - 1).execute()
        batch = res.data or []
        rows.extend(batch)
        if len(batch) < page_size:
            return rows
        start += page_size


def _slugify(name: str) -> str:
    """Same slugify rule as sqlite backend so portfolio_ids stay portable."""
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (name or "").strip()).strip("_")
    return s or "untitled"


# ----------------------------------------------------------------------
# Caches (per-process, invalidated on writes)
# ----------------------------------------------------------------------

_PF_CACHE: dict[str, list[dict]] = {}            # keyed by user_id
_CURRENT_PF_CACHE: dict[str, str] = {}           # user_id → portfolio_id
_TX_CACHE: dict[tuple[str, str], list[dict]] = {}  # (user_id, pf_id) → rows
_FX_CACHE: dict[tuple[str, str, str, str], float] = {}  # (user, pf, pair, date) → rate
_FX_LOADED: set[tuple[str, str]] = set()         # (user_id, pf_id) already pulled from DB
_HOLDINGS_CACHE: dict[tuple[str, str], list[dict]] = {}


def _invalidate_caches() -> None:
    _PF_CACHE.clear()
    _CURRENT_PF_CACHE.clear()
    _TX_CACHE.clear()
    _FX_CACHE.clear()
    _FX_LOADED.clear()
    _HOLDINGS_CACHE.clear()
    _sync_module_globals()


# ----------------------------------------------------------------------
# Portfolio registry
# ----------------------------------------------------------------------

def list_portfolios() -> list[dict]:
    uid = _user_id()
    if uid in _PF_CACHE:
        return _PF_CACHE[uid]
    res = _sb().table("portfolios").select("*").eq("user_id", uid).execute()
    rows = res.data or []
    _PF_CACHE[uid] = rows
    return rows


def current_portfolio() -> dict:
    """Return the active portfolio for this user. Auto-creates a default
    if the user has none yet (first signup → empty platform)."""
    uid = _user_id()
    pid = _CURRENT_PF_CACHE.get(uid)
    if pid is None:
        res = (_sb().table("current_portfolio").select("portfolio_id")
                 .eq("user_id", uid).limit(1).execute())
        if res.data:
            pid = res.data[0]["portfolio_id"]
        else:
            # First-time user — create a default portfolio
            pf = create_portfolio("My Portfolio", currency="EUR")
            pid = pf["id"]
        _CURRENT_PF_CACHE[uid] = pid

    # Return the portfolio dict
    pfs = list_portfolios()
    match = [p for p in pfs if p["id"] == pid]
    if not match:
        # Stale current — fall back to the first portfolio
        if pfs:
            pid = pfs[0]["id"]
            switch_portfolio(pid)
            return pfs[0]
        # No portfolios at all — create one
        return create_portfolio("My Portfolio", "EUR")
    return match[0]


def current_portfolio_currency() -> str:
    return (current_portfolio().get("currency") or "EUR").upper()


def switch_portfolio(pid: str) -> None:
    uid = _user_id()
    _sb().table("current_portfolio").upsert(
        {"user_id": uid, "portfolio_id": pid}, on_conflict="user_id"
    ).execute()
    _CURRENT_PF_CACHE[uid] = pid
    _invalidate_caches()


def create_portfolio(name: str, currency: str = "EUR") -> dict:
    uid = _user_id()
    pid = _slugify(name)
    # Ensure unique pid for this user
    existing = {p["id"] for p in list_portfolios()}
    i = 0
    while pid in existing:
        i += 1
        pid = f"{_slugify(name)}_{i}"
    row = {
        "user_id": uid, "id": pid, "name": name,
        "currency": (currency or "EUR").upper(),
        "seed_from_workbook": False,
    }
    _sb().table("portfolios").insert(row).execute()
    _sb().table("current_portfolio").upsert(
        {"user_id": uid, "portfolio_id": pid}, on_conflict="user_id"
    ).execute()
    _PF_CACHE.pop(uid, None)
    _CURRENT_PF_CACHE[uid] = pid
    _sync_module_globals()
    return row


def rename_portfolio(pid: str, new_name: str) -> None:
    uid = _user_id()
    _sb().table("portfolios").update({"name": new_name}).eq(
        "user_id", uid).eq("id", pid).execute()
    _PF_CACHE.pop(uid, None)


def delete_portfolio(pid: str) -> None:
    uid = _user_id()
    # Cascade-style delete (RLS enforces user_id)
    for table in ("holdings", "prices", "transactions", "fx_rates", "meta",
                  "current_portfolio", "portfolios"):
        q = _sb().table(table).delete().eq("user_id", uid)
        if table != "current_portfolio":
            q = q.eq("portfolio_id" if table != "portfolios" else "id", pid)
        else:
            q = q.eq("portfolio_id", pid)
        try:
            q.execute()
        except Exception:
            pass
    _invalidate_caches()


# ----------------------------------------------------------------------
# Holdings / ASSETS / tickers
# ----------------------------------------------------------------------

def _read_holdings_rows() -> list[dict]:
    uid = _user_id()
    pid = current_portfolio()["id"]
    key = (uid, pid)
    if key in _HOLDINGS_CACHE:
        return _HOLDINGS_CACHE[key]
    res = (_sb().table("holdings").select("*")
            .eq("user_id", uid).eq("portfolio_id", pid).execute())
    rows = res.data or []
    _HOLDINGS_CACHE[key] = rows
    return rows


def _sync_module_globals() -> None:
    """Refresh ASSETS / ISIN_BY_ASSET / TICKER_BY_ASSET from current portfolio.

    An asset is "active" (and thus listed in ASSETS, shown across every tab)
    only while it has at least one BUY/SELL transaction. Orphan holdings — an
    asset whose last transaction was deleted, or a register_asset that wasn't
    followed by a transaction — are kept as metadata but EXCLUDED from ASSETS,
    so a deleted asset disappears everywhere. The metadata maps still cover all
    holdings so a just-registered asset can resolve its ticker for the price
    backfill before its transaction is committed.
    """
    try:
        rows = _read_holdings_rows()
    except Exception:
        return
    try:
        tx_assets = {t["asset"] for t in _all_transactions()
                     if t.get("type") in ("BUY", "SELL")}
    except Exception:
        tx_assets = {r["asset"] for r in rows}   # fallback: show all
    ASSETS.clear()
    ASSETS.extend(r["asset"] for r in rows if r["asset"] in tx_assets)
    ISIN_BY_ASSET.clear()
    ISIN_BY_ASSET.update({r["asset"]: (r.get("isin") or "") for r in rows})
    TICKER_BY_ASSET.clear()
    TICKER_BY_ASSET.update({r["asset"]: (r.get("ticker") or "") for r in rows})
    # isin → ticker, layered over the static seed (mirrors data_sqlite)
    for r in rows:
        isin = r.get("isin")
        ticker = r.get("ticker")
        if isin and ticker:
            YF_TICKER_BY_ISIN[isin] = ticker


def register_asset(asset: str, isin: str, ticker: str,
                   fund: str = "—", fees: float = 0.0,
                   currency: str = "EUR") -> None:
    uid = _user_id()
    pid = current_portfolio()["id"]
    currency = (currency or "EUR").strip().upper() or "EUR"
    _sb().table("holdings").upsert({
        "user_id": uid, "portfolio_id": pid,
        "asset": asset, "isin": isin or None, "ticker": ticker or None,
        "fund": fund or "—", "fees": float(fees or 0),
        "currency": currency,
    }, on_conflict="user_id,portfolio_id,asset").execute()
    _HOLDINGS_CACHE.pop((uid, pid), None)
    _sync_module_globals()


# ----------------------------------------------------------------------
# Reads — static / price history / transactions
# ----------------------------------------------------------------------

def ensure_seeded() -> None:
    """No-op on cloud — new users start vierge."""
    _sync_module_globals()


def load_static() -> PortfolioStatic:
    """Build the static portfolio view (holdings + shares + cash)."""
    _sync_module_globals()
    rows = _read_holdings_rows()
    shares = current_shares()
    isins   = {r["asset"]: (r.get("isin") or "") for r in rows}
    funds   = {r["asset"]: (r.get("fund") or "—") for r in rows}
    fees    = {r["asset"]: float(r.get("fees") or 0) for r in rows}
    currencies = {r["asset"]: (r.get("currency") or "EUR").upper() for r in rows}
    return PortfolioStatic(
        shares=shares, isins=isins, funds=funds, fees=fees, currencies=currencies,
    )


def _first_tx_date_by_asset() -> dict[str, dt.date]:
    """Earliest BUY/SELL date per asset = when it entered THIS portfolio."""
    out: dict[str, dt.date] = {}
    for t in _all_transactions():
        if t.get("type") not in ("BUY", "SELL"):
            continue
        a = t["asset"]
        if a not in out or t["date"] < out[a]:
            out[a] = t["date"]
    return out


def load_price_history(full: bool = False) -> pd.DataFrame:
    """Wide DataFrame: date + one column per REGISTERED asset.

    Every asset in the current portfolio's holdings gets a column even when it
    has no price rows yet (filled with NaN). This is essential on the cloud
    backend: adding a transaction registers the asset but does NOT backfill
    prices, so without this guarantee the UI's per-asset indexing (allocation
    chart, the 3 price-history tables) would KeyError on a just-added asset and
    crash the whole page.

    Each asset is also clipped to its HOLDING period: its price is N/A before
    its first transaction, even if market prices exist earlier (a refetch from
    the portfolio's global inception can over-fetch them). So an asset's line
    and table rows start at its own acquisition date, not the portfolio's.
    """
    _sync_module_globals()
    uid = _user_id()
    pid = current_portfolio()["id"]
    rows = _select_all(lambda: _sb().table("prices").select("trade_date,asset,price")
             .eq("user_id", uid).eq("portfolio_id", pid)
             .order("trade_date").order("asset"))   # (date,asset) unique → safe paging
    if not rows:
        return pd.DataFrame(columns=["date", *ASSETS])
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["trade_date"])
    df = df.pivot(index="date", columns="asset", values="price").reset_index()
    df.columns.name = None
    for a in ASSETS:                      # NaN column for any unpriced asset
        if a not in df.columns:
            df[a] = float("nan")
    df = df.sort_values("date").reset_index(drop=True)
    # Forward-fill each asset's price across dates it didn't trade on (a foreign
    # market holiday, or a plain data gap): a partial-price day would otherwise
    # leave a NaN that every downstream calc treats as "missing" and drops from
    # that day's NAV — a huge one-day dip in the unit value, the allocation
    # evolution, and every performance metric. Carrying the last known close
    # keeps ALL portfolio maths (VL, NAV, allocation, attribution, risk, tables,
    # snapshot) coherent on non-trading days. Fill runs BEFORE the holding-period
    # clip so it never bleeds a price in before the asset was actually acquired.
    present = [a for a in ASSETS if a in df.columns]
    if present:
        df[present] = df[present].ffill()
    # Clip each asset to its holding period (NaN before its first transaction).
    first_tx = _first_tx_date_by_asset()
    dser = df["date"].dt.date
    for a in ASSETS:
        fd = first_tx.get(a)
        if fd is not None and a in df.columns:
            df.loc[dser < fd, a] = float("nan")
    return df


def load_position_history(full: bool = False) -> pd.DataFrame:
    """Mirror of load_price_history (kept for V15 API compatibility)."""
    return load_price_history(full=full)


def _buys_by_asset() -> dict[str, list[tuple[dt.date, float]]]:
    """All BUY (date, exact price paid) per asset, chronological."""
    out: dict[str, list[tuple[dt.date, float]]] = {}
    for t in _all_transactions():
        if t.get("type") == "BUY" and t.get("price"):
            out.setdefault(t["asset"], []).append((t["date"], float(t["price"])))
    for a in out:
        out[a].sort()
    return out


def first_buy_by_asset() -> dict[str, tuple[dt.date, float]]:
    """(date, exact price) of each asset's FIRST purchase — used as the start
    point of the displayed price series (the augmented history)."""
    return {a: lst[0] for a, lst in _buys_by_asset().items() if lst}


def avg_cost_by_asset() -> dict[str, tuple[dt.date, float]]:
    """(first-buy date, WEIGHTED-AVERAGE buy price) per asset.

    avg price = Σ(price×shares) / Σ(shares) over BUY transactions = the mean
    price paid per share acquired (the cost basis). This is the basis for every
    'Total Return' in the dashboard: perf = current / avg_cost − 1. The date is
    the first buy (used for the FX rate at the cost-basis anchor)."""
    agg: dict[str, dict] = {}
    for t in _all_transactions():
        if t.get("type") == "BUY" and t.get("price") and t.get("shares"):
            d = agg.setdefault(t["asset"], {"amt": 0.0, "sh": 0.0, "first": t["date"]})
            d["amt"] += float(t["price"]) * float(t["shares"])
            d["sh"] += float(t["shares"])
            if t["date"] < d["first"]:
                d["first"] = t["date"]
    return {a: (d["first"], d["amt"] / d["sh"]) for a, d in agg.items() if d["sh"] > 0}


def sell_pnl_rows() -> list[dict]:
    """One enriched row per SELL transaction: realized P&L vs the weighted-average
    cost of the BUYs made on/before the sale date. Handles partial sells (uses the
    shares actually sold). Amounts in the transaction's native currency; the % is
    currency-agnostic. Sorted most-recent first."""
    txs = _all_transactions()
    out: list[dict] = []
    for t in txs:
        if t.get("type") != "SELL":
            continue
        asset = t["asset"]
        sale_date = t["date"]
        sell_price = float(t.get("price") or 0.0)
        shares_sold = float(t.get("shares") or 0.0)
        amt = sh = 0.0
        for b in txs:
            if (b.get("type") == "BUY" and b["asset"] == asset
                    and b["date"] <= sale_date and b.get("price") and b.get("shares")):
                amt += float(b["price"]) * float(b["shares"])
                sh += float(b["shares"])
        avg_cost = (amt / sh) if sh > 0 else None
        pnl = ((sell_price - avg_cost) * shares_sold) if avg_cost is not None else None
        ret = ((sell_price / avg_cost - 1.0) if (avg_cost and avg_cost > 0) else None)
        out.append({
            "id": t.get("id"), "date": sale_date, "asset": asset,
            "shares": shares_sold, "sell_price": sell_price, "avg_cost": avg_cost,
            "currency": (t.get("currency") or "EUR").upper(),
            "pnl": pnl, "return_pct": ret,
        })
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


def augmented_price_history(price_history: pd.DataFrame | None = None) -> pd.DataFrame:
    """Close-price history with a synthetic PURCHASE row per BUY and SALE row per SELL.

    For each buy/sell (asset, date, price) a row is added at that date carrying the
    EXACT price traded for that asset (other assets keep their close as-of that
    date), sorted to appear just BEFORE that day's close. Result columns:
    date, is_buy (bool), is_sell (bool), <asset>… So each asset's series shows
    [prix d'achat, clôtures…, prix de vente] and every re-buy / vente is visible.

    Used only for DISPLAY (the 3 history tables + the price/allocation charts).
    NAV/VL calculations keep using the pure-close load_price_history().
    """
    ph = load_price_history() if price_history is None else price_history.copy()
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
        if a not in cols:
            continue
        for d, p in lst:
            buy_by_date.setdefault(d, {})[a] = p   # same-day re-buy: last wins

    sell_by_date: dict[dt.date, dict[str, float]] = {}
    for t in _all_transactions():
        if (t.get("type") == "SELL" and t.get("price")
                and t["asset"] in cols):
            sell_by_date.setdefault(t["date"], {})[t["asset"]] = float(t["price"])

    def close_vals_asof(d: dt.date) -> dict:
        prior = ph[ph["date"].dt.date <= d]
        src = prior.iloc[-1] if not prior.empty else None
        return {c: (src[c] if src is not None else float("nan")) for c in cols}

    events = []   # (timestamp, kind, {col: val})   kind: ""=close, "buy", "sell"
    for _, r in ph.iterrows():
        events.append((r["date"], "", {c: r[c] for c in cols}))
    for d, amap in buy_by_date.items():
        vals = close_vals_asof(d); vals.update(amap)    # bought assets at buy price
        events.append((pd.Timestamp(d), "buy", vals))
    for d, amap in sell_by_date.items():
        vals = close_vals_asof(d); vals.update(amap)    # sold assets at sell price
        events.append((pd.Timestamp(d), "sell", vals))

    # date asc; on the same date the buy/sell rows come before the close
    events.sort(key=lambda e: (e[0], 0 if e[1] else 1))
    rows = [{"date": ts, "is_buy": kind == "buy", "is_sell": kind == "sell", **vals}
            for ts, kind, vals in events]
    return pd.DataFrame(rows)[["date", "is_buy", "is_sell", *cols]]


def load_transactions() -> pd.DataFrame:
    uid = _user_id()
    pid = current_portfolio()["id"]
    rows = _select_all(lambda: _sb().table("transactions").select(
            "id,trade_date,asset,isin,txn_type,price,shares,amount_eur,currency")
            .eq("user_id", uid).eq("portfolio_id", pid)
            .order("trade_date", desc=True).order("id", desc=True))  # id unique → safe paging
    if not rows:
        return pd.DataFrame(columns=[
            "Id", "Date", "Asset", "ISIN", "Type",
            "Price", "Shares", "Total", "Currency",
        ])
    df = pd.DataFrame(rows).rename(columns={
        "id": "Id", "trade_date": "Date", "asset": "Asset", "isin": "ISIN",
        "txn_type": "Type", "price": "Price", "shares": "Shares",
        "amount_eur": "Total", "currency": "Currency",
    })
    df["Date"] = pd.to_datetime(df["Date"])
    df["Currency"] = df["Currency"].fillna("EUR").str.upper()
    return df


def _all_transactions() -> list[dict]:
    """Internal: raw transaction dicts ordered by date for the active portfolio."""
    uid = _user_id()
    pid = current_portfolio()["id"]
    key = (uid, pid)
    if key in _TX_CACHE:
        return _TX_CACHE[key]
    tx_rows = _select_all(lambda: _sb().table("transactions").select(
            "id,trade_date,asset,isin,txn_type,price,shares,amount_eur,currency")
            .eq("user_id", uid).eq("portfolio_id", pid)
            .order("trade_date").order("id"))       # id unique → safe paging
    rows = []
    for r in tx_rows:
        rows.append({
            "id": r["id"],
            "date": dt.date.fromisoformat(r["trade_date"]),
            "asset": r["asset"],
            "isin": r.get("isin") or "",
            "type": (r.get("txn_type") or "BUY").upper(),
            "price": float(r["price"]) if r.get("price") is not None else None,
            "shares": float(r["shares"]) if r.get("shares") is not None else 0.0,
            "amount": float(r["amount_eur"]),
            "currency": (r.get("currency") or "EUR").upper(),
        })
    _TX_CACHE[key] = rows
    return rows


def shares_held_as_of(when: dt.date | None = None) -> dict[str, float]:
    when = when or dt.date.today()
    held: dict[str, float] = {}
    for t in _all_transactions():
        if t["date"] > when:
            continue
        if t["type"] in ("BUY",):
            held[t["asset"]] = held.get(t["asset"], 0) + t["shares"]
        elif t["type"] in ("SELL",):
            held[t["asset"]] = held.get(t["asset"], 0) - t["shares"]
    return {a: h for a, h in held.items() if abs(h) > 1e-9}


def current_shares() -> dict[str, float]:
    return shares_held_as_of(dt.date.today())


# ----------------------------------------------------------------------
# Inception + meta
# ----------------------------------------------------------------------

def _meta_get(key: str) -> str | None:
    uid = _user_id()
    pid = current_portfolio()["id"]
    res = (_sb().table("meta").select("value")
             .eq("user_id", uid).eq("portfolio_id", pid).eq("key", key)
             .limit(1).execute())
    return res.data[0]["value"] if res.data else None


def _meta_set(key: str, value: str) -> None:
    uid = _user_id()
    pid = current_portfolio()["id"]
    _sb().table("meta").upsert({
        "user_id": uid, "portfolio_id": pid, "key": key, "value": value,
    }, on_conflict="user_id,portfolio_id,key").execute()


def get_inception_date() -> dt.date:
    """Start of the portfolio history / metrics.

    Never earlier than the oldest EXISTING transaction — so after deleting the
    first transaction(s), the history start moves forward to the new oldest one
    instead of clinging to a now-meaningless stored date. A manually-set
    inception is still honoured when it's LATER (start metrics partway in).
    """
    default = default_inception_date()
    v = _meta_get("inception_date")
    if v:
        try:
            return max(dt.date.fromisoformat(v), default)
        except Exception:
            pass
    return default


def set_inception_date(d: dt.date) -> None:
    _meta_set("inception_date", d.isoformat())


_MANUAL_GEO_PREFIX = "manual_geo::"


def set_manual_geo(asset: str, geo: dict[str, float] | None) -> None:
    """Persist (or clear) a user-entered geographic breakdown for `asset`.

    Stored in the `meta` key-value table (per user+portfolio) so it SURVIVES a
    Cloud reboot — unlike etf_compositions.json, which is ephemeral on Streamlit
    Cloud's filesystem. Read back by pro._load_compositions and layered over the
    automatic geography."""
    import json as _json
    key = _MANUAL_GEO_PREFIX + asset
    if geo:
        _meta_set(key, _json.dumps(geo))
        return
    uid = _user_id()
    pid = current_portfolio()["id"]
    _sb().table("meta").delete().eq("user_id", uid).eq(
        "portfolio_id", pid).eq("key", key).execute()


def get_all_manual_geo() -> dict[str, dict]:
    """All user-entered geo overrides for the current portfolio: {asset: {label: pct}}."""
    import json as _json
    uid = _user_id()
    pid = current_portfolio()["id"]
    # `meta` holds only a handful of keys per portfolio → fetch all and filter by
    # prefix in Python (avoids the ambiguous PostgREST LIKE-wildcard syntax).
    res = (_sb().table("meta").select("key,value")
             .eq("user_id", uid).eq("portfolio_id", pid).execute())
    out: dict[str, dict] = {}
    for r in (res.data or []):
        key = r.get("key") or ""
        if not key.startswith(_MANUAL_GEO_PREFIX):
            continue
        asset = key[len(_MANUAL_GEO_PREFIX):]
        try:
            g = _json.loads(r["value"]) if r.get("value") else None
        except Exception:
            g = None
        if g:
            out[asset] = g
    return out


def default_inception_date() -> dt.date:
    txs = _all_transactions()
    if txs:
        return min(t["date"] for t in txs)
    return dt.date.today()


def last_save_at() -> str | None:
    return _meta_get("last_save_at")


# ----------------------------------------------------------------------
# Writes — prices, transactions, cash, bulk
# ----------------------------------------------------------------------

def save_today(prices: dict[str, float],
               shares: dict[str, float] | None = None,
               when: dt.date | None = None) -> dict:
    uid = _user_id()
    pid = current_portfolio()["id"]
    when = when or dt.date.today()
    rows = []
    for asset, price in prices.items():
        if price is None:
            continue
        rows.append({
            "user_id": uid, "portfolio_id": pid,
            "trade_date": when.isoformat(),
            "asset": asset, "price": float(price),
        })
    if rows:
        _sb().table("prices").upsert(
            rows, on_conflict="user_id,portfolio_id,trade_date,asset"
        ).execute()
    _meta_set("last_save_at", dt.datetime.now(PARIS_TZ).isoformat(timespec="seconds"))
    sh = shares or shares_held_as_of(when)
    nav = sum(prices.get(a, 0) * sh.get(a, 0) for a in ASSETS)
    return {"date": when.isoformat(), "total_value": round(nav, 2), "rows": len(rows)}


def backfill_prices(rows: list[tuple[dt.date, str, float]]) -> dict:
    if not rows:
        return {"inserted": 0, "skipped": 0, "dates": []}
    uid = _user_id()
    pid = current_portfolio()["id"]
    pg_rows = [
        {"user_id": uid, "portfolio_id": pid,
         "trade_date": d.isoformat(), "asset": a, "price": float(p)}
        for (d, a, p) in rows if p is not None
    ]
    if pg_rows:
        _sb().table("prices").upsert(
            pg_rows, on_conflict="user_id,portfolio_id,trade_date,asset"
        ).execute()
    return {"inserted": len(pg_rows), "skipped": 0,
            "dates": sorted({d for d, _, _ in rows})}


def latest_price_date() -> dt.date | None:
    uid = _user_id()
    pid = current_portfolio()["id"]
    res = (_sb().table("prices").select("trade_date")
             .eq("user_id", uid).eq("portfolio_id", pid)
             .order("trade_date", desc=True).limit(1).execute())
    if res.data:
        return dt.date.fromisoformat(res.data[0]["trade_date"])
    return None


def earliest_price_date() -> dt.date | None:
    """Oldest stored price date for the current portfolio (any asset), or None.

    Used by heal_price_gaps to spot a HEAD gap — stored prices that begin well
    after the oldest transaction (e.g. a 2017 buy whose prices only start 2021
    because the original long-range fetch was truncated)."""
    uid = _user_id()
    pid = current_portfolio()["id"]
    res = (_sb().table("prices").select("trade_date")
             .eq("user_id", uid).eq("portfolio_id", pid)
             .order("trade_date").limit(1).execute())
    if res.data:
        return dt.date.fromisoformat(res.data[0]["trade_date"][:10])
    return None


def _backfill_asset_since(asset: str, since: dt.date) -> int:
    """Ensure a CONTINUOUS daily adjusted-close series for `asset` from `since`
    through today, fetching only the missing head/tail.

    Earlier this bailed out whenever the asset already had ANY price at/before
    `since` (`if earliest <= since: return 0`). That left a hole when an asset
    with OLD prices (e.g. data that stops in 2020) was re-bought years later:
    the gap up to today never got filled, so the dashboard forward-filled it with
    a stale price and NAV/VL/charts jumped the day the new buy's price finally
    "caught up". Now we look at BOTH ends of the stored series and fetch whatever
    is missing up to today. backfill_prices upserts, so re-fetching is idempotent.
    Best-effort: returns 0 on any failure without raising (never blocks a save).
    """
    ticker = (TICKER_BY_ASSET.get(asset) or "").strip()
    if not ticker:
        h = next((r for r in _read_holdings_rows() if r["asset"] == asset), None)
        ticker = ((h or {}).get("ticker") or "").strip()
    if not ticker:
        return 0
    uid = _user_id()
    pid = current_portfolio()["id"]
    base = (_sb().table("prices").select("trade_date")
              .eq("user_id", uid).eq("portfolio_id", pid).eq("asset", asset))
    e = base.order("trade_date").limit(1).execute()
    l = base.order("trade_date", desc=True).limit(1).execute()
    today = dt.date.today()
    earliest = dt.date.fromisoformat(e.data[0]["trade_date"][:10]) if e.data else None
    latest = dt.date.fromisoformat(l.data[0]["trade_date"][:10]) if l.data else None
    # Earliest date we must (re)fetch from to guarantee continuity through today.
    if earliest is None:
        start = since                              # no prices at all → full range
    else:
        start = since if earliest > since else None    # missing head before 1st close
        if latest is None or latest < today:           # stale tail / gap up to today
            start = min(start, latest) if start else latest
    if start is None:
        return 0                                   # already continuous through today
    try:
        import prices as _prices
        series = _prices.fetch_ticker_history(ticker, start, today)
    except Exception:
        return 0
    rows = [(d, asset, p) for d, p in series if p is not None]
    if rows:
        backfill_prices(rows)
    return len(rows)


def heal_price_gaps() -> int:
    """Self-healing safety net: ensure EVERY traded asset has a continuous price
    series from its first transaction through today, filling any hole.

    Backs up the per-transaction backfill for portfolios that already drifted
    into a gap (asset re-bought after its stored history went stale, or a stretch
    of days never saved) — a gap gets forward-filled with a stale price and
    silently corrupts NAV / VL / the price & allocation charts. Cheap when
    already continuous (two date lookups per asset, no fetch). Best-effort:
    never raises. Returns the number of price rows added. Called once per
    (session, portfolio) from the app's load path.
    """
    try:
        first_tx = _first_tx_date_by_asset()
    except Exception:
        return 0
    if not first_tx:
        return 0
    # Cheap guard: if the most recent stored price is current (≤4 days old —
    # covers weekends/holidays) AND there's no head gap, the portfolio is being
    # kept up to date, so skip the per-asset gap scan (2 DB calls/asset) for a
    # fast load. A real tail gap leaves `latest` old, which still triggers the
    # full heal below. A HEAD gap (stored prices start well after the oldest
    # transaction) is NOT visible in the tail, so we check it explicitly here —
    # otherwise an old buy whose long-range fetch was truncated never backfills.
    try:
        latest = latest_price_date()
        tail_fresh = latest is not None and (dt.date.today() - latest).days <= 4
        oldest_tx = min(first_tx.values())
        earliest = earliest_price_date()
        # >7 days of slack absorbs a normal weekend/holiday between the first
        # trade and its first available close; more than that is a real head gap.
        head_gap = earliest is None or (earliest - oldest_tx).days > 7
        if tail_fresh and not head_gap:
            return 0
    except Exception:
        pass
    added = 0
    for asset, fd in first_tx.items():
        try:
            added += _backfill_asset_since(asset, fd)
        except Exception:
            pass
    return added


def add_transaction(when: dt.date, asset: str, txn_type: str,
                    price: float, shares: float, isin: str | None = None,
                    currency: str | None = None) -> dict:
    uid = _user_id()
    pid = current_portfolio()["id"]
    txn_type = txn_type.upper()
    amount = float(price) * float(shares) if (price and shares) else 0.0
    if not currency:
        # Default to the asset's registered currency
        h = next((r for r in _read_holdings_rows() if r["asset"] == asset), None)
        currency = (h and h.get("currency")) or current_portfolio_currency()
    _sb().table("transactions").insert({
        "user_id": uid, "portfolio_id": pid,
        "trade_date": when.isoformat(),
        "asset": asset, "isin": isin,
        "txn_type": txn_type,
        "price": float(price), "shares": float(shares),
        "amount_eur": amount,
        "currency": currency.upper(),
    }).execute()
    _TX_CACHE.pop((uid, pid), None)
    # Backfill the asset's price history from the trade date so its line and
    # Pro views render continuously (cloud add doesn't otherwise store prices).
    backfilled = 0
    if txn_type in ("BUY", "SELL"):
        try:
            backfilled = _backfill_asset_since(asset, when)
        except Exception:
            backfilled = 0
    new_holding = shares_held_as_of(dt.date.today()).get(asset, 0)
    return {"date": when.isoformat(), "asset": asset, "type": txn_type,
            "price": price, "shares": shares, "amount": amount,
            "new_holding": new_holding, "backfilled_days": backfilled}


def add_cash_movement(when: dt.date, kind: str, amount: float) -> dict:
    uid = _user_id()
    pid = current_portfolio()["id"]
    kind = kind.upper()
    if kind not in ("DEPOSIT", "WITHDRAW"):
        raise ValueError(f"Unsupported cash kind: {kind}")
    pf_ccy = current_portfolio_currency()
    _sb().table("transactions").insert({
        "user_id": uid, "portfolio_id": pid,
        "trade_date": when.isoformat(),
        "asset": "Cash",
        "txn_type": kind, "amount_eur": float(amount),
        "currency": pf_ccy,
    }).execute()
    _TX_CACHE.pop((uid, pid), None)
    cash_after = cash_balance_as_of(dt.date.today())
    return {"date": when.isoformat(), "kind": kind, "amount": amount,
            "cash_after": cash_after}


def delete_transaction(tx_id: int) -> dict:
    uid = _user_id()
    pid = current_portfolio()["id"]
    res = (_sb().table("transactions").delete()
             .eq("user_id", uid).eq("portfolio_id", pid).eq("id", int(tx_id))
             .execute())
    deleted = 1 if res.data else 0
    asset = res.data[0].get("asset") if res.data else None
    _TX_CACHE.pop((uid, pid), None)
    # Asset lifecycle: an asset exists only while it has transactions. If this
    # was its last one, remove the asset entirely (holding + prices) so it
    # vanishes from ASSETS and therefore every tab — no orphan left behind.
    asset_removed = False
    if asset and asset != "Cash":
        rem = (_sb().table("transactions").select("id")
                 .eq("user_id", uid).eq("portfolio_id", pid)
                 .eq("asset", asset).limit(1).execute())
        if not rem.data:
            for table in ("prices", "holdings"):
                try:
                    (_sb().table(table).delete()
                       .eq("user_id", uid).eq("portfolio_id", pid)
                       .eq("asset", asset).execute())
                except Exception:
                    pass
            asset_removed = True
    _invalidate_caches()
    return {"deleted": deleted, "id": int(tx_id), "asset": asset,
            "asset_removed": asset_removed,
            "row": res.data[0] if res.data else None}


def add_transactions_bulk(rows: list[dict]) -> dict:
    inserted = 0
    errors = []
    for i, r in enumerate(rows):
        try:
            t = (r.get("type") or "").strip().upper()
            d = r.get("date")
            if isinstance(d, str):
                d = dt.date.fromisoformat(d)
            if t in ("DEPOSIT", "WITHDRAW"):
                add_cash_movement(d, t, float(r.get("amount") or 0))
            elif t in ("BUY", "SELL"):
                add_transaction(
                    d, r["asset"], t,
                    price=float(r.get("price") or 0),
                    shares=float(r.get("shares") or 0),
                    isin=r.get("isin"),
                    currency=r.get("currency"),
                )
            else:
                raise ValueError(f"type inconnu : {t!r}")
            inserted += 1
        except Exception as exc:
            errors.append({"row": i, "reason": str(exc), "data": r})
    _invalidate_caches()
    return {"inserted": inserted, "skipped": len(rows) - inserted, "errors": errors}


# ----------------------------------------------------------------------
# Cash walk + nav_series (reuse sqlite implementations operating on
# our local _all_transactions / shares_held_as_of / ASSETS)
# ----------------------------------------------------------------------

# The pure-Python derived functions in data_sqlite reference module globals
# like ASSETS, _all_transactions(), current_portfolio_currency() — those
# are NAME LOOKUPS at call time inside the sqlite module, so they bind to
# sqlite's own globals. To make them work with our cloud state, we
# re-implement them here (shorter than refactoring sqlite to accept context).

def _cash_walk(upto: dt.date | None = None) -> dict:
    """Mirrors data_sqlite._cash_walk exactly so callers see the same
    keys: cash, deposits, cash_by_date, deposit_by_date."""
    from collections import defaultdict
    pf_ccy = current_portfolio_currency()
    cash = 0.0
    deposits = 0.0
    cash_by_date: dict[dt.date, float] = {}
    deposit_by_date: dict[dt.date, float] = defaultdict(float)
    for t in _all_transactions():
        if upto is not None and t["date"] > upto:
            break
        amt = t["amount"]
        typ = t["type"]
        if typ in ("BUY", "SELL"):
            tx_ccy = (t.get("currency") or "EUR").upper()
            if tx_ccy != pf_ccy:
                try:
                    amt = amt * fx_rate(tx_ccy, pf_ccy, t["date"])
                except Exception:
                    pass
        if typ == "BUY":
            if cash >= amt:
                cash -= amt
            else:
                deposit = amt - cash
                deposits += deposit
                deposit_by_date[t["date"]] += deposit
                cash = 0.0
        elif typ == "SELL":
            cash += amt
        elif typ == "DEPOSIT":
            cash += amt
            deposits += amt
            deposit_by_date[t["date"]] += amt
        elif typ == "WITHDRAW":
            cash -= amt
            deposits -= amt
            deposit_by_date[t["date"]] -= amt
        cash_by_date[t["date"]] = cash
    return {"cash": cash, "deposits": deposits,
            "cash_by_date": cash_by_date,
            "deposit_by_date": dict(deposit_by_date)}


def cash_balance_as_of(when: dt.date | None = None) -> float:
    return _cash_walk(when or dt.date.today())["cash"]


def external_deposits_as_of(when: dt.date | None = None) -> float:
    return _cash_walk(when or dt.date.today())["deposits"]


def nav_series(price_history: pd.DataFrame | None = None,
               inception: dt.date | None = None) -> pd.DataFrame:
    if price_history is None:
        price_history = load_price_history(full=(inception is None))
    inception = inception or get_inception_date()
    if price_history.empty:
        return pd.DataFrame(columns=["date", "etf", "cash", "nav"])
    ph = price_history[price_history["date"].dt.date >= inception].sort_values("date").reset_index(drop=True)
    if ph.empty:
        return pd.DataFrame(columns=["date", "etf", "cash", "nav"])
    assets = [a for a in ASSETS if a in ph.columns]
    # Forward-fill each asset's price across dates it didn't trade on (foreign
    # market holiday, data gap): otherwise a missing (NaN) price was silently
    # skipped and the NAV dropped for that single day — a huge downward VL spike
    # that recovered the next day. Carry the last known close instead. (Fill
    # runs only from each asset's first real close onward; before acquisition
    # shares_held_as_of is 0, so a still-NaN early cell contributes nothing.)
    if assets:
        ph[assets] = ph[assets].ffill()
    walk = _cash_walk()
    cash_by_date = walk["cash_by_date"]
    pf_ccy = current_portfolio_currency()
    static = load_static()
    asset_ccy = {a: (static.currencies.get(a) or "EUR").upper() for a in assets}

    def cash_at(d):
        applicable = [cd for cd in cash_by_date if cd <= d]
        return cash_by_date[max(applicable)] if applicable else 0.0

    rows = []
    for i in range(len(ph)):
        d = ph.at[i, "date"].date()
        held = shares_held_as_of(d)
        etf = 0.0
        for a in assets:
            v = ph.at[i, a]
            if not pd.notna(v):
                continue
            rate = 1.0 if asset_ccy[a] == pf_ccy else fx_rate(asset_ccy[a], pf_ccy, d)
            etf += float(v) * held.get(a, 0) * rate
        cash = cash_at(d)
        rows.append({"date": ph.at[i, "date"], "etf": etf, "cash": cash, "nav": etf + cash})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------
# FX — cloud-native cache backed by the Postgres `fx_rates` table.
#
# Mirrors data_sqlite's fx_rate / prefetch_fx_window logic 1:1, but the
# durable cache lives in Postgres (scoped to user_id + portfolio_id) instead
# of a local sqlite file — so on Streamlit Cloud's ephemeral filesystem the
# FX history survives cold starts. The Yahoo fetch fallback is the *exact*
# data_sqlite._fx_fetch_yahoo (pure, no DB I/O) re-used verbatim.
#
# _FX_CACHE (declared above) is keyed (user_id, portfolio_id, pair, date_iso);
# _FX_LOADED tracks which (user_id, portfolio_id) pairs have had their rows
# pulled from Postgres, so we hit the DB at most once per portfolio per
# session (the cloud analogue of sqlite's `if _FX_CACHE: return` guard).
# ----------------------------------------------------------------------

# Pure Yahoo fetch — no DB I/O, no module-global reads — re-used as-is so the
# fetch / inverse-pair / reciprocate behavior stays identical to V15.
_fx_fetch_yahoo = _ds._fx_fetch_yahoo


def _fx_load_cache_from_db(uid: str, pid: str) -> None:
    """One-shot load of this portfolio's fx_rates rows into _FX_CACHE.

    Guarded by _FX_LOADED so we query Postgres at most once per
    (user, portfolio) per process — the cloud analogue of sqlite's lazy
    one-shot `_fx_load_cache_from_db`."""
    if (uid, pid) in _FX_LOADED:
        return
    fx_rows = _select_all(lambda: _sb().table("fx_rates").select("trade_date,pair,rate")
             .eq("user_id", uid).eq("portfolio_id", pid)
             .order("trade_date").order("pair"))   # (date,pair) unique → safe paging
    for r in fx_rows:
        _FX_CACHE[(uid, pid, r["pair"], str(r["trade_date"])[:10])] = float(r["rate"])
    _FX_LOADED.add((uid, pid))


def _fx_persist(uid: str, pid: str, pair: str,
                rows: list[tuple[dt.date, float]]) -> None:
    """Upsert fetched FX rows into the Postgres fx_rates table + warm cache."""
    if not rows:
        return
    pg_rows = [
        {"user_id": uid, "portfolio_id": pid, "trade_date": d.isoformat(),
         "pair": pair, "rate": float(rate)}
        for d, rate in rows
    ]
    _sb().table("fx_rates").upsert(
        pg_rows, on_conflict="user_id,portfolio_id,trade_date,pair"
    ).execute()
    for d, rate in rows:
        _FX_CACHE[(uid, pid, pair, d.isoformat())] = float(rate)


def fx_rate(from_ccy: str, to_ccy: str, when: dt.date | None = None) -> float:
    """1 unit of `from_ccy` = X units of `to_ccy` on `when` (or today).

    Cloud-native copy of data_sqlite.fx_rate: forward-fills from the last
    known earlier date (weekends / holidays), cold-fetches a ~400d window from
    Yahoo on a cache miss and persists it to the Postgres fx_rates table.
    Returns 1.0 when from == to or as a safe last-ditch fallback."""
    from_ccy = (from_ccy or "EUR").upper()
    to_ccy = (to_ccy or "EUR").upper()
    if from_ccy == to_ccy:
        return 1.0
    when = when or dt.date.today()
    when_iso = when.isoformat()
    pair = f"{from_ccy}{to_ccy}"
    uid = _user_id()
    pid = current_portfolio()["id"]
    _fx_load_cache_from_db(uid, pid)

    # Exact date hit
    hit = _FX_CACHE.get((uid, pid, pair, when_iso))
    if hit is not None:
        return hit

    # Most recent earlier date (forward-fill)
    candidates = [k for k in _FX_CACHE
                  if k[0] == uid and k[1] == pid and k[2] == pair and k[3] <= when_iso]
    if candidates:
        return _FX_CACHE[max(candidates)]

    # Cold cache: fetch a window ending today, persist, then look up
    start = min(when, dt.date.today() - dt.timedelta(days=400))
    rows = _fx_fetch_yahoo(from_ccy, to_ccy, start, dt.date.today())
    if rows:
        _fx_persist(uid, pid, pair, rows)
        candidates = [k for k in _FX_CACHE
                      if k[0] == uid and k[1] == pid and k[2] == pair and k[3] <= when_iso]
        if candidates:
            return _FX_CACHE[max(candidates)]
        # `when` older than the earliest fetched → use the earliest
        all_dates = sorted(k[3] for k in _FX_CACHE
                           if k[0] == uid and k[1] == pid and k[2] == pair)
        if all_dates:
            return _FX_CACHE[(uid, pid, pair, all_dates[0])]
    # Last-ditch safe fallback
    return 1.0


def prefetch_fx_window(from_ccy: str, to_ccy: str,
                       start: dt.date, end: dt.date) -> None:
    """Warm the FX cache for a date window. Cheap no-op if already covered.
    Cloud-native copy of data_sqlite.prefetch_fx_window — fetches only the
    uncovered head / tail of the window and persists it to Postgres."""
    if from_ccy == to_ccy:
        return
    from_ccy = from_ccy.upper()
    to_ccy = to_ccy.upper()
    pair = f"{from_ccy}{to_ccy}"
    uid = _user_id()
    pid = current_portfolio()["id"]
    _fx_load_cache_from_db(uid, pid)
    dates_for_pair = [dt.date.fromisoformat(k[3]) for k in _FX_CACHE
                      if k[0] == uid and k[1] == pid and k[2] == pair]
    earliest = min(dates_for_pair, default=None)
    latest = max(dates_for_pair, default=None)
    need_fetch_start = start if (earliest is None or earliest > start) else None
    need_fetch_end = end if (latest is None or latest < end) else None
    if need_fetch_start or need_fetch_end:
        rows = _fx_fetch_yahoo(from_ccy, to_ccy,
                               need_fetch_start or start,
                               need_fetch_end or end)
        if rows:
            _fx_persist(uid, pid, pair, rows)


def price_history_in_portfolio_currency(price_history: pd.DataFrame) -> pd.DataFrame:
    """Cloud-native copy of data_sqlite.price_history_in_portfolio_currency.

    Returns a copy of price_history with each asset column converted from its
    NATIVE currency to the current portfolio currency, using fx_rate at each
    row's date. EUR-on-EUR assets are no-ops. Re-implemented here (not
    re-exported) so current_portfolio_currency()/load_static()/ASSETS bind to
    THIS module's cloud helpers rather than data_sqlite's.
    """
    if price_history is None or price_history.empty:
        return price_history.copy() if price_history is not None else pd.DataFrame()
    out = price_history.copy()
    pf_ccy = current_portfolio_currency()
    static = load_static()
    asset_ccy = {a: (static.currencies.get(a) or "EUR").upper() for a in ASSETS}
    # Pre-warm FX cache for each non-pf currency over the window
    d0 = out["date"].min().date()
    d1 = out["date"].max().date()
    for ccy in set(asset_ccy.values()):
        if ccy != pf_ccy:
            try:
                prefetch_fx_window(ccy, pf_ccy, d0, d1)
            except Exception:
                pass
    # Drop duplicate columns first: the augmented price history (buy/sell rows)
    # can leave a duplicated asset column, which makes out[a] a DataFrame and
    # crashes the .astype(float) below. Keep the first occurrence.
    if out.columns.duplicated().any():
        out = out.loc[:, ~out.columns.duplicated()]
    for a in ASSETS:
        if a not in out.columns:
            continue
        ccy = asset_ccy[a]
        if ccy == pf_ccy:
            continue
        rates = out["date"].apply(
            lambda ts: fx_rate(ccy, pf_ccy, ts.date() if hasattr(ts, "date") else ts)
        )
        # Robust numeric coercion (mirrors app._num_col): the augmented frame may
        # carry object dtype, stray strings or non-scalar cells (a Series left in
        # a cell), all of which crash a plain .astype(float). Non-numeric → NaN
        # so a single odd asset can't take down the whole page. Index is kept so
        # the element-wise multiply with `rates` stays aligned.
        col = out[a]
        if isinstance(col, pd.DataFrame):          # duplicate column → take first
            col = col.iloc[:, 0]
        col = col.map(lambda x: x if pd.api.types.is_scalar(x) else float("nan"))
        col = pd.to_numeric(col, errors="coerce")
        out[a] = col * pd.to_numeric(rates, errors="coerce")
    return out


# ----------------------------------------------------------------------
# Unitized VL series — cloud-native copy of data_sqlite.compute_vl_series.
# References module-level names (ASSETS, nav_series, _cash_walk,
# shares_held_as_of, external_deposits_as_of, get_inception_date,
# load_price_history) which bind to THIS module's cloud helpers.
# ----------------------------------------------------------------------

def compute_vl_series(price_history: pd.DataFrame | None = None,
                      inception: dt.date | None = None) -> pd.DataFrame:
    """Day-by-day NAV, fund units, VL (base 100 at inception) and net invested.

    Units are created when you BUY (cash in) and destroyed when you SELL (cash
    out), at the VL prevailing just before the flow — so VL reflects ONLY market
    performance, not deposits/withdrawals. With no post-inception flows this
    reduces exactly to NAV / NAV_inception * 100.
    Returns columns: date, nav, units, vl, net_invested.
    """
    if price_history is None:
        price_history = load_price_history()
    inception = inception or get_inception_date()
    if price_history.empty:
        return pd.DataFrame(columns=["date", "nav", "units", "vl", "net_invested"])

    nv = nav_series(price_history, inception)
    if nv.empty:
        return pd.DataFrame(columns=["date", "nav", "units", "vl", "net_invested"])

    dates = [d.date() for d in nv["date"]]
    assets = [a for a in ASSETS if a in price_history.columns]
    ph = price_history[price_history["date"].dt.date >= inception].sort_values("date").reset_index(drop=True)
    # Forward-fill missing prices (foreign-market holidays / gaps) so the
    # pre-flow NAV used for unitization doesn't dip on a partial-price day —
    # same fix as nav_series (prevents the big downward VL spikes).
    if assets:
        ph[assets] = ph[assets].ffill()

    walk = _cash_walk()
    deposit_by_date = walk["deposit_by_date"]
    # External deposits AFTER inception drive unit creation. Inception-day
    # deposits are the initial capital (folded into units_0). Map each deposit
    # to the first trading date >= its date.
    cf_on: dict[dt.date, float] = defaultdict(float)
    for d_dep, amt in deposit_by_date.items():
        if d_dep <= inception:
            continue
        td = next((x for x in dates if x >= d_dep), dates[-1] if dates else None)
        if td is not None:
            cf_on[td] += amt

    def etf_value_on(row_idx: int, held: dict[str, float]) -> float:
        total = 0.0
        for a in assets:
            v = ph.at[row_idx, a]
            if pd.notna(v):
                total += float(v) * held.get(a, 0)
        return total

    out_rows = []
    units = None
    for i, d in enumerate(dates):
        nav = float(nv.at[i, "nav"])
        if i == 0:
            units = (nav / 100.0) if nav > 0 else 1.0
        else:
            cf = cf_on.get(d, 0.0)
            if cf and units:
                # VL just before the deposit: today's prices on yesterday's
                # shares + yesterday's cash (NAV excluding the new money).
                held_prev = shares_held_as_of(dates[i - 1])
                cash_prev = float(nv.at[i - 1, "cash"])
                nav_pre = etf_value_on(i, held_prev) + cash_prev
                vl_pre = (nav_pre / units) if units else 100.0
                if vl_pre > 0:
                    units += cf / vl_pre
        vl = (nav / units) if units else 100.0
        net_inv = external_deposits_as_of(d)
        out_rows.append({"date": nv.at[i, "date"], "nav": nav, "units": units,
                         "vl": vl, "net_invested": net_inv})

    return pd.DataFrame(out_rows)


# ----------------------------------------------------------------------
# Derived KPI snapshot — cloud-native copy of data_sqlite.compute_snapshot.
# Same name-binding rationale as compute_vl_series above.
# ----------------------------------------------------------------------

def compute_snapshot(static: PortfolioStatic,
                     prices: dict[str, float],
                     price_history: pd.DataFrame) -> dict:
    """Build the KPI snapshot consumed by the UI.

    Uses TIME-VARYING shares and a unitized VL. `prices` is the current
    per-asset price (live or last close); daily P&L is measured on the shares
    held going into the latest day, so a same-day trade doesn't masquerade as
    performance.
    """
    inception = get_inception_date()
    shares_now = static.shares  # current (today) shares
    cash_now = cash_balance_as_of(dt.date.today())

    # V11: FX conversion to the active portfolio's base currency
    pf_ccy = current_portfolio_currency()
    today = dt.date.today()

    def _to_pf(amount: float, native_ccy: str, when: dt.date | None = None) -> float:
        native_ccy = (native_ccy or "EUR").upper()
        if native_ccy == pf_ccy:
            return amount
        return amount * fx_rate(native_ccy, pf_ccy, when or today)

    positions: dict[str, dict] = {}
    etf_value = 0.0
    for asset in ASSETS:
        price = prices.get(asset)
        sh = shares_now.get(asset, 0)
        if price is None:
            continue
        native_ccy = (static.currencies.get(asset) or "EUR").upper()
        rate = 1.0 if native_ccy == pf_ccy else fx_rate(native_ccy, pf_ccy, today)
        native_value = price * sh
        value = native_value * rate
        positions[asset] = {
            "price": price, "shares": sh, "value": value,
            "native_price": price, "native_value": native_value,
            "currency": native_ccy, "fx_rate": rate,
        }
        etf_value += value
    total_value = etf_value + cash_now

    # Cash (PEA) appears as its own allocation line when non-zero. It has no
    # price/shares/returns; it's pure liquidity sitting in the plan.
    if cash_now > 1e-9:
        positions["Cash"] = {
            "price": None, "shares": 0, "value": cash_now, "is_cash": True,
            "daily_return": 0.0, "daily_pnl": 0.0,
            "total_return": 0.0, "total_return_eur": 0.0,
            "inception_price": None, "target_allocation": 0.0, "drift": 0.0,
        }

    # "Yesterday" = second-to-last price row; daily P&L on shares held into it.
    prev_row = None
    prev_date = None
    if not price_history.empty:
        hist_sorted = price_history.sort_values("date").reset_index(drop=True)
        if len(hist_sorted) >= 2:
            prev_row = hist_sorted.iloc[-2]
            prev_date = prev_row["date"].date()
    shares_prev = shares_held_as_of(prev_date) if prev_date else shares_now

    daily_pnl_eur = 0.0
    prev_nav = 0.0
    for asset in ASSETS:
        cur = prices.get(asset)
        prev = None
        if prev_row is not None and asset in prev_row.index and pd.notna(prev_row[asset]):
            prev = float(prev_row[asset])
        sh_prev = shares_prev.get(asset, 0)
        p = positions.setdefault(asset, {"price": None, "shares": shares_now.get(asset, 0), "value": 0.0})
        native_ccy = (static.currencies.get(asset) or "EUR").upper()
        if cur is not None and prev:
            # daily_return = NATIVE price ratio (currency cancels) — measures
            # pure stock performance independent of FX moves.
            p["daily_return"] = (cur / prev) - 1.0
            # FX rates: today vs previous trade date
            r_today = 1.0 if native_ccy == pf_ccy else fx_rate(native_ccy, pf_ccy, today)
            r_prev = (1.0 if native_ccy == pf_ccy
                      else fx_rate(native_ccy, pf_ccy, prev_date or today))
            # daily_return_pf = portfolio-currency ratio (stock + FX combined).
            # Equal to daily_return when native_ccy == pf_ccy.
            p["daily_return_pf"] = ((cur * r_today) / (prev * r_prev)) - 1.0
            # Daily P&L IN PORTFOLIO CURRENCY: today's price × FX_today minus
            # yesterday's price × FX_yesterday, on shares held into today.
            p["daily_pnl"] = (cur * r_today - prev * r_prev) * sh_prev
            daily_pnl_eur += p["daily_pnl"]
            prev_nav += prev * r_prev * sh_prev
        else:
            p["daily_return"] = 0.0
            p["daily_return_pf"] = 0.0
            p["daily_pnl"] = 0.0

    daily_pnl_pct = (daily_pnl_eur / prev_nav) if prev_nav else 0.0
    for p in positions.values():
        p["allocation"] = (p["value"] / total_value) if total_value else 0.0

    # --- Unitized VL series (time-weighted performance) ---
    vl_series = compute_vl_series(price_history, inception)
    if not vl_series.empty:
        last = vl_series.iloc[-1]
        vl = float(last["vl"])
        net_invested = float(last["net_invested"])
        # If live `prices` differ from the last stored row, re-value NAV with
        # live prices but keep the units from the series.
        units = float(last["units"]) if last["units"] else None
        if units and total_value > 0:
            vl = total_value / units
        nav_for_vl = total_value if total_value > 0 else float(last["nav"])
    else:
        vl = 100.0
        net_invested = sum((t["amount"] if t["type"] == "BUY" else -t["amount"])
                           for t in _all_transactions())
        nav_for_vl = total_value

    # Cash P&L = current market value − net cash invested (realized + unrealized)
    cash_pnl_eur = total_value - net_invested
    # Total return = the REAL money gain on invested capital (money-weighted):
    # (NAV − net invested) / net invested. The time-weighted performance lives in
    # the VL / unit value (snapshot["vl"], base 100 at the first real adjusted
    # close). Keeping % and € (cash_pnl_eur) on the same money basis so they match.
    total_return_pct = (cash_pnl_eur / net_invested) if net_invested > 0 else 0.0

    # --- Per-asset total return + target (inception) allocation ---
    inception_nav = 0.0
    if not price_history.empty:
        # Anchor everything at the EFFECTIVE inception (Settings date, else the
        # first transaction) — not the raw first price row — so inception NAV,
        # target allocations and per-asset "since inception" all start there.
        ph_sorted = price_history[price_history["date"].dt.date >= inception] \
            .sort_values("date").reset_index(drop=True)
        if ph_sorted.empty:
            ph_sorted = price_history.sort_values("date").reset_index(drop=True)
        first = ph_sorted.iloc[0]
        first_date = first["date"].date()
        shares_first = shares_held_as_of(first_date)

        def _first_seen(asset):
            """(price, date) of the asset's FIRST available close. An asset added
            mid-history has no price on the global inception date, so measuring
            its total return from there gave 0 %; measure from its own start."""
            if asset not in ph_sorted.columns:
                return None, None
            col = ph_sorted[asset]
            valid = col[col.notna()]
            if valid.empty:
                return None, None
            i0 = valid.index[0]
            return float(col.iloc[i0]), ph_sorted.at[i0, "date"].date()

        # Inception NAV in PORTFOLIO currency (portfolio composition at inception)
        inception_nav = 0.0
        for a in ASSETS:
            if a not in first.index or not pd.notna(first[a]):
                continue
            a_ccy = (static.currencies.get(a) or "EUR").upper()
            r_inc = 1.0 if a_ccy == pf_ccy else fx_rate(a_ccy, pf_ccy, first_date)
            inception_nav += float(first[a]) * shares_first.get(a, 0) * r_inc

        cost_map = avg_cost_by_asset()   # (first-buy date, weighted-avg cost)
        for asset in ASSETS:
            cur = prices.get(asset)
            if asset in cost_map:
                inc_date, inc_price = cost_map[asset]   # weighted-average cost basis
            else:
                inc_price, inc_date = _first_seen(asset)   # fallback: first close
            inc_date = inc_date or first_date
            sh = shares_now.get(asset, 0)
            a_ccy = (static.currencies.get(asset) or "EUR").upper()
            r_today = 1.0 if a_ccy == pf_ccy else fx_rate(a_ccy, pf_ccy, today)
            r_inc = 1.0 if a_ccy == pf_ccy else fx_rate(a_ccy, pf_ccy, inc_date)
            p = positions.setdefault(asset, {"price": None, "shares": sh, "value": 0.0})
            if cur is not None and inc_price:
                # Total return = portfolio-currency price change (incl. FX move)
                p["total_return"] = (cur * r_today) / (inc_price * r_inc) - 1.0
                p["total_return_eur"] = (cur * r_today - inc_price * r_inc) * sh
                p["inception_price"] = inc_price
            else:
                p["total_return"] = 0.0
                p["total_return_eur"] = 0.0
                p["inception_price"] = None
            if inc_price is not None and inception_nav > 0:
                p["target_allocation"] = (inc_price * r_inc * shares_first.get(asset, 0)) / inception_nav
            else:
                p["target_allocation"] = 0.0
            p["drift"] = p.get("allocation", 0.0) - p["target_allocation"]

    # Drop fully-exited assets (0 shares and 0 value) from the snapshot view
    positions = {a: p for a, p in positions.items()
                 if not (abs(p.get("shares", 0)) < 1e-9 and abs(p.get("value", 0)) < 1e-9)}

    # Guarantee every position carries the full key set the UI reads — an asset
    # held but missing a live price is first created in the total-return loop
    # (after the allocation pass), so without this it would lack "allocation"
    # (and friends) and crash app.py with a KeyError.
    _pos_defaults = {
        "price": None, "shares": 0, "value": 0.0, "allocation": 0.0,
        "daily_return": 0.0, "daily_return_pf": 0.0, "daily_pnl": 0.0,
        "total_return": 0.0, "total_return_eur": 0.0, "inception_price": None,
        "target_allocation": 0.0, "drift": 0.0, "currency": pf_ccy,
    }
    for p in positions.values():
        for k, v in _pos_defaults.items():
            p.setdefault(k, v)

    return {
        "positions": positions,
        "total_value": total_value,
        "daily_pnl_eur": daily_pnl_eur,
        "daily_pnl_pct": daily_pnl_pct,
        "prev_total": prev_nav,
        "inception_nav": inception_nav,
        "inception_date": inception,
        "total_return_eur": cash_pnl_eur,     # now cash-based (NAV − net invested)
        "total_return_pct": total_return_pct, # time-weighted (VL-based)
        "net_invested": net_invested,
        "cash_pnl_eur": cash_pnl_eur,
        "cash_balance": cash_now,
        "etf_value": etf_value,
        "vl": vl,
    }


# ----------------------------------------------------------------------
# Maintenance helpers (Settings buttons) — minimal cloud implementations
# ----------------------------------------------------------------------

def refetch_recent_closes(days: int = 7) -> dict:
    import prices as _prices
    today = dt.date.today()
    start = today - dt.timedelta(days=days)
    try:
        hist = _prices.fetch_history(start, today)
    except Exception:
        return {"overwritten": 0, "dates": [], "error": "yahoo_fetch_failed"}
    rows = []
    touched = set()
    for asset, series in hist.items():
        if asset not in ASSETS:
            continue
        for d, p in series:
            if p is None:
                continue
            rows.append((d, asset, float(p)))
            touched.add(d)
    summary = backfill_prices(rows)
    return {"overwritten": summary["inserted"], "dates": sorted(touched)}


def refetch_all_prices_from_inception() -> dict:
    """Refetch every asset's prices from its acquisition date through today.

    Fetches **per ticker via the chunked path** (`fetch_ticker_history`, ≤2-year
    windows, capped at 10 years) instead of one multi-year bulk request: on
    Cloud's shared IP a single long request is truncated to ~2017→2023, and the
    old code then **wiped the table** before writing that truncated result —
    deleting every recent price and opening a permanent 2023→today gap.

    Now the wipe is **conditional**: we only clear-and-replace when the fresh data
    actually reaches ~today (within 6 days). If Yahoo still comes back short, we
    upsert what we got (idempotent) without deleting the recent prices already
    stored, so a throttled fetch can never destroy good data."""
    uid = _user_id()
    pid = current_portfolio()["id"]
    import prices as _prices
    inc = get_inception_date()
    first_tx = _first_tx_date_by_asset()   # don't store prices before acquisition
    today = dt.date.today()
    rows = []
    reached_today = False
    for asset in ASSETS:
        ticker = (TICKER_BY_ASSET.get(asset) or "").strip()
        if not ticker:
            h = next((r for r in _read_holdings_rows() if r["asset"] == asset), None)
            ticker = ((h or {}).get("ticker") or "").strip()
        if not ticker:
            continue
        fd = first_tx.get(asset, inc)
        start = fd if fd >= inc else inc       # never store before inception
        try:
            series = _prices.fetch_ticker_history(ticker, start, today)
        except Exception:
            series = []
        for d, p in series:
            if p is not None and d >= start:
                rows.append((d, asset, float(p)))
                if (today - d).days <= 6:
                    reached_today = True
    if not rows:
        return {"refetched": 0, "error": "no_data_from_yahoo"}
    if reached_today:
        # Fresh data is complete through ~today → safe to clear-and-replace.
        _sb().table("prices").delete().eq("user_id", uid).eq("portfolio_id", pid).execute()
    backfill_prices(rows)
    return {"refetched": len(rows), "wiped": reached_today}


def backfill_all_assets_to_inception() -> dict:
    """Same as refetch_all_prices_from_inception for cloud (no granular fix needed)."""
    return refetch_all_prices_from_inception()


def price_on_date(asset: str, when: dt.date) -> tuple[float | None, str]:
    if asset not in ASSETS:
        return None, "not_found"
    uid = _user_id()
    pid = current_portfolio()["id"]
    res = (_sb().table("prices").select("price")
             .eq("user_id", uid).eq("portfolio_id", pid)
             .eq("trade_date", when.isoformat())
             .eq("asset", asset).limit(1).execute())
    if res.data:
        return float(res.data[0]["price"]), "db_cache"
    # Try Yahoo single-day fetch
    try:
        import prices as _prices
        hist = _prices.fetch_history(when, when)
        rows = hist.get(asset) or []
        if rows:
            d, p = rows[0]
            if p is not None:
                backfill_prices([(d, asset, float(p))])
                return float(p), "yahoo_fetch"
    except Exception:
        pass
    # Forward-fill from nearest earlier
    res = (_sb().table("prices").select("price")
             .eq("user_id", uid).eq("portfolio_id", pid)
             .lte("trade_date", when.isoformat())
             .eq("asset", asset).order("trade_date", desc=True).limit(1).execute())
    if res.data:
        return float(res.data[0]["price"]), "fallback_prev_close"
    return None, "not_found"
