# GPCP Dashboard — **ALPHA** · Full rebuild + handoff (SaaS branch)

> **ALPHA = the current known-good, fully-working cloud version.** After a long
> fight with Streamlit Cloud segfaults, this is the first version that boots,
> renders, updates prices, and survives reloads / re-logins / Refresh without
> crashing. Tag: `alpha`. Branch: `saas`.
>
> This doc lets you **rebuild the app from zero** and, above all, records the
> **hard-won fixes you must never undo**. Owner speaks French — reply in French.
> Charts / UI are in **English**.

---

## 0. TL;DR — what ALPHA is

A multi-tenant SaaS portfolio dashboard (Streamlit + Supabase Postgres), forked
from the local VA15 design. Same premium dark UI, same portfolio maths, but data
lives in Postgres (per-user, Row-Level-Security) and prices are fetched from
Yahoo **without yfinance**.

- **Branch:** `saas`. **Tag:** `alpha`. Never touch `va` / `va15` / `main` /
  `data_sqlite.py`.
- **Live URL:** `gabriel-peix-portfolio-app.streamlit.app` (Streamlit Community
  Cloud, free tier). Repo: `SadSlicer/gpcp-dashboard` (public).
- **Boot stamp:** the logs print `GPCP build=alpha` at startup — use it to confirm
  the live app is actually running this build.

---

## 1. ⚠️ THE 6 FIXES YOU MUST NEVER UNDO (why ALPHA exists)

These were paid for in blood (dozens of crash/deploy cycles). Undoing any one
brings back an **uncatchable segfault** that crashes the whole app on Streamlit
Cloud.

1. **No `yfinance` / `curl_cffi`.** yfinance's native HTTP backend (`curl_cffi`)
   **segfaults on Cloud's Linux container** — sometimes merely on import,
   uncatchable, killing the app. `requirements.txt` must NOT contain yfinance or
   curl_cffi. Prices come from **Yahoo's public JSON API via `requests`** (see
   `prices.py`: `_yahoo_chart` = v8 chart, `_yahoo_quote_summary` = v10). Requests
   needs a **cookie (GET fc.yahoo.com) + crumb** primed first, or Yahoo blocks the
   datacenter IP. Works for ETFs, `0P…` mutual funds, indices, crypto, 5y depth.

2. **Thread-local `requests` session.** `requests.Session` is NOT thread-safe;
   Streamlit runs every session in a thread. A shared session corrupts urllib3/SSL
   state → segfault on the *second* concurrent login. `prices._thread_session()`
   keeps one per thread (`threading.local`).

3. **Thread-local Supabase client.** Same bug on the DB side:
   `supabase_client._authed_client` / `get_client` cached ONE httpx client
   globally (`@lru_cache`) → shared across threads → segfault on re-login. Now
   cached **per (thread, token)** via `threading.local`.

4. **Skip heavy work in bare-mode runs.** Streamlit Cloud re-executes the whole
   app in "bare mode" (health checks / file-watch — the *"missing ScriptRunContext"*
   log lines, which are NORMAL). Running the full fetch + numpy/pandas render there,
   concurrently with a real session on the tiny free container, segfaults a native
   lib. `_has_script_ctx()` (via `get_script_run_ctx()`) gates `_auto_refresh_if_stale`,
   `_heal_price_gaps_once` and `pro.render` — they no-op when there's no real user
   context.

5. **Python pinned to 3.12 in Streamlit Cloud settings** (NOT the repo — it's a
   dashboard setting: Manage app → Settings → Python version). 3.14 was even worse
   for native wheels. Keep 3.12.

6. **Streamlit pinned `==1.57.0`** + **version-hardened tab CSS** in `theme.py`
   (targets legacy `[data-baseweb="tab"]` AND ARIA roles, force-hides inactive
   panels). A newer Streamlit changed the tabs DOM and broke the layout. Keep both.

7. **Native libs pinned:** `numpy==2.1.3`, `pandas==2.2.3`, `pyarrow==17.0.0`.
   Unpinned, every Cloud rebuild pulled the LATEST wheel → a bleeding-edge Linux
   wheel could segfault during render, making every redeploy a lottery (identical
   code, works one build, crashes the next). Pinned = the build is DETERMINISTIC.
   Validated on Python 3.12: installs as wheels + demo AppTest 0/0. If you ever
   bump one, re-validate on 3.12 (throwaway venv) that it installs as a wheel and
   the app boots — a version with no cp312 wheel builds from source and breaks.

**Deploy gotcha (wasted many cycles):** a plain **"Reboot app" reuses the CACHED
build** — it does NOT pick up a new push. You must push `deploy:main`, let Cloud
**rebuild** (reinstall deps), then it's live. Confirm via the `GPCP build=alpha`
log line. And a git push that says *"Everything up-to-date"* means the code is
already on GitHub — the problem is then Cloud not rebuilding, not the push.

**Never paste your GitHub PAT in chat.** Use a fresh PAT (scopes `repo`+`workflow`)
each deploy; revoke any that leaks.

---

## 2. Stack & architecture

| Layer | Tech |
|---|---|
| App / UI | Python · **Streamlit 1.57.0 (pinned)** · Plotly · custom CSS (`theme.py` = `va1theme`) |
| Data / math | pandas · NumPy |
| DB | **Supabase Postgres** + **Row-Level Security** (per `user_id`+`portfolio_id`) |
| Auth | **Supabase Auth** (bcrypt, JWT) — anon key only, never service_role |
| Prices / FX | **Yahoo public JSON API via `requests`** (`prices.py`) — NO yfinance |
| ETF composition | JustETF → fundinfo PDF (`pdfplumber`) + Yahoo quoteSummary fallback (`compositions_scraper.py`) |
| PDF report | ReportLab |
| Deploy | Streamlit Community Cloud · GitHub · orphan-branch push (`SAAS/deploy.sh`) |

**Dual-backend data layer.** `data.py` dispatches (per attribute access) to:
- `data_postgres.py` — the **cloud** backend (RLS, per-user). All SaaS logic here.
- `data_sqlite.py` — local + **demo** engine. **OFF-LIMITS / read-only.**
- `data_demo.py` — read-only demo (frozen `demo_data.json` + live tail).

**Caches are process-global** (`st.cache_data` + module dicts) → any per-user cache
MUST be keyed by `(user_id, portfolio_id)` or concurrent users leak/crash.

**Runtime flow:** visitor → access-code gate → Supabase login → dashboard. Backend
is Postgres (no `.db` is committed, so sqlite would be empty on Cloud). Note: the
`"SOURCE: sqlite snapshot · <date>"` badge is a **hardcoded label** in
`app._initial_prices` — it does NOT mean sqlite is active; it just shows the last
stored price date. Real backend check: `data._active_backend_name()`.

---

## 3. Files that matter

| File | Role |
|---|---|
| `app.py` | Streamlit UI: gate/login entry, header, tabs, KPIs, charts, Transactions form, Settings, the `GPCP build=alpha` stamp, `_has_script_ctx()` gating |
| `pro.py` | Pro tab (risk, calendar, attribution, correlation, benchmark, Monte Carlo, PDF, sector/geo). Benchmark + sector/geo fetch via `prices.*`; bare-mode gate at `render()` |
| `prices.py` | **requests-based Yahoo fetcher** — `_thread_session` (cookie+crumb, thread-local), `_yahoo_chart` (v8), `_yahoo_quote_summary` (v10); `fetch_latest_with_date` / `fetch_history` / `fetch_ticker_history` / `fetch_adjusted_close_on` / `fetch_benchmark_series` / `fetch_funds_sectors` / `fetch_yahoo_info` / `probe_ticker_fetch` (diagnostic). NO yfinance. `MAX_HISTORY = 5 years`. `YAHOO_ENABLED` master switch (True) |
| `data.py` | Backend dispatcher (PEP-562 `__getattr__` → sqlite or postgres) |
| `data_postgres.py` | Cloud engine: snapshot, VL, NAV, cash walk, FX, `load_price_history` (**paginated** `_select_all` — beware PostgREST's 1000-row cap), `heal_price_gaps`, `refetch_all_prices_from_inception`, `set_manual_geo`/`get_all_manual_geo`, `earliest_price_date` |
| `data_sqlite.py` | V15 engine (local/demo). **Read-only, off-limits.** |
| `data_demo.py` | Read-only demo backend |
| `supabase_client.py` | Client singletons — **thread-local** `_authed_client` / `get_client`; `pg_connect` for bulk SQL |
| `auth.py` | Access-code gate + sign-in/up + demo entry (branded login) |
| `compositions_scraper.py` | ISIN → factsheet geo+sector; `_yfinance_sector_fallback` / `lookup_yfinance_info` now route through `prices.*` (requests); `_parse_geo_input` (manual geo) |
| `theme.py` (`va1theme`) | CSS design system + Plotly styling. **Version-hardened tab CSS — keep it.** |
| `daily_update.py` | Price update job (used by the boot auto-refresh; `data.*` → active backend) |
| `etf_compositions.json` | Curated per-ETF geo/sector (monthly refresh) |
| `demo_data.json` | Frozen demo dataset |
| `requirements.txt` | **streamlit==1.57.0 pinned · requests · NO yfinance/curl_cffi** |
| `db/schema.sql` | Postgres schema (paste into Supabase SQL editor) |
| `SAAS/deploy.sh` | Orphan-branch deploy prep (prints the `git push`) |

---

## 4. Feature set (unchanged from the pre-crash good version)

- Multi-portfolio, multi-asset (ETF+stock), multi-currency (FX per date, cached).
  ISIN mandatory for a brand-new asset. Sold/deleted assets vanish from holdings
  views but keep their ledger + realized P&L.
- **VL / unit value** = time-weighted, base 100 at inception (neutralises flows).
  **Total Return** = money-weighted `(NAV − net invested) / net invested`. A ~5%
  gap between the two is NORMAL (TWR vs MWR), not a bug.
- Prices = adjusted close; forward-filled at source for foreign-market holidays;
  uniform inception = `max(Settings date, first tx)`.
- **Price history capped at 5 years** (`MAX_HISTORY`), the trade-date picker is
  blocked to `[today−5y, today]` (recomputed daily), with an English warning.
- Pro tab (all sub-tabs). Sector/Geo look-through: curated JSON → factsheet
  (requests/pdfplumber) → Yahoo quoteSummary fallback → Unknown. Optional manual
  geo at asset entry (persisted per-user in Postgres `meta`).
- Custom benchmark ticker; calendar heatmap month = last-biz-day-prev → last-biz-day
  (a month shows only if both real month-ends exist).
- Demo: 8 EUR ETFs, ~1 year, read-only.

---

## 5. Deploy runbook (ALPHA)

```bash
cd /Users/gabrielpeix/Documents/GPCP/DashBoard
git checkout saas
./SAAS/deploy.sh            # refreshes compositions, builds orphan 'deploy', prints the push
```
Then (owner runs — the assistant cannot push):
```bash
git push -f "https://SadSlicer:<FRESH_PAT>@github.com/SadSlicer/gpcp-dashboard.git" deploy:main
```
Then on Streamlit Cloud: **Manage app → ⋮ → Reboot app**, wait for the **rebuild**
to finish (deps reinstall), then hard-refresh (`Cmd+Shift+R`). Confirm
`GPCP build=alpha` in the logs.

**Verify any change headlessly before deploy:**
```bash
.venv/bin/python -m py_compile app.py pro.py prices.py data_postgres.py \
    compositions_scraper.py supabase_client.py theme.py
.venv/bin/python - <<'PY'
from streamlit.testing.v1 import AppTest
at = AppTest.from_file("app.py", default_timeout=180)
at.session_state["__demo_mode"] = True
at.run()
print("exceptions:", len(at.exception), "errors:", len(at.error))   # expect 0 0
PY
```
Headless tests catch Python exceptions but **NOT** CSS/DOM/browser rendering or
the Cloud-container segfaults — the owner must eyeball the deployed app (reload /
re-login / Refresh / Pro tab) after deploy.

---

## 6. Rebuild from ZERO (fresh Supabase + fresh Streamlit Cloud)

1. **Supabase project:** create it. In SQL Editor, run `db/schema.sql` (tables
   `app_user_profile`, `portfolios`, `current_portfolio`, `holdings`, `prices`,
   `transactions`, `fx_rates`, `meta`, all with RLS `user_id = auth.uid()`).
2. **Secrets** (Streamlit Cloud → App Settings → Secrets, and locally in
   `.streamlit/secrets.toml`, gitignored):
   ```toml
   SUPABASE_URL          = "https://<ref>.supabase.co"
   SUPABASE_ANON_KEY     = "eyJh…"      # anon key only, never service_role
   SUPABASE_DB_HOST      = "db.<ref>.supabase.co"
   SUPABASE_DB_PASSWORD  = "<db password>"
   ACCESS_CODE           = "<rotated gate code>"
   ```
3. **Code:** the `saas` branch tree at tag `alpha` is the source of truth. Key
   invariants when reconstructing: keep the 6 fixes in §1; `requirements.txt` as in
   §2 (no yfinance/curl_cffi); `prices.py` requests-based; thread-local sessions +
   Supabase clients; bare-mode gates.
4. **Streamlit Cloud app:** deploy from `SadSlicer/gpcp-dashboard` `main`, set
   **Python 3.12**, paste secrets. First run → enter ACCESS_CODE → create your
   account. Promote to admin in Supabase:
   ```sql
   UPDATE app_user_profile SET is_admin = TRUE
   WHERE user_id = (SELECT id FROM auth.users WHERE email = 'YOUR@EMAIL.COM');
   ```
5. **Migrate data (optional):** `migrate_to_supabase.py` pushes a local sqlite
   portfolio into Postgres under your admin user_id.
6. **Deploy** via §5.

---

## 7. Known limitations (accepted)

- Free tier: app **sleeps after ~7 days** idle (wakes in ~30 s — not a crash, and
  it no longer segfaults on wake). 1 CPU / 1 GB shared — heavy concurrent load is
  the ceiling; the §1.4 bare-mode gate is what keeps it under that ceiling.
- Scroll over Plotly charts can swallow the wheel (cosmetic; several fixes tried
  and reverted).
- Yahoo mutual-fund (`0P…`) NAV lags a few days — normal, not a gap.
- No server cron on free tier → prices update on session load (auto-refresh) and
  via the **Refresh & Save** button; price history self-heals gaps on load.

---

## 8. If it segfaults again

1. Get the **full log** (Manage app → logs). Look for `GPCP build=alpha` (confirms
   the live build) and where the last output is before `Segmentation fault`.
2. It is almost always a **native lib** (uncatchable). Prime suspects, in order:
   a **re-added yfinance/curl_cffi**; a **shared** network client (requests/httpx)
   across threads; heavy work running in **bare mode**; an unpinned native wheel
   (numpy/pandas/pyarrow) — pin it to a version that BOTH fetches AND boots on
   Cloud (can't be validated from macOS — only shows on the Linux container).
3. Reproduce with the previously-crashing actions: reload, re-login, Refresh, open
   the Pro tab. See `memory/saas-python-version-segfault.md` for the full history.
