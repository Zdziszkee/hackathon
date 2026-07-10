"""Premier Bank dashboard UI — clean, centered, HSBC-inspired.

Rebuilt from scratch: a single centered column, symmetric KPI strip, smooth
spline chart with red gradient fill, transaction-style risk borrower list,
and collapsible company detail cards. No sidebar, no right rail.

Color: brand red (#DB0011) for bad, green (#29B32E) for good, yellow
(#FFF34A) for warning. White cards on light grey, black ink, grey secondary
text. Univers/Helvetica Neue/Arial. Radii are subtle (8px cards, round pills).
Soft diffuse shadows.
"""

from __future__ import annotations

import base64
from collections.abc import Iterable
from pathlib import Path

import streamlit as st

from ews_ingest.dashboard.icons import (
    STATUS_ICON,
    ic_alert,
    ic_dollar,
    ic_file_text,
    ic_gauge,
    ic_gavel,
    ic_info,
    ic_landmark,
    ic_line_chart,
    ic_map_pin,
    ic_message,
    ic_minus,
    ic_newspaper,
    ic_plus,
    ic_shield,
    ic_truck,
    ic_zap,
)
from ews_ingest.dashboard.signals.protocol import SignalResult
from ews_ingest.dashboard.stats import PortfolioStats, SectorStat

__all__ = [
    "inject_theme",
    "render_company_card",
    "render_portfolio_overview",
    "render_topbar",
    "status_color",
]

# ---------------------------------------------------------------------------
# Status palette — green=good, yellow=warning, red=bad, grey=neutral
# ---------------------------------------------------------------------------

_C_WARN = "#FFF34A"
_C_WARN_FG = "#CA9A00"

_STATUS = {
    "good": {"fg": "#29B32E", "bg": "rgba(41,179,46,0.10)", "bd": "rgba(41,179,46,0.22)"},
    "warning": {
        "fg": _C_WARN_FG,
        "bg": "rgba(255,243,74,0.12)",
        "bd": "rgba(255,243,74,0.30)",
    },
    "bad": {"fg": "#DB0011", "bg": "rgba(219,0,17,0.08)", "bd": "rgba(219,0,17,0.22)"},
    "demo": {"fg": "#9FA1A4", "bg": "rgba(159,161,164,0.08)", "bd": "rgba(159,161,164,0.18)"},
    "unavailable": {
        "fg": "#C4C6C8",
        "bg": "rgba(196,198,200,0.06)",
        "bd": "rgba(196,198,200,0.16)",
    },
}

# Indicator icons are all grey — no per-indicator color tinting.
_IND_ICON = {
    "country": ic_map_pin,
    "industry": ic_landmark,
    "volatility": ic_zap,
    "geopolitical": ic_shield,
    "general_demand": ic_line_chart,
    "regulation": ic_gavel,
    "supply_chain": ic_truck,
    "profitability": ic_dollar,
    "macro_health": ic_gauge,
    "news_sentiment": ic_message,
    "ism": ic_line_chart,
}

# Grey tint for all indicator icon tiles
_IC_TINT = "#9FA1A4"

# ---------------------------------------------------------------------------
# HSBC logo (base64-embedded for inline HTML)
# ---------------------------------------------------------------------------

_LOGO_PATH = Path(__file__).resolve().parent / "assets" / "hsbc_logo.webp"


def _logo_b64() -> str:
    """Return the HSBC logo as a base64-encoded data URI, or empty string."""
    if not _LOGO_PATH.exists():
        return ""
    data = base64.b64encode(_LOGO_PATH.read_bytes()).decode("ascii")
    return f"data:image/webp;base64,{data}"


# ---------------------------------------------------------------------------
# Theme CSS
# ---------------------------------------------------------------------------

_THEME_CSS = """
<style>
:root{
  --brand-red:#DB0011; --brand-red-dark:#B4000E; --brand-red-tint:rgba(219,0,17,.08);
  --success:#29B32E; --warn:#FFF34A; --info:#2563EB;
  --ink-900:#1A1A1A; --ink-700:#333333; --ink-500:#9FA1A4; --ink-400:#BFC1C4;
  --line-200:#E6E6E6; --line-soft:#F0F0F0; --tile-100:#F7F7F7;
  --page-bg:#F5F5F5; --card-bg:#FFFFFF;
  --radius-card:8px; --radius-pill:999px; --radius-input:6px;
  --shadow-card:0 4px 12px rgba(0,0,0,0.03);
  --shadow-hover:0 6px 16px rgba(0,0,0,0.05);
}

html, body, [class*="css"]{
  font-family:Univers,"Univers Next","Helvetica Neue",Arial,sans-serif;
  color:var(--ink-900);
}

/* Hide chrome */
#MainMenu, footer, [data-testid="stToolbar"]{ visibility:hidden; }
[data-testid="stHeader"]{ background:transparent; }
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"]{ display:none !important; }
[data-testid="stAppViewContainer"]{ background:var(--page-bg); }

/* Centered single column — symmetric */
[data-testid="stAppViewContainer"] .stAppViewBlock,
[data-testid="stAppViewContainer"] .main .block-container{
  padding:40px 24px 64px; max-width:1100px; margin:0 auto; float:none;
}

h1,h2,h3,h4,h5,h6{ color:var(--ink-900); font-weight:700; }
[data-testid="stMarkdownContainer"]{ color:var(--ink-900); line-height:1.55; }
.stCaption, [data-testid="stCaptionContainer"]{ color:var(--ink-500) !important; font-size:12px; }
hr{ border:none; border-top:1px solid var(--line-200); margin:32px 0; }

/* Inputs */
.stTextInput label, .stTextInput > label{ display:none; }
.stTextInput > div > div > input{
  background:var(--card-bg) !important; border:1px solid var(--line-200) !important;
  border-radius:var(--radius-input) !important; color:var(--ink-900) !important;
  padding:10px 14px !important; font-size:14px !important; box-shadow:none !important;
  font-family:inherit;
}
.stTextInput > div > div > input:focus{
  border-color:var(--brand-red) !important; box-shadow:0 0 0 2px var(--brand-red-tint) !important;
  outline:none !important;
}
.stTextInput > div > div > input::placeholder{ color:var(--ink-500) !important; }

/* Buttons */
div[data-testid="stButton"] button{
  background:var(--card-bg); color:var(--ink-900); border:1px solid var(--line-200);
  border-radius:var(--radius-input); font-weight:600; padding:10px 20px; box-shadow:none;
  transition:background .15s ease, border-color .15s ease, color .15s ease;
  font-family:inherit; font-size:14px;
}
div[data-testid="stButton"] button:hover{ background:var(--line-soft); border-color:#D0D0D0; }
div[data-testid="stButton"] button:focus{ outline:2px solid var(--brand-red); outline-offset:2px; }
div[data-testid="stButton"] button[kind="primary"]{
  background:var(--brand-red); color:#fff; border:1px solid var(--brand-red);
}
div[data-testid="stButton"] button[kind="primary"]:hover{ background:var(--brand-red-dark); }
div[data-testid="stButton"] button:disabled{ opacity:.4; }

/* Alerts */
[data-testid="stAlert"]{
  background:var(--card-bg) !important; border:1px solid var(--line-200) !important;
  border-radius:var(--radius-card) !important; box-shadow:none !important;
  color:var(--ink-700) !important; padding:14px 18px !important;
}

/* Status widget */
[data-testid="stStatusWidget"]{
  background:var(--card-bg) !important; border:1px solid var(--line-200) !important;
  border-left:3px solid var(--brand-red) !important;
  border-radius:var(--radius-card) !important; box-shadow:var(--shadow-card) !important;
}

/* Progress bar */
.stProgress > div > div > div > div{ background-color:var(--brand-red) !important; }
.stProgress > div > div > div{ background-color:var(--line-200) !important; }

/* Expanders */
details[data-testid="stExpander"]{
  background:var(--card-bg) !important; border:1px solid var(--line-200) !important;
  border-radius:var(--radius-card) !important; box-shadow:var(--shadow-card) !important;
  padding:0 !important; overflow:hidden;
}
details[data-testid="stExpander"] summary{ padding:18px 24px !important; font-weight:600 !important; color:var(--ink-900) !important; }
details[data-testid="stExpander"] [data-testid="stExpanderDetails"]{ padding:0 24px 20px !important; }

/* ---- Component classes ---- */

/* Page header — centered, with HSBC logo */
.pb-header{ text-align:center; margin:8px 0 36px; }
.pb-header img.pb-logo{ height:48px; margin:0 auto 16px; display:block; }
.pb-header h1{ font-size:28px; font-weight:700; color:var(--ink-900); margin:0 0 6px; letter-spacing:-0.01em; }
.pb-header p{ font-size:14px; color:var(--ink-500); margin:0; }

/* Card */
.pb-card{
  background:var(--card-bg); border-radius:var(--radius-card); box-shadow:var(--shadow-card);
  padding:24px;
}
.pb-card-title{
  font-size:16px; font-weight:600; color:var(--ink-900); margin:0 0 20px;
  display:flex; align-items:center; gap:8px;
}
.pb-card-title::before{
  content:""; width:4px; height:16px; background:var(--brand-red); border-radius:2px;
}
.pb-card-sub{ font-size:12px; color:var(--ink-500); margin-left:auto; padding-left:12px; }

/* KPI cards — centered text, stacked vertically */
.pb-kpi{
  background:var(--card-bg); border-radius:var(--radius-card); box-shadow:var(--shadow-card);
  padding:28px 16px; text-align:center;
  display:flex; flex-direction:column; align-items:center; gap:6px;
}
.pb-kpi-val{ font-size:28px; font-weight:700; color:var(--ink-900); line-height:1.1; letter-spacing:-0.02em; }
.pb-kpi-lbl{ font-size:12px; font-weight:400; color:var(--ink-500); }
.pb-kpi-trend{
  display:inline-flex; align-items:center; gap:3px; font-size:12px; font-weight:600; margin-top:2px;
}

/* Chart card */
.pb-chart-head{ margin-bottom:16px; }
.pb-chart-title{ font-size:16px; font-weight:600; color:var(--ink-900); }
.pb-chart-meta{ font-size:12px; color:var(--ink-500); margin-top:2px; }
.pb-chart-big{ font-size:24px; font-weight:700; color:var(--ink-900); margin-top:8px; }
.pb-chart-svg{ width:100%; display:block; }

/* Distribution bars */
.pb-dist-row{ display:grid; grid-template-columns:72px 1fr 32px; align-items:center; gap:12px; margin-bottom:12px; }
.pb-dist-lbl{ font-size:13px; font-weight:500; color:var(--ink-700); }
.pb-dist-bar{ background:var(--line-soft); height:8px; border-radius:var(--radius-pill); overflow:hidden; }
.pb-dist-fill{ height:8px; border-radius:var(--radius-pill); }
.pb-dist-num{ font-size:13px; font-weight:700; color:var(--ink-900); text-align:right; }

/* Sector rows */
.pb-sec-row{ display:flex; align-items:center; gap:12px; padding:6px 0; }
.pb-sec-name{ font-size:13px; font-weight:500; color:var(--ink-700); flex:1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.pb-sec-meta{ font-size:12px; color:var(--ink-500); }
.pb-sec-bar{ width:50px; height:6px; border-radius:var(--radius-pill); background:var(--line-soft); overflow:hidden; flex-shrink:0; }
.pb-sec-bar-fill{ height:6px; border-radius:var(--radius-pill); }

/* Transaction rows (top risk borrowers) */
.pb-txn{ display:flex; align-items:center; gap:14px; padding:10px 4px; }
.pb-txn:hover{ background:var(--line-soft); border-radius:6px; }
.pb-txn-icon{
  width:40px; height:40px; border-radius:6px; background:var(--tile-100);
  display:flex; align-items:center; justify-content:center; flex-shrink:0;
}
.pb-txn-info{ flex:1; min-width:0; }
.pb-txn-name{ font-size:14px; font-weight:600; color:var(--ink-900); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.pb-txn-date{ font-size:12px; color:var(--ink-500); margin-top:1px; }
.pb-txn-amt{ font-size:14px; font-weight:700; color:var(--ink-900); text-align:right; white-space:nowrap; }
.pb-txn-amt-sub{ font-size:11px; color:var(--ink-500); font-weight:400; }

/* Pills/badges */
.pb-pill{
  display:inline-flex; align-items:center; gap:4px;
  border-radius:var(--radius-pill); padding:2px 10px;
  font-size:11px; font-weight:600;
}

/* Stat chips */
.pb-chips{ display:flex; gap:10px; flex-wrap:wrap; }
.pb-chip{
  display:inline-flex; align-items:center; gap:8px;
  background:var(--card-bg); border:1px solid var(--line-200); border-radius:var(--radius-pill);
  padding:6px 14px; font-size:13px; color:var(--ink-700); font-weight:500;
}

/* Company detail card — collapsible via native <details> */
details.pb-co-card{
  background:var(--card-bg); border-radius:var(--radius-card); box-shadow:var(--shadow-card);
  overflow:hidden; margin-bottom:16px;
}
details.pb-co-card > summary{
  list-style:none; cursor:pointer; outline:none;
  display:flex; align-items:center; gap:16px; padding:20px 24px;
  transition:background .15s ease;
}
details.pb-co-card > summary::-webkit-details-marker{ display:none; }
details.pb-co-card > summary::marker{ content:""; }
details.pb-co-card > summary:hover{ background:var(--line-soft); }
details.pb-co-card[open] > summary{ border-bottom:1px solid var(--line-soft); }
/* Company card toggle: plus when collapsed, minus when expanded */
.pb-co-toggle{ color:var(--ink-400); display:inline-flex; flex-shrink:0; margin-left:8px; }
details.pb-co-card > summary .pb-co-toggle .pb-ico-plus{ display:inline-flex; }
details.pb-co-card > summary .pb-co-toggle .pb-ico-minus{ display:none; }
details.pb-co-card[open] > summary .pb-co-toggle .pb-ico-plus{ display:none; }
details.pb-co-card[open] > summary .pb-co-toggle .pb-ico-minus{ display:inline-flex; }
.pb-co-score{
  width:48px; height:48px; border-radius:6px;
  display:flex; align-items:center; justify-content:center;
  font-size:20px; font-weight:700; flex-shrink:0;
}
.pb-co-titles{ flex:1; min-width:0; }
.pb-co-name{ font-size:16px; font-weight:600; color:var(--ink-900); }
.pb-co-meta{ font-size:12px; color:var(--ink-500); margin-top:2px; display:flex; gap:8px; align-items:center; }
.pb-co-ticker{ font-family:"JetBrains Mono",ui-monospace,monospace; font-size:12px; color:var(--ink-500); }
.pb-co-comp{ text-align:right; }
.pb-co-comp-num{ font-size:22px; font-weight:700; color:var(--ink-900); line-height:1; }
.pb-co-comp-lbl{ font-size:10px; text-transform:uppercase; letter-spacing:0.06em; color:var(--ink-500); font-weight:600; margin-top:3px; }

/* Indicator rows */
.pb-rows{ padding:0 12px 16px; }
details.pb-row{ padding:0; }
details.pb-row > summary{ list-style:none; outline:none; }
details.pb-row > summary::-webkit-details-marker{ display:none; }
details.pb-row > summary::marker{ content:""; }
.pb-row{
  display:grid; grid-template-columns:1fr auto 110px 22px; align-items:center; gap:14px;
  padding:12px; cursor:pointer;
}
.pb-row:hover{ background:var(--line-soft); border-radius:6px; }
.pb-row-left{ display:flex; align-items:center; gap:12px; min-width:0; }
.pb-row-tile{
  width:36px; height:36px; border-radius:6px; background:var(--tile-100);
  display:flex; align-items:center; justify-content:center; flex-shrink:0;
}
.pb-row-label{ font-size:14px; font-weight:500; color:var(--ink-900); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.pb-row-val{ font-size:14px; font-weight:600; color:var(--ink-900); font-family:"JetBrains Mono",ui-monospace,monospace; }
.pb-row-badge{
  display:inline-flex; align-items:center; gap:3px; border-radius:var(--radius-pill);
  padding:2px 8px; font-size:11px; font-weight:600; margin-left:6px;
}
.pb-row-right{ display:flex; align-items:center; gap:10px; justify-content:flex-end; }
.pb-row-bar{ background:var(--line-200); height:5px; width:70px; border-radius:var(--radius-pill); overflow:hidden; }
.pb-row-bar-fill{ height:5px; border-radius:var(--radius-pill); }
.pb-row-num{ font-size:12px; font-weight:700; color:var(--ink-500); min-width:22px; text-align:right; font-family:"JetBrains Mono",ui-monospace,monospace; }
/* Indicator row toggle: plus when collapsed, minus when expanded */
.pb-row-toggle{ color:var(--ink-400); display:inline-flex; flex-shrink:0; }
details.pb-row > summary .pb-row-toggle .pb-ico-plus{ display:inline-flex; }
details.pb-row > summary .pb-row-toggle .pb-ico-minus{ display:none; }
details.pb-row[open] > summary .pb-row-toggle .pb-ico-plus{ display:none; }
details.pb-row[open] > summary .pb-row-toggle .pb-ico-minus{ display:inline-flex; }

.pb-row-detail{ padding:8px 12px 14px 60px; }
.pb-row-desc{ font-size:13px; color:var(--ink-500); line-height:1.55; max-width:60ch; margin:8px 0 12px; }
.pb-row-detail-grid{
  display:grid; grid-template-columns:max-content 1fr; gap:4px 16px;
  background:var(--tile-100); border-radius:6px; padding:12px; margin-bottom:12px;
}
.pb-row-k{ font-size:10px; font-weight:600; text-transform:uppercase; letter-spacing:0.06em; color:var(--ink-500); }
.pb-row-v{ font-size:12px; color:var(--ink-700); font-family:"JetBrains Mono",ui-monospace,monospace; }
.pb-row-note{ display:flex; gap:6px; font-size:12px; color:var(--ink-500); margin-bottom:10px; max-width:70ch; }
.pb-row-src{ display:flex; gap:6px; flex-wrap:wrap; }
.pb-row-src-chip{
  display:inline-flex; align-items:center; gap:4px; background:var(--tile-100);
  border:1px solid var(--line-200); border-radius:4px; padding:3px 8px;
  font-size:11px; color:var(--ink-500); font-family:"JetBrains Mono",ui-monospace,monospace;
}

/* Risk exposure card — replaces the credit-card visual */
.pb-expose{ display:flex; flex-direction:column; gap:16px; }
.pb-donut-wrap{ display:flex; align-items:center; justify-content:center; gap:16px; }
.pb-donut-center{ text-align:center; }
.pb-donut-center .num{ font-size:28px; font-weight:700; color:var(--ink-900); line-height:1; }
.pb-donut-center .lbl{ font-size:12px; color:var(--ink-500); margin-top:2px; }
.pb-expose-legend{ display:flex; flex-direction:column; gap:8px; }
.pb-expose-leg-item{ display:flex; align-items:center; gap:8px; font-size:13px; color:var(--ink-700); }
.pb-expose-leg-dot{ width:10px; height:10px; border-radius:2px; flex-shrink:0; }
.pb-expose-leg-num{ margin-left:auto; font-weight:700; color:var(--ink-900); }
.pb-expose-stats{ display:flex; gap:12px; margin-top:4px; }
.pb-expose-stat{ flex:1; text-align:center; }
.pb-expose-stat .v{ font-size:18px; font-weight:700; color:var(--ink-900); }
.pb-expose-stat .l{ font-size:11px; color:var(--ink-500); margin-top:2px; }

/* Add-company toolbar */
.pb-toolbar{ display:flex; gap:10px; margin-bottom:24px; }

@media (prefers-reduced-motion: reduce){ *{ transition:none !important; animation:none !important; } }
</style>
"""


def inject_theme() -> None:
    st.markdown(_THEME_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def status_color(status: str) -> str:
    return _STATUS.get(status, _STATUS["unavailable"])["fg"]


def _token(status: str) -> dict[str, str]:
    return _STATUS.get(status, _STATUS["unavailable"])


def _esc(value: object) -> str:
    s = f"{value:.3f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _display_sector(sector: str) -> str:
    return (sector or "\u2014").replace("_", " ").title()


def _status_badge(status: str) -> str:
    tok = _token(status)
    return (
        f'<span class="pb-row-badge" '
        f'style="background:{tok["bg"]};color:{tok["fg"]};border:1px solid {tok["bd"]}">'
        f"{_esc(status)}</span>"
    )


def _composite_status(score: float) -> str:
    if score < 35:
        return "good"
    if score < 65:
        return "warning"
    return "bad"


# ---------------------------------------------------------------------------
# SVG spline chart — smooth red line with gradient area fill
# ---------------------------------------------------------------------------


def _spline_chart_svg(
    labels: list[str],
    values: list[float],
    width: int = 720,
    height: int = 260,
    line_color: str = "#DB0011",
) -> str:
    """A smooth spline area chart: 2px red line, gradient fill, dashed
    horizontal gridlines, uppercase x-axis labels. No vertical gridlines."""
    if not values:
        return ""
    n = len(values)
    pad_l, pad_r, pad_t, pad_b = 40, 16, 16, 30
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    vmin, vmax = min(values), max(values)
    if vmax == vmin:
        vmax = vmin + 1.0
    span = vmax - vmin

    def x(i: int) -> float:
        return pad_l + (i / max(1, n - 1)) * plot_w

    def y(v: float) -> float:
        return pad_t + plot_h - ((v - vmin) / span) * plot_h

    points = [(x(i), y(v)) for i, v in enumerate(values)]

    # Catmull-Rom -> cubic Bezier for smooth spline
    bezier = ""
    for i in range(n - 1):
        p0 = points[max(0, i - 1)]
        p1 = points[i]
        p2 = points[i + 1]
        p3 = points[min(n - 1, i + 2)]
        cp1x = p1[0] + (p2[0] - p0[0]) / 6
        cp1y = p1[1] + (p2[1] - p0[1]) / 6
        cp2x = p2[0] - (p3[0] - p1[0]) / 6
        cp2y = p2[1] - (p3[1] - p1[1]) / 6
        if i == 0:
            bezier += f"M{p1[0]:.1f},{p1[1]:.1f} "
        bezier += f"C{cp1x:.1f},{cp1y:.1f} {cp2x:.1f},{cp2y:.1f} {p2[0]:.1f},{p2[1]:.1f} "

    # Area path
    area_path = (
        bezier + f"L{x(n - 1):.1f},{(pad_t + plot_h):.1f} L{x(0):.1f},{(pad_t + plot_h):.1f} Z"
    )

    # Gridlines
    def grid(f: float) -> str:
        gv = vmin + span * f
        gy = y(gv)
        return (
            f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{width - pad_r}" y2="{gy:.1f}" '
            f'stroke="#E6E6E6" stroke-width="1" stroke-dasharray="3 4"/>'
        )

    grids = "".join(grid(f) for f in (0.0, 0.25, 0.5, 0.75, 1.0))

    # X-axis labels
    xlabs = "".join(
        f'<text x="{x(i):.1f}" y="{height - 8}" text-anchor="middle" '
        f'fill="#9FA1A4" font-family="Univers,Helvetica,Arial,sans-serif" '
        f'font-size="10" font-weight="600" letter-spacing="0.6">{_esc(lbl)}</text>'
        for i, lbl in enumerate(labels)
    )

    gid = "pbGrad"

    return (
        f'<svg class="pb-chart-svg" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="xMidYMid meet" role="img" aria-label="chart">'
        f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{line_color}" stop-opacity="0.18"/>'
        f'<stop offset="100%" stop-color="{line_color}" stop-opacity="0.0"/>'
        f"</linearGradient></defs>"
        f"{grids}"
        f'<path d="{area_path}" fill="url(#{gid})"/>'
        f'<path d="{bezier}" fill="none" stroke="{line_color}" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
        f"{xlabs}"
        f"</svg>"
    )


def _bar_chart_svg(
    labels: list[str],
    values: list[float],
    colors: list[str] | None = None,
    width: int = 720,
    height: int = 260,
    bar_color: str = "#DB0011",
) -> str:
    """Simple rounded-bar chart with dashed gridlines."""
    if not values:
        return ""
    n = len(values)
    pad_l, pad_r, pad_t, pad_b = 16, 16, 12, 28
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    vmax = max(values) * 1.15 if max(values) > 0 else 1.0
    gap = plot_w / n
    bar_w = max(10, gap * 0.5)

    def grid(y_val: float) -> str:
        gy = pad_t + plot_h - (y_val / vmax) * plot_h
        return (
            f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{width - pad_r}" y2="{gy:.1f}" '
            f'stroke="#E6E6E6" stroke-width="1" stroke-dasharray="3 4"/>'
        )

    grids = "".join(grid(v) for v in [vmax * f for f in (0.25, 0.5, 0.75, 1.0)])

    def bar(i: int, v: float) -> str:
        h = (v / vmax) * plot_h
        bx = pad_l + i * gap + (gap - bar_w) / 2
        by = pad_t + plot_h - h
        fill = colors[i] if colors and i < len(colors) else bar_color
        return f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w:.1f}" height="{h:.1f}" rx="4" ry="4" fill="{fill}"/>'

    bars = "".join(bar(i, v) for i, v in enumerate(values))

    xlabs = "".join(
        f'<text x="{pad_l + i * gap + gap / 2:.1f}" y="{height - 8}" text-anchor="middle" '
        f'fill="#9FA1A4" font-family="Univers,Helvetica,Arial,sans-serif" '
        f'font-size="10" font-weight="600" letter-spacing="0.6">{_esc(lbl)}</text>'
        for i, lbl in enumerate(labels)
    )

    return (
        f'<svg class="pb-chart-svg" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="xMidYMid meet" role="img" aria-label="bar chart">'
        f"{grids}{bars}{xlabs}</svg>"
    )


# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------


def render_topbar(n_companies: int, n_sources: int = 0) -> None:
    """Centered page header: HSBC logo, title + subtitle."""
    _ = (n_companies, n_sources)
    logo_uri = _logo_b64()
    logo_html = f'<img class="pb-logo" src="{logo_uri}" alt="HSBC" />' if logo_uri else ""
    st.markdown(
        f'<div class="pb-header">{logo_html}<h1>Portfolio Risk Dashboard</h1>'
        "<p>Cross-region wholesale credit early-warning signals</p></div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# KPI card
# ---------------------------------------------------------------------------


def _kpi_html(value: str, label: str, trend: str, *, positive: bool | None) -> str:
    """One KPI card: value centered, label below, trend with arrow."""
    if positive is None:
        trend_html = f'<span class="pb-kpi-trend" style="color:var(--ink-500)">{trend}</span>'
    else:
        color = "var(--success)" if positive else "var(--brand-red)"
        glyph = "\u2197" if positive else "\u2198"
        trend_html = f'<span class="pb-kpi-trend" style="color:{color}">{glyph} {trend}</span>'
    return f"""
    <div class="pb-kpi">
      <div class="pb-kpi-val">{value}</div>
      <div class="pb-kpi-lbl">{label}</div>
      {trend_html}
    </div>
    """


# ---------------------------------------------------------------------------
# Top risk borrowers — transaction-style rows
# ---------------------------------------------------------------------------


def _txn_html(rank: int, name: str, score: float, sector: str, status: str) -> str:
    tok = _token(status)
    fg = tok["fg"]
    # incoming (good) = green up-right arrow; outgoing (bad) = red down arrow
    positive = status == "good"
    glyph = "\u2197" if positive else "\u2198"
    sector_pretty = _display_sector(sector)
    return (
        f'<div class="pb-txn">'
        f'<div class="pb-txn-icon" style="color:{fg}">{glyph}</div>'
        f'<div class="pb-txn-info">'
        f'<div class="pb-txn-name">{rank}. {_esc(name)}</div>'
        f'<div class="pb-txn-date">{sector_pretty} \u00b7 composite risk</div>'
        f"</div>"
        f'<div style="text-align:right;">'
        f'<div class="pb-txn-amt" style="color:{fg}">{score:.0f}</div>'
        f'<div class="pb-txn-amt-sub">{status}</div>'
        f"</div>"
        f"</div>"
    )


# ---------------------------------------------------------------------------
# Sector + distribution helpers
# ---------------------------------------------------------------------------


def _sector_html(sec: SectorStat) -> str:
    status = _composite_status(sec.mean_risk)
    color = status_color(status)
    return (
        '<div class="pb-sec-row">'
        f'<span class="pb-sec-name">{_display_sector(sec.sector)}</span>'
        f'<span class="pb-sec-meta">{sec.count} \u00b7 {sec.share_pct:.0f}%</span>'
        f'<span class="pb-sec-bar"><span class="pb-sec-bar-fill" style="width:{sec.mean_risk:.0f}%;background:{color}"></span></span>'
        "</div>"
    )


def _distribution_html(stats: PortfolioStats) -> str:
    def row(label: str, count: int, color: str) -> str:
        pct = (count / stats.n_companies * 100) if stats.n_companies else 0
        return (
            f'<div class="pb-dist-row"><span class="pb-dist-lbl">{label}</span>'
            f'<div class="pb-dist-bar"><div class="pb-dist-fill" style="width:{pct:.0f}%;background:{color}"></div></div>'
            f'<span class="pb-dist-num">{count}</span></div>'
        )

    return (
        "<div>"
        + row("Good", stats.n_good, status_color("good"))
        + row("Warning", stats.n_warning, status_color("warning"))
        + row("Bad", stats.n_bad, status_color("bad"))
        + "</div>"
    )


# ---------------------------------------------------------------------------
# Risk exposure card (replaces the credit-card visual)
# ---------------------------------------------------------------------------


def _donut_svg(
    segments: list[tuple[float, str]],
    size: int = 120,
    stroke: int = 16,
) -> str:
    """A simple donut chart: ``segments`` = [(fraction, color), ...].

    Fractions must sum to <= 1.0. Drawn via stacked <circle> with
    stroke-dasharray for each arc segment.
    """
    r = (size - stroke) / 2
    cx = size / 2
    circ = 2 * 3.14159265 * r
    total = sum(f for f, _ in segments) or 1.0
    offset = 0.0
    arcs = ""
    for frac, color in segments:
        if frac <= 0:
            continue
        dash = frac / total * circ
        arcs += (
            f'<circle cx="{cx}" cy="{cx}" r="{r:.1f}" fill="none" '
            f'stroke="{color}" stroke-width="{stroke}" '
            f'stroke-dasharray="{dash:.1f} {circ - dash:.1f}" '
            f'stroke-dashoffset="{-offset:.1f}" transform="rotate(-90 {cx} {cx})"/>'
        )
        offset += dash
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
        f'role="img" aria-label="risk distribution donut">'
        f'<circle cx="{cx}" cy="{cx}" r="{r:.1f}" fill="none" '
        f'stroke="{"#F0F0F0"}" stroke-width="{stroke}"/>'
        f"{arcs}</svg>"
    )


def _risk_exposure_html(stats: PortfolioStats) -> str:
    """A donut chart of good/warning/bad borrower counts + a compact legend
    and stat row. Replaces the credit-card widget — fits the risk theme."""
    n = stats.n_companies or 1
    good_f = stats.n_good / n
    warn_f = stats.n_warning / n
    bad_f = stats.n_bad / n
    good_c = status_color("good")
    warn_c = status_color("warning")
    bad_c = status_color("bad")
    segments = [(good_f, good_c), (warn_f, warn_c), (bad_f, bad_c)]
    donut = _donut_svg(segments)
    worst = stats.worst_indicator_label or "\u2014"
    sent_str = f"{stats.mean_sentiment:+.1f}" if stats.mean_sentiment is not None else "\u2014"
    return f"""
    <div class="pb-card pb-expose">
      <div class="pb-card-title">Risk exposure</div>
      <div class="pb-donut-wrap">
        {donut}
        <div class="pb-donut-center">
          <div class="num">{stats.n_companies}</div>
          <div class="lbl">borrowers</div>
        </div>
        <div class="pb-expose-legend">
          <div class="pb-expose-leg-item">
            <span class="pb-expose-leg-dot" style="background:{good_c}"></span>
            Good <span class="pb-expose-leg-num">{stats.n_good}</span>
          </div>
          <div class="pb-expose-leg-item">
            <span class="pb-expose-leg-dot" style="background:{warn_c}"></span>
            Warning <span class="pb-expose-leg-num">{stats.n_warning}</span>
          </div>
          <div class="pb-expose-leg-item">
            <span class="pb-expose-leg-dot" style="background:{bad_c}"></span>
            Bad <span class="pb-expose-leg-num">{stats.n_bad}</span>
          </div>
        </div>
      </div>
      <div class="pb-expose-stats">
        <div class="pb-expose-stat">
          <div class="v">{stats.total_sanctions_flags}</div>
          <div class="l">sanctions flags</div>
        </div>
        <div class="pb-expose-stat">
          <div class="v">{sent_str}</div>
          <div class="l">news bias</div>
        </div>
        <div class="pb-expose-stat">
          <div class="v" style="font-size:14px;">{_esc(worst[:12])}</div>
          <div class="l">worst indicator</div>
        </div>
      </div>
    </div>
    """


# ---------------------------------------------------------------------------
# Portfolio overview — centered symmetric layout
# ---------------------------------------------------------------------------


def render_portfolio_overview(stats: PortfolioStats) -> None:
    """Centered symmetric overview:

    1. KPI strip (4 cards, centered text)
    2. Chart card (spline line + bar, side by side)
    3. Risk breakdown + sector exposure (side by side)
    4. Top risk borrowers list (full width)
    5. Risk exposure donut card (centered)
    """
    mean_status = _composite_status(stats.mean_risk)
    mean_color = status_color(mean_status)

    # -- KPI strip: 4 centered cards --
    kpi_htmls = [
        _kpi_html(
            f"{stats.mean_risk:.0f}",
            "Portfolio mean risk",
            f"{100 - stats.mean_risk:.1f}%",
            positive=stats.mean_risk < 50,
        ),
        _kpi_html(
            f"{stats.hhi:.0f}",
            "Sector concentration",
            stats.hhi_label,
            positive=stats.hhi_label == "low",
        ),
        _kpi_html(
            f"{stats.country_concentration_pct:.0f}%",
            "Country concentration",
            f"{stats.n_distinct_countries} countries",
            positive=stats.country_concentration_pct < 50,
        ),
        _kpi_html(
            f"{stats.data_coverage_pct:.0f}%",
            "Data coverage",
            f"{stats.n_companies} borrowers",
            positive=stats.data_coverage_pct >= 50,
        ),
    ]
    kpi_cols = st.columns(4, gap="medium")
    for col, html in zip(kpi_cols, kpi_htmls, strict=False):
        with col:
            st.markdown(html, unsafe_allow_html=True)

    st.write("")

    # -- Chart card: spline trend (mean risk over "sectors" as proxy timeline) --
    # Build a smooth spline from the sector mean-risk readings.
    spline_values = [s.mean_risk for s in stats.sectors[:8]] or [stats.mean_risk]
    spline_labels = [_display_sector(s.sector).split(" ")[0][:10] for s in stats.sectors[:8]] or [
        "Current"
    ]
    spline_svg = _spline_chart_svg(spline_labels, spline_values)

    # Bar chart: sector mean risk bars colored by status
    bar_labels = spline_labels
    bar_values = spline_values
    bar_colors = ["#DB0011"] * len(bar_values)
    bar_svg = _bar_chart_svg(bar_labels, bar_values, bar_colors)

    # Split: spline left, bar right — symmetric
    chart_cols = st.columns([1, 1], gap="medium")
    with chart_cols[0]:
        st.markdown(
            f"""
            <div class="pb-card">
              <div class="pb-chart-head">
                <div class="pb-chart-title">Risk trend</div>
                <div class="pb-chart-meta">mean risk across sectors</div>
                <div class="pb-chart-big" style="color:{mean_color}">{stats.mean_risk:.0f}<span style="font-size:14px;color:var(--ink-500);font-weight:400">/100</span></div>
              </div>
              {spline_svg}
            </div>
            """,
            unsafe_allow_html=True,
        )
    with chart_cols[1]:
        st.markdown(
            f"""
            <div class="pb-card">
              <div class="pb-chart-head">
                <div class="pb-chart-title">Sector risk</div>
                <div class="pb-chart-meta">mean risk by sector</div>
                <div class="pb-chart-big">{stats.n_companies}<span style="font-size:14px;color:var(--ink-500);font-weight:400"> borrowers</span></div>
              </div>
              {bar_svg}
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.write("")

    # -- Risk breakdown + sector exposure, side by side --
    sec_rows = "".join(_sector_html(s) for s in stats.sectors) or (
        '<div style="color:var(--ink-500);font-size:13px;">n/a</div>'
    )
    breakdown_cols = st.columns([1, 1], gap="medium")
    with breakdown_cols[0]:
        st.markdown(
            f"""
            <div class="pb-card">
              <div class="pb-card-title">Risk distribution</div>
              {_distribution_html(stats)}
            </div>
            """,
            unsafe_allow_html=True,
        )
    with breakdown_cols[1]:
        st.markdown(
            f"""
            <div class="pb-card">
              <div class="pb-card-title">Sector exposure</div>
              {sec_rows}
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.write("")

    # -- Top risk borrowers (transactions list) + credit card, side by side --
    top_rows = (
        "".join(
            _txn_html(i + 1, name, score, sector, _composite_status(score))
            for i, (name, score, sector) in enumerate(stats.top_risk)
        )
        or '<div style="color:var(--ink-500);font-size:13px;padding:8px;">No borrowers yet.</div>'
    )

    bottom_cols = st.columns([2, 1], gap="medium")
    with bottom_cols[0]:
        st.markdown(
            f"""
            <div class="pb-card">
              <div class="pb-card-title">Top risk borrowers<span class="pb-card-sub">highest first</span></div>
              {top_rows}
            </div>
            """,
            unsafe_allow_html=True,
        )
    with bottom_cols[1]:
        st.markdown(_risk_exposure_html(stats), unsafe_allow_html=True)

    # -- Stat chips (centered, full width) --
    chips_parts: list[str] = []
    chips_parts.append(
        f'<div class="pb-chip"><span style="color:var(--brand-red)">{ic_shield(14)}</span>'
        f"<span><b>{stats.total_sanctions_flags}</b> sanctions flags</span></div>"
    )
    if stats.mean_sentiment is not None:
        sent_color = "var(--success)" if stats.mean_sentiment > 0 else "var(--brand-red)"
        chips_parts.append(
            f'<div class="pb-chip"><span style="color:{sent_color}">{ic_newspaper(14)}</span>'
            f"<span>bias <b>{stats.mean_sentiment:+.1f}</b></span></div>"
        )
    if stats.worst_indicator_id:
        chips_parts.append(
            f'<div class="pb-chip"><span style="color:var(--warn)">{ic_alert(14)}</span>'
            f"<span>worst: <b>{_esc(stats.worst_indicator_label)}</b> ({stats.worst_indicator_mean:.0f})</span></div>"
        )
    st.write("")
    st.markdown(
        '<div style="text-align:center;"><div class="pb-chips">'
        + "".join(chips_parts)
        + "</div></div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Company detail card
# ---------------------------------------------------------------------------


def _row_html(
    indicator_id: str,
    label: str,
    description: str,
    result: SignalResult,
) -> str:
    tok = _token(result.status)
    fg = tok["fg"]
    status_ic = STATUS_ICON.get(result.status, ic_minus)(14)
    topic_ic_fn = _IND_ICON.get(indicator_id, ic_gauge)
    topic_ic = topic_ic_fn(16)
    tint = _IC_TINT

    badges = _status_badge(result.status)
    if result.status == "demo":
        badges += (
            '<span class="pb-row-badge" '
            'style="background:rgba(159,161,164,.08);color:#9FA1A4;border:1px solid rgba(159,161,164,.18);">demo</span>'
        )
    if result.missing_env:
        badges += (
            '<span class="pb-row-badge" '
            'style="background:rgba(255,243,74,.12);color:#CA9A00;border:1px solid rgba(255,243,74,.30);">key</span>'
        )

    mid = f'<span><span class="pb-row-val">{_esc(result.value)}</span>{badges}</span>'

    if result.status == "unavailable":
        bar = ""
        num = ""
    else:
        bar = (
            f'<span class="pb-row-bar"><span class="pb-row-bar-fill" '
            f'style="width:{result.score:.0f}%;background:{fg}"></span></span>'
        )
        num = f'<span class="pb-row-num">{result.score:.0f}</span>'

    desc_html = f'<div class="pb-row-desc">{_esc(description)}</div>' if description else ""
    detail_rows = ""
    if result.detail:
        items = sorted(result.detail.items())
        rows = "".join(
            f'<span class="pb-row-k">{_esc(k)}</span><span class="pb-row-v">{_esc(v)}</span>'
            for k, v in items
        )
        detail_rows = f'<div class="pb-row-detail-grid">{rows}</div>'
    note_html = ""
    if result.note:
        note_html = f'<div class="pb-row-note">{ic_info(13)}<span>{_esc(result.note)}</span></div>'
    src_html = ""
    if result.source_ids:
        chips = " ".join(
            f'<span class="pb-row-src-chip">{ic_file_text(12)}{_esc(s)}</span>'
            for s in result.source_ids
        )
        src_html = f'<div class="pb-row-src">{chips}</div>'
    detail_body = desc_html + detail_rows + note_html + src_html
    if not detail_body:
        detail_body = '<div class="pb-row-note">no detail</div>'

    return (
        f'<details class="pb-row"><summary>'
        f'<span class="pb-row-left">'
        f'<span class="pb-row-tile" style="color:{tint}">{topic_ic}</span>'
        f'<span class="pb-row-label">{_esc(label)}</span>'
        f"</span>"
        f"{mid}"
        f'<span class="pb-row-right">'
        f'<span style="color:{fg}">{status_ic}</span>'
        f"{bar}{num}"
        f'<span class="pb-row-toggle"><span class="pb-ico-plus">{ic_plus(16)}</span><span class="pb-ico-minus">{ic_minus(16)}</span></span>'
        "</span>"
        "</summary>"
        f'<div class="pb-row-detail">{detail_body}</div>'
        "</details>"
    )


def render_company_card(
    name: str,
    sector: str,
    ticker: str,
    composite: float,
    status: str,
    rows: Iterable[tuple[str, str, str, SignalResult]],
    sources: Iterable[str],
) -> None:
    """One collapsible borrower card: header with score tile, body with
    expandable indicator rows (data-table pattern)."""
    tok = _token(status)
    fg = tok["fg"]
    sector_pretty = _display_sector(sector)
    body_rows = "".join(_row_html(iid, lbl, desc, result) for iid, lbl, desc, result in rows)
    srcs = [s for s in sources if s]
    src_html = ""
    if srcs:
        chips = " ".join(
            f'<span class="pb-row-src-chip">{ic_file_text(12)}{_esc(s)}</span>' for s in srcs
        )
        src_html = (
            '<div style="padding:14px 24px 18px;border-top:1px solid var(--line-200);">'
            '<div style="font-size:12px;color:var(--ink-500);font-weight:600;margin-bottom:8px;">Sources</div>'
            f'<div class="pb-row-src">{chips}</div></div>'
        )

    html = f"""
    <details class="pb-co-card">
      <summary>
        <div class="pb-co-score" style="background:{tok["bg"]};color:{fg}">{composite:.0f}</div>
        <div class="pb-co-titles">
          <div class="pb-co-name">{_esc(name)}</div>
          <div class="pb-co-meta">
            <span class="pb-pill" style="background:{tok["bg"]};color:{tok["fg"]};border:1px solid {tok["bd"]}">{status}</span>
            <span class="pb-co-ticker">{_esc(ticker or "")}</span>
            <span style="color:var(--ink-400);">\u00b7</span>
            <span>{sector_pretty}</span>
          </div>
        </div>
        <div class="pb-co-comp">
          <div class="pb-co-comp-num" style="color:{fg}">{composite:.0f}</div>
          <div class="pb-co-comp-lbl">composite / 100</div>
        </div>
        <span class="pb-co-toggle"><span class="pb-ico-plus">{ic_plus(18)}</span><span class="pb-ico-minus">{ic_minus(18)}</span></span>
      </summary>
      <div class="pb-rows">{body_rows}</div>
      {src_html}
    </details>
    """
    st.markdown(html, unsafe_allow_html=True)
