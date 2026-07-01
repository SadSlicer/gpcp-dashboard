# GPCP Dashboard — Handoff pour reprendre dans une nouvelle conversation

> Donne ce fichier à une nouvelle session Claude Code (« Lis `SAAS/HANDOFF.md`
> en premier »). Il contient l'état actuel, l'architecture, le workflow de
> déploiement et tout ce qu'il faut pour continuer sans rien casser.
> **Aucun secret n'est dans ce fichier** (volontairement). L'utilisateur parle
> français → répondre en français.

---

## 0. Message d'ouverture à coller dans la nouvelle conversation

> Reprends le déploiement SaaS du dashboard GPCP. Lis d'abord `SAAS/HANDOFF.md`.
> **NE TOUCHE PAS** à la branche `va` ni au tag `va15` (VA15 local intact), ni à
> `main`/`v15`, ni à `data_sqlite.py` (read-only, c'est le moteur V15). Travaille
> uniquement sur la branche `saas`. L'app est **en ligne et fonctionnelle**
> (Streamlit Cloud + Supabase). Pour déployer : `./SAAS/deploy.sh` puis je lance
> le `git push` (tu ne peux pas pousser toi-même). Voici ce que je veux : …

---

## 1. Règles absolues

- **Ne JAMAIS toucher** : branche `va`, tag `va15` (VA15 = version locale sqlite
  pure, utilisée tous les jours), `main`/`v15`, ni `data_sqlite.py` (read-only,
  c'est le moteur V15). Le dossier local `portfolios/` = vraies données.
- **Travailler uniquement sur la branche `saas`.**
- Owner parle **français**. Répondre en français.
- **L'assistant NE PEUT PAS pousser** vers le remote public (le classifier
  auto-mode bloque l'exfiltration d'un repo-tree). → `./SAAS/deploy.sh` construit
  tout et **affiche** la commande `git push` que l'owner lance lui-même.
- Le classifier bloque aussi la **connexion directe à la base de prod**
  (`pg_connect`, cross-user). Pour inspecter des données live : l'owner lance
  `SAAS/diag_vl.py` (voie REST authentifiée), ou ajoute une règle de permission.

## 2. État actuel (en ligne ✅)

- **App** : Streamlit Community Cloud, host
  `gpcp-dashboard-uqjvyeg9auka2n9umb3wgw.streamlit.app`.
- **Repo** : `SadSlicer/gpcp-dashboard` (public). `main` du repo = une **branche
  orpheline** (1 commit, sans historique) reconstruite à chaque déploiement
  depuis l'arbre `saas` (voir §4).
- **Backend** : Supabase Postgres (ref `hthtdkvhzwpvhgzwhuqg`), RLS par user,
  Auth email/mot de passe. Admin = compte de l'owner (données GPCP migrées).
- **Branche de travail** : `saas`.
- **Flux runtime** : connexion → **Se connecter / Créer un compte** OU bouton
  **« Démo »**. (Le code d'accès global a été supprimé.) 1ʳᵉ connexion d'un
  nouveau compte → **création obligatoire du 1er portefeuille (nom + devise)**.

## 3. Architecture

`data.py` = **dispatcher** : `__getattr__` route chaque accès `data.X` vers le
backend actif décidé par `_active()`, dans cet ordre :
1. **`st.session_state["__demo_mode"]`** → `data_demo.install()` puis
   **`data_sqlite`** (moteur V15 patché avec les données démo, lecture seule).
2. **SaaS + user authentifié** → **`data_postgres`** (Supabase, RLS par user).
3. sinon → **`data_sqlite`** (V15 local).

- **`data_postgres.py`** = backend cloud (REST + JWT par requête, self-contained).
  Ré-implémente `compute_snapshot` / `compute_vl_series` / `nav_series` /
  `_cash_walk` / FX (`fx_rates`) / `augmented_price_history` (lignes achat **et**
  vente) / `sell_pnl_rows` / `heal_price_gaps`, etc. État par-session
  (`ASSETS`/maps = proxys `st.session_state`, pas des globals → pas de
  clobbering entre users concurrents).
- **`data_demo.py`** = backend démo lecture seule (voir §6).
- **`auth.py`** = sign in / sign up (Supabase) + bouton **Démo**. Plus de gate
  code d'accès. `require_auth()` renvoie un user synthétique en mode démo. JWT
  rafraîchi avant expiration.
- **`app.py`** = UI principale + onglets (`st.tabs`). **`pro.py`** = sous-onglets
  Pro. **`prices.py`** = Yahoo. **`compositions_scraper.py`** = secteur/géo ETF.
  **`daily_update.py`** = job prix. **`db/schema.sql`** = schéma Postgres.

### Points clés (gros pièges déjà corrigés — voir §9)
- **`st.cache_data` est global au process** → toute donnée user en cache DOIT
  être clé par user. `_load_all(_user_scope())` (= `(user_id, portfolio_id)`).
  Sinon crash + fuite de données entre users concurrents.
- **`_num_col()`** dans app.py : extraction numérique robuste des colonnes pour
  les 3 tableaux d'historique (gère colonne dupliquée / dtype objet / cellule
  non-scalaire) → un actif exotique (ETF levier…) ne fait plus crasher la page.
- **Prix par-actif** : « séance fermée → dernier adjusted close de CET actif ».
  `_initial_prices` prend le dernier non-NaN **par colonne** (pas la dernière
  ligne globale) → un actif clôturant un autre jour (US vs EU, férié) n'est plus
  exclu de la NAV.
- **Continuité des prix** : pas de cron serveur ; le backfill est gap-aware et
  `heal_price_gaps()` répare les trous au chargement (sinon forward-fill périmé
  → NAV/VL/graphe faux).
- **Perf** : `st.tabs` recalcule TOUS les onglets à chaque rerun → le Monte Carlo
  (`pro._mc_simulate`, graine fixe) est **mis en cache**. Si encore lent : passer
  les onglets en lazy-render (ne calculer que l'onglet actif) = chantier suivant.

## 4. Déploiement (⚠️ LE CŒUR)

**Une commande : `./SAAS/deploy.sh`** (depuis la branche `saas`). Elle :
1. rafraîchit les compositions ETF (factsheets live, best-effort) + commit si
   changé ;
2. construit la branche orpheline `deploy` **via `git commit-tree` depuis l'arbre
   `saas`** — le working tree n'est JAMAIS touché (⚠️ ne JAMAIS revenir à
   `checkout --orphan` + `git add -A` : ça avait avalé/supprimé des fichiers
   non-suivis) ;
3. vérifie l'absence de secrets/données dans le bundle ;
4. sauvegarde la version live dans `rollback` ;
5. **affiche** la commande `git push` à lancer toi-même (token = PAT classique,
   scopes **`repo` + `workflow`**).

Après push : Streamlit redéploie. **⚠️ Si une stacktrace ne correspond pas au
code déployé, c'est le process en mémoire → Manage app → ⋮ → Reboot app**, puis
`Cmd+Shift+R`. Vérifier ce qui est en ligne via l'**API GitHub**
(`/contents/<file>?ref=main`), pas `raw.githubusercontent` (cache CDN ~5 min).

## 5. Points de restauration (filet de sécurité)

Branches locales (ne bougent pas sauf si on les déplace) :
- **`pre-perf`** = version avant le lot « perf » (spinner net, sans cache MC).
- **`rollback`** = version live d'avant le dernier `deploy.sh` (mis à jour à
  chaque run de deploy.sh).
- Pour revenir : `git push -f "https://SadSlicer:<TOKEN>@github.com/SadSlicer/gpcp-dashboard.git" pre-perf:main` (ou `rollback:main`) puis Reboot.
- Les **données Supabase ne sont jamais touchées** par un deploy/rollback.

## 6. La démo (lecture seule)

- Bouton **« 👁 Découvrir la démo »** sur la page de connexion → `__demo_mode`
  → dashboard sans compte, **non modifiable**.
- **`demo_data.json`** = jeu figé : 12 actions US diversifiées (Microsoft, Apple,
  JPMorgan, Visa, J&J, UnitedHealth, P&G, Coca-Cola, Home Depot, ExxonMobil,
  Caterpillar, Disney), ~3 ans, USD, ~26 transactions (achats/ventes).
- **`data_demo.install()`** patche les *leaves* de `data_sqlite` pour servir ces
  données + **bloque toutes les écritures** (raise « lecture seule », attrapé par
  les try/except existants). Porte aussi les helpers que V15 sqlite n'avait pas
  (`augmented_price_history`, `sell_pnl_rows`, `avg_cost_by_asset`…).
- **Auto-à-jour** : base 3 ans figée (instantané) + **queue de cours récents en
  direct, cache 6 h** (`_live_tail`) → la démo se réactualise jusqu'au dernier
  jour de bourse. Best-effort (échec Yahoo → base figée).
- UI : bandeau « Mode démo », bouton « Quitter la démo » ; `Refresh & Save` et
  l'onglet Réglages masqués ; auto-refresh + création-de-portefeuille sautés.

## 7. Diagnostics & vérif live (hors Streamlit)

- **`SAAS/diag_vl.py`** : l'owner le lance (`.venv/bin/python SAAS/diag_vl.py [pf]
  [email]`), se connecte (mot de passe demandé, jamais stocké), et dump
  transactions / couverture de prix par actif (avec trous) / série VL / snapshot.
- Rendu headless complet : `streamlit.testing.v1.AppTest.from_file("app.py")` ;
  pour la démo injecter `at.session_state["__demo_mode"]=True` ; pour le cloud
  injecter `__saas_user={id,email,is_admin,_access_token,_refresh_token,_expires_at}`.

## 8. Secrets (PAS de valeurs ici)

- Local : `.streamlit/secrets.toml` (gitignoré) → `SUPABASE_URL`,
  `SUPABASE_ANON_KEY`, `SUPABASE_DB_HOST`, `SUPABASE_DB_PASSWORD` (⚠️ le mot de
  passe DB direct est **rejeté/obsolète** — `pg_connect` ne marche plus, utiliser
  la voie REST). `ACCESS_CODE` n'est **plus utilisé** (gate supprimé).
- Prod : Streamlit Cloud → Settings → Secrets. Jamais de `service_role`.
- ⚠️ Ne jamais committer : token GitHub, mots de passe, email perso de l'owner.

## 9. Changelog de cette session (du + récent au + ancien)

```
e9aaf1d démo auto-à-jour : base 3 ans figée + queue de cours live (cache 6 h)
64530e0 démo lecture seule + bouton « Démo » (data_demo, frozen US portfolio)
3e7db1a SAAS/diag_vl.py — diagnostic VL/prix live (read-only, email scrubé)
580753d création du 1er portefeuille OBLIGATOIRE à l'inscription (nom + devise)
8a11ae7 parsing secteurs robuste (fix Emerging Asia ESG — suffixe + libellés EN)
b527b14 suppression du gate code d'accès + lien JustETF pour CHAQUE ETF
63649c8 prix par-actif = dernier adjusted close (annule la logique horaire fausse)
3384217 refetch sûr la nuit (ne chasse plus un « today » inexistant)
26cec7b perf : Monte Carlo en cache + heal des trous prix allégé (garde)
9ae037a spinner net : élément propre (.gpcp-loader), pas body::after (blur du fond)
eb354a5 spinner sans assombrir la page (petit cadran flottant)
ddf9d06 géo nouvel ETF auto via factsheet + SpaceX en curé
1b0ca5d 2 colonnes de return sur vente : Réalisé vs Marché (auj.)
9d4c6bc fix crash ETF levier (_num_col) + Net investi = capital externe + lignes vente
7a62e08 fix trous d'historique de prix (forward-fill périmé qui faussait NAV/VL)
8d42892 SAAS/deploy.sh (commit-tree, sûr) + restauration HANDOFF
4de2cc9 refresh secteurs/géo ETF (factsheets de mai)
eccace2 durcissement graphe Allocation (anti-crash)
b9e8e87 fix crash/fuite multi-users — clé par-user sur le cache _load_all
```
(+ avant : a8ebc38 état par-session, NAV inclut le cash, P&L vente réalisé, etc.)

## 10. Nuances connues (PAS des bugs)

- **Perf par actif (coût moyen, money-weighted) ≠ VL portefeuille
  (time-weighted)** : deux méthodologies, ne somment pas. Voulu.
- **Refresh des expos ETF** : source de vérité = `./SAAS/deploy.sh` (re-scrape à
  chaque déploiement). La GitHub Action `refresh-compositions.yml` (cron le 15)
  est un backup peu fiable (commite sur `main`, écrasé par un deploy manuel). Les
  nouveaux ETF ajoutés en runtime : secteur (Yahoo) + géo (factsheet par ISIN)
  via `pro._live_geo_sector`, cache 1 j → rafraîchis quotidiennement.
- **SpaceX** : non coté → pas de données Yahoo → entrée curée manuelle dans
  `etf_compositions.json` (Industrials / USA).
- **Free tier** : Streamlit dort après ~7 j d'inactivité (réveil ~10 s) ;
  Supabase free se met en pause après ~1 semaine (réveil = 1 clic « Restore »).
- **Onglets `st.tabs`** : tout est recalculé à chaque rerun (Monte Carlo en cache
  pour limiter). Le vrai gain serait un lazy-render (chantier non fait).
