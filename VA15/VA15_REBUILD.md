# VA15 — Full rebuild spec (design + coherence layer on top of V15)

VA15 is the **consolidated** spec for the current dashboard state.
Supersedes VA1 / VA2 / VA4 rebuild docs (preserved in their tags).
VA3 / VA5 / VA6 numbers were experimentation milestones that didn't
ship as tags — their net useful effects are folded into VA15.

To rebuild VA15 from a fresh V15 checkout:

```bash
git checkout v15 -- .
git checkout -b va
# follow steps below in order
git tag va15
```

## 1. Files

```
NEW  theme.py                ← design tokens + CSS + Plotly theme + HTML helpers
NEW  VA15/CLAUDE.md          ← operational doc
NEW  VA15/VA15_REBUILD.md    ← this file
NEW  VA15/DESIGN_SYSTEM.md   ← palette/typography/spacing reference
MOD  app.py                  ← VA1 chrome + VA2 features + VA6 VL chart + VA15 time-varying tables
MOD  pro.py                  ← VA1 colors + VA4 pairwise correlation
                                + VA6 VL switch + VA15 EAR + Monte Carlo €
MOD  data.py                 ← +daily_return_pf, +price_on_date,
                                +add_transactions_bulk, +refetch_recent_closes
                                (no changes vs VA4)
MOD  .streamlit/config.toml  ← primaryColor #FF8800, base dark #08090B
MOD  .gitignore              ← reports/, node_modules/, *.log
```

## 2. Token map (theme.py)

`Tokens` frozen dataclass; DARK + LIGHT instances; `tokens_for(theme)`.
Fields: backgrounds (BG_DEEP/BASE/ELEVATED/INPUT, SURFACE_1/2/HOVER),
borders (1/2/3), text (PRIMARY/SECONDARY/MUTED/FAINT/DISABLED),
accents (ACCENT, ACCENT_SOFT/DEEP/GLOW/TINT/BORDER/ON), semantic
(SUCCESS/DANGER/INFO with glow), brand (BRAND, BRAND_GLOW = ACCENT
in VA15), gradients (GRAD_BRAND_LOGO, GRAD_TEXT_UP/DOWN, GRAD_AMBIENT,
GRAD_DIVIDER).

Semantic SUCCESS/DANGER are brand-independent — returns are always
green/red, never orange.

## 3. Build order

### Step A — Foundations (VA1)
1. `theme.py` with Tokens, DARK + LIGHT, `tokens_for()`
2. `ETF_COLORS` dict + `color_for_asset(asset, idx)` helper
3. `build_css(theme)` — full stylesheet including:
   - Inter + JetBrains Mono Google Fonts
   - All tokens as CSS custom properties on `:root`
   - body solid bg + `.stApp` transparent
   - Component classes: `.va1-header / .va1-pill / .va1-status /
     .va1-hero / .va1-card[-elevated|-inset] / .va1-section-head /
     .va1-divider / .kpi-card / .kpi-label / .kpi-badge-live /
     .kpi-value / .kpi-delta`
   - Streamlit overrides: `.stTabs` (2px accent underline on active,
     no permanent orange smear), `.stButton[kind=primary]` (orange CTA),
     inputs, `.stDataFrame`, `.stPlotlyChart` (overflow:visible),
     `[data-testid="stMetric"]`
   - Animations: `va1-enter`, `va1-pulse`, `va1-tab-enter`
   - `prefers-reduced-motion` media query
   - Inline `<script>` MutationObserver for tab fade-up re-trigger
4. `style_plotly(fig, theme)` with margins `l=52 r=24 b=56`, transparent
   paper, top-right legend, JetBrains Mono ticks/hover
5. HTML helpers: `kpi_card`, `header_html`, `status_bar_html`,
   `section_head`, `hero_nav_html`, `sparkline_svg`
6. `PLOTLY_CONFIG = {displayModeBar: False, displaylogo: False, scale: 2}`
7. `.streamlit/config.toml`: primaryColor #FF8800, base dark #08090B
8. `app.py` integration: import theme, replace inline palette with
   `tokens_for()`, replace inline CSS with `build_css()`, replace `kpi()`
   with theme helper, wrap major sections with `section_head()`
9. Bar charts with `textposition="outside"` need `cliponaxis=False`
   + x-range padding by 30% on each side
10. Replace every `ETF_COLORS.get(...)` with `color_for_asset(asset, idx)`

### Step B — VA2 features (currency clarity, auto-fetch, Excel import)
1. `data.price_on_date(asset, when) -> (price, source)`:
   ```
   db_cache → yahoo_fetch (cache result) → fallback_prev_close → not_found
   ```
2. `data.add_transactions_bulk(rows) -> {inserted, skipped, errors}`:
   loop add_transaction / add_cash_movement, capture per-row exceptions,
   single `_invalidate_caches()` at the end.
3. Price History tab — "Détail multi-devises" section, visible only
   when any asset's native ccy ≠ pf_ccy. Selectbox + 3-column table
   (Date | Prix natif | FX rate | Prix converti) recomputed
   cell-by-cell for self-verification.
4. New transaction form — "Saisie manuelle du prix" checkbox (default
   off); when off, Price is a read-only display rendering the
   auto-fetched price via `price_on_date()` with source badge.
5. Transactions tab — "Import en lot" section with file uploader,
   st.data_editor preview with per-row checkbox + status, pre-filled
   `.xlsx` template via openpyxl + st.download_button, bulk submit.

### Step C — VA4 correlation matrix
1. `pro.py` `_render_correlation` — use pairwise `.corr()` on raw
   `pct_change()` (no global dropna).
2. Excel-style colorscale:
   ```
   [0.0, "#F8696B"], [0.25, "#FBA075"], [0.5, "#FFEB84"],
   [0.75, "#A4D080"], [1.0, "#63BE7B"]
   ```
3. Hover tooltip includes n_obs:
   ```
   customdata=n_obs.values  where n_obs = rets.notna().T.dot(rets.notna())
   hovertemplate="<b>%{y} ↔ %{x}</b><br>ρ = %{z:.3f}<br>n = %{customdata} obs"
   ```

### Step D — VA6 (Overview VL chart + Pro VL audit + static bg)

1. **Overview chart** in `app.py`:
   ```python
   vl_series_df = data.compute_vl_series(price_history)
   vl_df = vl_series_df[["date", "vl", "nav"]].copy()
   # ... fig: y = vl_df["vl"], hover shows both VL and NAV €
   # Reference line at 100 (inception baseline)
   ```

2. **Pro tab** in `pro.py` — add helper:
   ```python
   def _portfolio_vl_series(price_history):
       vl = data.compute_vl_series(price_history)
       return vl.set_index("date")["vl"].rename("VL") if not vl.empty else pd.Series(dtype=float)
   ```
   then in `_render_risk_metrics`, `_render_calendar_heatmap`,
   `_render_benchmark`, `_render_monte_carlo`:
   ```python
   nav = _portfolio_vl_series(price_history)  # instead of _portfolio_nav_series
   ```

3. **Static background** in `theme.build_css()` — append this
   override at the very end of the `<style>` block:
   ```css
   body::before, body::after,
   [data-testid="stAppViewContainer"]::before,
   [data-testid="stAppViewContainer"]::after {
     animation: none !important;
   }
   ```
   This keeps the gradient visuals visible but freezes them — biggest
   single perf win. The CSS animation keyframes (`va3-bg-drift` etc.)
   remain in the stylesheet as dead code; they're just never triggered.

### Step E — VA15 coherence pass (the new in-this-rev material)

1. **Time-varying shares in 4 places** — replace `static.shares.get(a, 0)`
   (constant CURRENT shares) with `data.shares_held_as_of(date)` per row:

   - `app.py` Allocation evolution stacked area (around line 857):
     ```python
     _alloc_shares_at = [
         data.shares_held_as_of(d.date() if hasattr(d, "date") else d)
         for d in alloc_slice["date"]
     ]
     for a in data.ASSETS:
         shares_col = [h.get(a, 0) for h in _alloc_shares_at]
         alloc_slice[a] = alloc_slice[a].astype(float).fillna(0) * pd.Series(shares_col)
     nav_series = alloc_slice[list(data.ASSETS)].sum(axis=1)
     nav_series = nav_series.where(nav_series > 0, other=1.0)  # avoid /0
     for a in data.ASSETS:
         alloc_slice[a] = (alloc_slice[a] / nav_series) * 100.0
     ```

   - `app.py` Price History "Prix journaliers" table (Total column),
     "Valeur de position" table (all cells), "Historique NAV" table
     (NAV column) — pre-compute shares per date for the slice:
     ```python
     _shares_by_date_slice = [
         data.shares_held_as_of(d.date() if hasattr(d, "date") else d)
         for d in base["date"]
     ]
     def _shares_col(asset, shares_list):
         return pd.Series([h.get(asset, 0) for h in shares_list])
     # then multiply price × shares_col(a, _shares_by_date_slice) per asset
     ```

2. **"Historique NAV portefeuille" VL column** — replace the naive
   `NAV / inception_NAV × 100` (which jumps on flows) with the proper
   unitized VL:
   ```python
   _vl_proper = data.compute_vl_series(price_history_pf)
   if not _vl_proper.empty:
       _vl_map = dict(zip(_vl_proper["date"], _vl_proper["vl"]))
       nav_full["VL"] = nav_full["date"].map(_vl_map).ffill().bfill()
   # Daily Change uses VL pct_change (true perf, no flow noise)
   # Δ € keeps NAV.diff() (intuitive € movement)
   nav_full["Daily Change"] = nav_full["VL"].pct_change()
   nav_full["Δ €"] = nav_full["NAV"].diff()
   ```

3. **Monte Carlo: start at real NAV in €** — `_render_monte_carlo`
   signature gains `snapshot` parameter:
   ```python
   def _render_monte_carlo(static, price_history, snapshot, palette):
       nav = _portfolio_vl_series(price_history)
       # ... calibrate GBM on VL returns ...
       nav_eur_now = float(snapshot.get("total_value") or 0.0) or float(nav.iloc[-1])
       nav0 = nav_eur_now  # paths denominated in real €
   ```
   and dispatch update:
   ```python
   _render_monte_carlo(static, price_history, snapshot, palette)
   ```

4. **Geometric annualized return** in `_render_risk_metrics`:
   ```python
   total_growth = float((1.0 + rets).prod())
   if n > 0 and total_growth > 0:
       ann_return = total_growth ** (TRADING_DAYS / n) - 1.0
   else:
       ann_return = 0.0
   # Sharpe / Sortino keep arithmetic mean × 252 / √252 — textbook
   ```

## 4. yfinance contract — `auto_adjust=True` everywhere

Audit:
```bash
grep -rn 'auto_adjust=False' --include='*.py' .   # must return nothing
```

## 5. Animation strategy in Streamlit (VA15 final answer)

After multiple attempts (VA5 motion via `st.components.v1.html` —
broken since 2026-06-01 ; inline `<script>` — sanitized by st.markdown),
the conclusion is:

**Only CSS animations work reliably in Streamlit.** No way to run JS
that touches the app DOM. Use:

- CSS `@keyframes` for entrance / hover / pulse
- `transition: ... cubic-bezier(0.34, 1.56, 0.64, 1)` to approximate
  spring physics
- `MutationObserver` from a `<script>` in `st.markdown` does NOT execute
  (innerHTML scripts are no-ops in browsers — this is by design)

Number animations (count-up, ticker) and true spring physics will come
back natively when the SaaS migration (Next.js + motion lib, already
in package.json) ships.

## 6. Coherence invariants — validation script

```python
# 1. Smoke test
from streamlit.testing.v1 import AppTest
at = AppTest.from_file('app.py', default_timeout=60); at.run()
assert not at.exception, at.exception
assert not at.error, at.error

# 2. VL doesn't move on a synthetic DEPOSIT
import data, datetime as dt
ph = data.load_price_history()
vl_before = data.compute_vl_series(ph)["vl"].iloc[-1]
data.add_cash_movement(dt.date.today(), "DEPOSIT", 1000.0)
vl_after = data.compute_vl_series(ph)["vl"].iloc[-1]
assert abs(vl_after - vl_before) < 1e-6, "VL must NOT jump on a deposit"

# 3. No raw color hex outside theme.py
import subprocess
out = subprocess.check_output(
    ['grep', '-rn', '#FF8800', '--include=*.py', '.']
).decode()
# only theme.py and app.py header should reference it

# 4. ETF_COLORS is canonical (no duplicate dict in pro.py)
out = subprocess.check_output(
    ['grep', '-rn', 'ETF_COLORS = {', '--include=*.py', '.']
).decode()
# only theme.py should declare it
```

## 7. Rollback

```bash
git checkout main          # → V15
git checkout va15 -- .     # → restore VA15 from any branch
git checkout va4 -- .      # → VA4 (without VL switch + time-varying tables)
```

VA4 → VA15 is purely additive in terms of files (no rename). Going
back keeps the database / portfolios intact since none of the schema
changed.

## 8. The 18 VA15 commandments

1. Design tokens live in `theme.py` only. No raw hex anywhere else.
2. Every "+/-" or "▲/▼" return uses SUCCESS or DANGER — never ACCENT.
3. Asset → color via `color_for_asset(asset, idx)`.
4. Every distinct section inside a tab gets a `section_head()`.
5. Plotly figures go through `style_plotly()`.
6. Bar charts with outside text → `cliponaxis=False` + 30% x-range pad.
7. `.stPlotlyChart` is `overflow: visible` — fullscreen button must work.
8. Background is STATIC (no animations on body / stAppViewContainer
   pseudo-elements). Other animations (cards, badges, tabs) remain.
9. Streamlit `st.markdown` sanitizes `<script>` — don't waste time on JS.
10. Card / button hover = subtle translateY + accent border + glow (CSS).
11. Dark + Light parity always; toggle in the page header column.
12. Performance metrics on portfolio series ALWAYS use VL (unitized),
    never raw NAV — otherwise flows contaminate the result.
13. Position values and allocation % over historical dates use
    `shares_held_as_of(date)`, never `static.shares` (which is current).
14. Monte Carlo path simulation starts at real NAV in € (snapshot
    ["total_value"]) but calibrates GBM on VL returns.
15. Displayed "Annualized Return" uses the geometric / EAR formula
    `(1+r).prod()^(252/n) - 1`. Sharpe / Sortino keep arithmetic
    × 252 / × √252 (textbook).
16. Correlation matrix is pairwise (`rets.corr()` on raw pct_change),
    hover shows ρ AND n_obs.
17. Currency cells always show the right symbol — Price column native,
    Total / Σ / NAV / Value in pf_ccy.
18. Owner speaks French — reply in French.
