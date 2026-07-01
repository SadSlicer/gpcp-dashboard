# GPCP Dashboard — Runbook de déploiement (branche `saas`)

> Version finale opérationnelle. Le backend cloud (`data_postgres.py`) est
> complet, cloud-natif, et **testé bout-en-bout contre Supabase live**
> (propagation JWT + RLS + isolation cross-tenant + `compute_snapshot` /
> `compute_vl_series` vérifiés exacts). Il reste 3 actions que **toi seul**
> peux faire : fournir le mot de passe DB, lancer la migration, pousser sur
> GitHub. Ce fichier les détaille.

---

## ✅ Ce qui est déjà fait et vérifié (sur `saas`, non commité jusqu'à ton OK)

- `data_postgres.py` — cloud-natif complet. `compute_snapshot`,
  `compute_vl_series`, `price_history_in_portfolio_currency` re-implémentés
  ligne-à-ligne (prouvés code-identiques à `data_sqlite`). Zéro monkey-patch.
- **Chaîne d'auth corrigée** (bug critique trouvé) : chaque requête cloud
  porte désormais le JWT de l'utilisateur (`supabase_client.get_user_client()`),
  sinon RLS renvoyait 0 ligne pour tout le monde. Isolation par utilisateur +
  refresh automatique du token avant expiration.
- `data.py` — routing cloud↔sqlite réactivé (fallback sqlite si pas d'auth).
- `migrate_to_supabase.py` — script de migration sqlite → Postgres (ci-dessous).
- App démarre proprement (`streamlit run app.py`, HTTP 200, zéro traceback).
- Audit de complétude : toutes les fonctions `data.X` utilisées par l'UI
  existent dans `data_postgres`.

---

## 1. Pré-requis côté Supabase (déjà fait, à vérifier)

- Projet `Portfolio DashBoard` (ref `hthtdkvhzwpvhgzwhuqg`) créé.
- `db/schema.sql` exécuté (8 tables + RLS + trigger `on_auth_user_created`).
- Email confirmation désactivée (Auth → Providers → Email → "Confirm email" OFF)
  — sinon le signup ne renvoie pas de session immédiate.

---

## 2. Secrets (Streamlit Cloud → Settings → Secrets)

Copie le contenu de ton `.streamlit/secrets.toml` local :

```toml
SUPABASE_URL          = "https://hthtdkvhzwpvhgzwhuqg.supabase.co"
SUPABASE_ANON_KEY     = "eyJh..."                 # clé anon (publique, OK)
SUPABASE_DB_HOST      = "db.hthtdkvhzwpvhgzwhuqg.supabase.co"
SUPABASE_DB_PASSWORD  = "<TON mot de passe DB Supabase>"   # ⚠️ à fournir
ACCESS_CODE           = "gpcp-2026-private"        # rotatable
```

> `SUPABASE_DB_PASSWORD` n'est PAS utilisé par le runtime de l'app ni par la
> migration (on passe par l'API REST + JWT). Il n'est requis que si un jour
> tu veux des connexions Postgres brutes (`supabase_client.pg_connect()`).
> Tu peux l'omettre pour l'instant.

---

## 3. Déployer sur Streamlit Cloud

Le repo public ne doit contenir QUE l'état courant, **sans l'historique**
(les branches `main`/`va` contiennent des `.db` perso dans de vieux commits).
On pousse donc une **branche orpheline**.

### 3a. Helper script (recommandé)

```bash
./deploy.sh
```

`deploy.sh` (fourni) :
1. vérifie qu'aucun fichier sensible n'est suivi,
2. crée une branche orpheline `deploy` à partir de l'état courant de `saas`,
3. commit « Public deploy » sans historique,
4. te montre la commande de push exacte (il ne pousse PAS tout seul).

### 3b. Ou à la main

```bash
git remote add origin https://github.com/SadSlicer/gpcp-dashboard.git  # une fois
git checkout --orphan deploy
git rm -rf --cached portfolios 2>/dev/null || true   # double sécurité
git add -A
git commit -m "Public deploy"
git push -f origin deploy:main
git checkout saas        # revenir bosser sur saas
```

### 3c. Brancher l'app

1. https://share.streamlit.io → **New app** → repo `SadSlicer/gpcp-dashboard`,
   branche `main`, fichier `app.py`.
2. **Advanced settings → Secrets** : colle le bloc de la section 2.
3. Deploy. À la première visite : code d'accès → **Créer un compte** avec ton
   vrai email admin.

---

## 4. Te promouvoir admin (Supabase → SQL Editor)

```sql
UPDATE app_user_profile SET is_admin = TRUE
WHERE user_id = (SELECT id FROM auth.users WHERE email = 'YOUR_ADMIN_EMAIL');
```

---

## 5. Migrer tes données locales (GPCP / TEST / BackTest)

Une fois ton compte admin créé (en ligne OU en local), depuis ta machine :

```bash
.venv/bin/python migrate_to_supabase.py
```

- Te demande email + mot de passe (le compte que tu viens de créer).
- Lit `portfolios/_registry.json` + chaque `portfolio_<id>.db`.
- Pousse portfolios, holdings, transactions, prices, fx_rates, meta sous ton
  `user_id` via l'API REST authentifiée (RLS l'accepte).
- **Idempotent** : ré-exécutable sans dupliquer (il remplace les rows du
  portfolio ciblé avant de réinsérer).

Vérifie ensuite dans Supabase → Table Editor → `transactions` que tes lignes
sont là, puis recharge l'app : tes portfolios apparaissent.

---

## 6. Tester en local avant de déployer (optionnel mais conseillé)

`secrets.toml` présent → SaaS mode auto-actif.

```bash
launchctl kickstart -k gui/$(id -u)/com.gpcp.dashboard.server   # ou ./run.sh
```

→ http://localhost:8501 → code d'accès `gpcp-2026-private` → crée un compte de
test → ajoute une transaction → vérifie dans Supabase. Pour repasser en V15
pur (sans auth) : renomme temporairement `.streamlit/secrets.toml`.

---

## 7. Limites free tier (rappel)

- Streamlit Cloud : app dort après 7 j d'inactivité (réveil ~10 s), 1 GB RAM.
- Supabase free : 500 MB Postgres, 50k MAU/mois, 5 GB egress/mois.
- Yahoo Finance : limites par IP (Streamlit Cloud partage des IP — OK en usage
  perso).

---

## 8. Rollback (VA15 jamais touchée)

```bash
git checkout va            # → VA15 local pur, intact
git checkout va15 -- .     # restaurer VA15 par-dessus n'importe quelle branche
```
