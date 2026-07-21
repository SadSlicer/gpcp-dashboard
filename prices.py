"""Yahoo Finance price fetching for the portfolio's ETFs.

The asset set is DYNAMIC (V5): it comes from data.ASSETS / data.ISIN_BY_ASSET /
data.YF_TICKER_BY_ISIN, which are kept in sync with the holdings table and may
include user-added ETFs. We import the module (not the names) so we always read
the current registry, and resolve each asset's Yahoo ticker defensively.

── NO yfinance / curl_cffi ───────────────────────────────────────────────────
yfinance's native HTTP backend (curl_cffi) SEGFAULTS on Streamlit Cloud's Linux
container — uncatchable, it kills the whole app. So this module talks to Yahoo's
public JSON API **directly with `requests`** (a pure-Python HTTP client that can
never segfault): the v8 `chart` endpoint for prices and v10 `quoteSummary` for
sector / metadata, after seeding a cookie + crumb (which is what unblocks the
datacenter IP). Nothing here imports yfinance, so the app can't crash on a fetch.
"""

from __future__ import annotations

import datetime as dt
import threading

import requests

import data

MAX_HISTORY = dt.timedelta(days=1825)   # 5 years — hard cap on look-back depth

# Master switch (emergency mute). Fetching is pure-`requests` and crash-safe, so
# leave True; when False the public fetch functions return empty and the app
# renders purely from the prices already stored in Postgres.
YAHOO_ENABLED = True

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
_HTTP_TIMEOUT = 25

# THREAD-LOCAL session. A `requests.Session` is NOT thread-safe, and Streamlit runs
# every user session in its own thread — a single shared session used concurrently
# corrupts the urllib3/SSL state and SEGFAULTS the process (it worked on the first
# login, then crashed on a second concurrent one). So each thread gets its OWN
# session, reused within that thread, never shared across threads.
_tls = threading.local()


def _thread_session(force: bool = False) -> tuple[requests.Session, str]:
    """(session, crumb) for THIS thread, primed with Yahoo's cookie + crumb (what
    unblocks a datacenter IP). Built once per thread; force=True rebuilds it."""
    s = getattr(_tls, "session", None)
    if s is not None and not force:
        return s, getattr(_tls, "crumb", "")
    s = requests.Session()
    s.headers.update({"User-Agent": _UA, "Accept": "*/*",
                      "Accept-Language": "en-US,en;q=0.9"})
    try:
        s.get("https://fc.yahoo.com", timeout=_HTTP_TIMEOUT)
    except Exception:
        pass
    crumb = ""
    try:
        r = s.get("https://query2.finance.yahoo.com/v1/test/getcrumb",
                  timeout=_HTTP_TIMEOUT)
        crumb = (r.text or "").strip() if r.status_code == 200 else ""
    except Exception:
        crumb = ""
    _tls.session = s
    _tls.crumb = crumb
    return s, crumb


def _yahoo_chart(ticker: str, start: dt.date, end: dt.date) -> list[tuple[dt.date, float]]:
    """Daily adjusted closes for one `ticker` via Yahoo's v8 chart API. Returns
    [(date, close), …] (chronological), or [] on any failure. One retry with a
    fresh (thread-local) session covers an expired cookie/crumb."""
    ticker = (ticker or "").strip()
    if not ticker or end < start:
        return []
    p1 = int(dt.datetime(start.year, start.month, start.day,
                         tzinfo=dt.timezone.utc).timestamp())
    p2 = int(dt.datetime(end.year, end.month, end.day,
                         tzinfo=dt.timezone.utc).timestamp()) + 86400
    for attempt in range(2):
        s, _ = _thread_session(force=(attempt > 0))
        try:
            r = s.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
                      params={"period1": p1, "period2": p2, "interval": "1d",
                              "events": "div,splits"}, timeout=_HTTP_TIMEOUT)
            if r.status_code != 200:
                continue
            res = ((r.json().get("chart") or {}).get("result") or [None])[0]
            if not res:
                continue
            ts = res.get("timestamp") or []
            ind = res.get("indicators") or {}
            adj = (ind.get("adjclose") or [{}])[0].get("adjclose")
            close = (ind.get("quote") or [{}])[0].get("close")
            vals = adj if adj else close
            out = []
            for t, v in zip(ts, vals or []):
                if v is not None:
                    d = dt.datetime.fromtimestamp(t, dt.timezone.utc).date()
                    out.append((d, float(v)))
            return out
        except Exception:
            continue
    return []


def _yahoo_quote_summary(ticker: str, modules: str) -> dict:
    """v10 quoteSummary result dict for `ticker` (or {} on failure)."""
    ticker = (ticker or "").strip()
    if not ticker:
        return {}
    for attempt in range(2):
        s, crumb = _thread_session(force=(attempt > 0))
        try:
            r = s.get(f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}",
                      params={"modules": modules, "crumb": crumb},
                      timeout=_HTTP_TIMEOUT)
            if r.status_code != 200:
                continue
            res = ((r.json().get("quoteSummary") or {}).get("result") or [None])[0]
            return res or {}
        except Exception:
            continue
    return {}


def _ticker_for(asset: str) -> str | None:
    """Resolve an asset's Yahoo ticker, or None if unknown (skip it)."""
    tk = data.TICKER_BY_ASSET.get(asset)
    if tk:
        return tk
    isin = data.ISIN_BY_ASSET.get(asset)
    if not isin:
        return None
    return data.YF_TICKER_BY_ISIN.get(isin)


def _assets_with_tickers() -> list[tuple[str, str]]:
    """[(asset, ticker), …] for every registered asset that has a ticker."""
    data.ensure_seeded()
    out = []
    for a in data.ASSETS:
        tk = _ticker_for(a)
        if tk:
            out.append((a, tk))
    return out


def fetch_latest_with_date() -> dict[str, tuple[dt.date, float]]:
    """Fetch each ETF's most recent close. Returns {asset: (trade_date, price)}."""
    if not YAHOO_ENABLED:
        return {}
    today = dt.date.today()
    start = today - dt.timedelta(days=10)
    out: dict[str, tuple[dt.date, float]] = {}
    for asset, tk in _assets_with_tickers():
        series = _yahoo_chart(tk, start, today)
        if series:
            out[asset] = series[-1]
    return out


def fetch_latest_prices() -> dict[str, float]:
    """Backward-compatible: just the prices, no dates."""
    return {a: p for a, (_, p) in fetch_latest_with_date().items()}


def fetch_history(start: dt.date, end: dt.date) -> dict[str, list[tuple[dt.date, float]]]:
    """Fetch daily closes for all ETFs between `start` and `end` (both inclusive).
    Returns {asset: [(date, close), ...]}."""
    pairs = _assets_with_tickers()
    out: dict[str, list[tuple[dt.date, float]]] = {a: [] for a, _ in pairs}
    if not YAHOO_ENABLED or end < start or not pairs:
        return out
    for asset, tk in pairs:
        out[asset] = _yahoo_chart(tk, start, end)
    return out


def fetch_adjusted_close_on(ticker: str, when: dt.date) -> float | None:
    """Adjusted close for `ticker` on `when` (or the most recent trading day
    before it). None when there's no data."""
    if not YAHOO_ENABLED:
        return None
    series = _yahoo_chart((ticker or "").strip(), when - dt.timedelta(days=10), when)
    best = None
    for d, p in series:
        if d <= when:
            best = p
    if best is not None:
        return best
    return series[0][1] if series else None


def fetch_ticker_history(ticker: str, start: dt.date, end: dt.date) -> list[tuple[dt.date, float]]:
    """Daily adjusted closes for one `ticker`, capped at MAX_HISTORY (5 years)."""
    if not YAHOO_ENABLED:
        return []
    ticker = (ticker or "").strip()
    if not ticker or end < start:
        return []
    floor = end - MAX_HISTORY
    if start < floor:
        start = floor
    return _yahoo_chart(ticker, start, end)


def fetch_benchmark_series(ticker: str, start: dt.date, end: dt.date) -> list[tuple[dt.date, float]]:
    """Daily closes for one benchmark ticker → list[(date, price)]."""
    return fetch_ticker_history(ticker, start, end)


# yfinance funds_data.sector_weightings-style keys → the topHoldings JSON keys
# (they're the same slugs), so callers' _YF_SECTOR_MAP keeps working unchanged.
def fetch_funds_sectors(ticker: str) -> dict:
    """{sector_slug: weight(0-1)} for a fund via quoteSummary topHoldings, or {}."""
    if not YAHOO_ENABLED:
        return {}
    res = _yahoo_quote_summary(ticker, "topHoldings")
    rows = (res.get("topHoldings") or {}).get("sectorWeightings") or []
    out: dict[str, float] = {}
    for entry in rows:
        if not isinstance(entry, dict):
            continue
        for k, v in entry.items():
            try:
                out[k] = float(v.get("raw")) if isinstance(v, dict) else float(v)
            except (TypeError, ValueError):
                continue
    return out


def fetch_yahoo_info(ticker: str) -> dict:
    """A small subset of Yahoo `.info` via quoteSummary → dict (may be empty)."""
    if not YAHOO_ENABLED:
        return {}
    res = _yahoo_quote_summary(ticker, "assetProfile,quoteType,price")
    ap = res.get("assetProfile") or {}
    qt = res.get("quoteType") or {}
    pr = res.get("price") or {}

    def _txt(v):
        return v if isinstance(v, str) else (v.get("raw") if isinstance(v, dict) else v)
    return {
        "sector": ap.get("sector") or "",
        "country": ap.get("country") or "",
        "quoteType": (qt.get("quoteType") or "").upper(),
        "longName": qt.get("longName") or pr.get("longName") or "",
        "shortName": qt.get("shortName") or pr.get("shortName") or "",
        "currency": (pr.get("currency") or "").upper(),
        "fundFamily": ap.get("companyOfficers") and "" or "",   # not in this module
        "category": "",
        "isin": "",
    }


def probe_ticker_fetch(ticker: str, start: dt.date, end: dt.date | None = None) -> dict:
    """DIAGNOSTIC ONLY (Settings). Exercises the SAME requests path the app uses
    and reports row count / first / last / seconds / error for a full-range shot,
    a recent 1-year shot, and per ~1-year window."""
    import time
    ticker = (ticker or "").strip()
    end = end or dt.date.today()
    window = dt.timedelta(days=365)

    def _one(a: dt.date, b: dt.date) -> dict:
        t0 = time.time()
        series = _yahoo_chart(ticker, a, b)
        secs = round(time.time() - t0, 1)
        n = len(series)
        return {"n": n, "first": series[0][0].isoformat() if n else None,
                "last": series[-1][0].isoformat() if n else None,
                "secs": secs, "error": None if n else "no data"}

    out: dict = {"ticker": ticker, "range": f"{start} → {end}"}
    out["single_full"] = _one(start, end)
    out["recent_1y"] = _one(max(start, end - window), end)
    windows = []
    ws = start
    while ws <= end:
        we = min(ws + window, end)
        r = _one(ws, we)
        r["window"] = f"{ws} → {we}"
        windows.append(r)
        ws = we + dt.timedelta(days=1)
    out["windows"] = windows
    out["stitched_last"] = max((w["last"] for w in windows if w["last"]), default=None)
    return out


def most_common_trade_date(quotes: dict[str, tuple[dt.date, float]]) -> dt.date | None:
    """Return the trade date most quotes agree on."""
    if not quotes:
        return None
    counts: dict[dt.date, int] = {}
    for d, _ in quotes.values():
        counts[d] = counts.get(d, 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])[0]
