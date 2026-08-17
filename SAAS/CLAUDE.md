# GPCP Dashboard — SaaS deployment (branch `saas`)

> Branch: `saas` (forked from VA15). Local pure-Streamlit version is
> preserved on branch `va` (tag `va15`). This branch refactors data
> persistence from local sqlite to Supabase Postgres + adds a global
> access-code gate and per-user authentication.

## 1. The stack

| Layer | Service | Cost |
|---|---|---|
| **App hosting** | Streamlit Community Cloud | Free for public apps |
| **Database** | Supabase Postgres | Free (500 MB, 50k MAU/mo) |
| **Authentication** | Supabase Auth | Included with Supabase free |
| **Source code** | GitHub public repo | Free |
| **Total monthly cost** | — | **0 €** |

## 2. Flow at runtime

```
visitor → https://gpcp-dashboard.streamlit.app
   ↓
[Page 1] "Code d'accès"
   ├─ code == ACCESS_CODE secret? no  → show error, stay on page
   └─ yes → next
   ↓
[Page 2] "Se connecter / Créer un compte"
   ├─ signin → Supabase Auth checks bcrypt'd password
   └─ signup → Supabase creates auth.users row, trigger inserts profile
   ↓
[Dashboard VA15] — identical UI, but data.py reads/writes Supabase
                    with user_id filter (RLS enforces isolation server-side)
```

## 3. Files added on the `saas` branch

```
NEW  requirements.txt   ← +supabase, +psycopg2-binary, +bcrypt, +python-dotenv
NEW  supabase_client.py ← Client singleton + secrets helpers
NEW  auth.py            ← gate + signin/signup UI, require_auth() entry point
NEW  db/schema.sql      ← Postgres schema to paste in Supabase SQL editor
NEW  SAAS/CLAUDE.md     ← this file
MOD  .gitignore         ← excludes portfolios/*.db + secrets files
DEL  portfolios/*.db    ← untracked (production data lives in Postgres)

TODO (next steps, not yet committed):
  - data.py refactor to dual-mode (sqlite local OR postgres cloud)
  - app.py integration: `auth.require_auth()` at the top
  - Migration script: dump local sqlite → insert into Postgres for admin user
  - SAAS/DEPLOY.md operational runbook
```

## 4. Secrets — never commit these

All secrets live in `.streamlit/secrets.toml` (gitignored) locally,
and in **Streamlit Cloud → App Settings → Secrets** in production.

```toml
# .streamlit/secrets.toml  (gitignored)
SUPABASE_URL          = "https://<project-ref>.supabase.co"
SUPABASE_ANON_KEY     = "eyJh..."     # anon/public key (safe to ship to clients)
SUPABASE_DB_HOST      = "db.<project-ref>.supabase.co"
SUPABASE_DB_PASSWORD  = "<DB password chosen at project creation>"
ACCESS_CODE           = "<rotated regularly by admin>"
```

The **service_role key** must NEVER appear in this app (it bypasses RLS).
We only use the `anon` key — RLS policies enforce per-user isolation
server-side.

## 5. Admin first-time setup (you, after deploy)

1. Push the saas branch to GitHub (`origin/main` on `SadSlicer/gpcp-dashboard`).
2. Deploy to Streamlit Cloud, paste the secrets above.
3. Visit the public URL → enter ACCESS_CODE → "Créer un compte" with your
   real email + a strong password.
4. Open Supabase → SQL Editor → run:
   ```sql
   UPDATE app_user_profile SET is_admin = TRUE
   WHERE user_id = (SELECT id FROM auth.users WHERE email = 'YOUR@EMAIL.COM');
   ```
5. Reload the dashboard — you're now admin.
6. Run the migration script (local) to push your `portfolios/portfolio_GPCP.db`
   and `portfolios/portfolio_TEST.db` into Postgres under your admin user_id.

## 6. Local dev keeps working

`data.py` will be dual-mode:
- If `SUPABASE_URL` is set in env / secrets → Postgres backend
- Otherwise → sqlite backend (current V15 behavior)

So `git checkout va && ./run.sh` still works exactly like before, no
secrets needed.

## 7. Rollback

```bash
git checkout va             # → VA15 local pure (untouched)
git checkout va15 -- .      # restore VA15 over any branch
git checkout main           # → V15 raw
```

The `saas` branch never modifies `main` or `va`. Tagged states:
- `va15` — current local production
- `v15`  — functional baseline

## 8. Limitations of the free tier

- Streamlit Cloud free apps **sleep after 7 days of inactivity** (wake on
  first visit, takes ~10 s)
- Streamlit Cloud free apps run with **1 GB RAM** — fine for this app
- Supabase free tier: **500 MB Postgres + 50 k monthly active users +
  5 GB egress/mo** — comfortably enough for personal use with a few friends
- Yahoo Finance daily limits are per-IP — Streamlit Cloud shares IPs so
  heavy concurrent refreshes could hit limits (in practice fine)
