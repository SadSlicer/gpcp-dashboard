#!/usr/bin/env python3
"""Standalone daily-update job. Designed to be run unattended by `launchd`.

Idempotent: safe to run multiple times a day, on weekends, on holidays —
it only writes if Yahoo returned a *new* trade date that's not already
in `portfolio.db`.

Usage:
    .venv/bin/python daily_update.py [--force]

    --force  Save the fetched prices even if their trade date is already
             present (used to overwrite a partial intraday capture).
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Make sure imports resolve regardless of how launchd invokes us
ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import data                    # noqa: E402  (after sys.path)
import prices                  # noqa: E402

LOG_PATH = ROOT / "daily_update.log"


def _setup_logging() -> logging.Logger:
    logger = logging.getLogger("gpcp.daily")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    fh = RotatingFileHandler(LOG_PATH, maxBytes=512_000, backupCount=3)
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


def _backfill_gaps(log: logging.Logger) -> int:
    """If the DB is missing intermediate trading days (Mac off for a while),
    pull Yahoo history for the missing window and bulk-insert. Yahoo's response
    *is* the trading calendar: weekends + Euronext holidays are absent from
    its response, so we only ever insert real trading days.
    """
    latest = data.latest_price_date()
    today = dt.date.today()
    if latest is None:
        log.info("Backfill skipped: DB has no prices yet (cold start).")
        return 0
    # Start one day AFTER the last saved date; end yesterday (today is handled
    # by the live-fetch step that follows).
    start = latest + dt.timedelta(days=1)
    end = today - dt.timedelta(days=1)
    if end < start:
        log.info("Backfill: nothing to do (latest=%s, end=%s).", latest, end)
        return 0

    log.info("Backfill window: %s → %s (looking for missing trading days)", start, end)
    history = prices.fetch_history(start, end)
    rows: list[tuple[dt.date, str, float]] = []
    for asset, series in history.items():
        for d, p in series:
            if start <= d <= end:
                rows.append((d, asset, p))

    if not rows:
        log.info("Backfill: Yahoo returned no rows (no trading days in window).")
        return 0

    # Group by date to count complete vs partial days
    dates_count: dict[dt.date, int] = {}
    for d, _, _ in rows:
        dates_count[d] = dates_count.get(d, 0) + 1
    n_assets = len(data.ASSETS)
    for d in sorted(dates_count):
        marker = "✓" if dates_count[d] == n_assets else "⚠"
        log.info("  %s %s: %d/%d ETFs", marker, d.isoformat(), dates_count[d], n_assets)

    summary = data.backfill_prices(rows)
    log.info("Backfill: inserted %d rows across %d trading day(s) (skipped %d already-present).",
             summary["inserted"], len(summary["dates"]), summary["skipped"])
    return summary["inserted"]


def run(force: bool = False) -> int:
    log = _setup_logging()
    log.info("=== daily_update start (force=%s) ===", force)

    data.ensure_seeded()
    latest_saved = data.latest_price_date()
    log.info("Latest saved trade date in DB: %s", latest_saved)

    # Backfill any missing weekday closes between latest_saved and yesterday,
    # using Yahoo as the implicit trading-day calendar.
    try:
        _backfill_gaps(log)
    except Exception:
        log.exception("Backfill failed (continuing with daily fetch)")

    # V13.1: always overwrite the last ~7 calendar days with the official
    # close from Yahoo's history endpoint. This kills any intraday snapshot
    # that the "Refresh & Save" button may have written during market hours.
    try:
        fix = data.refetch_recent_closes(days=7)
        if fix.get("dates"):
            log.info("Fix-up: overwrote %d rows across %d day(s) with official closes.",
                     fix["overwritten"], len(fix["dates"]))
    except Exception:
        log.exception("Fix-up of recent closes failed (continuing)")

    log.info("Fetching prices from Yahoo Finance…")
    quotes = prices.fetch_latest_with_date()
    if not quotes:
        log.error("Yahoo returned no quotes; aborting.")
        return 2

    log.info("Got %d / %d quotes.", len(quotes), len(data.ASSETS))
    for asset, (d, p) in sorted(quotes.items()):
        log.info("  %-14s %s  %.4f €", asset, d.isoformat(), p)

    trade_date = prices.most_common_trade_date(quotes)
    log.info("Consensus trade date: %s", trade_date)

    if trade_date is None:
        log.error("No consensus trade date; aborting.")
        return 3

    if not force and latest_saved is not None and trade_date <= latest_saved:
        log.info("Nothing to do — %s already saved (weekend/holiday or already-run today).",
                 trade_date.isoformat())
        return 0

    # All quotes must agree on the date — otherwise it's an intraday capture
    # where one ETF lags the others; we still save but log a warning.
    dates = {d for d, _ in quotes.values()}
    if len(dates) > 1:
        log.warning("Quotes span multiple dates %s — saving under %s.",
                    sorted(d.isoformat() for d in dates), trade_date.isoformat())

    price_map = {a: p for a, (_, p) in quotes.items()}
    summary = data.save_today(price_map, when=trade_date)
    log.info("SAVED: date=%s NAV=%.2f € rows=%d",
             summary["date"], summary["total_value"], summary["rows"])
    # NB: ETF sector/geo compositions are refreshed separately, once a month,
    # by monthly_compositions_update.py (scrapes the official factsheets).
    log.info("=== daily_update done ===")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="GPCP daily price update")
    ap.add_argument("--force", action="store_true",
                    help="Save even if the trade date is already present.")
    args = ap.parse_args()
    try:
        return run(force=args.force)
    except Exception as exc:  # pragma: no cover
        _setup_logging().exception("Unhandled error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
