#!/usr/bin/env python3
"""Monthly job: refresh ETF sector + geo compositions from official factsheets.

Runs on the 15th of each month via launchd (com.gpcp.dashboard.compositions).
By the 15th the previous month-end factsheet (MR_*_YYYY-MM-DD.pdf) is published
on fundinfo, so we always pull recent data.

Thin wrapper around compositions_scraper.refresh_all() with file logging.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import compositions_scraper  # noqa: E402

LOG_PATH = ROOT / "compositions_update.log"


def _logger() -> logging.Logger:
    log = logging.getLogger("gpcp.compo")
    log.setLevel(logging.INFO)
    if log.handlers:
        return log
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    fh = RotatingFileHandler(LOG_PATH, maxBytes=512_000, backupCount=3)
    fh.setFormatter(fmt)
    log.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(sh)
    return log


def main() -> int:
    log = _logger()
    log.info("=== monthly_compositions_update start ===")
    try:
        summary = compositions_scraper.refresh_all(log)
    except Exception:
        log.exception("Composition refresh crashed")
        return 1
    log.info("Updated: %s", summary["updated"])
    if summary["untouched"]:
        log.warning("Untouched (kept old data): %s",
                    [f"{a} ({r})" for a, r in summary["untouched"]])
    log.info("=== monthly_compositions_update done ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
