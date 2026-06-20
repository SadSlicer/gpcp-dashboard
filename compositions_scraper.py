"""V4 — Scrape ETF compositions (sector + geo) from official issuer factsheets.

Pipeline per ETF:
  1. Fetch the justETF profile page → grep the latest 'MR' (Monthly Report) PDF URL
     hosted on api.fundinfo.com.
  2. Download the PDF (~400 KB) and extract text with pdfplumber.
  3. Find lines matching `<Label> XX,XX %` on the composition page.
  4. Classify each line as Geo or Sector by checking against known French
     country / sector vocabularies (the two never overlap).
  5. Translate French labels → the English keys used in etf_compositions.json.
  6. Validate (sum 90-110 %, each value 0-100, ≥3 entries per dimension).
  7. Atomic write to etf_compositions.json.

The official PDFs are republished every month-end by Amundi/BNP. Designed to
run on the 15th of each month — by then the previous month's MR is available.

If a PDF can't be found or parsed for a given ETF, the existing entry in the
JSON is left untouched and a warning is logged. The whole pipeline never
overwrites good data with bad.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import logging
import os
import re
import tempfile
import urllib.request
from pathlib import Path

# NOTE: pdfplumber is imported lazily inside parse_factsheet_pdf() — it is only
# needed for ETF factsheet PDF parsing. Keeping it out of module scope means
# `import compositions_scraper` (used by the transaction-save flow for
# lookup_yfinance_info) never fails if pdfplumber is absent.

ROOT = Path(__file__).resolve().parent
JSON_PATH = ROOT / "etf_compositions.json"


# ---------------------------------------------------------------------------
# Vocabulary maps (French ↔ English JSON keys)
# ---------------------------------------------------------------------------

SECTOR_FR_TO_EN: dict[str, str] = {
    # Amundi
    "technologies de l'info.":  "Tech",
    "technologie de l'information": "Tech",  # BNP variant
    "finance":                   "Financials",
    "santé":                     "Healthcare",
    "conso cyclique":            "Consumer Disc.",
    "conso non cyclique":        "Consumer Staples",
    "services de communication": "Communication",
    "industrie":                 "Industrials",
    "énergie":                   "Energy",
    "services publics":          "Utilities",
    "matériaux":                 "Materials",
    "immobilier":                "Real Estate",
    # BNP variants
    "biens de consommation cyclique": "Consumer Disc.",
    "biens de consommation non cyclique": "Consumer Staples",
    "biens de consommation de base": "Consumer Staples",
    "services de télécommunications": "Communication",
    "industriels":               "Industrials",
    "matières premières":        "Materials",
    # BNP Stoxx 600 specific labels
    "consommation de base":      "Consumer Staples",
    "consommation discrétionnaire": "Consumer Disc.",
    "energie":                   "Energy",
    "technologie de l'information": "Tech",
    "autre":                     "Other",
    "autres":                    "Other",
}

COUNTRY_FR_TO_EN: dict[str, str] = {
    "états-unis":      "USA",
    "etats-unis":      "USA",
    "japon":           "Japan",
    "royaume-uni":     "UK",
    "france":          "France",
    "allemagne":       "Germany",
    "suisse":          "Switzerland",
    "pays-bas":        "Netherlands",
    "suède":           "Sweden",
    "espagne":         "Spain",
    "italie":          "Italy",
    "danemark":        "Denmark",
    "irlande":         "Ireland",
    "canada":          "Canada",
    "norvège":         "Norway",
    "finlande":        "Finland",
    "belgique":        "Belgium",
    "autriche":        "Austria",
    "luxembourg":      "Luxembourg",
    "chine":           "China",
    "taïwan":          "Taiwan",
    "taiwan":          "Taiwan",
    "inde":            "India",
    "corée du sud":    "South Korea",
    "corée":           "South Korea",
    "coree":           "South Korea",
    "brésil":          "Brazil",
    "bresil":          "Brazil",
    "afrique du sud":  "South Africa",
    "arabie saoudite": "Saudi Arabia",
    "mexique":         "Mexico",
    "malaysie":        "Malaysia",
    "malaisie":        "Malaysia",
    "thaïlande":       "Thailand",
    "thailande":       "Thailand",
    "indonésie":       "Indonesia",
    "indonesie":       "Indonesia",
    "philippines":     "Philippines",
    "emirats arabes unis": "UAE",
    "émirats arabes unis": "UAE",
    "qatar":           "Qatar",
    "koweït":          "Kuwait",
    "turquie":         "Turkey",
    "pologne":         "Poland",
    "hongrie":         "Hungary",
    "rép. tchèque":    "Czech Republic",
    "grèce":           "Greece",
    "russie":          "Russia",
    "chili":           "Chile",
    "pérou":           "Peru",
    "colombie":        "Colombia",
    "argentine":       "Argentina",
    "autres pays":     "Other",
    "autre pays":      "Other",
    "autres":          "Other",
    "autre":           "Other",
}

# Accept these JSON keys as valid (used for validation cross-check)
VALID_SECTOR_KEYS = set(SECTOR_FR_TO_EN.values())
VALID_COUNTRY_KEYS = set(COUNTRY_FR_TO_EN.values())


# ---------------------------------------------------------------------------
# Discovery + download
# ---------------------------------------------------------------------------

UA = "Mozilla/5.0 (Macintosh; GPCP Dashboard composition scraper)"


def _http_get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def find_monthly_report_url(isin: str) -> str | None:
    """Scrape justETF for this ISIN's most recent Monthly Report PDF URL."""
    page_url = f"https://www.justetf.com/fr/etf-profile.html?isin={isin}"
    try:
        html = _http_get(page_url, timeout=15).decode("utf-8", errors="ignore")
    except Exception:
        return None
    # Look for MR_FR_fr_{ISIN}_*.pdf  (Monthly Report, French version)
    candidates = re.findall(
        rf'https://api\.fundinfo\.com/document/[a-z0-9_]+/MR_[A-Z]{{2}}_fr_{isin}_[A-Z]+_\d{{4}}-\d{{2}}-\d{{2}}\.pdf',
        html,
    )
    if not candidates:
        # Fall back to any MR_*_{ISIN}_* URL
        candidates = re.findall(
            rf'https://api\.fundinfo\.com/document/[a-z0-9_]+/MR_[^"]*{isin}[^"]*\.pdf',
            html,
        )
    if not candidates:
        return None
    # Pick the most recent (URLs end in YYYY-MM-DD.pdf — sortable)
    return sorted(candidates, reverse=True)[0]


# ---------------------------------------------------------------------------
# PDF parsing
# ---------------------------------------------------------------------------

_PAIR_RE = re.compile(r'(.+?)\s+(\d{1,3}[,.]\d{1,2})\s*%')


def _normalize_label(raw: str) -> str:
    """Lowercase, strip surrounding punctuation/whitespace, normalize spaces."""
    s = raw.lower().strip()
    s = re.sub(r'\s+', ' ', s)
    return s.strip(" .,;:-")


def _extract_pairs_from_text(text: str) -> list[tuple[str, float]]:
    """Find every '<label> XX,XX %' on its own row, return [(label, pct)]."""
    pairs: list[tuple[str, float]] = []
    for line in text.split("\n"):
        # Skip lines that are tick marks like '0 % 20 % 40 % …' (chart axes)
        if re.match(r'^\s*(\d{1,3}\s*%\s*){3,}', line):
            continue
        # A row may contain MULTIPLE label–% pairs (geo + sector side by side
        # in some Amundi pages). Extract them greedily.
        for m in _PAIR_RE.finditer(line):
            label = _normalize_label(m.group(1))
            try:
                val = float(m.group(2).replace(",", "."))
            except ValueError:
                continue
            if 0 < val <= 100 and 2 <= len(label) <= 60:
                pairs.append((label, val))
    return pairs


def _classify_pairs(pairs: list[tuple[str, float]]) -> tuple[dict, dict]:
    """Split raw pairs into (geo_dict, sector_dict) using vocabulary maps."""
    geo: dict[str, float] = {}
    sec: dict[str, float] = {}
    for label, val in pairs:
        # Try sector first (more distinctive)
        if label in SECTOR_FR_TO_EN:
            key = SECTOR_FR_TO_EN[label]
            sec[key] = sec.get(key, 0.0) + val
            continue
        if label in COUNTRY_FR_TO_EN:
            key = COUNTRY_FR_TO_EN[label]
            geo[key] = geo.get(key, 0.0) + val
            continue
        # Try partial match: some labels arrive with trailing punctuation we missed
        for k_fr, k_en in SECTOR_FR_TO_EN.items():
            if label.startswith(k_fr) or k_fr.startswith(label):
                if abs(len(label) - len(k_fr)) <= 3:
                    sec[k_en] = sec.get(k_en, 0.0) + val
                    break
        else:
            for k_fr, k_en in COUNTRY_FR_TO_EN.items():
                if label.startswith(k_fr) or k_fr.startswith(label):
                    if abs(len(label) - len(k_fr)) <= 3:
                        geo[k_en] = geo.get(k_en, 0.0) + val
                        break
        # Anything still unmatched is silently dropped — likely a non-composition line
    return geo, sec


def _parse_bnp_sections(full_text: str) -> tuple[dict, dict]:
    """BNP factsheets list composition as 'Label NN,NN' WITHOUT a % per line
    (the '%' lives in the section header 'par Secteur (%)'). Country rows also
    sit next to holdings in a two-column layout. We scan label–number pairs
    inside the relevant sections and let the vocab maps keep only real
    countries / sectors.
    """
    geo: dict[str, float] = {}
    sec: dict[str, float] = {}

    # Sector block: from "par Secteur" to the next "Total" or "Source"
    sec_start = full_text.find("par Secteur")
    if sec_start >= 0:
        tail = full_text[sec_start:]
        end = min([x for x in [tail.find("Total"), tail.find("Source")] if x > 0] or [len(tail)])
        block = tail[:end]
        for m in re.finditer(r'([A-Za-zÀ-ÿ’\' .-]+?)\s+(\d{1,3}[,.]\d{1,2})', block):
            lbl = _normalize_label(m.group(1))
            if lbl in SECTOR_FR_TO_EN:
                key = SECTOR_FR_TO_EN[lbl]
                sec[key] = sec.get(key, 0.0) + float(m.group(2).replace(",", "."))

    # Country block: from "par Pays" to the sector header
    geo_start = full_text.find("par Pays")
    if geo_start >= 0:
        tail = full_text[geo_start:]
        end = tail.find("par Secteur")
        block = tail[:end if end > 0 else len(tail)]
        for m in re.finditer(r'([A-Za-zÀ-ÿ’\' .-]+?)\s+(\d{1,3}[,.]\d{1,2})', block):
            lbl = _normalize_label(m.group(1))
            if lbl in COUNTRY_FR_TO_EN:
                key = COUNTRY_FR_TO_EN[lbl]
                geo[key] = geo.get(key, 0.0) + float(m.group(2).replace(",", "."))

    return geo, sec


def parse_factsheet_pdf(pdf_bytes: bytes) -> tuple[dict, dict]:
    """Return (geo, sector) dicts {label: pct}. Either may be empty.

    Tries the standard (Amundi) layout first; if that yields nothing, falls
    back to the BNP section-header layout.
    """
    import pdfplumber  # lazy: only the factsheet path needs it
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        full_text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    pairs = _extract_pairs_from_text(full_text)
    geo, sec = _classify_pairs(pairs)
    if not geo and not sec:
        geo, sec = _parse_bnp_sections(full_text)
    return geo, sec


# ---------------------------------------------------------------------------
# Validation + normalization
# ---------------------------------------------------------------------------

def _validate(breakdown: dict, kind: str) -> tuple[bool, str]:
    if not breakdown:
        return False, f"{kind}: empty"
    s = sum(breakdown.values())
    if not (85.0 <= s <= 115.0):
        return False, f"{kind}: sum {s:.2f} outside [85,115]"
    for k, v in breakdown.items():
        if v < 0 or v > 100.05:
            return False, f"{kind}: {k}={v:.2f} out of range"
    return True, "OK"


def _normalize_100(breakdown: dict) -> dict:
    s = sum(breakdown.values())
    if s <= 0:
        return breakdown
    scaled = {k: round(v * 100.0 / s, 2) for k, v in breakdown.items()}
    diff = round(100.0 - sum(scaled.values()), 2)
    if abs(diff) > 0.001:
        biggest = max(scaled, key=scaled.get)
        scaled[biggest] = round(scaled[biggest] + diff, 2)
    return scaled


# ---------------------------------------------------------------------------
# Atomic JSON write
# ---------------------------------------------------------------------------

def _load_json() -> dict:
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _atomic_save(payload: dict) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".etf_compositions.", suffix=".tmp", dir=str(ROOT))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, JSON_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

# yfinance sector keys → JSON keys (fallback only, e.g. IBEX has no factsheet)
_YF_SECTOR_MAP = {
    "technology": "Tech", "financial_services": "Financials", "healthcare": "Healthcare",
    "consumer_cyclical": "Consumer Disc.", "consumer_defensive": "Consumer Staples",
    "communication_services": "Communication", "industrials": "Industrials",
    "energy": "Energy", "utilities": "Utilities", "basic_materials": "Materials",
    "realestate": "Real Estate",
}
_YF_TICKER = {
    "FR0011871128": "PSP5.PA", "FR0013412020": "PAEEM.PA", "FR0011550193": "ETZ.PA",
    "LU1681038672": "RS2K.PA", "FR0011871110": "PUST.PA", "FR0010655746": "CS1.PA",
    "FR0013411980": "PTPXE.PA",
}


def _ticker_for_isin(isin: str) -> str | None:
    """Resolve an ISIN to its Yahoo ticker — checks the dynamic registry first
    (so newly added ETFs work), then the original-7 hardcoded map."""
    try:
        import data
        data.ensure_seeded()
        tk = data.YF_TICKER_BY_ISIN.get(isin)
        if tk:
            return tk
    except Exception:
        pass
    return _YF_TICKER.get(isin)


def _yfinance_sector_fallback(isin: str) -> dict | None:
    """Last-resort sector breakdown from yfinance (no geo). Returns {key: pct}."""
    ticker = _ticker_for_isin(isin)
    if not ticker:
        return None
    try:
        import yfinance as yf
        raw = yf.Ticker(ticker).funds_data.sector_weightings or {}
    except Exception:
        return None
    if not raw:
        return None
    out: dict[str, float] = {}
    for k, v in raw.items():
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        name = _YF_SECTOR_MAP.get(k, "Other")
        out[name] = out.get(name, 0.0) + f * 100.0
    return out or None


def refresh_one(asset: str, isin: str, log: logging.Logger) -> dict:
    """Run the full pipeline for one ETF. Returns a result dict.

    Strategy: official factsheet PDF first (geo + sector); if that fails,
    fall back to yfinance for sector only (geo left to existing JSON).
    """
    result = {"asset": asset, "isin": isin, "status": "skip", "reason": "",
              "geo": None, "sector": None, "mr_url": None, "source": None}

    mr_url = find_monthly_report_url(isin)
    if mr_url:
        result["mr_url"] = mr_url
        try:
            pdf_bytes = _http_get(mr_url, timeout=30)
            geo, sec = parse_factsheet_pdf(pdf_bytes)
            ok_g, msg_g = _validate(geo, "geo")
            ok_s, msg_s = _validate(sec, "sector")
            if ok_g or ok_s:
                if ok_g:
                    result["geo"] = _normalize_100(geo)
                if ok_s:
                    result["sector"] = _normalize_100(sec)
                result["status"] = "ok"
                result["source"] = "official factsheet (fundinfo)"
                result["reason"] = f"geo: {msg_g}  sector: {msg_s}"
                return result
            log.info("  PDF found but unparseable (%s | %s) — trying yfinance…", msg_g, msg_s)
        except Exception as e:
            log.info("  PDF error (%s) — trying yfinance…", type(e).__name__)

    # Fallback: yfinance sector-only
    yf_sec = _yfinance_sector_fallback(isin)
    if yf_sec:
        ok_s, msg_s = _validate(yf_sec, "sector")
        if ok_s:
            result["sector"] = _normalize_100(yf_sec)
            result["status"] = "ok"
            result["source"] = "yfinance (sector only — no factsheet PDF)"
            result["reason"] = f"yfinance sector: {msg_s}"
            return result

    result["reason"] = "no factsheet PDF and yfinance fallback unavailable"
    return result


def refresh_all(logger: logging.Logger | None = None) -> dict:
    """Iterate all ETFs in the JSON, scrape factsheets, validate, write back."""
    log = logger or logging.getLogger("gpcp.scraper")

    payload = _load_json()
    today = dt.date.today().isoformat()

    updated: list[str] = []
    untouched: list[tuple[str, str]] = []

    for asset, entry in payload.items():
        if asset.startswith("_"):
            continue
        isin = entry.get("isin", "")
        if not isin:
            untouched.append((asset, "missing ISIN"))
            continue

        log.info("Refreshing %s [%s]…", asset, isin)
        res = refresh_one(asset, isin, log)

        if res["status"] != "ok":
            log.warning("  ✗ %s: %s — keeping existing data.", asset, res["reason"])
            untouched.append((asset, res["reason"]))
            continue

        # Apply only the dimensions that validated
        changed = []
        if res["geo"] is not None:
            entry["geo"] = res["geo"]
            changed.append(f"geo({len(res['geo'])} entries)")
        if res["sector"] is not None:
            entry["sector"] = res["sector"]
            changed.append(f"sector({len(res['sector'])} entries)")
        entry["last_verified"] = today
        entry["last_auto_refresh"] = today
        entry["last_auto_refresh_source"] = res.get("source") or "unknown"
        if res.get("mr_url"):
            entry["source_pdf"] = res["mr_url"]
        updated.append(asset)
        log.info("  ✓ %s: %s", asset, " + ".join(changed))

    if updated:
        _atomic_save(payload)
        log.info("Wrote etf_compositions.json: updated %d ETF(s).", len(updated))
    else:
        log.info("No ETF updated.")

    return {"updated": updated, "untouched": untouched}


def lookup_yfinance_info(ticker: str) -> dict:
    """Best-effort metadata lookup for ANY ticker (stock or ETF).

    Returns: {isin, fund, sector, country, long_name}. All fields may be empty.
    Used by the simplified V10 new-asset form to fill defaults so the user only
    has to provide a name + ticker.
    """
    try:
        import yfinance as yf
        info = (yf.Ticker(ticker).info or {})
    except Exception:
        return {"isin": "", "fund": "", "sector": "", "country": "", "long_name": ""}
    return {
        "isin":      (info.get("isin") or "").strip().upper(),
        "fund":      info.get("fundFamily") or "",
        "sector":    info.get("sector") or info.get("category") or "",
        "country":   info.get("country") or "",
        "long_name": info.get("longName") or info.get("shortName") or "",
        "currency":  (info.get("currency") or "").strip().upper(),  # V11
    }


def seed_stock_compositions(asset: str, ticker: str) -> bool:
    """If the JSON entry for `asset` has empty geo/sector after the PDF + ETF
    fallbacks, fill it from yfinance.Ticker(ticker).info — a stock has ONE
    sector and ONE country, so each becomes 100 %.
    Returns True if anything was written.
    """
    payload = _load_json()
    entry = payload.get(asset)
    if not entry:
        return False
    needs_geo = not entry.get("geo")
    needs_sec = not entry.get("sector")
    if not needs_geo and not needs_sec:
        return False
    info = lookup_yfinance_info(ticker)
    wrote = False
    if needs_geo and info.get("country"):
        entry["geo"] = {info["country"]: 100.0}
        wrote = True
    if needs_sec and info.get("sector"):
        entry["sector"] = {info["sector"]: 100.0}
        wrote = True
    if wrote:
        entry["last_verified"] = dt.date.today().isoformat()
        entry["last_auto_refresh"] = dt.date.today().isoformat()
        entry["last_auto_refresh_source"] = "yfinance.info (stock)"
        _atomic_save(payload)
    return wrote


def ensure_asset_entry(asset: str, isin: str, ticker: str,
                       issuer: str = "—") -> None:
    """Make sure `asset` has a stub entry in etf_compositions.json so the
    monthly scraper picks it up like every other ETF. No network call."""
    payload = _load_json()
    if asset in payload:
        # keep existing breakdowns; just refresh identifiers
        payload[asset].update({"isin": isin, "ticker": ticker, "issuer": issuer,
                               "factsheet_url": f"https://www.justetf.com/fr/etf-profile.html?isin={isin}"})
    else:
        payload[asset] = {
            "isin": isin, "ticker": ticker, "issuer": issuer,
            "factsheet_url": f"https://www.justetf.com/fr/etf-profile.html?isin={isin}",
            "last_verified": "", "geo": {}, "sector": {},
        }
    _atomic_save(payload)


def refresh_asset(asset: str, logger: logging.Logger | None = None) -> dict:
    """Scrape a SINGLE asset's factsheet now and persist it. Returns the result."""
    log = logger or logging.getLogger("gpcp.scraper")
    payload = _load_json()
    entry = payload.get(asset)
    if not entry or not entry.get("isin"):
        return {"asset": asset, "status": "skip", "reason": "no entry / ISIN"}
    res = refresh_one(asset, entry["isin"], log)
    if res["status"] == "ok":
        if res["geo"] is not None:
            entry["geo"] = res["geo"]
        if res["sector"] is not None:
            entry["sector"] = res["sector"]
        entry["last_verified"] = dt.date.today().isoformat()
        entry["last_auto_refresh"] = dt.date.today().isoformat()
        entry["last_auto_refresh_source"] = res.get("source") or "unknown"
        if res.get("mr_url"):
            entry["source_pdf"] = res["mr_url"]
        _atomic_save(payload)
    return res


def main() -> int:
    import sys
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")
    log = logging.getLogger("gpcp.scraper")
    log.info("=== compositions_scraper start ===")
    summary = refresh_all(log)
    log.info("=== done — updated: %s ; untouched: %s ===",
             summary["updated"], [a for a, _ in summary["untouched"]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
