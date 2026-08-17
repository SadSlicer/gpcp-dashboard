# GPCP Dashboard — Reprise du projet (handoff)

> Doc de reprise pour **continuer dans une nouvelle conversation**. À lire en
> premier, AVEC `SAAS/ALPHA_REBUILD.md` (les 7 correctifs à ne jamais défaire)
> et `Final/README.md` (restauration de la version stable).
> **Propriétaire : francophone → répondre en français. UI/graphiques en anglais.**
> Dernière mise à jour : 2026-08-17.

---

## 0. En une phrase

SaaS de suivi de portefeuille (Streamlit + Supabase Postgres), branche **`saas`**,
déployé sur Streamlit Community Cloud. Prix via **Yahoo JSON API en `requests`
(PAS yfinance)**. Design premium « fintech » (navy/or, IBM Plex, mode sombre par
défaut suivant l'OS). Depuis la base stable `alpha`, une longue série de commits
a refait toute la DA, réorganisé les onglets, et corrigé plusieurs bugs
métier (FX, VL, benchmark).

---

## 1. Où on en est (état au 2026-08-17)

- **Branche** : `saas`. **HEAD** : `cea34ce` (revert du menu vertical maison).
- **Working tree propre.** Tout est committé.
- **Tags** : `alpha` (version stable de référence, commit 43ee0ab), `v15`, `va15`.
  ⚠️ Ne JAMAIS écraser le tag `alpha` ni le dossier `/Users/gabrielpeix/Documents/GPCP/Final/`.
- **Fichiers clés** (lignes) : `app.py` (~2600), `pro.py` (~2350), `theme.py`
  (~1170), `data_postgres.py` (~1790), `prices.py` (~300), `auth.py` (~280).

### Décision structurante la plus récente (IMPORTANT)
La navigation de 1er niveau utilise **`st.tabs`** (barre affichée **verticalement
à gauche via CSS**), et les **sous-onglets Analytics s'affichent en 2e colonne
verticale à droite** de la nav.
- Un essai de **menu vertical maison** (boutons + `st.rerun`, avec accordéon +
  PDF Export en 1er niveau) a été **RÉVERTÉ** (`cea34ce` annule `a3b6958`) :
  les boutons rechargeaient toute l'app à chaque clic. Les `st.tabs` basculent
  **côté client** (instantané, pas de rerun) → c'est la version voulue.
- **Conséquence** : ne PAS refaire un menu à base de `st.button`+`st.rerun` pour
  la nav principale. Si on veut un accordéon sans rechargement, il faudra une
  autre technique (composant HTML/JS custom), à valider.

---

## 2. Historique des changements depuis `alpha` (résumé)

Du plus ancien au plus récent (voir `git log` pour le détail) :

1. **Refonte DA complète** — palette navy/or, IBM Plex Sans/Mono, suppression
   glassmorphism/glows/dégradés/emojis, mode clair de référence puis passé en
   **sombre par défaut suivant l'OS** (config.toml + `st.context.theme.type`,
   voir §4). `theme.py` = source unique du visuel.
2. **Réorganisation en 5 sections** : Dashboard · Holdings · History · Analytics
   · Settings. Dashboard recomposé (bandeau KPI, courbe VL + allocation,
   tableau holdings dense en **HTML** — `theme.data_table` / `sortable_table` /
   `df_table`).
3. **Bugs métier corrigés** :
   - **FX cassé sur le cloud** : le fetcher FX utilisait `yfinance` (absent du
     cloud → correctif #1) ; réécrit en `requests` via `prices._yahoo_chart`
     dans `data_postgres._fx_fetch_yahoo`.
   - **Benchmark** : fenêtre commune stricte (normalisation des index date à
     minuit avant intersection) — corrige un décalage de dates cloud.
   - **VL base 100** : ancrée sur le **capital investi** (pas la clôture
     d'inception) → VL == Total return sur un flux unique. Cf. §5.
   - **Calendar heatmap** : perf annuelle en close-to-close (vrai YTD), pas la
     somme des mois.
4. **Refresh automatique** : à la connexion (`_auto_refresh_if_stale` lance
   tout `daily_update.run` 1×/session) + après écriture
   (`_invalidate_after_write`). Évite les données périmées.
5. **Colonne FX** dédiée + panneau « Currency effect » (P&L de change) dans
   Holdings.
6. **Mode démo** = **un seul ETF BlackRock, iShares Core S&P 500 (CSPX.AS,
   coté EUR), 5 ans** (2021-08 → 2026-08), 1 transaction. `demo_data.json`
   régénéré. Bandeau démo mis à jour.
7. **Transactions** sortie de History → bouton **« + Transaction »** (barre
   d'app, haut-droite) ouvre une **page dédiée** (flag `_show_tx`, rendue avant
   les onglets + `st.stop()`). Import Excel/CSV replié dans un expander.
8. **Nav verticale à gauche** (CSS sur `st.tabs`), scopée à l'app via
   `build_css(sidebar_nav=True)` — le **login reste horizontal** (auth.py appelle
   sans le flag). Sous-onglets en 2e colonne verticale plus petite.
9. **Tooltip KPI** : « ? » sur *Unit value* et *Total return* expliquant
   time-weighted vs money-weighted (ils diffèrent légitimement quand on investit
   à des dates différentes — ce n'est PAS un bug).

---

## 3. Architecture (rappel)

- **`data.py`** dispatch (PEP-562) → `data_postgres.py` (cloud, RLS par
  user_id+portfolio_id) OU `data_sqlite.py` (local/démo, **OFF-LIMITS**).
- **`data_demo.py`** : lit `demo_data.json`, alimente le moteur `data_sqlite`
  (démo = read-only, backend sqlite en mémoire + queue de prix live).
- **`prices.py`** : fetch Yahoo en `requests` (cookie+crumb thread-local),
  `_yahoo_chart` (v8), `_yahoo_quote_summary` (v10). `MAX_HISTORY = 5 ans`.
- **`pro.py`** : onglet Analytics (Risk, Calendar, Attribution, Correlation,
  Benchmark, Monte Carlo, PDF, Sector/Geo). Gate bare-mode dans `render()`.
- **`theme.py`** (`va1theme`) : design system + `build_css()` + `style_plotly()`
  + helpers HTML (`kpi_card`, `panel_head`, `data_table`, `df_table`,
  `sortable_table`, `alloc_bars`, `tag`).

---

## 4. Thème (mécanique à connaître)

- **Sombre par défaut, suit l'OS**, basculable via ⋮ → Settings (natif Streamlit).
- `config.toml` définit `[theme.light]` ET `[theme.dark]` → pilote la **chrome
  canvas des `st.dataframe`** (que le CSS n'atteint pas).
- `build_css(active)` émet **UNE seule palette par rendu**, choisie par
  `st.context.theme.type` (lu dans `app._active_theme()`), pour rester en phase
  avec le natif. Ne pas ré-émettre les deux palettes + switch client.
- Changer d'OS à chaud demande un **reload** pour que Streamlit re-détecte.

---

## 5. Invariants métier délicats (ne pas casser)

- **VL base 100 (time-weighted)** vs **Total return (money-weighted)** : égaux
  seulement si **un seul flux** (une transaction, pas d'autre entrée/sortie).
  Différents dès qu'on investit à des dates différentes → **normal** (TWR≠MWR).
  Ancrage VL sur le capital investi (`external_deposits_as_of(dates[0])/100`)
  dans `data_postgres.compute_vl_series` — correctif dans le **backend cloud
  seulement** (`data_sqlite` intouchable ; la démo à flux unique reste correcte).
- **Prix = adjusted close** (dividendes réinvestis).
- **FX** : fetch en `requests` (jamais yfinance côté cloud), auto-heal des trous
  au chargement + prefetch de fenêtre.

---

## 6. Les 7 correctifs ALPHA (JAMAIS défaire — cf. ALPHA_REBUILD.md §1)

1. Pas de `yfinance`/`curl_cffi` (segfault cloud) → prix & FX en `requests`.
2. Session `requests` **thread-local** (`prices._thread_session`).
3. Client Supabase **thread-local** (`supabase_client`).
4. **Gate bare-mode** (`_has_script_ctx`) sur auto_refresh/heal/`pro.render`.
5. **Python 3.12** dans les Settings Streamlit Cloud (dashboard, pas le repo).
6. **`streamlit==1.57.0`** + CSS d'onglets durci (sélecteurs `[data-baseweb="tab"]`
   ET rôles ARIA + hard-hide des panneaux). ⚠️ La nav verticale et les tableaux
   HTML sont **spécifiques à 1.57** (`:has()`, structure DOM des tabs).
7. **Pins natifs** : `numpy==2.1.3`, `pandas==2.2.3`, `pyarrow==17.0.0`.

---

## 7. Workflow de travail (appris à la dure)

- **Une amélioration à la fois** : coder → `py_compile` → **AppTest démo
  headless en `__demo_mode`** (attendu **0 exception / 0 erreur**) → commit isolé
  → déployer.
- **Valider sur la pile de PROD** : le venv local peut être en Python 3.14 /
  pandas 3.0. Créer un venv **3.12** jetable aux versions épinglées et tester
  avec `-W error::FutureWarning` (ça a déjà attrapé un `FutureWarning` pandas
  2.2 invisible en local).
- Le **mobile** et le **conteneur Linux du cloud** ne sont pas testables en
  local → validation finale par le propriétaire après déploiement.
- **Ne pas toucher** : `data_sqlite.py`, branches `va`/`va15`/`main`, les 7
  correctifs.

### Lancer/tester en local
```bash
cd /Users/gabrielpeix/Documents/GPCP/DashBoard
./run.sh                                  # http://localhost:8501
# AppTest headless (démo) :
.venv/bin/python - <<'PY'
from streamlit.testing.v1 import AppTest
at = AppTest.from_file("app.py", default_timeout=180)
at.session_state["__demo_mode"] = True
at.run(); print("exceptions:", len(at.exception), "errors:", len(at.error))  # 0 0
PY
```

---

## 8. Déploiement

```bash
cd /Users/gabrielpeix/Documents/GPCP/DashBoard
git checkout saas
./SAAS/deploy.sh          # refresh compositions, construit la branche orphan 'deploy', imprime le push
```
Puis (le **propriétaire** lance le push, PAT frais scopes repo+workflow, jamais
collé dans le chat) :
```bash
git push -f https://github.com/SadSlicer/gpcp-dashboard.git deploy:main
```
Puis Streamlit Cloud : **Manage app → ⋮ → Reboot app**, **attendre le REBUILD**
(un simple reboot réutilise le cache), puis `Cmd+Shift+R`. Confirmer le stamp
`GPCP-BOOT-START build=…` dans les logs.

---

## 9. Filet de sécurité (revenir à la version stable)

- `git checkout alpha` (ou `git checkout alpha -- .`).
- Ou depuis le dossier figé : `rsync -a --exclude '.git' --exclude '.venv'
  --exclude '.streamlit/secrets.toml' /Users/gabrielpeix/Documents/GPCP/Final/
  /Users/gabrielpeix/Documents/GPCP/DashBoard/` (NE PAS mettre `--delete` — ça
  effacerait les .db locaux et les Excel d'origine).
- Pour annuler UNE modif récente : `git revert <hash>` (comme on vient de le
  faire pour le menu maison).

---

## 10. Pistes / TODO possibles

- Refonte ergonomique plus poussée de la **page Transactions** (validée en
  headless seulement — masquée en démo, à itérer sur un compte réel non-démo).
- **Mobile** : la nav verticale se replie < 900px, mais l'ensemble mérite un
  vrai passage responsive.
- Accordéon Analytics **sans rechargement** (si souhaité) : nécessiterait un
  composant custom, pas des `st.button`.
- Le mode **clair** est fonctionnel mais moins peaufiné que le sombre.
