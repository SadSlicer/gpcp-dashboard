# SAAS Deployment — MAJ / Handoff

> Document à donner à une nouvelle session Claude Code pour reprendre
> le déploiement multi-tenant. Lis ce fichier en premier.

## 🚨 RÈGLE ABSOLUE : NE PAS TOUCHER À VA15

L'utilisateur tient à conserver **VA15** (sa version locale pure Streamlit, qu'il utilise tous les jours).

**Ne JAMAIS toucher à** :
- Branche `va` (= état VA15)
- Tag `va15` (= snapshot gelé)
- `main` + tag `v15`
- Le dossier `portfolios/` local (contient les vraies données GPCP / TEST)

**Travailler UNIQUEMENT sur** :
- Branche `saas` (= déploiement public WIP)
- Fichiers spécifiques au déploiement : `data_postgres.py`, `auth.py`, `supabase_client.py`, `db/schema.sql`, `SAAS/*`

Rollback safe :
```bash
git checkout va                # → VA15 (rien n'a changé là-bas)
git checkout va15 -- .         # → restaurer VA15 sur n'importe quelle branche
```

---

## 🎯 Objectif global

Déployer GPCP Dashboard en **public + multi-user gratuit** :
- Hosting : Streamlit Community Cloud (free, deploy depuis GitHub)
- DB : Supabase Postgres (free 500 MB, auth, RLS)
- Auth : Supabase Auth (email + bcrypt)
- Code d'accès global (rotation par admin)
- Chaque user voit UNIQUEMENT ses portfolios

Admin = `YOUR_ADMIN_EMAIL` (a déjà créé son compte côté Supabase).

---

## ✅ Ce qui marche déjà (commité sur `saas`)

### Infra
- ✅ Supabase project `Portfolio DashBoard` créé (ref `hthtdkvhzwpvhgzwhuqg`)
- ✅ Schéma SQL exécuté → 8 tables + RLS + trigger `on_auth_user_created`
- ✅ Email confirmation **désactivée** dans Supabase Auth (pour les tests)
- ✅ Repo GitHub créé : https://github.com/SadSlicer/gpcp-dashboard (vide pour l'instant)

### Code
- ✅ `.gitignore` exclut `portfolios/*.db`, `_registry.json`, `.streamlit/secrets.toml`, `.env`, `node_modules/`
- ✅ `.streamlit/secrets.toml` (gitignoré) configuré localement avec URL + anon key + access code
- ✅ `requirements.txt` ajoute `supabase>=2.5`, `psycopg2-binary>=2.9`, `bcrypt>=4.1`, `python-dotenv>=1.0`
- ✅ `supabase_client.py` : helper connexion + `is_saas_mode()`
- ✅ `auth.py` : flow gate code → signin/signup tabs → set `st.session_state["__saas_user"]`
- ✅ `app.py` : appelle `auth.require_auth()` avant `st.set_page_config` si `is_saas_mode()`
- ✅ Le flow gate → signup → login → dashboard a été **testé bout en bout**, marche

### Architecture data
- ✅ `data.py` (ancien V15) renommé en `data_sqlite.py` (VA15 intact)
- ✅ Nouveau `data.py` est un dispatcher avec `__getattr__` qui route vers l'actif backend
- ✅ **Routing cloud RÉACTIVÉ** (`_active()` route vers `data_postgres` si SaaS mode + user authentifié, sinon `data_sqlite`)
- ✅ **`data_postgres.py` cloud-natif COMPLET** — `compute_snapshot`, `compute_vl_series` et `price_history_in_portfolio_currency` re-implémentés ligne-à-ligne (vérifiés code-identiques à `data_sqlite`), plus AUCUN monkey-patch. Seuls `_ds.*` restants : constantes (`DEFAULT_INCEPTION`, `CURRENCY_SYMBOL`, `COMMON_CURRENCIES`), `PortfolioStatic`, helpers purs (`trading_day_rangebreaks`) et sous-système FX (`fx_rate`, `prefetch_fx_window` — persistance Postgres = phase-2).

---

## ✅ FAIT (session du 2026-06-10) — backend cloud complet + testé

### Ce qui a été livré
- **`compute_snapshot`, `compute_vl_series`** re-implémentés cloud-natifs (copie
  ligne-à-ligne, prouvés **code-identiques** à `data_sqlite` via `inspect`).
  Plus AUCUN monkey-patch.
- **`price_history_in_portfolio_currency`** : le MAJ disait qu'on pouvait le
  garder via `_ds.` — **c'était faux** (son corps fait des lookups
  `current_portfolio_currency()`/`load_static()`/`ASSETS` qui se liaient aux
  globals sqlite → il aurait lu les données sqlite). Re-implémenté cloud-natif.
- **`ROOT` + `YF_TICKER_BY_ISIN`** ajoutés (l'UI les utilise via le dispatcher ;
  `YF_TICKER_BY_ISIN` est maintenu isin→ticker dans `_sync_module_globals`).
- **🔴 BUG CRITIQUE corrigé — propagation JWT / RLS** : `supabase_client.get_client()`
  était un singleton anon partagé. Conséquences : (1) RLS (`user_id = auth.uid()`)
  voyait un uid NULL → **toutes** les lectures cloud revenaient vides ; (2) risque
  de **fuite cross-tenant** (un client mutable partagé entre users). Corrigé :
  - `supabase_client` : `new_anon_client()` (auth, frais) + `_authed_client(token)`
    (caché par token, porte le JWT user) + `get_user_client()` (lit le token
    depuis `session_state`).
  - `auth.py` : stocke `_access_token`/`_refresh_token`/`_expires_at` au login,
    lit le profil avec le client authentifié, **rafraîchit le token** avant
    expiration (`_ensure_fresh_session()` appelé dans `require_auth`).
  - `data_postgres._sb()` → `get_user_client()`.

### Règle d'or (respectée)
`data_postgres.py` n'appelle **JAMAIS** `_ds.something` pour des fonctions qui
touchent aux données. Les seuls `_ds.*` restants : constantes (`ROOT`,
`DEFAULT_INCEPTION`, `CURRENCY_SYMBOL`, `COMMON_CURRENCIES`), `PortfolioStatic`,
helpers purs (`trading_day_rangebreaks`) et le sous-système FX (`fx_rate`,
`prefetch_fx_window` — persistance Postgres = phase-2).

### Tests passés (contre Supabase **live**)
19 checks ✅ : user vierge → `[]`, auto-create portfolio, snapshot vide cohérent
(NAV 0 / vl 100), register/deposit/BUY passent RLS WITH CHECK, `compute_snapshot`
exact (NAV 1040 = 20×12 + 800 cash), `compute_vl_series` colonnes OK,
**isolation cross-tenant prouvée** (user2 ne voit pas les portfolios de user1).
App démarre sans traceback (HTTP 200). Audit complétude : toutes les `data.X`
de l'UI résolvent dans `data_postgres`.

---

## 🗺️ Plan détaillé pour la nuit

### Étape 1 — Reset le routing (déjà fait, à vérifier)

Dans `data.py` la fonction `_active()` retourne toujours `data_sqlite` pour l'instant. Une fois `data_postgres.py` solide, retirer le `return data_sqlite` en début de fonction pour réactiver le routing conditionnel.

### Étape 2 — Re-implémenter `_cash_walk` (déjà fait — vérifier)

✅ Fait dans la dernière itération. Les 4 clés sont présentes. Comparer ligne par ligne avec `data_sqlite._cash_walk` (lignes 667-723 de data_sqlite.py).

### Étape 3 — Re-implémenter `compute_snapshot`

Copier le corps de `data_sqlite.compute_snapshot` (chercher `def compute_snapshot` dans `data_sqlite.py`, ~lignes 1450-1750) dans `data_postgres.py`. Remplacer dans la copie :
- `_all_transactions()` → `_all_transactions()` (déjà dans data_postgres, ok)
- `shares_held_as_of()` → `shares_held_as_of()` (déjà dans data_postgres, ok)
- `current_portfolio_currency()` → `current_portfolio_currency()` (déjà dans data_postgres, ok)
- `_cash_walk()` → `_cash_walk()` (déjà dans data_postgres, ok)
- `get_inception_date()` → `get_inception_date()` (déjà dans data_postgres, ok)
- `fx_rate()` → utiliser celle ré-exportée depuis `_ds.fx_rate` pour l'instant (à terme : implem cloud avec cache Postgres)
- `ASSETS` → `ASSETS` (la liste locale du module)
- Toute référence à `static` reste passée en argument

REMPLACER la fonction `compute_snapshot` wrappée par monkey-patch (lignes ~640-670 de data_postgres.py).

### Étape 4 — Re-implémenter `compute_vl_series`

Pareil : copier le corps de `data_sqlite.compute_vl_series` (chercher dans data_sqlite.py vers ligne 1570-1700), adapter les appels internes au module cloud.

### Étape 5 — Tests progressifs

1. `data._active_backend_name()` retourne `data_postgres` quand SaaS mode + user logué
2. `data.list_portfolios()` retourne `[]` pour un user vierge
3. `data.current_portfolio()` auto-crée "My Portfolio"
4. `data.compute_snapshot(load_static(), {}, load_price_history())` retourne un snapshot vide cohérent (NAV=0, vl=100, etc.)
5. Créer une transaction BUY via l'UI → vérifier insertion en DB Supabase via `SELECT * FROM transactions` côté SQL Editor
6. Switcher de portfolio → vérifier que les données changent
7. Logout / re-login → données persistantes

### Étape 6 — Réactiver le routing

Dans `data.py`, supprimer la ligne :
```python
return data_sqlite  # TEMPORARY rollback
```
en début de `_active()`. Garder le reste tel quel.

### Étape 7 — Migration des données GPCP + TEST vers Postgres (admin only)

Créer `migrate_to_supabase.py` qui :
1. Lit ton `portfolios/portfolio_GPCP.db` local
2. Demande tes credentials Supabase + ton email admin
3. Push toutes les rows (portfolios, holdings, transactions, prices, fx_rates, meta) avec `user_id = TON_UUID` dans Postgres
4. Idem pour `portfolio_TEST.db`
5. Tu lances UNE FOIS depuis ta machine : `.venv/bin/python migrate_to_supabase.py`

Squelette :
```python
import sqlite3, sys
from supabase_client import pg_connect
import getpass

email = input("Ton email admin Supabase : ")
# Récupérer le UUID via SELECT id FROM auth.users WHERE email = ?
# (ou demander à l'utilisateur de le coller manuellement)
admin_uid = input("Ton user_id (UUID, copier depuis Supabase) : ")

for slug, dbpath in [("GPCP", "portfolios/portfolio_GPCP.db"),
                     ("TEST", "portfolios/portfolio_TEST.db")]:
    con = sqlite3.connect(dbpath)
    # ... pour chaque table : SELECT ... → INSERT INTO postgres ... avec user_id et portfolio_id
```

### Étape 8 — Promotion admin via SQL

Une fois la migration faite :
```sql
-- Dans Supabase SQL Editor :
UPDATE app_user_profile SET is_admin = TRUE
WHERE user_id = (SELECT id FROM auth.users WHERE email = 'YOUR_ADMIN_EMAIL');
```

### Étape 9 — Deploy Streamlit Cloud

1. Initialiser le repo git remote :
   ```bash
   git remote add origin https://github.com/SadSlicer/gpcp-dashboard.git
   ```
2. ⚠️ NE PAS push la branche `va` ou `main` (contiennent l'historique sqlite avec données perso)
3. Créer une branche orpheline `deploy` qui contient SEULEMENT l'état actuel sans aucune histoire :
   ```bash
   git checkout --orphan deploy
   git rm -rf --cached portfolios  # double safety, gitignore le fait déjà
   git add .
   git commit -m "Initial public deploy"
   git push -u origin deploy:main
   ```
4. Sur https://streamlit.io/cloud → "Deploy an app" → choisir le repo `SadSlicer/gpcp-dashboard`, branche `main`, fichier `app.py`
5. Configurer les Secrets dans Streamlit Cloud (Settings → Secrets) : copier le contenu de `.streamlit/secrets.toml` local
6. Tester l'URL publique

---

## 📁 Fichiers clés

| Fichier | Statut | Rôle |
|---|---|---|
| `app.py` | Modifié pour appeler `auth.require_auth()` | UI principal V15 + auth gate au début |
| `data.py` | Dispatcher | Route vers sqlite ou postgres |
| `data_sqlite.py` | **NE PAS MODIFIER** | V15 sqlite, copié de `data.py` original |
| `data_postgres.py` | **À RE-IMPLÉMENTER** | Backend cloud, ~70% fait mais avec monkey-patches à virer |
| `supabase_client.py` | OK | Connexion + secrets + is_saas_mode |
| `auth.py` | OK | Gate code + Supabase signin/signup UI |
| `db/schema.sql` | OK + exécuté | Schéma Postgres |
| `.streamlit/secrets.toml` | OK (gitignored) | Secrets locaux |
| `SAAS/CLAUDE.md` | Doc opérationnelle | Stack overview |
| `SAAS/MAJ.md` | **Ce fichier** | Handoff session-à-session |

---

## 🧪 Comment tester localement pendant le dev

1. `secrets.toml` est configuré → SaaS mode actif automatiquement
2. Lancer le serveur : `launchctl kickstart -k gui/$(id -u)/com.gpcp.dashboard.server`
3. Aller sur http://localhost:8501
4. Hard reload (`Cmd+Shift+R`)
5. Code d'accès : `gpcp-2026-private`
6. Tu peux logout via le bouton "Verrouiller la session" en bas du formulaire login si besoin

Pour **revenir au mode V15 pur** (sans auth) le temps de debug :
- Temporairement renommer `.streamlit/secrets.toml` → `secrets.toml.bak`
- `is_saas_mode()` retournera False → auth bypassée → dashboard V15 normal
- Renommer en arrière pour réactiver SaaS

---

## 📌 Secrets à transmettre à Streamlit Cloud lors du deploy

Contenu de `.streamlit/secrets.toml` (à copier-coller dans l'UI Settings → Secrets de Streamlit Cloud) :
```toml
SUPABASE_URL          = "https://hthtdkvhzwpvhgzwhuqg.supabase.co"
SUPABASE_ANON_KEY     = "eyJh..."                # voir le fichier local
SUPABASE_DB_HOST      = "db.hthtdkvhzwpvhgzwhuqg.supabase.co"
SUPABASE_DB_PASSWORD  = "<à demander à l'admin Gabriel>"
ACCESS_CODE           = "gpcp-2026-private"      # rotatable
```

L'utilisateur devra te donner le `SUPABASE_DB_PASSWORD` (qu'il n'a pas encore partagé — c'est celui qu'il a choisi à la création du projet Supabase).

---

## ⏱️ Estimation effort

- Étape 3 (compute_snapshot) : 1h
- Étape 4 (compute_vl_series) : 30 min
- Étape 5 (tests + fix divers) : 1-2h
- Étape 6 (réactivation routing) : 5 min
- Étape 7 (migration script) : 1-2h
- Étape 8 (promotion admin) : 1 min
- Étape 9 (deploy Streamlit Cloud) : 1h

**Total : ~5-7h** de travail focalisé.

---

## 💬 Message d'ouverture pour la nouvelle session

Coller ceci au début de la nouvelle conversation Claude Code :

> Continue le déploiement SaaS du dashboard GPCP. Lis d'abord `SAAS/MAJ.md`
> qui contient le plan détaillé. **NE PAS toucher à la branche `va` ni au
> tag `va15`** — VA15 local doit rester intact. Travailler uniquement sur
> la branche `saas`. La tâche principale est de re-implémenter
> `data_postgres.py` de manière cloud-native (pas de monkey-patch sur
> `data_sqlite`), puis déployer sur Streamlit Cloud. Commence par lire le
> MAJ.md, puis annonce-moi le plan avant de coder.

---

## 🏁 État final (2026-06-10)

- Backend cloud `data_postgres.py` **complet, cloud-natif, testé live** ✅
- Chaîne d'auth JWT/RLS corrigée et vérifiée (isolation cross-tenant) ✅
- Routing cloud↔sqlite **réactivé** (fallback sqlite si pas d'auth) ✅
- `migrate_to_supabase.py` + `deploy.sh` + `SAAS/DEPLOY.md` livrés ✅
- VA15 totalement préservée sur branche `va` (jamais touchée) ✅

### Il reste 3 actions côté Gabriel (voir `SAAS/DEPLOY.md`)
1. **Déployer** : `./deploy.sh` puis `git push -f origin deploy:main`, brancher
   l'app sur Streamlit Cloud + coller les Secrets.
2. **Migrer** : `.venv/bin/python migrate_to_supabase.py` (email + mdp admin).
3. **Promotion admin** : le `UPDATE app_user_profile SET is_admin = TRUE …` SQL.

> Note : le test live a créé quelques comptes jetables `clitest_*@example.com` /
> `clifinal_*@example.com` dans Supabase → Authentication. Inoffensifs
> (isolés par RLS, données supprimées). Supprime-les depuis le dashboard
> Supabase si tu veux faire le ménage (nécessite le service_role, donc UI only).
