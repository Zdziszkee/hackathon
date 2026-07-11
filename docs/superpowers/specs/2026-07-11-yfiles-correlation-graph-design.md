# yFiles Correlation Graph — Design Spec

**Date:** 2026-07-11
**Status:** Approved (awaiting user review of written spec)
**Scope:** Single feature, single iteration.

## Problem

`src/ews_ingest/dashboard/app.py:319` calls `render_correlation_graph`, but the
current implementation (`src/ews_ingest/dashboard/ui.py:1137`) only renders a row
of chips. The intent — a node-edge visualization of the portfolio's company
correlations — is stubbed out with a comment: *"placeholder — swap with real
causality data later"*.

`yfiles-graphs-for-streamlit>=1.3.0` is already a declared dependency
(`pyproject.toml:17`) but unused. The user wants the real graph brought back at
the top of the dashboard, with a click-to-focus interaction that ties the
graph to the company cards below.

## Goal

Replace the chip placeholder with a real interactive company-correlation graph
rendered via the yFiles Streamlit component, placed in the same slot (immediately
after `render_topbar`, before `render_portfolio_overview`). Clicking a node
selects it; a "Jump to selected company" button then scrolls the matching
company card into view and expands it.

## Non-Goals (YAGNI)

- Edge semantics beyond same-sector and score-proximity. No Wikidata ownership,
  no shared-source edges, no per-indicator correlation. (User explicitly chose
  the simple option; those alternatives are recorded here for the future.)
- Grouping nodes by sector, heatmap overlay, geospatial layout, animated
  transitions, indicator→indicator relationships.
- A side panel that re-introduces the right-rail the recent UI rework removed.
- A new dependency. The library is already declared.

## Architecture

### Module layout

- `src/ews_ingest/dashboard/graph.py` (new) — pure functions:
  - `build_company_nodes(companies: list[CompanyGraph]) -> list[Node]`
  - `build_correlation_edges(companies: list[CompanyGraph]) -> list[EdgeTuple]`
  - `select_focus_from_returned(returned: tuple[list, list] | None) -> str | None`
  The "edge-builder" logic moves out of `app.py:217-245` into this module so it
  is testable without importing Streamlit.
- `src/ews_ingest/dashboard/ui.py` — `render_correlation_graph` is rewritten to
  call `StreamlitGraphWidget(...).show()`. New helper
  `render_graph_jump_button(ticker: str | None)` renders the "↳ Jump to
  selected company" button (or `None` if no selection). `render_company_card`
  gains an `anchor_id: str` parameter and emits `<details id="pb-co-{anchor_id}">`.
- `src/ews_ingest/dashboard/app.py` — `_render_correlation_graph` shrinks to
  call the new pure functions and hand the result to the yFiles renderer; it
  also captures the `sync_selection` return value into
  `st.session_state["graph_selected"]`. `_render_company_cards` reads
  `st.session_state["focus_company"]`, forces the matching card open, and
  injects the one-time JS scroll shim.

### Data flow

```
main() [app.py]
  ├─ render_topbar(...)
  ├─ _render_correlation_graph(computed)
  │    ├─ build_company_nodes(companies_graph)         [graph.py]
  │    ├─ build_correlation_edges(companies_graph)     [graph.py]
  │    ├─ render_correlation_graph(nodes, edges)      [ui.py]
  │    │    └─ StreamlitGraphWidget(...).show()       ← yFiles WebGL iframe
  │    └─ graph_selected, _ = return_value
  │         └─ st.session_state["graph_selected"] = selected_ticker
  ├─ render_portfolio_overview(stats)
  └─ _render_company_cards(computed)
       └─ if focus_company:
            - open <details id="pb-co-{ticker}">
            - inject <script>scrollIntoView({behavior:smooth})</script>
              once, then clear focus flag
```

### Why a button bridge (not a direct click-to-scroll)

yFiles is a custom Streamlit component (WebGL iframe). It cannot reach into the
parent page's DOM. The supported return channel is
`sync_selection=True`, which surfaces the selected nodes on the *next* rerun.
Streamlit does not auto-rerun on custom component value change, so we surface
the selection with a small "↳ Jump to selected company" button below the graph.
The button sets `st.session_state["focus_company"]` and triggers `st.rerun()`,
which scrolls + expands the matching card.

The yFiles built-in sidebar (`sidebar={"enabled": True, "start_with":
"Neighborhood"}`) still gives the user rich on-click details (neighbor list,
properties panel) without depending on the jump button, so the graph is useful
even before the user clicks the bridge button.

## Component Design

### yFiles `StreamlitGraphWidget` settings

- `nodes` — from `build_company_nodes`. Each `Node`:
  - `id`: company ticker (uppercase, stable key, matches the anchor id on
    the corresponding `<details>`).
  - `properties`: `{"label": ticker, "name": company.name, "sector": sector,
    "score": composite, "status": "good|warning|bad", "anchor_id": ticker}`.
- `edges` — from `build_correlation_edges`. Each `Edge`:
  - `start`, `end`: node ids (ticker).
  - `properties`: `{"weight": 0.35|0.75, "kind": "sector|score"}`.
- `directed=False` (correlations are undirected).
- `graph_layout=Layout.ORGANIC` (force-directed, best for free-form networks).
- `key="ews_corr_graph"` (survives reruns).
- `sync_selection=True` (returns `(selected_nodes, selected_edges)`).
- `sidebar={"enabled": True, "start_with": "Neighborhood"}`.
- `overview=True` (minimap, can be turned off if too noisy).

### Mappings

- `node_label_mapping = "label"` (renders the ticker).
- `node_color_mapping`: callable returning `#29B32E` (good),
  `#F59E0B` (warning), `#DB0011` (bad), or `#9FA1A4` (demo / unknown).
- `node_scale_factor_mapping`: `0.8 + 0.6 * (score / 100)`. Floor 0.8, ceiling 1.4.
- `node_styles_mapping`: returns `NodeStyle(shape=NodeShape.ELLIPSE)`. Does
  *not* set `color` here — `node_color_mapping` owns the color so the two
  mappings don't fight.
- `edge_styles_mapping`: returns `EdgeStyle(thickness=1.5 if weight<0.5 else 3.0,
  color="#9CA3AF", directed=False)`.
- `heat_mapping`: not used.

### Jump-to-selected button

- `render_graph_jump_button(ticker)` renders a small Streamlit button below the
  graph: `st.button("↳ Jump to selected company", key="ews_graph_jump",
  disabled=ticker is None)`.
- On click, sets `st.session_state["focus_company"] = ticker` and calls
  `st.rerun()`. The button is rendered when `st.session_state["graph_selected"]`
  is non-empty; otherwise disabled with help text *"Click a node in the graph
  first."*

### Card scroll shim

`render_company_card(name, sector, ticker, composite, status, …, anchor_id)`
emits `<details id="pb-co-{anchor_id}" …>`. When
`st.session_state["focus_company"]` is set, the card's `open` attribute is
forced and a one-time JS snippet is injected:

```html
<script>
  (function () {
    const el = document.getElementById("pb-co-{{ticker}}");
    if (el) el.scrollIntoView({behavior: "smooth", block: "start"});
  })();
</script>
```

Wrapped in `st.components.v1.html(..., height=0)` and gated by a
`st.session_state["scroll_done_{ticker}"]` flag so it fires exactly once per
selection.

### Edge-builder logic (ported from `app.py:217-245`, ticker-keyed)

The body is the same as the existing inline loop, but takes the new
`CompanyGraph` named tuple and emits `(ticker_i, ticker_j, weight)` so the
edge endpoints match the node ids.

```python
class CompanyGraph(NamedTuple):
    name: str
    score: float
    sector: str
    status: str  # "good" | "warning" | "bad"
    ticker: str  # uppercase; the node id and edge endpoint


def build_correlation_edges(
    companies: list[CompanyGraph],
) -> list[tuple[str, str, float]]:
    edges: list[tuple[str, str, float]] = []
    n = len(companies)
    for i in range(n):
        for j in range(i + 1, n):
            c_i = companies[i]
            c_j = companies[j]
            if c_i.sector == c_j.sector and c_i.sector != "Unknown":
                edges.append((c_i.ticker, c_j.ticker, 0.75))
            elif abs(c_i.score - c_j.score) < 10:
                edges.append((c_i.ticker, c_j.ticker, 0.35))
    return edges[:30]


def build_company_nodes(
    companies: list[CompanyGraph],
) -> list[Node]:
    return [
        Node(
            id=c.ticker,
            properties={
                "label": c.ticker,
                "name": c.name,
                "sector": c.sector,
                "score": c.score,
                "status": c.status,
                "anchor_id": c.ticker,
            },
        )
        for c in companies
    ]


def select_focus_from_returned(
    returned: tuple[list[dict], list[dict]] | None,
) -> str | None:
    """Pick the focus ticker from a yFiles `sync_selection` return value.

    Returns the first selected node's id, or None if the selection is empty
    or no node is selected. (Multi-select is collapsed to the first node —
    the jump button and scroll shim operate on a single card at a time.)
    """
    if not returned:
        return None
    nodes, _edges = returned
    if not nodes:
        return None
    first = nodes[0]
    return first.get("id") if isinstance(first, dict) else None
```

`_render_correlation_graph` constructs `list[CompanyGraph]` from `computed`
and passes it to the pure functions.

## Error Handling

- **yFiles import failure** — guarded at module import time in `ui.py`:
  ```python
  try:
      from yfiles_graphs_for_streamlit import (
          StreamlitGraphWidget,
          Node,
          Edge,
          NodeShape,
          NodeStyle,
          EdgeStyle,
          Layout,
      )
      _YFILES_AVAILABLE = True
  except ImportError:
      _YFILES_AVAILABLE = False
  ```
  If unavailable, `render_correlation_graph` falls back to the chip view (a
  narrowed copy of today's implementation) and logs once via
  `logging.getLogger(__name__).warning("yFiles Graphs for Streamlit not installed; falling back to chip view.")`.
- **No companies** — early `return` (current behavior preserved).
- **> 30 edges** — capped by `build_correlation_edges` (current behavior preserved).
- **Unknown sector** — never produces a sector-edge (current behavior preserved).
- **Selection in demo mode** — selection still works; the focused card may be
  one of the demo set. If `focus_company` doesn't match a real card, the
  scroll shim is a no-op and `focus_company` is cleared on the next rerun.
- **`focus_company` lifecycle** — the flag is set on jump-button click,
  consumed on the next rerun (card opens + shim fires), then cleared
  immediately after so a later unrelated rerun doesn't re-trigger the scroll.
  The clear is unconditional — successful scroll or not.
- **Rerun loop** — the JS shim is gated by a `scroll_done_{ticker}` session flag
  that is set immediately after the shim is rendered, so it cannot loop.
- **yFiles unavailable** — narrows to a chip-strip fallback in `ui.py` only.
  This is a hard-import failure path, not a demo path. The demo path always
  uses the real yFiles graph.

## Demo Fallback

The existing landing-empty demo (4–5 fake companies with synthetic scores)
flows through the same `build_company_nodes` + `build_correlation_edges`
+ `StreamlitGraphWidget.show()` path. There is no separate "demo" branch in
the graph layer. The chip-strip path exists only as the fallback for the
yFiles-import-failure case (a hard import error, not a runtime state).

## Testing

`tests/dashboard/test_correlation_graph.py` (new). Pure-function tests, no
Streamlit:

| Test | Setup | Assertion |
|------|-------|-----------|
| `test_edge_same_sector_strong` | A and B, sector "Tech", scores 50 and 60 | 1 edge (A,B,0.75) |
| `test_edge_score_proximity_moderate` | A "Tech" 50, B "Health" 55 | 1 edge (A,B,0.35) |
| `test_edge_unknown_sector_no_sector_match` | A "Tech" 50, B "Unknown" 50 | 1 edge, weight 0.35 (score-proximity), not 0.75 |
| `test_edge_no_match` | A "Tech" 50, B "Health" 80 | 0 edges |
| `test_edge_caps_at_30` | 12 companies, all same sector | 30 edges max (C(12,2) = 66) |
| `test_node_status_color` | good / warning / bad / demo | returns the 4 hex colors in spec |
| `test_node_scale_factor` | score 0, 50, 100 | 0.8, ~1.1, 1.4 (within ±0.05) |
| `test_node_id_is_ticker` | ticker "aapl" | node id is "AAPL" |
| `test_focus_picks_ticker_from_returned` | returned = ([{"id": "AAPL"}], []) | "AAPL" |
| `test_focus_none_when_nothing_selected` | returned = ([], []) | None |

Tests run under the existing `pytest` config (`addopts = "-m 'not integration'"`
already excludes network tests; these are unit tests so no marker change).

## Files Touched

- `src/ews_ingest/dashboard/graph.py` — new, ~80 lines.
- `src/ews_ingest/dashboard/ui.py` — `render_correlation_graph` rewritten
  (~50 lines), `render_company_card` gains `anchor_id` param (one line of HTML
  change), new `render_graph_jump_button` (~15 lines), `__all__` updated.
- `src/ews_ingest/dashboard/app.py` — `_render_correlation_graph` rewritten
  to call the pure functions and capture `sync_selection`
  (~15 line diff), `_render_company_cards` reads `focus_company` and injects
  the shim (~20 line diff), `main` passes `focus_company` through.
- `tests/dashboard/test_correlation_graph.py` — new, ~120 lines.

Total net change: ~300 lines, one new module, one new test file, no new
dependencies, no schema or data-pipeline changes.

## Acceptance Criteria

1. With at least 3 companies in the portfolio, the yFiles graph renders in
   the same position as today's chip strip (top of dashboard, after topbar).
2. Nodes are colored by status and sized by composite score, matching the
   existing palette.
3. Clicking a node highlights it (built-in yFiles behavior) and the
   "↳ Jump to selected company" button becomes enabled.
4. Clicking the jump button scrolls the matching company card into view and
   expands it. Clicking the button again on a different node scrolls to a
   different card.
5. With the landing zone empty, the demo companies render through the same
   graph path (no chip fallback in normal operation).
6. `uv run ruff check . && uv run ruff format --check . && uv run ty check`
   all pass.
7. `uv run pytest tests/dashboard/test_correlation_graph.py` is green.
8. No new dependencies in `pyproject.toml`.
9. `focus_company` is consumed exactly once per click: set by the jump
   button, used on the next rerun, then cleared. A subsequent unrelated
   rerun (e.g. toggling a different widget) does not re-scroll the page.
10. The graph's WebGL state survives a rerun triggered by an unrelated
    Streamlit widget (verified by `key="ews_corr_graph"`).
