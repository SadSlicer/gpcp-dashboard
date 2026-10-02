# GPCP Dashboard — VA1 Design System

Synthèse des recommandations du skill `ui-ux-pro-max` combinées avec
l'identité existante (orange `#FF8800` = brand GPCP, à conserver).

**Cible esthétique** : Bloomberg Terminal × Linear × Stripe Dashboard
— dark mode dense, monospace pour les chiffres, hiérarchie typographique
nette, animations subtiles, WCAG AA.

---

## 1. Pattern & Style

| Dimension | Choix | Source |
|---|---|---|
| Pattern | **Real-Time / Operations** | Skill — fits a portfolio tracker with live prices |
| Style | **Data-Dense Dashboard** (WCAG AA, dark+light) | Skill |
| Mood | corporate, trustworthy, professional, technical, precision | Skill (Financial Trust + Terminal CLI) |
| Modes | Dark (default) + Light, parité totale | Skill recommendation |

---

## 2. Color tokens

### Dark mode (default)

| Token | Value | Usage |
|---|---|---|
| `--bg-base` | `#0A0E14` | Background page (légèrement bleuté, pas du noir pur) |
| `--bg-surface` | `#11161D` | Cards, panels, tab background |
| `--bg-elevated` | `#1A2029` | Hover state cards, modals, popovers |
| `--bg-input` | `#0D1218` | Inputs, selects, textareas |
| `--border-subtle` | `#1F2730` | Cell borders, table dividers |
| `--border-default` | `#2A3340` | Card borders, focus rings |
| `--border-strong` | `#3D4654` | Selected, active states |
| `--text-primary` | `#E8ECF1` | Body text, table cells |
| `--text-secondary` | `#A1ABBA` | Sub-labels, descriptions |
| `--text-muted` | `#6B7585` | Tertiary, captions, timestamps |
| `--text-disabled` | `#3D4654` | Disabled states |
| `--accent` | `#FF8800` | **GPCP brand orange** (CTAs, headlines, focus) |
| `--accent-hover` | `#FF9933` | Lighter on hover |
| `--accent-subtle` | `#FF880022` | Subtle highlight bg (e.g. selected row) |
| `--success` | `#10B981` | Positive returns, deposits, success toasts (emerald, pas teal) |
| `--success-bg` | `#10B98115` | Success row highlight |
| `--danger` | `#F43F5E` | Negative returns, withdrawals, errors (rose, pas red plat) |
| `--danger-bg` | `#F43F5E15` | Danger row highlight |
| `--info` | `#3B82F6` | Neutral info, links |
| `--warning` | `#F59E0B` | Warnings, FX disclaimers |

### Light mode (parité)

| Token | Value |
|---|---|
| `--bg-base` | `#F6F8FB` |
| `--bg-surface` | `#FFFFFF` |
| `--bg-elevated` | `#FAFBFD` |
| `--border-subtle` | `#E5E9F0` |
| `--border-default` | `#CDD4DE` |
| `--text-primary` | `#0F172A` |
| `--text-secondary` | `#475569` |
| `--text-muted` | `#94A3B8` |
| `--accent` | `#E67700` (orange, contrasté pour fond clair) |
| `--success` | `#059669` |
| `--danger` | `#DC2626` |

### Palette ETF (graphs)
Une palette catégorielle accessible, max contraste mutuel, daltonien-safe :

| ETF | Couleur | Hex |
|---|---|---|
| S&P 500 | Orange (brand) | `#FF8800` |
| Emerging ESG | Emerald | `#10B981` |
| Stoxx 600 | Sky | `#0EA5E9` |
| Russel 2000 | Violet | `#A855F7` |
| NASDAQ | Amber | `#FBBF24` |
| IBEX | Rose | `#F43F5E` |
| TOPIX | Lime | `#84CC16` |
| Cash | Slate | `#64748B` |

---

## 3. Typography

Pairing **Financial Trust + Tabular Numbers** :

```css
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');
```

| Rôle | Font | Notes |
|---|---|---|
| Body / labels / headings | `IBM Plex Sans` | Skill: "Excellent for data, conveys trust" |
| Chiffres / prix / KPI values | `JetBrains Mono` | `font-variant-numeric: tabular-nums` |
| Code / IDs / tickers | `JetBrains Mono` | Letters too, for monospace ID/ISIN/ticker |

### Type scale (rem-based, 16px = 1rem)

| Token | Size | Line | Weight | Usage |
|---|---|---|---|---|
| `--text-xs` | 11px | 1.4 | 500 | Section headers caps, labels |
| `--text-sm` | 13px | 1.5 | 400 | Sub-labels, captions |
| `--text-base` | 14px | 1.5 | 400 | Body, table cells |
| `--text-md` | 16px | 1.5 | 500 | Form inputs, primary body |
| `--text-lg` | 18px | 1.4 | 600 | Section titles |
| `--text-xl` | 24px | 1.3 | 600 | Page section H |
| `--text-2xl` | 32px | 1.2 | 700 | KPI values |
| `--text-3xl` | 40px | 1.15 | 700 | Hero NAV / brand |

### Tabular-num enforcement
Toutes les colonnes numériques :
```css
.tabular { font-variant-numeric: tabular-nums; font-family: var(--font-mono); }
```

---

## 4. Spacing scale (4pt grid)

| Token | Value | Usage |
|---|---|---|
| `--space-0` | 0 | — |
| `--space-1` | 4px | Inline gaps |
| `--space-2` | 8px | Inner padding tight |
| `--space-3` | 12px | Default padding cells |
| `--space-4` | 16px | Card padding S |
| `--space-5` | 20px | — |
| `--space-6` | 24px | Card padding M, section gap S |
| `--space-8` | 32px | Card padding L, section gap M |
| `--space-10` | 40px | Section gap L |
| `--space-12` | 48px | Hero spacing |
| `--space-16` | 64px | Page gutters |

---

## 5. Radius

| Token | Value | Usage |
|---|---|---|
| `--radius-sm` | 4px | Inputs, buttons, badges |
| `--radius-md` | 8px | Cards, panels |
| `--radius-lg` | 12px | Modals, hero cards |
| `--radius-pill` | 999px | Tags, pills |

---

## 6. Elevation (shadows)

Discret — pas de drop-shadow lourd type Material. Borders d'abord, shadow ensuite.

```css
--shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.3);
--shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.4), 0 2px 4px -2px rgba(0, 0, 0, 0.3);
--shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.5), 0 4px 6px -4px rgba(0, 0, 0, 0.4);
--shadow-focus: 0 0 0 3px rgba(255, 136, 0, 0.25);   /* accent ring */
```

---

## 7. Motion

| Token | Value | Usage |
|---|---|---|
| `--duration-fast` | 120ms | Micro feedback (hover color, focus ring) |
| `--duration-base` | 180ms | Default transitions |
| `--duration-slow` | 250ms | Modal in/out, tab content fade |
| `--ease-out` | `cubic-bezier(0.22, 1, 0.36, 1)` | Default easing (skill: ease-out for entering) |
| `--ease-in` | `cubic-bezier(0.55, 0, 0.95, 0.55)` | For exit animations (~60% duration of enter) |

Règles (skill) :
- Animer `transform` + `opacity` uniquement (jamais width/height/top/left)
- Respect `prefers-reduced-motion`
- Exit animations 60-70% de la durée de l'enter
- Skeleton loaders dès qu'une opération > 300ms

---

## 8. Component patterns (recettes)

### KPI Card
```
┌─────────────────────────────┐
│ DAILY RETURN          [pill]│   ← label CAPS, text-xs, muted
│                             │
│ −0.27 %                     │   ← value, text-2xl, mono, semantic color
│                             │
│ ▼ −0,18 €                   │   ← context, text-sm, muted or semantic
└─────────────────────────────┘
   bg-surface, border-default, radius-md, padding 6, shadow-sm
```

### Tab navigation
- Horizontal pills sans background
- Active = underline 2px accent + text-primary bold
- Inactive = text-secondary
- Hover = text-primary, no underline
- Focus visible = ring accent

### DataFrame styling (Streamlit Styler)
- Header : bg-base, text-xs muted CAPS, letter-spacing 0.5px
- Cells : text-base mono pour nombres, sans pour text
- Row hover : bg-elevated, transition 120ms
- Borders : border-subtle entre rangées, aucun vertical
- Signed values : success/danger color + font-weight 600

### Plotly theme (financial)
- Background : transparent (laisse le bg-surface du parent)
- Grid : `--border-subtle` à 30% opacity
- Axis lines : hidden
- Tick labels : text-muted, mono
- Tooltips : bg-elevated, border-default, radius-md, shadow-md
- Line widths : 2px (data lines), 1px (reference lines)

### Forms
- Inputs : bg-input, border-default, radius-sm, padding 3
- Focus : border-accent + shadow-focus
- Labels : text-xs CAPS muted above
- Helper text : text-xs muted below
- Primary button : bg-accent text-on-accent, hover bg-accent-hover
- Secondary : bg-transparent border-default text-primary

---

## 9. Hierarchy & layout

- **Header** (sticky top, h=64px) : brand + portfolio name + version badge + theme toggle
- **Status bar** (h=48px, sous header) : NAV | Day P&L | VL | source | timestamp — tous en mono
- **Action bar** (h=56px) : Refresh & Save button + filtres globaux
- **Tab nav** (h=48px)
- **Content** : padding-x 16 (mobile) → 32 (desktop), max-width 1440px
- **Section spacing** : space-10 entre sections, space-6 entre éléments d'une section

Mobile-first :
- Stack vertical < 768px
- KPI cards 2 colonnes < 1024px, 4 sinon
- DataFrames : horizontal scroll wrapper

---

## 10. Anti-patterns (à éviter, source : skill)

- ❌ Emoji utilisé comme icône structurelle (utiliser SVG Heroicons/Lucide)
- ❌ Color-only semantics (les ▲▼ + chiffres + couleur, jamais couleur seule)
- ❌ Animations décoratives sans signification
- ❌ Drop-shadow lourd "Material"
- ❌ Width/height animations (perf)
- ❌ Tables horizontalement débordantes sans scroll wrapper
- ❌ Placeholder utilisé comme label
- ❌ Hover-only interactions critiques (touch)
- ❌ Focus rings invisibles ou supprimés
- ❌ Tracking serré sur du body text

---

## 11. Implementation plan (résumé)

| Surface | Fichier | Priorité |
|---|---|---|
| Design tokens centralisés | `theme.py` (nouveau) + `.streamlit/config.toml` | 1 |
| Global CSS injection | `app.py` (remplace CUSTOM_CSS) | 1 |
| Header + status bar | `app.py` | 2 |
| Tab navigation | `app.py` (Streamlit native + CSS override) | 3 |
| KPI cards (kpi()) | `app.py` | 4 |
| DataFrames Styler | `app.py` (Positions, Price History x3, Transactions) | 5 |
| Plotly theme | nouveau helper dans `theme.py`, utilisé partout | 6 |
| Forms | `app.py` (new tx, new asset, settings) | 7 |
| Delete tx confirmation | `app.py` | 8 |
| Pro tab sub-tabs | `pro.py` (uniquement rendu, pas calculs) | 9 |

---

## 12. Pre-delivery checklist (skill)

- [ ] No emojis as icons (SVG only)
- [ ] cursor-pointer on all clickable
- [ ] Hover states 120-250ms
- [ ] Contrast ratio ≥ 4.5:1 verified
- [ ] Focus states visible
- [ ] `prefers-reduced-motion` respected
- [ ] Responsive: 375 / 768 / 1024 / 1440
- [ ] Tabular-num on all numeric columns
- [ ] Loading skeleton for >300ms operations
- [ ] Dark + Light mode parity verified
- [ ] All V15 functional invariants preserved (tabs, KPIs, forms, charts, calculations)
