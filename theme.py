"""VA1 v3 — Design tokens + CSS + Plotly theme.

Premium dark, orange brand (#FF8800) as the accent everywhere.
Linear-grade structure, glassmorphism, 3 card variants, section heads
with accent bar, tab-switch fade-up animation, fixed chart sizing.

Pure design layer — no business logic.
"""

from __future__ import annotations

from dataclasses import dataclass

import plotly.graph_objects as go


# ----------------------------------------------------------------------
# Tokens
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class Tokens:
    BG_DEEP: str
    BG_BASE: str
    BG_ELEVATED: str
    BG_INPUT: str
    SURFACE_1: str
    SURFACE_2: str
    SURFACE_HOVER: str
    BORDER_1: str
    BORDER_2: str
    BORDER_3: str
    TEXT_PRIMARY: str
    TEXT_SECONDARY: str
    TEXT_MUTED: str
    TEXT_FAINT: str
    TEXT_DISABLED: str
    ACCENT: str
    ACCENT_SOFT: str
    ACCENT_DEEP: str
    ACCENT_GLOW: str
    ACCENT_TINT: str
    ACCENT_BORDER: str
    ACCENT_ON: str        # text color ON accent button
    BRAND: str            # = ACCENT in VA1 v3 (orange brand restored)
    BRAND_GLOW: str
    DANGER: str
    DANGER_GLOW: str
    SUCCESS: str          # universal green for positive performance
    SUCCESS_GLOW: str
    INFO: str
    GRAD_BRAND_LOGO: str
    GRAD_TEXT_UP: str
    GRAD_TEXT_DOWN: str
    GRAD_AMBIENT: str
    GRAD_DIVIDER: str     # horizontal accent-fading line


DARK = Tokens(
    # VA1 v3: deeper charcoal (less pure black) + cool gray undertone for
    # a richer, less harsh background. Animated gradient layered above.
    BG_DEEP        = "#10131A",
    BG_BASE        = "#13161E",
    BG_ELEVATED    = "#1A1E27",
    BG_INPUT       = "#15181F",
    SURFACE_1      = "rgba(255, 255, 255, 0.025)",
    SURFACE_2      = "rgba(255, 255, 255, 0.045)",
    SURFACE_HOVER  = "rgba(255, 255, 255, 0.07)",
    BORDER_1       = "rgba(255, 255, 255, 0.06)",
    BORDER_2       = "rgba(255, 255, 255, 0.10)",
    BORDER_3       = "rgba(255, 255, 255, 0.16)",
    TEXT_PRIMARY   = "#F4F5F7",
    TEXT_SECONDARY = "#B4B7BD",
    TEXT_MUTED     = "#7A7D85",
    TEXT_FAINT     = "#4D5058",
    TEXT_DISABLED  = "#34363D",
    ACCENT         = "#FF8800",
    ACCENT_SOFT    = "#FFA42E",
    ACCENT_DEEP    = "#CC6D00",
    ACCENT_GLOW    = "rgba(255, 136, 0, 0.32)",
    ACCENT_TINT    = "rgba(255, 136, 0, 0.12)",
    ACCENT_BORDER  = "rgba(255, 136, 0, 0.30)",
    ACCENT_ON      = "#1A0F00",
    BRAND          = "#FF8800",
    BRAND_GLOW     = "rgba(255, 136, 0, 0.35)",
    DANGER         = "#F25068",
    DANGER_GLOW    = "rgba(242, 80, 104, 0.32)",
    SUCCESS        = "#10D982",
    SUCCESS_GLOW   = "rgba(16, 217, 130, 0.30)",
    INFO           = "#5E6AD2",
    GRAD_BRAND_LOGO = "linear-gradient(135deg, #FFA42E 0%, #FF6B00 100%)",
    GRAD_TEXT_UP   = "linear-gradient(135deg, #1FE89A 0%, #10D982 100%)",
    GRAD_TEXT_DOWN = "linear-gradient(135deg, #F25068 0%, #C53E54 100%)",
    GRAD_AMBIENT   = (
        # Layered radial gradients — animated via the .va1-bg layer (CSS)
        "radial-gradient(ellipse 1400px 800px at 20% 10%, "
        "rgba(255,136,0,0.10) 0%, transparent 55%), "
        "radial-gradient(ellipse 1000px 700px at 85% 50%, "
        "rgba(94,106,210,0.08) 0%, transparent 55%), "
        "radial-gradient(ellipse 900px 600px at 40% 90%, "
        "rgba(180,183,189,0.05) 0%, transparent 55%)"
    ),
    GRAD_DIVIDER   = (
        "linear-gradient(90deg, rgba(255,136,0,0.35) 0%, "
        "rgba(255,136,0,0.10) 30%, transparent 100%)"
    ),
)

LIGHT = Tokens(
    BG_DEEP        = "#F6F8FB",
    BG_BASE        = "#FFFFFF",
    BG_ELEVATED    = "#FAFBFD",
    BG_INPUT       = "#FFFFFF",
    SURFACE_1      = "rgba(15, 23, 42, 0.02)",
    SURFACE_2      = "rgba(15, 23, 42, 0.04)",
    SURFACE_HOVER  = "rgba(15, 23, 42, 0.06)",
    BORDER_1       = "rgba(15, 23, 42, 0.06)",
    BORDER_2       = "rgba(15, 23, 42, 0.10)",
    BORDER_3       = "rgba(15, 23, 42, 0.16)",
    TEXT_PRIMARY   = "#0F172A",
    TEXT_SECONDARY = "#475569",
    TEXT_MUTED     = "#94A3B8",
    TEXT_FAINT     = "#CBD5E1",
    TEXT_DISABLED  = "#E2E8F0",
    ACCENT         = "#E67700",
    ACCENT_SOFT    = "#FF8800",
    ACCENT_DEEP    = "#B85F00",
    ACCENT_GLOW    = "rgba(230, 119, 0, 0.28)",
    ACCENT_TINT    = "rgba(230, 119, 0, 0.10)",
    ACCENT_BORDER  = "rgba(230, 119, 0, 0.30)",
    ACCENT_ON      = "#FFFFFF",
    BRAND          = "#E67700",
    BRAND_GLOW     = "rgba(230, 119, 0, 0.28)",
    DANGER         = "#DC2626",
    DANGER_GLOW    = "rgba(220, 38, 38, 0.28)",
    SUCCESS        = "#059669",
    SUCCESS_GLOW   = "rgba(5, 150, 105, 0.28)",
    INFO           = "#4F46E5",
    GRAD_BRAND_LOGO = "linear-gradient(135deg, #FFA42E 0%, #FF6B00 100%)",
    GRAD_TEXT_UP   = "linear-gradient(135deg, #10D982 0%, #059669 100%)",
    GRAD_TEXT_DOWN = "linear-gradient(135deg, #F25068 0%, #DC2626 100%)",
    GRAD_AMBIENT   = (
        "radial-gradient(ellipse 1200px 600px at 50% -10%, "
        "rgba(230,119,0,0.05) 0%, transparent 60%), "
        "radial-gradient(ellipse 800px 600px at 100% 100%, "
        "rgba(79,70,229,0.04) 0%, transparent 60%)"
    ),
    GRAD_DIVIDER   = (
        "linear-gradient(90deg, rgba(230,119,0,0.30) 0%, "
        "rgba(230,119,0,0.10) 30%, transparent 100%)"
    ),
)


def tokens_for(theme: str) -> Tokens:
    return LIGHT if theme == "light" else DARK


# ----------------------------------------------------------------------
# ETF palette — S&P 500 = brand orange. Others spread across hue wheel
# avoiding direct conflict with accent and avoiding any pair too close.
# ----------------------------------------------------------------------

ETF_COLORS = {
    "S&P 500":      "#FF8800",  # brand orange (the headline ETF)
    "NASDAQ":       "#06B6D4",  # cyan
    "Stoxx 600":    "#6366F1",  # indigo
    "Russel 2000":  "#A855F7",  # violet
    "Emerging ESG": "#10D982",  # emerald (freed from accent role)
    "IBEX":         "#F25068",  # rose
    "TOPIX":        "#FBBF24",  # amber
    "Cash":         "#64748B",  # slate
}


def color_for_asset(asset: str, idx: int = 0) -> str:
    if asset in ETF_COLORS:
        return ETF_COLORS[asset]
    fallback = ["#FF8800", "#06B6D4", "#6366F1", "#A855F7",
                "#10D982", "#F25068", "#FBBF24", "#EC4899", "#14B8A6"]
    return fallback[idx % len(fallback)]


# ----------------------------------------------------------------------
# CSS generator
# ----------------------------------------------------------------------

def build_css(theme: str = "dark") -> str:
    t = tokens_for(theme)

    return f"""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');

  :root {{
    --bg-deep:        {t.BG_DEEP};
    --bg-base:        {t.BG_BASE};
    --bg-elevated:    {t.BG_ELEVATED};
    --bg-input:       {t.BG_INPUT};
    --surface-1:      {t.SURFACE_1};
    --surface-2:      {t.SURFACE_2};
    --surface-hover:  {t.SURFACE_HOVER};
    --border-1: {t.BORDER_1};
    --border-2: {t.BORDER_2};
    --border-3: {t.BORDER_3};
    --text-primary:   {t.TEXT_PRIMARY};
    --text-secondary: {t.TEXT_SECONDARY};
    --text-muted:     {t.TEXT_MUTED};
    --text-faint:     {t.TEXT_FAINT};
    --text-disabled:  {t.TEXT_DISABLED};
    --accent:         {t.ACCENT};
    --accent-soft:    {t.ACCENT_SOFT};
    --accent-deep:    {t.ACCENT_DEEP};
    --accent-glow:    {t.ACCENT_GLOW};
    --accent-tint:    {t.ACCENT_TINT};
    --accent-border:  {t.ACCENT_BORDER};
    --accent-on:      {t.ACCENT_ON};
    --brand:          {t.BRAND};
    --brand-glow:     {t.BRAND_GLOW};
    --danger:         {t.DANGER};
    --success:        {t.SUCCESS};
    --grad-up:        {t.GRAD_TEXT_UP};
    --grad-down:      {t.GRAD_TEXT_DOWN};
    --grad-brand-logo: {t.GRAD_BRAND_LOGO};
    --grad-divider:   {t.GRAD_DIVIDER};
    --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    --font-mono: 'JetBrains Mono', 'SF Mono', Menlo, monospace;
    --r-xs: 4px; --r-sm: 6px; --r-md: 8px; --r-lg: 12px; --r-xl: 16px;
    --ease: cubic-bezier(0.16, 1, 0.3, 1);
    --shadow-1: 0 1px 2px rgba(0,0,0,0.4);
    --shadow-2: 0 4px 12px rgba(0,0,0,0.3), 0 1px 3px rgba(0,0,0,0.25);
    --shadow-3: 0 24px 48px rgba(0,0,0,0.5), 0 4px 12px rgba(0,0,0,0.3);
    --shadow-glow-accent: 0 0 24px {t.ACCENT_GLOW};
    --focus-ring: 0 0 0 3px {t.ACCENT_GLOW};
  }}

  html, body {{
    background: {t.BG_DEEP} !important;
    color: var(--text-primary);
    font-family: var(--font-sans);
    font-size: 14px; line-height: 1.55; letter-spacing: -0.005em;
    -webkit-font-smoothing: antialiased;
    position: relative;
    min-height: 100%;
  }}
  [data-testid="stAppViewContainer"], .stApp {{
    background: transparent !important;
    color: var(--text-primary);
    position: relative;
    z-index: 2;
    transform: translateZ(0);   /* force compositing layer */
  }}
  ::selection {{ background: var(--accent-tint); color: var(--text-primary); }}

  /* ============================================================
     VA3 — 4 stacked always-on background layers
     Aurora-style flowing whites + orange/indigo drift + slow rotate
     ============================================================ */

  /* Layer 1 — orange/indigo/gray drift (slower, less prominent) */
  body::before {{
    content: '';
    position: fixed; inset: -10%;
    z-index: 0; pointer-events: none;
    background: {t.GRAD_AMBIENT};
    background-size: 130% 130%;
    animation: va3-bg-drift 30s ease-in-out infinite alternate;
    will-change: transform;
    transform: translate3d(0, 0, 0);
    contain: strict;
  }}

  /* Layer 2 — RENFORCÉ — 4 white/gray blobs with bigger amplitude */
  body::after {{
    content: '';
    position: fixed; inset: -25%;
    z-index: 1; pointer-events: none;
    background:
      radial-gradient(circle 520px at 20% 25%, rgba(255,255,255,0.085) 0%, transparent 55%),
      radial-gradient(circle 640px at 80% 70%, rgba(220,225,235,0.075) 0%, transparent 55%),
      radial-gradient(circle 420px at 55% 15%, rgba(255,255,255,0.06) 0%, transparent 60%),
      radial-gradient(circle 480px at 35% 85%, rgba(200,210,225,0.055) 0%, transparent 55%);
    filter: blur(6px);
    mix-blend-mode: screen;
    animation: va3-bg-orbit 36s ease-in-out infinite alternate;
    will-change: transform;
    transform: translate3d(0, 0, 0);
    contain: strict;
  }}

  /* Layer 3 — slow conic gray sweep (perceptible always-on rotation, blur reduced for perf) */
  [data-testid="stAppViewContainer"]::before {{
    content: '';
    position: fixed; inset: -30%;
    z-index: 0; pointer-events: none;
    background: conic-gradient(
      from 0deg at 50% 50%,
      rgba(255,255,255,0.04) 0deg,
      transparent 60deg,
      rgba(200,210,220,0.05) 140deg,
      transparent 220deg,
      rgba(255,255,255,0.035) 300deg,
      transparent 360deg
    );
    filter: blur(35px);
    animation: va3-bg-rotate 80s linear infinite;
    will-change: transform;
    transform: translate3d(0, 0, 0);
    transform-origin: 50% 50%;
    contain: strict;
  }}

  /* Layer 4 — NEW VA3 — aurora wave flowing across the entire viewport
     via background-position (cheap composite, no filter blur) */
  [data-testid="stAppViewContainer"]::after {{
    content: '';
    position: fixed; inset: 0;
    z-index: 1; pointer-events: none;
    background:
      radial-gradient(ellipse 60% 40% at 25% 50%, rgba(255,255,255,0.07) 0%, transparent 60%),
      radial-gradient(ellipse 50% 35% at 75% 30%, rgba(230,235,245,0.06) 0%, transparent 60%),
      radial-gradient(ellipse 55% 30% at 50% 80%, rgba(255,255,255,0.05) 0%, transparent 60%);
    background-size: 260% 260%;
    background-repeat: no-repeat;
    mix-blend-mode: screen;
    animation: va3-bg-flow 22s ease-in-out infinite alternate;
    will-change: background-position;
    transform: translate3d(0, 0, 0);
    contain: strict;
  }}

  @keyframes va3-bg-drift {{
    0%   {{ transform: translate3d(0, 0, 0) scale(1); opacity: 0.9; }}
    50%  {{ transform: translate3d(30px, -20px, 0) scale(1.05); opacity: 1; }}
    100% {{ transform: translate3d(-25px, 30px, 0) scale(0.98); opacity: 0.92; }}
  }}
  @keyframes va3-bg-orbit {{
    0%   {{ transform: translate3d(0, 0, 0) rotate(0deg) scale(1); }}
    50%  {{ transform: translate3d(-140px, 110px, 0) rotate(6deg) scale(1.10); }}
    100% {{ transform: translate3d(120px, -90px, 0) rotate(-5deg) scale(0.94); }}
  }}
  @keyframes va3-bg-rotate {{
    from {{ transform: translate3d(0, 0, 0) rotate(0deg); }}
    to   {{ transform: translate3d(0, 0, 0) rotate(360deg); }}
  }}
  @keyframes va3-bg-flow {{
    0%   {{ background-position: 0% 0%, 100% 100%, 50% 50%; }}
    50%  {{ background-position: 100% 50%, 0% 50%, 80% 20%; }}
    100% {{ background-position: 50% 100%, 50% 0%, 20% 80%; }}
  }}

  #MainMenu, footer, [data-testid="stToolbar"] {{ visibility: hidden; height: 0; }}
  [data-testid="stHeader"] {{ background: transparent; height: 0; }}

  .block-container {{
    padding-top: 1.2rem !important;
    padding-bottom: 3rem !important;
    max-width: 1400px !important;
  }}

  /* ============================================================
     HEADER
     ============================================================ */
  .va1-header {{
    display: flex; justify-content: space-between; align-items: center;
    padding: 14px 0;
    margin-bottom: 4px;
    border-bottom: 1px solid var(--border-1);
    animation: va1-enter 0.5s var(--ease) both;
  }}
  .va1-brand {{ display: flex; align-items: center; gap: 12px; }}
  .va1-brand-logo {{
    width: 32px; height: 32px; border-radius: 8px;
    background: var(--grad-brand-logo);
    display: grid; place-items: center;
    font-weight: 800; font-size: 14px; color: white;
    box-shadow: 0 4px 12px var(--brand-glow), inset 0 1px 0 rgba(255,255,255,0.25);
  }}
  .va1-brand-name {{ font-size: 15px; font-weight: 600; letter-spacing: -0.01em; color: var(--text-primary); }}
  .va1-brand-divider {{ width: 1px; height: 18px; background: var(--border-2); margin: 0 6px; }}
  .va1-brand-tag {{ font-size: 12px; color: var(--text-secondary); font-weight: 500; }}
  .va1-pill {{
    display: inline-flex; align-items: center; gap: 6px;
    padding: 5px 10px; border-radius: 999px;
    background: var(--surface-1); border: 1px solid var(--border-1);
    font-size: 11px; color: var(--text-secondary);
    font-weight: 500; font-family: var(--font-mono);
    transition: all 180ms var(--ease);
  }}
  .va1-pill:hover {{ background: var(--surface-2); border-color: var(--border-2); }}
  .va1-pill-dot {{
    width: 6px; height: 6px; border-radius: 50%;
    background: var(--accent);
    box-shadow: 0 0 6px var(--accent-glow);
    animation: va1-pulse 2s ease-in-out infinite;
  }}
  @keyframes va1-pulse {{
    0%, 100% {{ opacity: 1; transform: scale(1); }}
    50% {{ opacity: 0.6; transform: scale(0.85); }}
  }}

  /* ============================================================
     STATUS BAR
     ============================================================ */
  .va1-status {{
    display: flex; gap: 28px; align-items: center;
    padding: 14px 4px 18px 4px;
    flex-wrap: wrap;
    animation: va1-enter 0.5s var(--ease) 0.05s both;
  }}
  .va1-status-item {{ display: flex; flex-direction: column; gap: 2px; }}
  .va1-status-label {{
    font-size: 10px; color: var(--text-muted);
    text-transform: uppercase; letter-spacing: 0.08em;
    font-weight: 500;
  }}
  .va1-status-value {{
    font-family: var(--font-mono); font-variant-numeric: tabular-nums;
    font-size: 15px; color: var(--text-primary); font-weight: 500;
  }}
  .va1-status-value.up   {{ color: var(--success); }}
  .va1-status-value.down {{ color: var(--danger); }}
  .va1-status-sep {{ width: 1px; height: 28px; background: var(--border-1); }}

  /* ============================================================
     NAV HERO (Overview only) — large NAV + meta + sparkline
     ============================================================ */
  .va1-hero {{
    display: grid; grid-template-columns: 1fr auto; gap: 28px;
    align-items: center;
    padding: 28px 32px;
    margin-bottom: 32px;
    background: var(--bg-elevated);
    border: 1px solid var(--border-2);
    border-radius: var(--r-lg);
    position: relative; overflow: hidden;
    animation: va1-enter 0.6s var(--ease) 0.10s both;
  }}
  .va1-hero::before {{
    content: ''; position: absolute; inset: 0;
    background: radial-gradient(circle at 0% 0%, var(--accent-tint), transparent 50%);
    opacity: 0.6; pointer-events: none;
  }}
  .va1-hero-label {{
    font-size: 11px; font-weight: 600; letter-spacing: 0.1em;
    color: var(--text-muted); text-transform: uppercase;
    display: inline-flex; gap: 8px; align-items: center;
    margin-bottom: 10px; position: relative; z-index: 1;
  }}
  .va1-hero-label::before {{
    content: ''; width: 24px; height: 2px;
    background: linear-gradient(90deg, var(--accent), transparent);
    border-radius: 1px;
  }}
  .va1-hero-nav {{
    font-family: var(--font-mono); font-variant-numeric: tabular-nums;
    font-size: 48px; font-weight: 600;
    line-height: 1; letter-spacing: -0.03em;
    color: var(--text-primary);
    position: relative; z-index: 1;
  }}
  .va1-hero-meta {{
    display: flex; gap: 22px; margin-top: 18px; align-items: center;
    flex-wrap: wrap;
    position: relative; z-index: 1;
  }}
  .va1-hero-pill {{
    display: inline-flex; flex-direction: column; gap: 2px;
    padding: 8px 14px;
    background: var(--surface-1);
    border: 1px solid var(--border-1);
    border-radius: var(--r-md);
  }}
  .va1-hero-pill-label {{
    font-size: 10px; color: var(--text-muted);
    text-transform: uppercase; letter-spacing: 0.08em; font-weight: 500;
  }}
  .va1-hero-pill-value {{
    font-family: var(--font-mono); font-variant-numeric: tabular-nums;
    font-size: 14px; color: var(--text-primary); font-weight: 500;
  }}
  .va1-hero-pill-value.up   {{ color: var(--success); }}
  .va1-hero-pill-value.down {{ color: var(--danger); }}
  .va1-hero-spark {{
    width: 280px; height: 90px; position: relative; z-index: 1;
  }}

  /* ============================================================
     CARDS — 3 variants
     ============================================================ */
  /* Default: subtle surface, used for most blocks */
  .va1-card {{
    background: var(--surface-1);
    border: 1px solid var(--border-1);
    border-radius: var(--r-lg);
    padding: 22px 24px;
    margin-bottom: 28px;
    transition: border-color 180ms var(--ease);
    animation: va1-enter 0.5s var(--ease) 0.15s both;
    contain: layout style;
  }}
  .va1-card:hover {{ border-color: var(--border-2); }}

  /* Elevated: more prominent — NAV hero already its own, this is for forms / key actions */
  .va1-card-elevated {{
    background: var(--bg-elevated);
    border: 1px solid var(--border-2);
    border-radius: var(--r-lg);
    padding: 24px 26px;
    margin-bottom: 28px;
    box-shadow: var(--shadow-2);
    transition: border-color 180ms var(--ease), box-shadow 180ms var(--ease);
    animation: va1-enter 0.5s var(--ease) 0.20s both;
    contain: layout style;
  }}
  .va1-card-elevated:hover {{ border-color: var(--border-3); }}

  /* Inset: visually recessed, used for secondary data (delete block, sub-tables) */
  .va1-card-inset {{
    background: var(--bg-base);
    border: 1px solid var(--border-1);
    border-radius: var(--r-lg);
    padding: 20px 22px;
    margin-bottom: 28px;
    box-shadow: inset 0 1px 0 rgba(0,0,0,0.15);
  }}

  /* ============================================================
     SECTION HEAD — accent vertical bar + title + sub + divider
     ============================================================ */
  .va1-section-head {{
    display: flex; align-items: flex-start; gap: 12px;
    margin: 36px 0 14px 0;
    padding-left: 0;
  }}
  .va1-section-head:first-child {{ margin-top: 8px; }}
  .va1-section-bar {{
    width: 3px;
    align-self: stretch;
    background: var(--accent);
    border-radius: 2px;
    box-shadow: 0 0 8px var(--accent-glow);
    min-height: 32px;
  }}
  .va1-section-text {{ display: flex; flex-direction: column; gap: 2px; }}
  .va1-section-title {{
    font-size: 14px; font-weight: 600;
    color: var(--text-primary);
    text-transform: uppercase; letter-spacing: 0.08em;
  }}
  .va1-section-sub {{
    font-size: 12px; color: var(--text-muted); font-weight: 400;
  }}
  .va1-divider {{
    height: 1px; border: none;
    background: var(--grad-divider);
    margin: 8px 0 18px 0;
  }}

  /* ============================================================
     KPI cards — VA3 perf: GPU layer + contain + explicit transitions
     ============================================================ */
  .kpi-card {{
    position: relative;
    padding: 18px 20px;
    background: var(--surface-1);
    border: 1px solid var(--border-1);
    border-radius: var(--r-lg);
    transition: transform 180ms var(--ease),
                box-shadow 180ms var(--ease),
                border-color 180ms var(--ease),
                background-color 180ms var(--ease);
    overflow: hidden;
    height: 100%;
    opacity: 0; transform: translate3d(0, 12px, 0);
    animation: va1-enter 0.5s var(--ease) forwards;
    will-change: transform;
    contain: layout style paint;
  }}
  .kpi-card:hover {{
    background: var(--surface-2);
    border-color: var(--border-3);
    transform: translate3d(0, -3px, 0) scale(1.005);
    box-shadow: 0 8px 22px rgba(0,0,0,0.35),
                0 0 0 1px var(--accent-tint);
  }}
  .kpi-card::before {{
    content: ''; position: absolute; inset: 0; border-radius: inherit;
    padding: 1px;
    background: linear-gradient(135deg, var(--accent-tint), transparent 60%);
    -webkit-mask: linear-gradient(#000,#000) content-box, linear-gradient(#000,#000);
    -webkit-mask-composite: xor; mask-composite: exclude;
    opacity: 0; transition: opacity 250ms var(--ease); pointer-events: none;
  }}
  .kpi-card:hover::before {{ opacity: 1; }}
  .kpi-label {{
    display: flex; justify-content: space-between; align-items: center;
    font-size: 11px; font-weight: 500; color: var(--text-muted);
    text-transform: uppercase; letter-spacing: 0.06em;
    margin-bottom: 14px;
  }}
  .kpi-badge-live {{
    display: inline-flex; gap: 5px; align-items: center;
    font-size: 9px; font-weight: 700; letter-spacing: 0.06em;
    padding: 2px 7px; border-radius: 999px;
    background: var(--accent-tint); color: var(--accent);
    border: 1px solid var(--accent-border);
    text-transform: uppercase;
  }}
  .kpi-badge-live::before {{
    content: ''; width: 5px; height: 5px; border-radius: 50%;
    background: var(--accent); box-shadow: 0 0 6px var(--accent-glow);
    animation: va1-pulse 2s ease-in-out infinite;
  }}
  .kpi-value {{
    font-family: var(--font-mono); font-variant-numeric: tabular-nums;
    font-size: 26px; font-weight: 600;
    letter-spacing: -0.025em; line-height: 1.1;
    color: var(--text-primary);
  }}
  .kpi-value.up   {{ background: var(--grad-up); -webkit-background-clip: text; background-clip: text; color: transparent; }}
  .kpi-value.down {{ background: var(--grad-down); -webkit-background-clip: text; background-clip: text; color: transparent; }}
  .kpi-delta, .kpi-sub {{
    font-family: var(--font-mono); font-size: 12px;
    color: var(--text-muted); margin-top: 6px;
  }}
  .kpi-delta.up   {{ color: var(--success); }}
  .kpi-delta.down {{ color: var(--danger); }}

  /* ============================================================
     Streamlit overrides
     ============================================================ */

  /* Tabs — bigger, bolder, more legible (VA1 v3) */
  .stTabs [data-baseweb="tab-list"] {{
    gap: 6px;
    background: transparent;
    border-bottom: 1px solid var(--border-1);
    padding: 0;
    border-radius: 0;
    margin-bottom: 28px;
  }}
  .stTabs [data-baseweb="tab"] {{
    background: transparent !important;
    color: var(--text-muted) !important;
    padding: 18px 26px !important;
    font-weight: 500 !important;
    font-size: 15px !important;
    letter-spacing: -0.005em !important;
    text-transform: none !important;
    border-radius: 0 !important;
    border-bottom: 2px solid transparent !important;
    transition: color 200ms var(--ease), border-color 200ms var(--ease), background 200ms var(--ease) !important;
    min-height: 52px !important;
  }}
  .stTabs [data-baseweb="tab"]:hover {{
    color: var(--text-secondary) !important;
    background: var(--surface-1) !important;
  }}
  .stTabs [aria-selected="true"] {{
    background: transparent !important;
    color: var(--text-primary) !important;
    font-weight: 600 !important;
    border-bottom-color: var(--accent) !important;
    /* VA1 v4: removed box-shadow + ::after — was creating a permanent
       orange smear under all tabs. Only the 2px underline remains. */
  }}

  /* TAB TRANSITION ANIMATION — applied via JS observer to re-trigger on switch */
  .stTabs [data-baseweb="tab-panel"] {{
    animation: va1-tab-enter 0.45s var(--ease) both;
  }}
  .stTabs [data-baseweb="tab-panel"].va1-replay {{
    animation: none;
  }}
  .stTabs [data-baseweb="tab-panel"].va1-just-shown {{
    animation: va1-tab-enter 0.45s var(--ease) both;
  }}
  @keyframes va1-tab-enter {{
    from {{ opacity: 0; transform: translateY(14px); filter: blur(2px); }}
    to   {{ opacity: 1; transform: translateY(0); filter: blur(0); }}
  }}
  /* Stagger inside the active panel — direct children of the panel */
  .stTabs [data-baseweb="tab-panel"].va1-just-shown > div > div > div {{
    animation: va1-enter 0.5s var(--ease) both;
  }}

  /* Buttons — VA3: stronger hover affordance + GPU-cheap transitions */
  .stButton > button {{
    background: var(--surface-1);
    color: var(--text-primary);
    border: 1px solid var(--border-1);
    border-radius: var(--r-sm);
    padding: 9px 16px;
    font-weight: 500; font-size: 13px;
    letter-spacing: 0; text-transform: none;
    font-family: var(--font-sans);
    cursor: pointer;
    transition: transform 180ms var(--ease),
                box-shadow 180ms var(--ease),
                border-color 180ms var(--ease),
                background-color 180ms var(--ease);
    will-change: transform;
  }}
  .stButton > button:hover {{
    background: var(--bg-elevated);
    border-color: var(--border-3);
    transform: translate3d(0, -2px, 0) scale(1.01);
    box-shadow: 0 4px 12px rgba(0,0,0,0.35),
                0 0 0 1px var(--accent-tint);
  }}
  .stButton > button:active {{
    transform: translate3d(0, 0, 0) scale(0.99);
    transition-duration: 80ms;
  }}
  .stButton > button:focus,
  .stButton > button:focus-visible {{ outline: none; box-shadow: var(--focus-ring); }}

  .stButton > button[kind="primary"],
  .stButton > button[data-testid="baseButton-primary"] {{
    background: var(--accent) !important;
    color: var(--accent-on) !important;
    border-color: var(--accent-deep) !important;
    font-weight: 600;
    box-shadow: var(--shadow-1), inset 0 1px 0 rgba(255,255,255,0.18) !important;
    position: relative; overflow: hidden;
    will-change: transform;
  }}
  .stButton > button[kind="primary"]:hover,
  .stButton > button[data-testid="baseButton-primary"]:hover {{
    background: var(--accent-soft) !important;
    box-shadow: 0 10px 28px var(--accent-glow),
                0 0 0 1px var(--accent-soft),
                inset 0 1px 0 rgba(255,255,255,0.32) !important;
    transform: translate3d(0, -3px, 0) scale(1.02);
  }}
  .stButton > button[kind="primary"]:active,
  .stButton > button[data-testid="baseButton-primary"]:active {{
    transform: translate3d(0, -1px, 0) scale(0.99);
    transition-duration: 80ms;
  }}

  /* Inputs */
  .stTextInput input, .stNumberInput input, .stDateInput input,
  [data-baseweb="select"] > div, [data-baseweb="input"] > div {{
    background: var(--bg-input) !important;
    border: 1px solid var(--border-1) !important;
    color: var(--text-primary) !important;
    border-radius: var(--r-sm) !important;
    font-family: var(--font-mono) !important;
    font-size: 13px !important;
    transition: all 180ms var(--ease);
  }}
  .stTextInput input:hover, .stNumberInput input:hover, .stDateInput input:hover {{
    border-color: var(--border-2) !important;
  }}
  .stTextInput input:focus, .stNumberInput input:focus, .stDateInput input:focus {{
    border-color: var(--accent) !important;
    box-shadow: var(--focus-ring) !important;
    outline: none !important;
  }}

  label, .stTextInput label, .stNumberInput label, .stSelectbox label,
  .stDateInput label, .stMultiSelect label, .stRadio label, .stCheckbox label {{
    color: var(--text-muted) !important;
    font-size: 11px !important;
    font-weight: 500 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.06em !important;
  }}

  [data-baseweb="select"] {{ font-family: var(--font-sans) !important; }}
  [data-baseweb="select"] > div {{ background: var(--bg-input) !important; }}

  /* DataFrames */
  [data-testid="stDataFrame"], [data-testid="stTable"] {{
    background: var(--surface-1);
    border-radius: var(--r-lg);
    border: 1px solid var(--border-1);
    overflow: hidden;
  }}
  [data-testid="stDataFrame"] td, [data-testid="stTable"] td {{
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
  }}

  /* Plotly chart container — VA1 v4: overflow VISIBLE so axes labels
     are never clipped and the Streamlit native fullscreen button (⛶)
     stays accessible. Padding minimal so the chart uses the space. */
  .stPlotlyChart {{
    background: var(--surface-1);
    border: 1px solid var(--border-1);
    border-radius: var(--r-lg);
    padding: 4px 4px 8px 4px;
    overflow: visible;
    min-width: 0;
  }}
  .stPlotlyChart > div {{ width: 100% !important; min-width: 0 !important; }}
  .js-plotly-plot, .js-plotly-plot .plotly {{ width: 100% !important; }}
  /* Sharper rendering — pixel-aligned via SVG shape-rendering hints */
  .js-plotly-plot svg {{ shape-rendering: geometricPrecision; }}
  /* Streamlit fullscreen button on charts — make sure it stays visible */
  [data-testid="StyledFullScreenButton"] {{
    background: var(--bg-elevated) !important;
    border: 1px solid var(--border-2) !important;
    color: var(--text-primary) !important;
    border-radius: var(--r-sm) !important;
  }}

  /* Metric (st.metric) */
  [data-testid="stMetric"] {{
    background: var(--surface-1);
    border: 1px solid var(--border-1);
    border-radius: var(--r-lg);
    padding: 16px 18px;
    transition: all 200ms var(--ease);
  }}
  [data-testid="stMetric"]:hover {{
    background: var(--surface-2); border-color: var(--border-2);
    transform: translateY(-1px);
  }}
  [data-testid="stMetricLabel"] {{
    color: var(--text-muted) !important;
    font-size: 11px !important; font-weight: 500 !important;
    text-transform: uppercase; letter-spacing: 0.06em;
  }}
  [data-testid="stMetricValue"] {{
    font-family: var(--font-mono) !important;
    font-variant-numeric: tabular-nums;
    color: var(--text-primary) !important;
  }}

  .stAlert {{ border-radius: var(--r-md); border: 1px solid var(--border-1); }}
  [data-testid="stToast"] {{
    background: var(--bg-elevated); border: 1px solid var(--border-2);
    border-radius: var(--r-md); box-shadow: var(--shadow-2);
  }}

  .stMarkdown p, .stMarkdown li {{ color: var(--text-secondary); font-size: 14px; }}
  .stMarkdown h1, .stMarkdown h2, .stMarkdown h3, .stMarkdown h4 {{
    color: var(--text-primary); letter-spacing: -0.02em;
    font-family: var(--font-sans);
  }}

  /* ============================================================
     Animations
     ============================================================ */
  @keyframes va1-enter {{
    from {{ opacity: 0; transform: translateY(8px); }}
    to   {{ opacity: 1; transform: translateY(0); }}
  }}

  [data-testid="column"]:nth-child(1) .kpi-card {{ animation-delay: 0.05s; }}
  [data-testid="column"]:nth-child(2) .kpi-card {{ animation-delay: 0.10s; }}
  [data-testid="column"]:nth-child(3) .kpi-card {{ animation-delay: 0.15s; }}
  [data-testid="column"]:nth-child(4) .kpi-card {{ animation-delay: 0.20s; }}
  [data-testid="column"]:nth-child(5) .kpi-card {{ animation-delay: 0.25s; }}

  @media (prefers-reduced-motion: reduce) {{
    *, *::before, *::after {{
      animation-duration: 0.01ms !important;
      transition-duration: 0.01ms !important;
    }}
  }}

  /* ============================================================
     User-requested override — kill background animations only.
     Surgical: keep the gradient visuals, just stop the motion.
     ============================================================ */
  body::before, body::after,
  [data-testid="stAppViewContainer"]::before,
  [data-testid="stAppViewContainer"]::after {{
    animation: none !important;
  }}
</style>

<script>
// ============================================================
// Tab transition observer — re-triggers va1-just-shown class
// on every tab activation so the entrance animation replays.
// ============================================================
(function() {{
  if (window.__va1TabObserverInstalled) return;
  window.__va1TabObserverInstalled = true;

  function attach() {{
    const panels = document.querySelectorAll('.stTabs [data-baseweb="tab-panel"]');
    panels.forEach(panel => {{
      if (panel.__va1Watched) return;
      panel.__va1Watched = true;
      const obs = new MutationObserver(() => {{
        if (!panel.hidden && panel.offsetParent !== null) {{
          // VA3: re-trigger via rAF to avoid synchronous reflow jank
          panel.classList.remove('va1-just-shown');
          requestAnimationFrame(() => {{
            requestAnimationFrame(() => panel.classList.add('va1-just-shown'));
          }});
        }}
      }});
      obs.observe(panel, {{ attributes: true, attributeFilter: ['hidden', 'aria-hidden', 'style'] }});
    }});
  }}

  // Watch for late-mounted tab panels
  const root = new MutationObserver(attach);
  root.observe(document.body, {{ childList: true, subtree: true }});
  attach();
}})();
</script>
"""


# ----------------------------------------------------------------------
# Plotly theme — VA1 v3 (fixes overflow + compact margins)
# ----------------------------------------------------------------------

def style_plotly(fig: go.Figure, *, theme: str = "dark",
                 height: int = 360, showlegend: bool = True,
                 legend_pos: str = "top-right") -> go.Figure:
    """Apply the VA1 theme to a Plotly figure.

    - Transparent paper/plot so the ambient gradient shows through.
    - Compact margins (no waste of space).
    - Legend repositioned INSIDE the plot top-right (default) to keep
      it inside the container; can be 'bottom' or 'hidden' too.
    - Autosize true so it fills the container width.
    """
    t = tokens_for(theme)

    if legend_pos == "top-right":
        legend = dict(
            bgcolor="rgba(0,0,0,0.0)",
            font=dict(color=t.TEXT_SECONDARY, size=11,
                      family="Inter, sans-serif"),
            orientation="h", yanchor="bottom", y=1.02,
            xanchor="right", x=1,
        )
    elif legend_pos == "bottom":
        legend = dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(color=t.TEXT_SECONDARY, size=11),
            orientation="h", yanchor="top", y=-0.18,
        )
    else:
        legend = dict(visible=False)
        showlegend = False

    # VA1 v4 — generous margins so axis ticks never get clipped by the
    # container padding. Bottom 56 = room for x-tick labels, left 52 =
    # room for y-tick labels (and currency/percent suffixes).
    fig.update_layout(
        autosize=True,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=t.TEXT_SECONDARY,
                  family="Inter, -apple-system, sans-serif", size=12),
        margin=dict(
            l=52, r=24,
            t=48 if showlegend and legend_pos == "top-right" else 28,
            b=56, pad=0,
        ),
        height=height,
        showlegend=showlegend,
        legend=legend,
        hoverlabel=dict(
            bgcolor=t.BG_ELEVATED, bordercolor="rgba(255,136,0,0.4)",
            font=dict(color=t.TEXT_PRIMARY, family="JetBrains Mono"),
        ),
    )
    fig.update_xaxes(
        gridcolor="rgba(255,255,255,0.04)",
        zeroline=False, linecolor="rgba(255,255,255,0)",
        tickcolor="rgba(255,255,255,0)",
        tickfont=dict(color=t.TEXT_MUTED, size=11, family="JetBrains Mono"),
        automargin=True, showspikes=False,
    )
    fig.update_yaxes(
        gridcolor="rgba(255,255,255,0.04)",
        zeroline=False, linecolor="rgba(255,255,255,0)",
        tickcolor="rgba(255,255,255,0)",
        tickfont=dict(color=t.TEXT_MUTED, size=11, family="JetBrains Mono"),
        automargin=True,
    )
    return fig


# Plotly config helper — sharp exports + clean modebar (used at call sites
# that need extra polish; the global stylesheet covers default rendering).
PLOTLY_CONFIG = {
    "displayModeBar": False,
    "displaylogo": False,
    "toImageButtonOptions": {"scale": 2, "format": "png"},
    "responsive": True,
}


# ----------------------------------------------------------------------
# Component HTML helpers
# ----------------------------------------------------------------------

def kpi_card(label: str, value: str,
             delta: str | None = None,
             direction: str = "",
             live: bool = False) -> str:
    badge = '<span class="kpi-badge-live">Live</span>' if live else ""
    value_cls = "up" if direction == "up" else ("down" if direction == "down" else "")
    delta_html = ""
    if delta:
        delta_cls = "up" if direction == "up" else ("down" if direction == "down" else "")
        delta_html = f'<div class="kpi-delta {delta_cls}">{delta}</div>'
    return (
        f'<div class="kpi-card">'
        f'<div class="kpi-label">{label}{badge}</div>'
        f'<div class="kpi-value {value_cls}">{value}</div>'
        f'{delta_html}'
        f'</div>'
    )


def header_html(pf_name: str, pf_ccy: str, source: str, version: str = "VA1") -> str:
    return (
        f'<div class="va1-header">'
        f'  <div class="va1-brand">'
        f'    <div class="va1-brand-logo">G</div>'
        f'    <span class="va1-brand-name">{pf_name}</span>'
        f'    <span class="va1-brand-divider"></span>'
        f'    <span class="va1-brand-tag">Portfolio Terminal · {pf_ccy}</span>'
        f'  </div>'
        f'  <div style="display:flex;gap:8px;align-items:center">'
        f'    <span class="va1-pill"><span class="va1-pill-dot"></span>{source}</span>'
        f'    <span class="va1-pill">{version}</span>'
        f'  </div>'
        f'</div>'
    )


def status_bar_html(items: list[tuple[str, str, str]]) -> str:
    parts = []
    for i, (label, value, cls) in enumerate(items):
        if i:
            parts.append('<div class="va1-status-sep"></div>')
        parts.append(
            f'<div class="va1-status-item">'
            f'<div class="va1-status-label">{label}</div>'
            f'<div class="va1-status-value {cls}">{value}</div>'
            f'</div>'
        )
    return f'<div class="va1-status">{"".join(parts)}</div>'


def section_head(title: str, sub: str | None = None) -> str:
    """A section header with the orange accent bar + title + optional sub +
    divider. Wrap this BEFORE any standalone section in a tab."""
    sub_html = f'<div class="va1-section-sub">{sub}</div>' if sub else ""
    return (
        f'<div class="va1-section-head">'
        f'<div class="va1-section-bar"></div>'
        f'<div class="va1-section-text">'
        f'<div class="va1-section-title">{title}</div>'
        f'{sub_html}'
        f'</div></div>'
        f'<hr class="va1-divider" />'
    )


def hero_nav_html(nav_value: str, daily: str, daily_dir: str,
                  vl: str, total_return: str, total_dir: str,
                  sparkline_svg: str = "") -> str:
    """Big NAV hero banner for the Overview tab. `sparkline_svg` is an
    inline <svg> string (any size — CSS will clamp to 280x90)."""
    return (
        f'<div class="va1-hero">'
        f'  <div>'
        f'    <div class="va1-hero-label">Net Asset Value</div>'
        f'    <div class="va1-hero-nav">{nav_value}</div>'
        f'    <div class="va1-hero-meta">'
        f'      <div class="va1-hero-pill">'
        f'        <div class="va1-hero-pill-label">Daily</div>'
        f'        <div class="va1-hero-pill-value {daily_dir}">{daily}</div>'
        f'      </div>'
        f'      <div class="va1-hero-pill">'
        f'        <div class="va1-hero-pill-label">VL · base 100</div>'
        f'        <div class="va1-hero-pill-value">{vl}</div>'
        f'      </div>'
        f'      <div class="va1-hero-pill">'
        f'        <div class="va1-hero-pill-label">Total Return</div>'
        f'        <div class="va1-hero-pill-value {total_dir}">{total_return}</div>'
        f'      </div>'
        f'    </div>'
        f'  </div>'
        f'  <div class="va1-hero-spark">{sparkline_svg}</div>'
        f'</div>'
    )


def sparkline_svg(points: list[float], color: str = "#FF8800",
                  width: int = 280, height: int = 90) -> str:
    """Build a tiny SVG sparkline from a list of values."""
    if not points or len(points) < 2:
        return ""
    mn, mx = min(points), max(points)
    rng = (mx - mn) or 1.0
    step = width / (len(points) - 1)
    coords = []
    for i, v in enumerate(points):
        x = i * step
        y = height - ((v - mn) / rng) * (height * 0.85) - (height * 0.075)
        coords.append(f"{x:.1f},{y:.1f}")
    path = "M " + " L ".join(coords)
    area_path = path + f" L {width:.1f},{height:.1f} L 0,{height:.1f} Z"
    return (
        f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" '
        f'style="width:100%;height:100%;display:block">'
        f'<defs><linearGradient id="va1spark" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{color}" stop-opacity="0.45"/>'
        f'<stop offset="100%" stop-color="{color}" stop-opacity="0"/>'
        f'</linearGradient></defs>'
        f'<path d="{area_path}" fill="url(#va1spark)"/>'
        f'<path d="{path}" fill="none" stroke="{color}" '
        f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
        f'</svg>'
    )
