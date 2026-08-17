#!/usr/bin/env python3
"""Diagnostic VL — dump a live portfolio and reconstruct its VL series.

Uses the SAME authenticated REST path as the app (sign in → RLS-scoped reads),
so it works even though the direct DB password is rejected. Read-only.

    .venv/bin/python SAAS/diag_vl.py                 # TEST portfolio, default email
    .venv/bin/python SAAS/diag_vl.py TEST you@mail   # explicit portfolio / email

You'll be prompted for your dashboard password (hidden, never printed). Paste the
whole output back. It NEVER writes to the DB.
"""
from __future__ import annotations
import os, sys, getpass, datetime as dt
# Script lives in SAAS/ — put repo root on path + make it cwd so imports and
# st.secrets (.streamlit/secrets.toml) resolve.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); os.chdir(_ROOT)
import pandas as pd
import supabase_client as sc
import data_sqlite as ds          # trusted VL engine (identical to cloud)

want  = (sys.argv[1] if len(sys.argv) > 1 else "test").lower()
email = sys.argv[2] if len(sys.argv) > 2 else input("Email du compte : ").strip()
pwd   = getpass.getpass(f"Mot de passe du dashboard pour {email} : ")

r = sc.new_anon_client().auth.sign_in_with_password({"email": email, "password": pwd})
token = r.session.access_token
cli = sc._authed_client(token)
def rows(table, sel, pid=None, order=None):
    q = cli.table(table).select(sel)
    if pid is not None: q = q.eq("portfolio_id", pid)
    if order: q = q.order(order)
    return q.execute().data or []

pfs = cli.table("portfolios").select("*").execute().data or []
match = [p for p in pfs if want in (p["id"] or "").lower() or want in (p.get("name") or "").lower()] or pfs
if not match:
    print("Aucun portefeuille trouvé."); sys.exit(1)
pf = match[0]; pid = pf["id"]; pf_ccy = (pf.get("currency") or "EUR").upper()
print(f"=== Portfolio: id={pid!r} name={pf.get('name')!r} ccy={pf_ccy} ===\n")

txrows = rows("transactions", "trade_date,asset,txn_type,price,shares,amount_eur,currency", pid, "trade_date")
print("--- TRANSACTIONS ---")
for r_ in txrows:
    print(f"  {r_['trade_date']}  {(r_['txn_type'] or '').upper():8} {r_['asset']:8} "
          f"price={r_['price']} shares={r_['shares']} amt={r_['amount_eur']} {r_['currency']}")

TX=[{"id":i,"date":dt.date.fromisoformat(str(t["trade_date"])[:10]),"asset":t["asset"],
     "type":(t["txn_type"] or "BUY").upper(),"price":float(t["price"]) if t["price"] is not None else None,
     "shares":float(t["shares"] or 0),"amount":float(t["amount_eur"] or 0),
     "currency":(t["currency"] or "EUR").upper()} for i,t in enumerate(txrows)]

meta={m["key"]:m["value"] for m in rows("meta","key,value",pid)}
print("\n--- META ---", meta)

hold = rows("holdings","asset,isin,ticker,currency",pid)
print("--- HOLDINGS (asset → ticker, ce qui sert au backfill Yahoo) ---")
for h in hold:
    print(f"  {h['asset']:10} ticker={h.get('ticker')!r}  isin={h.get('isin')!r}  ccy={h.get('currency')}")

FX={}
for f in rows("fx_rates","trade_date,pair,rate",pid):
    FX.setdefault(f["pair"],{})[str(f["trade_date"])[:10]]=float(f["rate"])
def fx_rate(a,b,when=None):
    a,b=(a or "EUR").upper(),(b or "EUR").upper()
    if a==b: return 1.0
    tbl=FX.get(a+b)
    if not tbl: return 1.0
    wi=(when or dt.date.today()).isoformat()
    ks=[k for k in tbl if k<=wi]
    return tbl[max(ks)] if ks else tbl[min(tbl)]

prows = rows("prices","trade_date,asset,price",pid,"trade_date")
# Per-asset price coverage + gap detection — THE key diagnostic for this bug.
from collections import defaultdict
_cov=defaultdict(list)
for p in prows: _cov[p["asset"]].append(dt.date.fromisoformat(str(p["trade_date"])[:10]))
print(f"\n--- COUVERTURE PRIX par asset (total rows={len(prows)}) ---")
for a,dl in _cov.items():
    dl=sorted(dl)
    gaps=[(dl[i-1].isoformat(),dl[i].isoformat()) for i in range(1,len(dl)) if (dl[i]-dl[i-1]).days>10]
    print(f"  {a:10} n={len(dl):4}  {dl[0]} → {dl[-1]}  TROUS(>10j)={gaps[:6]}")

ASSETS=list(dict.fromkeys(t["asset"] for t in TX if t["type"] in ("BUY","SELL")))
if prows:
    pdf=pd.DataFrame(prows); pdf["date"]=pd.to_datetime(pdf["trade_date"])
    ph=pdf.pivot_table(index="date",columns="asset",values="price",aggfunc="last").reset_index()
    ph.columns.name=None
else:
    ph=pd.DataFrame(columns=["date",*ASSETS])
for a in ASSETS:
    if a not in ph.columns: ph[a]=float("nan")
ph=ph.sort_values("date").reset_index(drop=True)
firsttx={}
for t in TX:
    if t["type"] in ("BUY","SELL"):
        firsttx[t["asset"]]=min(firsttx.get(t["asset"],t["date"]),t["date"])
dser=ph["date"].dt.date
for a in ASSETS:
    fd=firsttx.get(a)
    if fd is not None and a in ph.columns: ph.loc[dser<fd,a]=float("nan")

ccy_map={t["asset"]:t["currency"] for t in TX if t["type"] in ("BUY","SELL")}
inc=min((t["date"] for t in TX), default=dt.date.today())
if meta.get("inception_date"):
    try: inc=max(dt.date.fromisoformat(meta["inception_date"]), inc)
    except Exception: pass

ds.ASSETS=ASSETS
ds._all_transactions=lambda: TX
ds.current_portfolio_currency=lambda: pf_ccy
ds.fx_rate=fx_rate
ds.prefetch_fx_window=lambda *a,**k: None
ds.get_inception_date=lambda: inc
ds.default_inception_date=lambda: inc
ds.load_static=lambda: ds.PortfolioStatic(
    shares=ds.shares_held_as_of(dt.date.today()),isins={a:"" for a in ASSETS},
    funds={a:"-" for a in ASSETS},fees={a:0.0 for a in ASSETS},currencies=ccy_map)

print(f"\n--- inception={inc}  ASSETS={ASSETS}  price rows={len(ph)} ---")
vl=ds.compute_vl_series(ph.copy(), inc)
print("\n--- VL SERIES (last 25): date | nav | units | vl | net_invested ---")
for _,r_ in vl.tail(25).iterrows():
    print(f"  {r_['date'].date()}  nav={r_['nav']:.2f}  units={r_['units']:.4f}  vl={r_['vl']:.4f}  net_inv={r_['net_invested']:.2f}")
print("\n--- UNITS CHANGES (should change ONLY on a deposit/withdrawal day) ---")
prev=None
for _,r_ in vl.iterrows():
    if prev is not None and abs(r_['units']-prev)>1e-6:
        print(f"  {r_['date'].date()}: units {prev:.4f} → {r_['units']:.4f}  net_inv={r_['net_invested']:.2f}")
    prev=r_['units']
last_prices={a:float(ph[a].dropna().iloc[-1]) for a in ASSETS if a in ph and ph[a].notna().any()}
snap=ds.compute_snapshot(ds.load_static(), last_prices, ph.copy())
print(f"\n--- SNAPSHOT --- NAV={snap['total_value']:.2f} cash={snap['cash_balance']:.2f} "
      f"vl={snap['vl']:.4f} total_return={snap['total_return_pct']*100:+.3f}% net_invested={snap['net_invested']:.2f}")
print("\n(colle toute cette sortie)")
