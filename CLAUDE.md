# GPCP Dashboard

Local Streamlit dashboard replacing an Excel ETF portfolio tracker.
Two parallel lines of work:

- **Functional**: V15 (tag `v15`, on branch `main`) — multi-portfolio,
  multi-asset, multi-currency, adjusted-close, deletable transactions.
- **Visual + coherence**: **VA15** (tag `va15`, on branch `va`) —
  premium dark redesign built on top of V15, plus all the unitized-VL
  and time-varying-shares fixes so historical metrics stay coherent
  as the portfolio evolves.

Owner speaks French — reply in French.

## 👉 Start here (read in order)

If you're going to **touch UI / design / coherence**:
1. **`VA15/CLAUDE.md`** — current visual + coherence operational doc
2. **`VA15/VA15_REBUILD.md`** — how to rebuild VA15 from a fresh V15
3. **`VA15/DESIGN_SYSTEM.md`** — palette / typography / spacing reference

If you're going to **touch data / business logic**:
1. **`git show v15:V15/CLAUDE.md`** — V15 architecture (folder removed; in tag)
2. **`git show v15:V15/V15_REBUILD.md`** — full from-zero rebuild spec

Contract:
- V15 logic is read-only from the VA branch
- VA design code (`theme.py`, CSS, Plotly styling) is read-only from a
  V branch

## Branch + tag map

| Branch | Tag | What |
|---|---|---|
| `main` | `v15` | V15 — functional source of truth |
| `va` | `va15` | VA15 — current premium design + coherence pass |

```bash
git checkout main           # → V15 (instant rollback)
git checkout va             # → VA15 (current design line)
git checkout va15 -- .      # → restore VA15 over any branch
git checkout v15 -- .       # → restore V15 over any branch
git show va4:VA4/CLAUDE.md  # consult an older doc (folder removed)
```

Tags (most recent first):
`va15`, `va4`, `va2`, `va1`, `v15`, `v13`, `v12`, `v11`, `v10`, `v7`,
`v6`, `v5`, `v4`, `v3`, `v2`, `v2-step1`, `v1`.

The V15/, VA1/, VA2/, VA4/ folders have been removed from the working
tree to save disk space — preserved verbatim in their tags:

```bash
git show va4:VA4/CLAUDE.md
git show va2:VA2/CLAUDE.md
git show v15:V15/V15_REBUILD.md
```

## VA15 in one paragraph

VA15 consolidates the VA1 premium Linear-grade dark redesign (Tokens
dataclass in `theme.py`, Inter + JetBrains Mono fonts, glassmorphism
cards, KPI stagger, tab fade-up, dual Daily Return display), the VA2
features (Price History multi-currency detail, auto-fetch price by
date, Excel bulk import with preview), the VA4 pairwise correlation
matrix with Excel red→yellow→green colorscale, the VA6 background
de-animation (static gradient = no GPU compositing = consistent
60fps), the VA6 Overview chart switch from raw NAV in € to **VL base
100** (so new transactions don't appear as fake performance), the
VA6 Pro tab audit (Risk Metrics / Calendar / Benchmark / Monte Carlo
all switched to VL series, no flow contamination), and the **VA15
coherence pass** : time-varying shares in 4 places (Allocation
evolution + 3 Price History tables — historical values now reflect
shares held at that date, not current shares); "Historique NAV"
table VL column rebuilt from `compute_vl_series()` (no more naive
NAV/inception_NAV ratio that jumped on flows); Monte Carlo simulation
starts at the real current NAV in €; Annualized Return KPI uses the
geometric / EAR formula `(1+r).prod()^(252/n) - 1` (Sharpe / Sortino
keep textbook arithmetic). V15 functional invariants 100% preserved.

## Quick run

```bash
cd /Users/gabrielpeix/Documents/GPCP/DashBoard
./run.sh                         # → http://localhost:8501
# or restart the launchd-managed server:
launchctl kickstart -k gui/$(id -u)/com.gpcp.dashboard.server
```
