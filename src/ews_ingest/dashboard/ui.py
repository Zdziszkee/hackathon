"""Streamlit UI: minimal dark dashboard inspired by shadcn/ui, Lin/Anthropic.

Design tokens (zinc grayscale + semantic accents), Lucide stroke icons, native
``<details>`` as shadcn Collapsible, ``<summary>`` rows that rotate a chevron,
and an expanded panel showing the indicator's detail dict + note + sources.
"""

from __future__ import annotations

from collections.abc import Iterable

import streamlit as st

from ews_ingest.dashboard.icons import (
    STATUS_ICON,
    Icon,
    ic_activity,
    ic_bar_chart,
    ic_boxes,
    ic_chevron_down,
    ic_factory,
    ic_file_text,
    ic_gauge,
    ic_globe,
    ic_info,
    ic_map_pin,
    ic_minus,
    ic_newspaper,
    ic_scale,
    ic_shield,
    ic_trending,
)
from ews_ingest.dashboard.signals.protocol import SignalResult
from ews_ingest.dashboard.stats import PortfolioStats, SectorStat

__all__ = [
    "inject_theme",
    "render_company_card",
    "render_portfolio_overview",
    "status_color",
]

# Semantic accent colors (shadcn tokens — matching the request):
#   good  = emerald (ok)   warning = amber (warning)
#   bad   = red (error)    demo    = zinc  (neutral)   other = blue (info)
_STATUS = {
    "good": {"fg": "#34d399", "bg": "rgba(52,211,153,0.10)", "bd": "rgba(52,211,153,0.25)"},
    "warning": {"fg": "#fbbf24", "bg": "rgba(251,191,36,0.10)", "bd": "rgba(251,191,36,0.25)"},
    "bad": {"fg": "#f87171", "bg": "rgba(248,113,113,0.10)", "bd": "rgba(248,113,113,0.25)"},
    "demo": {"fg": "#a1a1aa", "bg": "rgba(161,161,170,0.08)", "bd": "rgba(161,161,170,0.18)"},
    "unavailable": {
        "fg": "#71717a",
        "bg": "rgba(113,113,122,0.06)",
        "bd": "rgba(113,113,122,0.16)",
    },
}

# Indicator id -> topic icon (consistent visual cue per category) + tint.
_IND_ICON = {
    "country": (ic_map_pin, "#60a5fa"),  # blue
    "industry": (ic_factory, "#a78bfa"),  # violet
    "volatility": (ic_trending, "#f472b6"),  # pink
    "geopolitical": (ic_shield, "#fb923c"),  # orange
    "general_demand": (ic_trending, "#34d399"),  # emerald
    "regulation": (ic_scale, "#fbbf24"),  # amber
    "supply_chain": (ic_boxes, "#22d3ee"),  # cyan
    "profitability": (ic_bar_chart, "#a3e635"),  # lime
    "macro_health": (ic_activity, "#f87171"),  # red
    "news_sentiment": (ic_newspaper, "#c084fc"),  # purple
}


def _display_sector(sector: str) -> str:
    """Format a free-form sector string for display. Returns ``"—"`` for empty."""
    if not sector:
        return "—"
    return sector.title()


_THEME_CSS = """
<style>
  /* hide the sidebar entirely */
  [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] { display: none !important; }

  .stApp { background: #09090b; }
  .block-container { padding: 2.4rem 2rem 4rem !important; max-width: 1080px; }

  [data-testid="stMarkdownContainer"] { color: #e4e4e7; line-height: 1.55; }
  [data-testid="stMetricValue"] { font-weight: 700 !important; color: #fafafa !important;
                                   font-family: "JetBrains Mono","SF Mono",ui-monospace,monospace; }
  [data-testid="stMetricLabel"] { color: #71717a !important; font-size: 0.7rem !important;
                                   text-transform: uppercase; letter-spacing: 0.08em; }

  /* dark inputs */
  .stTextInput > div > div > input, .stSelectbox div[data-baseweb="select"] > div {
    background: #18181b !important;
    border: 1px solid #27272a !important; border-radius: 8px !important;
    color: #e4e4e7 !important;
  }
  .stTextInput > div > div > input::placeholder { color: #52525b !important; }
  .stSelectbox svg { color: #71717a !important; }
  .stSelectbox div[data-baseweb="select"] > div > div { color: #e4e4e7 !important; }
  .stSelectbox div[data-baseweb="select"] > div:has(> div[class*="placeholder"]) > div { color: #52525b !important; }

  hr { border-color: #1f1f23 !important; margin: 2rem 0 !important; }

  /* streamlit expander restyle (for methodology) */
  details[data-testid="stExpander"] {
    border: 1px solid #27272a !important; border-radius: 12px !important;
    background: #18181b !important; box-shadow: none !important;
  }

  /* company card — shadcn Card: a folded <details> (collapsed by default) */
  details.rw-card {
    background: #18181b;
    border: 1px solid #27272a;
    border-radius: 14px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.25);
    padding: 0;
    margin-bottom: 1rem;
    overflow: hidden;
  }
  details.rw-card > summary {
    cursor: pointer; list-style: none; outline: none;
    padding: 1.3rem 1.6rem;
    display: flex; justify-content: space-between; align-items: center; gap: 1rem;
  }
  details.rw-card > summary::-webkit-details-marker { display: none; }
  details.rw-card > summary:hover { background: rgba(255,255,255,0.02); }
  details.rw-card[open] > summary { border-bottom: 1px solid #27272a; }
  .rw-card-body { padding: 0.4rem 1.6rem 0.8rem; }
  .rw-card-head {
    display: flex; justify-content: space-between; align-items: center; gap: 1rem;
  }
  .rw-name { font-size: 1.1rem; font-weight: 600; color: #fafafa; letter-spacing: -0.01em; }
  .rw-pill {
    background: rgba(255,255,255,0.06); color: #d4d4d8; border: 1px solid #27272a;
    border-radius: 999px; padding: 2px 10px; font-size: 0.62rem; font-weight: 500;
    margin-left: 10px; letter-spacing: 0.02em;
  }
  .rw-ticker {
    color: #71717a; font-size: 0.72rem; margin-left: 8px;
    font-family: "JetBrains Mono", ui-monospace, monospace;
  }
  .rw-comp { text-align: right; white-space: nowrap; }
  .rw-comp-num {
    font-size: 2rem; font-weight: 700; line-height: 1;
    font-family: "JetBrains Mono", ui-monospace, monospace;
  }
  .rw-comp-cap {
    color: #52525b; font-size: 0.56rem; margin-top: 3px;
    text-transform: uppercase; letter-spacing: 0.1em;
  }
  .rw-card-head-right { display: flex; align-items: center; gap: 0.8rem; }
  .rw-card-chev { color: #52525b; transition: transform 0.15s ease; display: inline-flex; }
  details.rw-card[open] > summary .rw-card-chev { transform: rotate(180deg); }

  /* indicator list (vertical, one after another) */
  .rw-rows { list-style: none; margin: 0; padding: 0; }
  .rw-row { border-bottom: 1px solid #1f1f23; }
  .rw-row:last-child { border-bottom: none; }
  .rw-row > summary {
    display: grid;
    grid-template-columns: 1fr auto 130px 22px;
    align-items: center; gap: 1rem;
    padding: 0.85rem 0;
    cursor: pointer; list-style: none; outline: none;
  }
  .rw-row > summary::-webkit-details-marker { display: none; }
  .rw-row > summary:hover { background: rgba(255,255,255,0.02); }
  .rw-row-left { display: flex; align-items: center; gap: 10px; min-width: 0; }
  .rw-icon { display: inline-flex; color: #71717a; }
  .rw-topic-icon { display: inline-flex; }
  .rw-label { color: #d4d4d8; font-size: 0.84rem; font-weight: 500;
              white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .rw-mid { display: flex; align-items: center; gap: 8px; }
  .rw-val { color: #fafafa; font-size: 0.92rem; font-weight: 600;
            font-family: "JetBrains Mono", ui-monospace, monospace; }
  .rw-badge {
    border-radius: 999px; padding: 1px 8px; font-size: 0.55rem; font-weight: 600;
    letter-spacing: 0.04em; text-transform: uppercase;
    display: inline-flex; align-items: center; gap: 3px;
  }
  .rw-right { display: flex; align-items: center; gap: 8px; justify-content: flex-end; }
  .rw-bar { background: #27272a; border-radius: 999px; height: 4px; width: 70px; overflow: hidden; }
  .rw-bar-fill { height: 4px; border-radius: 999px; }
  .rw-num { color: #71717a; font-size: 0.72rem; font-weight: 600; min-width: 22px;
            text-align: right; font-family: "JetBrains Mono", ui-monospace, monospace; }
  .rw-chev { color: #52525b; transition: transform 0.15s ease; }
  .rw-row[open] > summary .rw-chev { transform: rotate(180deg); }
  .rw-row[open] > summary { padding-bottom: 0.4rem; }

  /* expanded detail panel */
  .rw-detail {
    padding: 0.7rem 0 1rem 32px;
    color: #a1a1aa; font-size: 0.74rem;
    border-top: 1px solid #1f1f23;
    margin-top: 0.2rem;
  }
  .rw-desc {
    color: #a1a1aa; font-size: 0.72rem; line-height: 1.5;
    padding: 0.3rem 0 0.6rem;
    border-bottom: 1px dashed rgba(255,255,255,0.05);
    margin-bottom: 0.4rem;
    max-width: 60ch;
  }
  .rw-detail-grid {
    display: grid; grid-template-columns: max-content 1fr; gap: 4px 14px;
    margin: 0.4rem 0 0.5rem;
  }
  .rw-k { color: #52525b; text-transform: uppercase; letter-spacing: 0.06em;
          font-size: 0.6rem; font-weight: 600; }
  .rw-v { color: #e4e4e7; font-family: "JetBrains Mono", ui-monospace, monospace;
         font-size: 0.74rem; }
  .rw-note { display: flex; gap: 6px; color: #71717a; font-size: 0.7rem;
             margin-top: 0.4rem; max-width: 70ch; }
  .rw-src { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 0.5rem; }
  .rw-src-chip {
    display: inline-flex; align-items: center; gap: 4px;
    background: rgba(255,255,255,0.04); border: 1px solid #27272a;
    border-radius: 6px; padding: 2px 7px; font-size: 0.62rem;
    color: #71717a; font-family: "JetBrains Mono", ui-monospace, monospace;
  }

  /* toolbar */
  .rw-toolbar { display: flex; align-items: flex-end; gap: 0.8rem; margin-bottom: 1.5rem; }
  .rw-toolbar > div { flex: 1; }
  .rw-toolbar > div:first-child { flex: 3; }
  .rw-search-ic { position: relative; }
</style>
<style>
  /* --- Portfolio overview panel --- */
  .rw-ov {
    background: #18181b;
    border: 1px solid #27272a;
    border-radius: 14px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.25);
    padding: 1.5rem 1.6rem 1.2rem;
    margin-bottom: 0.5rem;
  }
  .rw-ov-top { display: grid; grid-template-columns: repeat(4,1fr); gap: 1rem; }
  .rw-ov-tile { display: flex; gap: 0.8rem; align-items: flex-start; }
  .rw-ov-label {
    color: #71717a; font-size: 0.64rem; text-transform: uppercase;
    letter-spacing: 0.08em; font-weight: 600;
  }
  .rw-ov-val {
    font-size: 1.7rem; font-weight: 800; line-height: 1.1;
    margin-top: 2px;
    font-family: "JetBrains Mono","SF Mono",ui-monospace,monospace;
  }
  .rw-ov-sub { color: #52525b; font-size: 0.62rem; margin-top: 1px; }
  .rw-ov-ic { display: inline-flex; padding-top: 4px; }

  .rw-ov-divider { border: none; border-top: 1px solid #27272a; margin: 1.4rem 0 1.2rem !important; }

  .rw-ov-body { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }
  .rw-panel-title {
    color: #71717a; font-size: 0.66rem; text-transform: uppercase;
    letter-spacing: 0.08em; font-weight: 600; margin-bottom: 0.7rem;
  }

  /* sector rows */
  .rw-sectors { display: flex; flex-direction: column; gap: 0.55rem; }
  .rw-sector-row { display: flex; align-items: center; gap: 10px; }
  .rw-sector-name { color: #d4d4d8; font-size: 0.82rem; font-weight: 500;
                    min-width: 120px; }
  .rw-sector-meta { color: #71717a; font-size: 0.74rem;
                    flex: 1; font-family: "JetBrains Mono", ui-monospace, monospace; }
  .rw-sector-row .rw-dot { flex-shrink: 0; }

  /* distribution bars */
  .rw-dist { display: flex; flex-direction: column; gap: 0.4rem; }
  .rw-dist-row { display: grid; grid-template-columns: 60px 1fr 24px;
                 align-items: center; gap: 8px; }
  .rw-dist-label { color: #a1a1aa; font-size: 0.7rem; font-weight: 500; }
  .rw-dist-bar { background: #27272a; border-radius: 999px; height: 5px; overflow: hidden; }
  .rw-dist-fill { height: 5px; border-radius: 999px; }
  .rw-dist-num { color: #a1a1aa; font-size: 0.7rem; font-weight: 600; text-align: right;
                 font-family: "JetBrains Mono", ui-monospace, monospace; }

  /* top 3 */
  .rw-top3 { display: flex; flex-direction: column; gap: 0.35rem; }
  .rw-top3-row { display: grid; grid-template-columns: 18px 1fr 30px auto;
                 align-items: center; gap: 8px; }
  .rw-top3-num { color: #52525b; font-size: 0.68rem; font-weight: 600;
                 font-family: "JetBrains Mono", ui-monospace, monospace; }
  .rw-top3-name { color: #d4d4d8; font-size: 0.78rem; font-weight: 500; overflow: hidden;
                  text-overflow: ellipsis; white-space: nowrap; }
  .rw-top3-score { color: #f87171; font-size: 0.74rem; font-weight: 700; text-align: right;
                   font-family: "JetBrains Mono", ui-monospace, monospace; }
  .rw-top3-pil {
    background: rgba(255,255,255,0.05); color: #a1a1aa; border: 1px solid #27272a;
    border-radius: 999px; padding: 1px 7px; font-size: 0.55rem; font-weight: 500;
  }

  /* worst indicator */
  .rw-worst-row { display: flex; align-items: center; gap: 8px; }
  .rw-worst-label { color: #d4d4d8; font-size: 0.78rem; font-weight: 500; }
  .rw-worst-score { color: #71717a; font-size: 0.7rem;
                    font-family: "JetBrains Mono", ui-monospace, monospace; }

  /* chips */
  .rw-chips { display: flex; gap: 0.6rem; flex-wrap: wrap; margin-top: 0.8rem; }
  .rw-chip {
    display: inline-flex; align-items: center; gap: 6px;
    background: rgba(255,255,255,0.04); border: 1px solid #27272a;
    border-radius: 999px; padding: 3px 10px; font-size: 0.68rem; color: #d4d4d8;
  }

  /* panels gap */
  .rw-ov-right { display: flex; flex-direction: column; gap: 1.1rem; }

  /* hide Streamlit's sticky header (top bar + toolbar) */
  [data-testid="stHeader"] { display: none; }
  #MainMenu { visibility: hidden; }
  footer { visibility: hidden; }
  [data-testid="stToolbar"] { display: none; }
</style>
"""


def inject_theme() -> None:
    """Inject dark dashboard CSS (shadcn tokens) once per page render."""
    st.markdown(_THEME_CSS, unsafe_allow_html=True)


def status_color(status: str) -> str:
    return _STATUS.get(status, _STATUS["unavailable"])["fg"]


def _token(status: str) -> dict[str, str]:
    return _STATUS.get(status, _STATUS["unavailable"])


def _field(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value).replace("<", "&lt;").replace(">", "&gt;")


def _badge(text: str, kind: str = "demo") -> str:
    if kind == "key":
        fg, bg, bd = "#fbbf24", "rgba(251,191,36,0.10)", "rgba(251,191,36,0.30)"
    else:  # demo / none
        fg, bg, bd = "#a1a1aa", "rgba(161,161,170,0.08)", "rgba(161,161,170,0.18)"
    return (
        f'<span class="rw-badge" style="background:{bg};color:{fg};border:1px solid {bd};'
        f'">{_field(text)}</span>'
    )


def _row_html(
    indicator_id: str,
    label: str,
    description: str,
    result: SignalResult,
) -> str:
    tok = _token(result.status)
    fg = tok["fg"]
    status_ic = STATUS_ICON.get(result.status, ic_minus)(14)
    status_icon = f'<span class="rw-icon" style="color:{fg};display:inline-flex">{status_ic}</span>'
    topic_ic_fn, tint = _IND_ICON.get(indicator_id, (ic_gauge, "#71717a"))
    topic_ic = topic_ic_fn(15)
    topic_icon = f'<span class="rw-topic-icon" style="color:{tint}">{topic_ic}</span>'

    mid_extras = ""
    if result.status == "demo":
        mid_extras += _badge("demo")
    if result.missing_env:
        mid_extras += _badge("key", "key")
    mid = (
        f'<span class="rw-mid"><span class="rw-val">{_field(result.value)}</span>'
        f"{mid_extras}</span>"
    )

    if result.status == "unavailable":
        bar = ""
        num = ""
    else:
        bar = (
            f'<span class="rw-bar"><span class="rw-bar-fill" '
            f'style="width:{result.score:.0f}%;background:{fg}"></span></span>'
        )
        num = f'<span class="rw-num">{result.score:.0f}</span>'

    # detail panel (expanded)
    desc_html = f'<div class="rw-desc">{description}</div>' if description else ""
    detail_rows = ""
    if result.detail:
        items = sorted(result.detail.items())
        detail_rows = "".join(
            f'<span class="rw-k">{_field(k)}</span><span class="rw-v">{_field(v)}</span>'
            for k, v in items
        )
        detail_rows = f'<div class="rw-detail-grid">{detail_rows}</div>'
    note_html = ""
    if result.note:
        note_html = (
            f'<div class="rw-note"><span class="rw-icon">{ic_info(13)}</span>'
            f"<span>{_field(result.note)}</span></div>"
        )
    src_html = ""
    if result.source_ids:
        chips = " ".join(
            f'<span class="rw-src-chip">{ic_file_text(12)}{s}</span>' for s in result.source_ids
        )
        src_html = f'<div class="rw-src">{chips}</div>'
    detail_body = desc_html + detail_rows + note_html + src_html
    if not detail_body:
        detail_body = '<div class="rw-note">no detail</div>'

    return (
        f'<details class="rw-row"><summary>'
        f'<span class="rw-row-left">{topic_icon}<span class="rw-label">{label}</span></span>'
        f"{mid}"
        f'<span class="rw-right">{status_icon}{bar}{num}'
        f'<span class="rw-chev">{ic_chevron_down(16)}</span></span>'
        f"</summary>"
        f'<div class="rw-detail">{detail_body}</div>'
        f"</details>"
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
    """Render one company card (collapsible, collapsed by default).

    ``rows`` yields ``(indicator_id, label, description, result)`` tuples.
    Uses a native ``<details>`` mirroring the shadcn Collapsible pattern.
    """
    tok = _token(status)
    fg = tok["fg"]
    sector_pretty = _display_sector(sector)
    body_rows = "".join(_row_html(iid, label, desc, result) for iid, label, desc, result in rows)
    srcs = [s for s in sources if s]
    src_html = ""
    if srcs:
        chips = " ".join(f'<span class="rw-src-chip">{ic_file_text(12)}{s}</span>' for s in srcs)
        src_html = (
            '<div style="padding:0.7rem 0 0.3rem;border-top:1px solid #1f1f23;'
            f'color:#52525b;font-size:0.62rem;">{chips}</div>'
        )
    html = f"""
    <details class="rw-card">
      <summary>
        <div class="rw-card-head" style="flex:1;">
          <div>
            <span class="rw-name">{name}</span>
            <span class="rw-pill">{sector_pretty}</span>
            <span class="rw-ticker">{ticker}</span>
          </div>
          <div class="rw-card-head-right">
            <div class="rw-comp">
              <div class="rw-comp-num" style="color:{fg}">{composite:.0f}</div>
              <div class="rw-comp-cap">composite risk</div>
            </div>
            <span class="rw-card-chev">{ic_chevron_down(18)}</span>
          </div>
        </div>
      </summary>
      <div class="rw-card-body">
        <ul class="rw-rows">{body_rows}</ul>
        {src_html}
      </div>
    </details>
    """
    st.markdown(html, unsafe_allow_html=True)


def _ov_tile_html(icon: str, label: str, value: str, sub: str, color: str = "#fafafa") -> str:
    return f"""
    <div class="rw-ov-tile">
      <div class="rw-ov-ic" style="color:{color}">{icon}</div>
      <div>
        <div class="rw-ov-label">{label}</div>
        <div class="rw-ov-val" style="color:{color}">{value}</div>
        <div class="rw-ov-sub">{sub}</div>
      </div>
    </div>
    """


def _distribution_html(n_good: int, n_warn: int, n_bad: int, n_total: int) -> str:
    def bar(label: str, count: int, color: str) -> str:
        pct = count / n_total * 100 if n_total else 0
        return (
            f'<div class="rw-dist-row"><span class="rw-dist-label">{label}</span>'
            f'<div class="rw-dist-bar"><div class="rw-dist-fill" '
            f'style="width:{pct:.0f}%;background:{color}"></div></div>'
            f'<span class="rw-dist-num">{count}</span></div>'
        )

    return (
        '<div class="rw-dist">'
        + bar("Good", n_good, "#34d399")
        + bar("Warning", n_warn, "#fbbf24")
        + bar("Bad", n_bad, "#f87171")
        + "</div>"
    )


def _sector_html(sec: SectorStat) -> str:
    status = "good" if sec.mean_risk < 35 else "warning" if sec.mean_risk < 65 else "bad"
    color = status_color(status)
    icon = ic_factory(15)
    name = _display_sector(sec.sector)
    return (
        '<div class="rw-sector-row">'
        f'<span class="rw-icon" style="color:{color}">{icon}</span>'
        f'<span class="rw-sector-name">{name}</span>'
        f'<span class="rw-sector-meta">{sec.count} · {sec.share_pct:.0f}% · mean {sec.mean_risk:.0f}</span>'
        f'<span class="rw-dot" style="background:{color}"></span>'
        "</div>"
    )


def _top3_html(top: list[tuple[str, float, str]]) -> str:
    if not top:
        return '<div class="rw-note">n/a</div>'
    rows = ""
    for i, (name, score, sector) in enumerate(top, 1):
        rows += (
            f'<div class="rw-top3-row"><span class="rw-top3-num">{i}</span>'
            f'<span class="rw-top3-name">{name}</span>'
            f'<span class="rw-top3-score">{score:.0f}</span>'
            f'<span class="rw-top3-pil">{_display_sector(sector)}</span></div>'
        )
    return f'<div class="rw-top3">{rows}</div>'


def render_portfolio_overview(stats: PortfolioStats) -> None:
    """Portfolio-level overview: 4-tile top row, then a 2-column body."""
    mean_status = "good" if stats.mean_risk < 35 else "warning" if stats.mean_risk < 65 else "bad"
    mean_color = status_color(mean_status)
    hhi_status = (
        "bad"
        if stats.hhi_label == "high"
        else "warning"
        if stats.hhi_label == "moderate"
        else "good"
    )
    hhi_color = status_color(hhi_status)
    ctry_status = (
        "bad"
        if stats.country_concentration_pct >= 80
        else ("warning" if stats.country_concentration_pct >= 50 else "good")
    )
    ctry_color = status_color(ctry_status)

    top_row = "".join(
        [
            _ov_tile_html(
                ic_gauge(20),
                "Portfolio mean risk",
                f"{stats.mean_risk:.0f}/100",
                "across all borrowers",
                mean_color,
            ),
            _ov_tile_html(
                ic_factory(20),
                "Sector concentration",
                f"{stats.hhi:.0f}",
                f"{stats.hhi_label} (HHI)",
                hhi_color,
            ),
            _ov_tile_html(
                ic_globe(20),
                "Country concentration",
                f"{stats.country_concentration_pct:.0f}%",
                f"{stats.n_distinct_countries} country",
                ctry_color,
            ),
            _ov_tile_html(
                ic_activity(20),
                "Data coverage",
                f"{stats.data_coverage_pct:.0f}%",
                "backed by landed data",
                "#a1a1aa",
            ),
        ]
    )

    sectors_html = "".join(_sector_html(s) for s in stats.sectors)
    sectors_html = f'<div class="rw-sectors">{sectors_html}</div>'

    right_panel = (
        '<div class="rw-panel">'
        '<div class="rw-panel-title">Risk distribution</div>'
        + _distribution_html(stats.n_good, stats.n_warning, stats.n_bad, stats.n_companies)
        + "</div>"
        '<div class="rw-panel">'
        '<div class="rw-panel-title">Top 3 risk borrowers</div>'
        + _top3_html(stats.top_risk)
        + "</div>"
    )
    if stats.worst_indicator_id:
        worst_icon = Icon(16, _worst_icon_paths())
        right_panel += (
            '<div class="rw-panel"><div class="rw-panel-title">Worst-performing indicator</div>'
            f'<div class="rw-worst-row">{worst_icon}'
            f'<span class="rw-worst-label">{stats.worst_indicator_label}</span>'
            f'<span class="rw-worst-score">mean {stats.worst_indicator_mean:.0f}/100</span></div></div>'
        )
    chips = ""
    chips += (
        f'<div class="rw-chip"><span class="rw-icon" style="color:#fb923c">'
        f"{ic_shield(15)}</span>"
        f"<span>{stats.total_sanctions_flags} sanctions flags</span></div>"
    )
    if stats.mean_sentiment is not None:
        sent_color = "#34d399" if stats.mean_sentiment > 0 else "#f87171"
        chips += (
            f'<div class="rw-chip"><span class="rw-icon" style="color:{sent_color}">'
            f"{ic_newspaper(15)}</span>"
            f"<span>news tone {stats.mean_sentiment:+.1f}</span></div>"
        )
    right_panel += f'<div class="rw-chips">{chips}</div>'

    html = f"""
    <div class="rw-ov">
      <div class="rw-ov-top">{top_row}</div>
      <hr class="rw-ov-divider">
      <div class="rw-ov-body">
        <div class="rw-ov-left">
          <div class="rw-panel-title">Sector exposure</div>
          {sectors_html}
        </div>
        <div class="rw-ov-right">{right_panel}</div>
      </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def _worst_icon_paths() -> str:
    return '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>'
