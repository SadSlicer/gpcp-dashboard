#!/usr/bin/env python3
"""One-shot migration : local sqlite portfolios → Supabase Postgres.

Run this ONCE from your machine, after you have:
  1. Deployed the app and created your admin account (signup with your email).
  2. (Optional) promoted yourself to admin via the SQL in db/schema.sql.

It reads every `portfolios/portfolio_<id>.db` listed in
`portfolios/_registry.json` and copies all rows (portfolios, holdings,
transactions, prices, fx_rates, meta) into Postgres under YOUR user_id.

Auth model: you sign in with your email + password; the script uses the
returned JWT for all inserts, so Row-Level Security accepts them
(user_id = auth.uid()). No service_role key or DB password needed.

Idempotent: for each portfolio it WIPES that portfolio's rows for your
user first, then re-inserts — so you can safely re-run it.

    .venv/bin/python migrate_to_supabase.py
"""

from __future__ import annotations

import datetime as dt
import getpass
import json
import os
import sqlite3
import sys
from pathlib import Path

import supabase_client

ROOT = Path(__file__).resolve().parent
PORTFOLIOS_DIR = ROOT / "portfolios"
REGISTRY_PATH = PORTFOLIOS_DIR / "_registry.json"

CHUNK = 500   # rows per upsert batch


def _chunks(seq, n=CHUNK):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _date(s: str) -> str:
    """Normalize a sqlite trade_date (may carry a time) to YYYY-MM-DD."""
    return (s or "")[:10]


def main() -> int:
    if not REGISTRY_PATH.exists():
        print(f"❌ {REGISTRY_PATH} introuvable — rien à migrer.")
        return 1
    reg = json.loads(REGISTRY_PATH.read_text() or "{}")
    portfolios = reg.get("portfolios", [])
    current_id = reg.get("current_id")
    if not portfolios:
        print("❌ Aucun portfolio dans le registre.")
        return 1

    print("Portfolios trouvés :",
          ", ".join(f"{p['id']} ({p.get('currency', 'EUR')})" for p in portfolios))
    print(f"Portfolio courant : {current_id}\n")

    # --- Authenticate (get JWT + uid) -------------------------------------
    # Email: 1st CLI arg, else GPCP_MIGRATE_EMAIL env, else prompt.
    # Password: GPCP_MIGRATE_PASSWORD env (non-interactive), else hidden prompt
    #           (NEVER passed as a CLI arg — it would land in shell history).
    email = (sys.argv[1] if len(sys.argv) > 1 else None) \
        or os.environ.get("GPCP_MIGRATE_EMAIL") \
        or input("Email admin Supabase : ")
    email = email.strip()
    password = os.environ.get("GPCP_MIGRATE_PASSWORD") or getpass.getpass(
        f"Mot de passe pour {email} : ")
    anon = supabase_client.new_anon_client()
    try:
        resp = anon.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as exc:
        print(f"❌ Connexion échouée : {exc}")
        return 1
    if not resp.user or not resp.session:
        print("❌ Identifiants invalides ou session absente.")
        return 1
    uid = resp.user.id
    token = resp.session.access_token
    sb = supabase_client._authed_client(token)
    print(f"✅ Connecté — {email} — user_id = {uid}\n")

    auto_yes = os.environ.get("GPCP_MIGRATE_YES") or not sys.stdin.isatty()
    if auto_yes:
        print(f"Migration de {len(portfolios)} portfolio(s) (mode non-interactif)…")
    elif input(f"Migrer {len(portfolios)} portfolio(s) vers ce compte ? "
               "(les rows existantes de ces portfolios seront REMPLACÉES) [y/N] "
               ).strip().lower() not in ("y", "yes", "o", "oui"):
        print("Annulé.")
        return 0

    totals = {"portfolios": 0, "holdings": 0, "transactions": 0,
              "prices": 0, "fx_rates": 0, "meta": 0}

    for p in portfolios:
        pid = p["id"]
        ccy = (p.get("currency") or "EUR").upper()
        dbpath = PORTFOLIOS_DIR / f"portfolio_{pid}.db"
        print(f"── Portfolio {pid} ──")
        if not dbpath.exists():
            print(f"   ⚠️  {dbpath.name} absent — ignoré.")
            continue
        con = sqlite3.connect(dbpath)
        con.row_factory = sqlite3.Row

        # 1. Idempotency: wipe this user's rows for this portfolio
        for table in ("transactions", "prices", "fx_rates", "meta", "holdings"):
            sb.table(table).delete().eq("user_id", uid).eq("portfolio_id", pid).execute()

        # 2. Portfolio registry row (upsert)
        sb.table("portfolios").upsert({
            "user_id": uid, "id": pid, "name": p.get("name") or pid,
            "currency": ccy, "seed_from_workbook": bool(p.get("seed_from_workbook")),
        }, on_conflict="user_id,id").execute()
        totals["portfolios"] += 1

        # 3. Holdings (carry asset currency for tx fallback)
        hold_ccy: dict[str, str] = {}
        h_rows = []
        for r in con.execute("SELECT * FROM holdings"):
            a_ccy = (r["currency"] or "EUR").upper()
            hold_ccy[r["asset"]] = a_ccy
            h_rows.append({
                "user_id": uid, "portfolio_id": pid,
                "asset": r["asset"], "isin": r["isin"] or None,
                "fund": r["fund"] or "—", "fees": float(r["fees"] or 0),
                "ticker": (r["ticker"] if "ticker" in r.keys() else None) or None,
                "currency": a_ccy,
            })
        for batch in _chunks(h_rows):
            if batch:
                sb.table("holdings").upsert(
                    batch, on_conflict="user_id,portfolio_id,asset").execute()
        totals["holdings"] += len(h_rows)
        print(f"   holdings    : {len(h_rows)}")

        # 4. Transactions (do NOT carry sqlite id — Postgres BIGSERIAL assigns)
        t_rows = []
        for r in con.execute("SELECT * FROM transactions ORDER BY trade_date, id"):
            asset = r["asset"]
            tx_ccy = (r["currency"] if "currency" in r.keys() else None)
            if not tx_ccy:
                tx_ccy = hold_ccy.get(asset, ccy)   # Cash → portfolio ccy
            t_rows.append({
                "user_id": uid, "portfolio_id": pid,
                "trade_date": _date(r["trade_date"]),
                "asset": asset, "isin": r["isin"] or None,
                "txn_type": (r["txn_type"] or "BUY").upper(),
                "price": float(r["price"]) if r["price"] is not None else None,
                "shares": float(r["shares"]) if r["shares"] is not None else None,
                "amount_eur": float(r["amount_eur"]),
                "currency": (tx_ccy or "EUR").upper(),
            })
        for batch in _chunks(t_rows):
            if batch:
                sb.table("transactions").insert(batch).execute()
        totals["transactions"] += len(t_rows)
        print(f"   transactions: {len(t_rows)}")

        # 5. Prices
        p_rows = [{
            "user_id": uid, "portfolio_id": pid,
            "trade_date": _date(r["trade_date"]),
            "asset": r["asset"], "price": float(r["price"]),
        } for r in con.execute("SELECT * FROM prices")]
        for batch in _chunks(p_rows):
            if batch:
                sb.table("prices").upsert(
                    batch, on_conflict="user_id,portfolio_id,trade_date,asset").execute()
        totals["prices"] += len(p_rows)
        print(f"   prices      : {len(p_rows)}")

        # 6. FX rates
        fx_rows = [{
            "user_id": uid, "portfolio_id": pid,
            "trade_date": _date(r["trade_date"]),
            "pair": r["pair"], "rate": float(r["rate"]),
        } for r in con.execute("SELECT * FROM fx_rates")]
        for batch in _chunks(fx_rows):
            if batch:
                sb.table("fx_rates").upsert(
                    batch, on_conflict="user_id,portfolio_id,trade_date,pair").execute()
        totals["fx_rates"] += len(fx_rows)
        print(f"   fx_rates    : {len(fx_rows)}")

        # 7. Meta
        m_rows = [{
            "user_id": uid, "portfolio_id": pid,
            "key": r["key"], "value": r["value"],
        } for r in con.execute("SELECT * FROM meta")]
        for batch in _chunks(m_rows):
            if batch:
                sb.table("meta").upsert(
                    batch, on_conflict="user_id,portfolio_id,key").execute()
        totals["meta"] += len(m_rows)
        print(f"   meta        : {len(m_rows)}")

        con.close()

    # 8. Set current portfolio
    if current_id:
        sb.table("current_portfolio").upsert(
            {"user_id": uid, "portfolio_id": current_id},
            on_conflict="user_id").execute()
        print(f"\nPortfolio courant réglé sur « {current_id} »")

    print("\n✅ Migration terminée :")
    for k, v in totals.items():
        print(f"   {k:13}: {v}")
    print("\nRecharge l'app — tes portfolios doivent apparaître.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
