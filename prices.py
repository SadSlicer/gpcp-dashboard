"""Yahoo Finance price fetching for the portfolio's ETFs.

The asset set is DYNAMIC (V5): it comes from data.ASSETS / data.ISIN_BY_ASSET /
data.YF_TICKER_BY_ISIN, which are kept in sync with the holdings table and may
include user-added ETFs. We import the module (not the names) so we always read
the current registry, and resolve each asset's Yahoo ticker defensively.

We always carry the **trade date** alongside the price so the rest of the
system can detect weekends / public holidays: on those days Yahoo simply
returns the previous close, and we must not save that as a fresh row.
"""

from __future__ import annotations

import datetime as dt

import yfinance as yf

import data


def _ticker_for(asset: str) -> str | None:
    """Resolve an asset's Yahoo ticker, or None if unknown (skip it).

    V10: prefer the direct asset→ticker registry so assets without ISIN still
    resolve (any stock by name + ticker).
    """
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
    """Fetch each ETF's most recent close. Returns {asset: (trade_date, price)}.

    `trade_date` is the actual date Yahoo last had a quote for — on a Saturday
    this will typically be Friday's date for European ETFs.
    """
    out: dict[str, tuple[dt.date, float]] = {}

    pairs = _assets_with_tickers()
    # Bulk download first (one HTTP call), per-ticker fallback after.
    tickers = [tk for _, tk in pairs]
    try:
        bulk = yf.download(
            tickers=" ".join(tickers),
            period="7d",
            interval="1d",
            progress=False,
            auto_adjust=True,
            group_by="ticker",
            threads=True,
        )
    except Exception:
        bulk = None

    for asset, tk in pairs:
        try:
            if bulk is not None and (tk, "Close") in bulk.columns:
                series = bulk[(tk, "Close")].dropna()
                if not series.empty:
                    out[asset] = (series.index[-1].date(), float(series.iloc[-1]))
                    continue
            elif bulk is not None and "Close" in bulk.columns:
                series = bulk["Close"].dropna()
                if not series.empty:
                    out[asset] = (series.index[-1].date(), float(series.iloc[-1]))
                    continue
        except Exception:
            pass

        try:
            hist = yf.Ticker(tk).history(period="7d", auto_adjust=True)
            series = hist["Close"].dropna()
            if not series.empty:
                out[asset] = (series.index[-1].date(), float(series.iloc[-1]))
        except Exception:
            continue

    return out


def fetch_latest_prices() -> dict[str, float]:
    """Backward-compatible: just the prices, no dates."""
    return {a: p for a, (_, p) in fetch_latest_with_date().items()}


def fetch_history(start: dt.date, end: dt.date) -> dict[str, list[tuple[dt.date, float]]]:
    """Fetch daily closes for all 7 ETFs between `start` and `end` (both inclusive).

    Returns {asset: [(date, close), ...]}. The trading calendar is **implicit
    in Yahoo's response** — only days the ETF actually traded come back, so
    weekends and Euronext holidays are naturally excluded without us needing
    a hand-maintained calendar.
    """
    pairs = _assets_with_tickers()
    out: dict[str, list[tuple[dt.date, float]]] = {a: [] for a, _ in pairs}
    if end < start or not pairs:
        return out

    tickers = [tk for _, tk in pairs]

    # yfinance's `end` is *exclusive*; add a day so we include `end` itself.
    end_excl = end + dt.timedelta(days=1)

    try:
        bulk = yf.download(
            tickers=" ".join(tickers),
            start=start.isoformat(),
            end=end_excl.isoformat(),
            interval="1d",
            progress=False,
            auto_adjust=True,
            group_by="ticker",
            threads=True,
        )
    except Exception:
        bulk = None

    for asset, tk in pairs:
        series = None
        try:
            if bulk is not None and (tk, "Close") in bulk.columns:
                series = bulk[(tk, "Close")].dropna()
            elif bulk is not None and "Close" in bulk.columns and len(pairs) == 1:
                series = bulk["Close"].dropna()
        except Exception:
            series = None

        # Per-ticker fallback
        if series is None or series.empty:
            try:
                hist = yf.Ticker(tk).history(
                    start=start.isoformat(),
                    end=end_excl.isoformat(),
                    interval="1d",
                    auto_adjust=True,
                )
                series = hist["Close"].dropna() if not hist.empty else None
            except Exception:
                series = None

        if series is None or series.empty:
            continue

        for idx, val in series.items():
            d = idx.date() if hasattr(idx, "date") else idx
            out[asset].append((d, float(val)))

    return out


def fetch_adjusted_close_on(ticker: str, when: dt.date) -> float | None:
    """Adjusted close for a single `ticker` on `when` (or the most recent
    trading day before it).

    Used to auto-fill the price of a brand-new asset that isn't registered
    yet, straight from the Yahoo ticker the user typed. `auto_adjust=True` →
    split/dividend-adjusted, consistent with fetch_history. Returns None when
    there's no data (invalid or non-public ticker) so the caller can fall back
    to manual entry.
    """
    ticker = (ticker or "").strip()
    if not ticker:
        return None
    start = when - dt.timedelta(days=10)       # cushion for weekends/holidays
    end_excl = when + dt.timedelta(days=1)      # yfinance `end` is exclusive
    try:
        hist = yf.Ticker(ticker).history(
            start=start.isoformat(), end=end_excl.isoformat(),
            interval="1d", auto_adjust=True,
        )
    except Exception:
        return None
    if hist is None or hist.empty or "Close" not in hist.columns:
        return None
    series = hist["Close"].dropna()
    if series.empty:
        return None
    # Last close on/before `when` (forward-fill across non-trading days)
    best = None
    for idx, val in series.items():
        d = idx.date() if hasattr(idx, "date") else idx
        if d <= when:
            best = float(val)
    return best if best is not None else float(series.iloc[0])


def fetch_ticker_history(ticker: str, start: dt.date, end: dt.date) -> list[tuple[dt.date, float]]:
    """Daily adjusted closes for a single `ticker` from `start` to `end` (incl.).

    Used to backfill a newly-added asset's price history straight from its Yahoo
    ticker, so its line/charts/Pro views have a continuous series from the
    acquisition date. Returns [] on any failure (invalid ticker, network).
    """
    ticker = (ticker or "").strip()
    if not ticker or end < start:
        return []
    end_excl = end + dt.timedelta(days=1)         # yfinance `end` is exclusive
    try:
        hist = yf.Ticker(ticker).history(
            start=start.isoformat(), end=end_excl.isoformat(),
            interval="1d", auto_adjust=True,
        )
    except Exception:
        return []
    if hist is None or hist.empty or "Close" not in hist.columns:
        return []
    out: list[tuple[dt.date, float]] = []
    for idx, val in hist["Close"].dropna().items():
        d = idx.date() if hasattr(idx, "date") else idx
        out.append((d, float(val)))
    return out


def most_common_trade_date(quotes: dict[str, tuple[dt.date, float]]) -> dt.date | None:
    """Return the trade date most quotes agree on — used to decide whether a
    save would actually advance the historical log."""
    if not quotes:
        return None
    counts: dict[dt.date, int] = {}
    for d, _ in quotes.values():
        counts[d] = counts.get(d, 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])[0]
