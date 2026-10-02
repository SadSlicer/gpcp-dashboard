# GPCP Dashboard — VA15 (consolidated visual + coherence layer)

> Tag: `va15`. Branch: `va`. Built on top of V15 (functional source on
> `main`). Owner speaks French — reply in French.

VA15 consolidates VA1 (Linear-grade dark + theme.py + glassmorphism),
VA2 (currency clarity + auto-fetch + Excel bulk import), VA4 (Excel-
style pairwise correlation, disk cleanup), the VA5 motion attempt
(REMOVED — Streamlit `st.markdown` sanitizes `<script>` tags and
`st.components.v1.html` was removed after 2026-06-01 so the iframe
trick no longer works), VA6 (Overview VL chart + Pro tab VL audit +
static animation-free background), and the **VA15 coherence pass**
(time-varying shares everywhere, EAR / geometric annualized return,
Monte Carlo uses real € as starting point).

## 1. What VA15 fixes vs VA4

### Static, non-animated background (no more lag)
The 4-layer always-on animated background from VA1/VA3 (drift gradients,
orbiting white blobs, conic gray sweep, Aurora flow) is **disabled via
a `animation: none !important` override** at the end of `theme.build_css()`.
The gradients themselves remain visible (subtle orange halo top + indigo
bottom) so the page keeps depth, but the GPU no longer composites
animated layers every frame. Net result: dashboard is consistently
fluid at 60fps on the user's machine.

### Overview chart : VL base 100, not raw NAV
`app.py` Overview tab now plots `data.compute_vl_series(price_history)`
indexed at 100 instead of `data.nav_series(price_history)` in €. Reason:
every BUY / DEPOSIT moves NAV mechanically (you added value, that's not
performance) — so the "NAV over time" curve jumped on every transaction,
misleading the user into thinking they had outperformed. The unitized
VL neutralizes flows (units are created on inflow at the prevailing
VL; VL only moves on market performance), so the curve now reflects
pure market performance. Hover tooltip still shows the NAV in € for
context.

### Pro tab uses VL instead of raw NAV (4 sub-tabs)
New helper `pro._portfolio_vl_series(price_history)` returns the VL
series. The following sub-tabs all switched their input source from
the raw NAV series (which had flow contamination) to the VL series:

- **Risk Metrics**: Sharpe / Sortino / VaR / CVaR / max drawdown — all
  computed on VL returns now, so they're statistically clean.
- **Calendar Heatmap**: monthly returns reflect pure performance.
- **Benchmark Comparison**: VL indexed at 100 vs benchmark indexed at
  100 — fair comparison. Both are now pure-performance series.
- **Monte Carlo Simulator**: GBM (μ, σ) calibrated on VL returns. Path
  simulation **starts at the real current NAV in €** (via `snapshot
  ["total_value"]`), not 100, so projected paths are denominated in
  real money. Sub-title now reads `"Départ : NAV actuelle = X €"`.

### Time-varying shares in all historical tables (huge bug fix)
Before VA15, several tables used `static.shares.get(a, 0)` — i.e.
**current** shares — to compute values for **historical dates**. This
silently rewrote the past: if you bought 5 more shares of Nasdaq
yesterday, every historical row showed those 10 new shares as if you'd
owned them since inception. Fixed by computing `data.shares_held_as_of
(date)` per row.

Locations fixed:
- `app.py` Allocation tab — "Évolution des allocations" stacked area:
  per-row time-varying shares so the stacked % is faithful to your
  actual holdings at each point in time.
- `app.py` Price History tab — three sub-tables (Prix journaliers par
  ETF [Total column], Valeur de position journalière par ETF [all
  cells], Historique NAV portefeuille [NAV column]) all use time-
  varying shares.

### "Historique NAV portefeuille" VL column rebuilt
The same table used to compute its VL column as `NAV / inception_NAV
× 100` — a naive ratio that jumped on every flow (just like raw NAV).
Now the VL column comes from `data.compute_vl_series()` (proper
unitized VL) and the "Daily Change %" column is computed on VL too
(real perf), while "Δ €" stays on NAV (intuitive "how much my pocket
moved"). The Overview VL chart and this column now share the SAME
source — no more divergence possible.

### Geometric annualized return (EAR-style) for the Annualized Return KPI
Risk Metrics' "Annualized Return" KPI used `mean_d × 252` (arithmetic
annualization, biased upward) which is fine as Sharpe-input but
inaccurate as a displayed annual return. Switched to the geometric
formula:

```python
total_growth = (1 + rets).prod()
ann_return  = total_growth ** (TRADING_DAYS / n) - 1.0
```

This is the true CAGR realized over the period extrapolated to a full
year — the standard reported by fund managers. Sharpe / Sortino keep
the textbook arithmetic mean × √252 because that's their canonical
formula.

## 2. Files touched vs VA4

```
MOD  theme.py    — adds the user-requested `animation: none !important`
                    override at the end of build_css()
MOD  app.py      — Overview NAV chart → VL base 100;
                    Allocation evolution uses time-varying shares;
                    Price History 3 tables use time-varying shares;
                    Historique NAV VL column uses compute_vl_series.
MOD  pro.py      — _portfolio_vl_series helper;
                    Risk Metrics / Calendar / Benchmark / Monte Carlo
                    switched to VL series;
                    Monte Carlo accepts `snapshot` arg + uses real NAV
                    in € as starting point;
                    Annualized Return now uses geometric formula.
NEW  VA15/CLAUDE.md
NEW  VA15/VA15_REBUILD.md
NEW  VA15/DESIGN_SYSTEM.md  (copied from VA4)
DEL  VA4/                    (preserved in tag va4)
```

VA5 left no permanent code — the `motion_inject_html()` exploration was
removed when it broke the page (`st.components.v1.html` no longer works).
The CSS-only animations from VA1+ (hover lifts, stagger entrance, pulse
dots, tab fade-up) remain active and provide the polished feel.

## 3. The `theme.py` API (unchanged from VA4)

```python
theme.tokens_for(theme_str)         # → Tokens dataclass (dark | light)
theme.build_css(theme_str)          # → full <style>…</style> string
theme.style_plotly(fig, theme=...)  # → applies VA-style theming
theme.ETF_COLORS                    # → canonical dict
theme.color_for_asset(asset, idx)   # → with fallback palette for custom
theme.kpi_card(label, value, ...)   # → HTML
theme.header_html(pf_name, pf_ccy, source, version)
theme.status_bar_html(items)
theme.section_head(title, sub=None)
theme.hero_nav_html(...)
theme.sparkline_svg(points, color, width, height)
theme.PLOTLY_CONFIG                  # → {displayModeBar, displaylogo, scale:2}
```

## 4. Helpers added to data.py over time (still present)

```python
data.price_on_date(asset, when) -> (price_native, source)
data.add_transactions_bulk(rows) -> {"inserted", "skipped", "errors"}
data.refetch_recent_closes(days=7)
data.daily_return_pf in compute_snapshot (alongside daily_return)
data.compute_vl_series(price_history)   # already in V15, central to VA15
data.shares_held_as_of(when)            # already in V15, central to VA15
```

## 5. Coherence invariants

These should now ALL hold:

| Invariant | How it's enforced |
|---|---|
| New BUY/DEPOSIT does NOT bump VL | VL comes from compute_vl_series (unitized) |
| Overview VL chart matches Historique NAV's VL column | Both call data.compute_vl_series() |
| Historical position values reflect shares held at that date | shares_held_as_of(date) per row in 4 places |
| Risk metrics aren't inflated by flow spikes | All read VL series, not NAV |
| Monte Carlo paths are in € of real money | Starts at snapshot["total_value"] |
| Annualized Return matches CAGR | Geometric formula (1+r).prod()^(252/n)-1 |
| Sharpe / Sortino follow textbook | mean × 252 / std × √252 (arithmetic, intentional) |
| Per-asset price column native, value column pf_ccy | Positions table (VA1) |
| Correlation matrix is pairwise | rets.corr() on raw pct_change() (VA4) |
| Currency cells labeled with correct symbol | All KPI/Total cells (VA1) |

## 6. Known caveats

- VL series can have NaN until the first inception trading day. The
  Historique NAV table forward-fills, so the user never sees gaps.
- Correlation matrix may not be PSD when assets have very different
  histories (pairwise corr). Fine for visual reading; don't feed into
  a Markowitz optimizer.
- Streamlit `st.markdown` sanitizes `<script>` tags. JS-based animations
  (count-up, spring physics, magnetic cursor) are NOT possible in local
  Streamlit. They'll come back natively when the SaaS migration (Next.js
  + FastAPI + Supabase + Stripe + motion lib, already npm-installed) is
  done.
- Allocation Drift "vs Inception" is still potentially misleading when
  you add new assets later (a new asset has target=0 → always +100%
  drift). Not yet fixed — a "vs 1/N equiweight" toggle was attempted but
  not kept. Open for VA16.
- Pro Risk Metrics use `dropna()` on the per-asset returns chain which
  is fine after the VL switch (VL is always defined past inception).

## 7. Rollback

```bash
git checkout main         # → V15 raw (instant rollback from anywhere)
git checkout va15 -- .    # → restore VA15 over any branch
git checkout va4 -- .     # → VA4 (without the coherence fixes)
git checkout va2 -- .     # → VA2 (without Excel correlation + pairwise)
git checkout va1 -- .     # → VA1 (without VA2 features)
git checkout v15 -- .     # → raw V15
```

Older doc folders preserved verbatim in their tags:

```bash
git show va4:VA4/CLAUDE.md
git show va2:VA2/CLAUDE.md
git show v15:V15/V15_REBUILD.md
```

## 8. Quick run

```bash
cd /Users/gabrielpeix/Documents/GPCP/DashBoard
./run.sh                    # → http://localhost:8501
launchctl kickstart -k gui/$(id -u)/com.gpcp.dashboard.server
```

## 9. Likely VA16 candidates (open / discussed)

- Allocation Drift: equiweight 1/N toggle (proper "balance" metric)
- Custom target allocation per asset in Settings
- Daily Update enhancement: invalidate VL cache on new transactions
- MCP server exposing portfolio data (read-only first)
- The big one: SaaS migration (option D) — Next.js + FastAPI + Supabase
  + Stripe + native motion library (already in package.json)
