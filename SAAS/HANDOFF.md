# GPCP Dashboard — Handoff pour reprendre dans une nouvelle conversation

> Donne ce fichier à une nouvelle session Claude Code (« Lis `SAAS/HANDOFF.md`
> en premier »). Il contient l'état actuel, l'architecture, le workflow de
> déploiement et tout ce qu'il faut pour continuer sans rien casser.
> **Aucun secret n'est dans ce fichier** (volontairement). L'utilisateur parle
> français → répondre en français.

---

## 0. Message d'ouverture à coller dans la nouvelle conversation

> Reprends le déploiement SaaS du dashboard GPCP. Lis d'abord
> `SAAS/HANDOFF.md`. **NE TOUCHE PAS** à la branche `va` ni au tag `va15`
> (VA15 local intact). Travaille uniquement sur la branche `saas`. L'app est
> déjà **en ligne et fonctionnelle** sur Streamlit Cloud + Supabase. Pour tout
> changement : code sur `saas`, reconstruis la branche orpheline `deploy`,
> donne-moi la commande `git push` (tu ne peux pas pousser toi-même), je
> déploie. Voici ce que je veux corriger/ajouter : …

---

## 1. Règles absolues

- **Ne JAMAIS toucher** : branche `va`, tag `va15` (VA15 = version locale pure
  sqlite, utilisée tous les jours), `main`/`v15`, ni `data_sqlite.py`
  (read-only, c'est V15). Le dossier `portfolios/` local = vraies données.
- **Travailler uniquement sur la branche `saas`.**
- Owner parle **français**.

## 2. État actuel (en ligne et fonctionnel ✅)

- **App publique** : Streamlit Community Cloud, URL host
  `gpcp-dashboard-uqjvyeg9auka2n9umb3wgw.streamlit.app`.
- **Repo GitHub** : `SadSlicer/gpcp-dashboard` (public). La branche `main` du
  repo = ce que Streamlit déploie (une **branche orpheline**, 1 commit, sans
  historique — voir §5).
- **Backend** : Supabase Postgres (ref `hthtdkvhzwpvhgzwhuqg`), RLS par user,
  Auth email/mot de passe. **Admin** = le compte email de l'owner (déjà créé,
  données GPCP migrées). Code d'accès global (gate) rotaté par l'admin.
- **Branche de travail** : `saas` (HEAD = `b5977cd` à la rédaction).
- **Point de restauration** : branche locale **`rollback`** = dernière version
  qui marche (voir §6).

## 3. Architecture (l'essentiel)

- `data.py` = **dispatcher** : `__getattr__` route vers `data_postgres` si
  (SaaS mode + user authentifié) sinon `data_sqlite` (fallback local). Tout le
  code UI fait `import data` puis `data.X()`.
- `data_postgres.py` = backend cloud (Supabase via REST + JWT). **Self-contained**
  (pas de monkey-patch de `data_sqlite`). Re-implémente `compute_snapshot`,
  `compute_vl_series`, `nav_series`, `_cash_walk`,
  `price_history_in_portfolio_currency`, FX cloud (`fx_rate` sur table
  `fx_rates`), etc.
- **Auth** (`auth.py` + `supabase_client.py`) : chaque requête data porte le
  **JWT de l'utilisateur** via `supabase_client.get_user_client()` (lit le
  token dans `st.session_state["__saas_user"]`). NE JAMAIS utiliser le client
  anon pour des données (RLS renverrait 0 ligne). Token rafraîchi avant
  expiration dans `require_auth()`.
- **État par-session** : `ASSETS` / `ISIN_BY_ASSET` / `TICKER_BY_ASSET` /
  `YF_TICKER_BY_ISIN` dans `data_postgres` sont des **proxys liés à
  `st.session_state`** (PAS des globals partagés), sinon des users concurrents
  se clobberaient dans le même process Streamlit. Hors session (cron/tests) →
  fallback process-local (détecté via `get_script_run_ctx()`).
- **Fichiers clés** : `app.py` (UI principale + onglets), `pro.py` (sous-onglets
  Pro), `prices.py` (Yahoo), `compositions_scraper.py` (secteur/géo ETF),
  `db/schema.sql` (schéma Postgres), `migrate_to_supabase.py` (migration
  sqlite→Postgres, one-shot).

## 4. Méthodologie / décisions produit déjà implémentées

- **Total Return par actif** = `cours actuel / coût d'achat MOYEN pondéré − 1`
  (en devise du portefeuille, FX inclus). `avg_cost_by_asset()` =
  Σ(prix×parts des BUY)/Σ(parts BUY). Utilisé partout (Positions, snapshot,
  Pro → Attribution).
- **VL (base 100)** = performance **time-weighted**, basée NAV, neutralisant
  les flux (unitisée). `NAV = Σ(actifs) + cash`. La VL graphe = VL table =
  header = `compute_vl_series` (même série). Les gains d'un actif **vendu**
  sont conservés (figés en cash à la vente, NAV-neutre).
- **Historique des prix** : série « augmentée » = `[prix d'achat, 1ʳᵉ clôture,
  clôtures…]`, une ligne « · achat » par BUY (`augmented_price_history()`).
  Chaque actif clippé à sa **date d'achat** (`load_price_history` met NaN avant).
- **NAV inclut le cash** dans les 3 tableaux d'historique (colonne Cash).
- **Ventes** : table « Ventes réalisées — P&L » + colonne « Return vente » sur
  la ligne SELL de l'historique. Vente totale → portefeuille all-cash géré
  (plus de crash). `sell_pnl_rows()` calcule le P&L réalisé vs coût moyen.
- **Suppression d'actif** : supprimer la dernière transaction d'un actif le
  retire **partout** (cascade holding+prix ; orphelins exclus de `ASSETS`).
- **Risk metrics** : EAR/EDR géométrique (rf→daily = `(1+rf)^(1/252)−1` ;
  Sharpe/Sortino annualisent la moyenne via EAR ; vol = σ·√252). Rendement
  annualisé = EAR arithmétique `(1+r̄)^252−1`.
- **Diversification score** = `(1 − ρ̄ pondérée) × 100`, ρ̄ pondérée par les
  poids `Σ wᵢwⱼρᵢⱼ / Σ wᵢwⱼ`.
- **Sector/Geo** : live Yahoo pour TOUT actif — actions via `.info`
  (secteur+pays), ETF via `funds_data.sector_weightings` (secteur). JSON curé
  (7 ETF) gardé pour le géo factsheet.
- **Heures** : tout en **Europe/Paris** (serveur en UTC).
- **Refresh mensuel des expos** : GitHub Action
  `.github/workflows/refresh-compositions.yml` (le 15 du mois) → commit le
  `etf_compositions.json` → redéploie.

## 5. Workflow de déploiement (⚠️ LIRE — c'est le cœur)

**TL;DR — une seule commande : `./SAAS/deploy.sh`.** Elle refait les compositions
ETF (factsheets live), construit la branche `deploy` **via `git commit-tree`
depuis l'arbre `saas`** (le working tree n'est JAMAIS touché — fini le fichier
non-suivi avalé/supprimé par l'ancien `git add -A`), vérifie l'absence de
secrets, sauvegarde `rollback`, puis **affiche** la commande `git push` à lancer
toi-même. Détail manuel équivalent :

1. Coder + commit sur `saas`.
2. Reconstruire la branche orpheline `deploy` (état courant, sans historique) :
   ```bash
   git config user.name "SadSlicer"
   git config user.email "SadSlicer@users.noreply.github.com"   # noreply = pas d'email perso publié
   git branch -D deploy 2>/dev/null || true
   git checkout --orphan deploy
   git add -A && git commit -m "GPCP Dashboard — public deploy"
   git checkout saas
   ```
   `.gitignore` exclut déjà `*.xlsm/*.xlsx/*.docx/portfolios/*.db/_registry.json/.streamlit/secrets.toml/.env`.
   **Toujours vérifier** qu'aucun secret/donnée perso n'est dans le bundle :
   `git ls-tree -r --name-only deploy | grep -iE '\.xlsm|\.db$|secrets|\.env'` → doit être vide.
3. **C'EST L'UTILISATEUR QUI POUSSE** — l'assistant NE PEUT PAS : le classifier
   auto-mode **bloque tout push d'un repo-tree vers un remote public externe**
   (exfiltration). Donne-lui la commande (token = PAT GitHub avec scopes
   **`repo` + `workflow`**, le scope `workflow` est requis car le bundle
   contient `.github/workflows/`) :
   ```bash
   cd /Users/gabrielpeix/Documents/GPCP/DashBoard && git push -f "https://SadSlicer:<TOKEN>@github.com/SadSlicer/gpcp-dashboard.git" deploy:main
   ```
4. Streamlit redéploie au push. **Reboot** si nouvelle dépendance
   (Manage app → ⋮ → Reboot app). Puis `Cmd+Shift+R`.
5. **Vérifier ce qui est déployé via l'API GitHub** (pas `raw.githubusercontent`
   qui a ~5 min de cache CDN) :
   `curl -s "https://api.github.com/repos/SadSlicer/gpcp-dashboard/contents/app.py?ref=main" | python3 -c "import sys,json,base64;print(base64.b64decode(json.load(sys.stdin)['content']).decode())"`

## 6. Rollback (filet de sécurité)

- Avant un push risqué : `git fetch <repo-url> +main:rollback` (sauve la version
  live actuelle dans la branche locale `rollback`).
- Pour revenir en arrière : l'utilisateur pousse
  `git push -f "https://SadSlicer:<TOKEN>@github.com/SadSlicer/gpcp-dashboard.git" rollback:main`
  puis reboot. `rollback` actuel = `595a313`.
- Les **données Supabase ne sont jamais touchées** par un deploy/rollback (seul
  le code change).

## 7. Vérifier/tester contre Supabase live (hors Streamlit)

Pattern utilisé tout au long (nécessite les creds admin de l'owner) :
```python
import supabase_client as sc, data_postgres as dp
r = sc.new_anon_client().auth.sign_in_with_password({"email": EMAIL, "password": PWD})
uid, tok = r.user.id, r.session.access_token
dp._user_id = lambda: uid
dp._sb = lambda: sc._authed_client(tok)
dp._CURRENT_PF_CACHE[uid] = "GPCP"      # ou le portfolio voulu
for c in (dp._HOLDINGS_CACHE, dp._TX_CACHE, dp._PF_CACHE, dp._FX_CACHE): c.clear()
dp.ASSETS.clear()
# … appeler dp.load_static() / dp.compute_snapshot(...) / dp.sell_pnl_rows() …
```
- Lancer avec `PYTHONPATH=. .venv/bin/python -c "…"`.
- **Rendu complet headless** (toutes pages, détecte les exceptions) :
  `streamlit.testing.v1.AppTest.from_file("app.py")` + injecter
  `at.session_state["__saas_gate_passed"]=True` et `at.session_state["__saas_user"]={id,email,is_admin,_access_token,_refresh_token,_expires_at}`.
- Filtrer le bruit : `grep -vE "ScriptRunContext|Session state|peewee|yfinance"`.
- Les tests créent des users jetables `cli*@example.com` dans Supabase Auth
  (inoffensifs, RLS-isolés, lignes supprimées en fin de test ; les rows
  `auth.users` restent — suppression manuelle possible côté Supabase).

## 8. Secrets — où ils sont (PAS de valeurs ici)

- Local : `.streamlit/secrets.toml` (gitignoré) → `SUPABASE_URL`,
  `SUPABASE_ANON_KEY` (publique), `SUPABASE_DB_HOST`, `SUPABASE_DB_PASSWORD`,
  `ACCESS_CODE`.
- Prod : Streamlit Cloud → Settings → Secrets (mêmes clés).
- ⚠️ Ne JAMAIS mettre dans le repo : token GitHub, mot de passe DB/compte,
  valeur du code d'accès. Le `service_role` Supabase n'est PAS utilisé (anon +
  RLS uniquement).

## 9. Historique des changements de cette session (du + récent au + ancien)

```
(saas) refresh compositions ETF (factsheets mai) + SAAS/deploy.sh (commit-tree)
(saas) durcissement graphe Allocation (dédup colonnes + to_numeric, anti-crash)
b9e8e87 fix crash/fuite multi-users — clé par-user sur le cache _load_all
b5977cd NAV inclut le cash dans les tableaux + return réalisé sur chaque ligne SELL
e05c86d fix crash vente totale + table « Ventes réalisées » (P&L)
3ce3e6a Total Return sur coût d'achat moyen partout + Attribution FX-cohérente
a8ebc38 état des actifs PAR-SESSION (fix clobbering/crash multi-utilisateurs)
2bbfb33 compute_snapshot garantit toutes les clés de position (fix KeyError 'allocation')
d1a5a79 Attribution mesure chaque actif depuis son prix d'achat exact
8cc7be8 perf depuis le prix d'achat exact (pas la 1ʳᵉ clôture)
77f9b9a fuseau Paris + diversification pondérée + secteur live ETF/actions
befe5a8 Attribution affiche tous les actifs
a973277 clip price history à la période de détention + annualisé EAR
265120f risk metrics EAR/EDR + GitHub Action refresh mensuel
f4c10ed audit cycle de vie actif : suppression cascade, total-return, PDF, sector/geo
faa44f3 ligne de prix d'un nouvel actif depuis l'achat + backfill à l'ajout
3f25096 load_price_history renvoie toujours une colonne par actif (fix KeyError)
ab25bcc fix save nouvel actif (pdfplumber) + auto adjusted-close par date
456d159 scrub email admin des docs + gitignore *.docx
ad8ce4b cache FX cloud-natif (table Postgres fx_rates)
3745554 exclure *.xlsm/*.xlsx du repo (données perso)
cfa7c89 fix KeyError '€' Pro sector/geo (look-through vide)
```

## 10. Nuances connues (PAS des bugs)

- **Perf par actif (coût moyen, money-weighted) ≠ VL portefeuille
  (time-weighted)** : deux méthodologies distinctes, ne somment pas. Le P&L €
  (NAV − net investi) est la ligne de fond money-weighted. Voulu.
- **Géo des ETF non-curés** : Yahoo ne donne pas de répartition pays pour un
  fonds → géo vide pour un nouvel ETF (secteur OK via funds_data). Le JSON curé
  couvre le géo des 7 ETF suivis.
- **Refresh des expos ETF** : la **source de vérité = `./SAAS/deploy.sh`** (re-scrape
  les factsheets à chaque déploiement). La GitHub Action `refresh-compositions.yml`
  (cron le 15) est un **backup** : elle n'a jamais tourné de façon fiable (fichier
  ajouté le 16/06 → 1er cron 15/07) et commite sur `main`, donc un deploy manuel
  l'écrase — c'est pour ça que le refresh est fait au deploy. Les actions
  individuelles sont de toute façon en **live** (yfinance, caché 1j).
- **Free tier** : Streamlit dort après ~7j d'inactivité (réveil ~10s) ;
  Supabase free se met en **pause** après ~1 semaine sans activité (réveil = 1
  clic « Restore » dans le dashboard Supabase).
