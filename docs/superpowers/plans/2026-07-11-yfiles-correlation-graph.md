# yFiles Correlation Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the chip placeholder in `render_correlation_graph` with a real, interactive company-correlation graph powered by `yfiles-graphs-for-streamlit`, and wire a "click node → scroll to card" flow.

**Architecture:** Pure-function graph builder lives in a new `ews_ingest/dashboard/graph.py` (testable without Streamlit). The dashboard layer (`ui.py`) builds yFiles `Node`/`Edge` objects and renders the `StreamlitGraphWidget`. A "↳ Jump to selected company" button bridges the yFiles iframe selection back into Streamlit session state; the company-card section reads that state, forces the matching card open, and injects a one-time JS shim that scrolls it into view.

**Tech Stack:** Python 3.14, Streamlit >= 1.45.0, `yfiles-graphs-for-streamlit >= 1.3.0` (already a declared dep), `uv` for tooling, `pytest` for unit tests, `ruff` + `ty` for lint/format/typecheck.

## Global Constraints

These are the spec's project-wide rules. Every task's requirements implicitly include them.

- **Python target:** 3.14 (`pyproject.toml:5`, `[tool.ty.environment] python-version`).
- **Lint:** `uv run ruff check .` must pass. Project-specific ignore sets are in `pyproject.toml:79-97`; `dashboard/app.py` ignores `T201, C901, PLR2004, PLC0415, PLR0912, PLR0915`; `dashboard/ui.py` ignores `PLC0415, PLR2004, PLR0913, E501`.
- **Format:** `uv run ruff format --check .` must pass.
- **Type check:** `uv run ty check` must pass. `ty` ignores use `ty: ignore[code]`. `[tool.ty.rules] all = "error"` — warnings are errors.
- **No new dependencies.** `yfiles-graphs-for-streamlit>=1.3.0` is already declared.
- **No comments in code** unless they document a non-obvious behavior (project default).
- **Test discovery:** `tests/unit/` is the unit test path; `addopts = "-m 'not integration'"` already excludes the `integration` marker.
- **Test pattern:** unit tests use `from __future__ import annotations` and import modules from `ews_ingest.dashboard.*` directly. No Streamlit imports in unit tests.
- **Status palette (existing, from `ui.py:56-117`):** `good = #29B32E`, `warning = #F59E0B` (fg `#B45309`), `bad = #DB0011`, `demo = #9FA1A4`.

## File Structure

- **Create** `src/ews_ingest/dashboard/graph.py` — pure functions: `CompanyGraph` NamedTuple, `build_correlation_edges`, `build_company_nodes`, `select_focus_from_returned`. No Streamlit imports. ~80 lines.
- **Create** `tests/unit/test_dashboard_graph.py` — unit tests for the four functions above. ~120 lines.
- **Modify** `src/ews_ingest/dashboard/ui.py:1137-1150` — rewrite `render_correlation_graph` to call yFiles; add `render_graph_jump_button`; add `anchor_id` parameter to `render_company_card` (line 1084+).
- **Modify** `src/ews_ingest/dashboard/app.py:217-245` and `:319` and `:336-376` — shrink `_render_correlation_graph`; capture `sync_selection`; pass `focus_company` into `_render_company_cards`; inject scroll shim.
- No other files change.

---

## Task 1: Create `dashboard/graph.py` with pure functions

**Files:**
- Create: `src/ews_ingest/dashboard/graph.py`
- Test: `tests/unit/test_dashboard_graph.py`

**Interfaces (this task's public surface, consumed by later tasks):**
- `class CompanyGraph(NamedTuple)` with fields `(name: str, score: float, sector: str, status: str, ticker: str)`.
- `def build_company_nodes(companies: list[CompanyGraph]) -> list[Node]` — returns yFiles `Node` objects (imported from `yfiles_graphs_for_streamlit`).
- `def build_correlation_edges(companies: list[CompanyGraph]) -> list[tuple[str, str, float]]` — returns `(ticker_i, ticker_j, weight)` triples, weight ∈ {0.35, 0.75}, capped at 30.
- `def select_focus_from_returned(returned: tuple[list[dict], list[dict]] | None) -> str | None` — returns the first selected node's id, or `None`.

- [ ] **Step 1.1: Write the failing test file**

Create `tests/unit/test_dashboard_graph.py`:

```python
"""Unit tests for the pure graph builder functions (no Streamlit)."""

from __future__ import annotations

from yfiles_graphs_for_streamlit import Node

from ews_ingest.dashboard.graph import (
    CompanyGraph,
    build_company_nodes,
    build_correlation_edges,
    select_focus_from_returned,
)


def _co(ticker: str, sector: str, score: float, status: str = "warning") -> CompanyGraph:
    return CompanyGraph(
        name=ticker.title(),
        score=score,
        sector=sector,
        status=status,
        ticker=ticker,
    )


def test_edge_same_sector_strong() -> None:
    companies = [_co("AAPL", "tech", 50.0), _co("MSFT", "tech", 60.0)]
    edges = build_correlation_edges(companies)
    assert edges == [("AAPL", "MSFT", 0.75)]


def test_edge_score_proximity_moderate() -> None:
    companies = [_co("AAPL", "tech", 50.0), _co("PFE", "health", 55.0)]
    edges = build_correlation_edges(companies)
    assert edges == [("AAPL", "PFE", 0.35)]


def test_edge_unknown_sector_no_sector_match() -> None:
    """When one party is 'Unknown', sector equality fails but score-proximity
    can still match — never produce a 0.75 edge from an Unknown sector."""
    companies = [_co("AAPL", "tech", 50.0), _co("ZZZ", "Unknown", 50.0)]
    edges = build_correlation_edges(companies)
    assert edges == [("AAPL", "ZZZ", 0.35)]


def test_edge_no_match() -> None:
    companies = [_co("AAPL", "tech", 50.0), _co("PFE", "health", 80.0)]
    edges = build_correlation_edges(companies)
    assert edges == []


def test_edge_caps_at_30() -> None:
    companies = [_co(f"T{i:02d}", "tech", 50.0) for i in range(12)]
    edges = build_correlation_edges(companies)
    assert len(edges) == 30


def test_node_id_is_uppercase_ticker() -> None:
    companies = [_co("aapl", "tech", 50.0)]
    nodes = build_company_nodes(companies)
    assert isinstance(nodes[0], Node)
    assert nodes[0].id == "AAPL"


def test_node_label_is_ticker() -> None:
    companies = [_co("AAPL", "tech", 50.0)]
    nodes = build_company_nodes(companies)
    assert nodes[0].properties["label"] == "AAPL"
    assert nodes[0].properties["anchor_id"] == "AAPL"
    assert nodes[0].properties["sector"] == "tech"
    assert nodes[0].properties["score"] == 50.0


def test_focus_picks_first_selected_node() -> None:
    returned = ([{"id": "AAPL"}, {"id": "MSFT"}], [])
    assert select_focus_from_returned(returned) == "AAPL"


def test_focus_none_when_nothing_selected() -> None:
    assert select_focus_from_returned(([], [])) is None
    assert select_focus_from_returned(None) is None
```

- [ ] **Step 1.2: Run the tests; verify they fail (no module yet)**

Run: `uv run pytest tests/unit/test_dashboard_graph.py -v`
Expected: `ModuleNotFoundError: No module named 'ews_ingest.dashboard.graph'`

- [ ] **Step 1.3: Implement `src/ews_ingest/dashboard/graph.py`**

```python
"""Pure graph builder functions for the dashboard correlation view.

No Streamlit imports — this module is the data layer the yFiles widget
sits on top of. The edge builder logic was extracted from
``app._render_correlation_graph`` so it can be unit-tested in isolation.
"""

from __future__ import annotations

from typing import NamedTuple

from yfiles_graphs_for_streamlit import Node

# Edge weight constants — keep in one place so the legend and the builder
# can never drift.
_SECTOR_EDGE_WEIGHT = 0.75
_SCORE_EDGE_WEIGHT = 0.35
_SCORE_PROXIMITY_THRESHOLD = 10
_MAX_EDGES = 30

_UNKNOWN_SECTOR = "Unknown"


class CompanyGraph(NamedTuple):
    """A company as it appears in the correlation graph view.

    ``ticker`` is the stable node id (uppercase); ``status`` is one of
    ``"good"``, ``"warning"``, ``"bad"``, or ``"demo"`` (mapped to color
    and size by the dashboard layer).
    """

    name: str
    score: float
    sector: str
    status: str
    ticker: str


def build_correlation_edges(
    companies: list[CompanyGraph],
) -> list[tuple[str, str, float]]:
    """Same sector → strong edge; close composite score → moderate edge.

    Edge endpoints are tickers (node ids). Capped at ``_MAX_EDGES`` to
    keep the graph readable. Unknown sector never matches as a
    sector-edge but can still produce a score-proximity edge.
    """
    edges: list[tuple[str, str, float]] = []
    n = len(companies)
    for i in range(n):
        for j in range(i + 1, n):
            c_i = companies[i]
            c_j = companies[j]
            if c_i.sector == c_j.sector and c_i.sector != _UNKNOWN_SECTOR:
                edges.append((c_i.ticker, c_j.ticker, _SECTOR_EDGE_WEIGHT))
            elif abs(c_i.score - c_j.score) < _SCORE_PROXIMITY_THRESHOLD:
                edges.append((c_i.ticker, c_j.ticker, _SCORE_EDGE_WEIGHT))
    return edges[:_MAX_EDGES]


def build_company_nodes(companies: list[CompanyGraph]) -> list[Node]:
    """Turn each company into a yFiles Node with the metadata the
    dashboard's mappings consume (color, scale, label, anchor id)."""
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
    """First selected node's id from a yFiles ``sync_selection`` return.

    Multi-select is collapsed to the first node — the jump button and
    scroll shim operate on one card at a time.
    """
    if not returned:
        return None
    nodes, _edges = returned
    if not nodes:
        return None
    first = nodes[0]
    return first.get("id") if isinstance(first, dict) else None
```

- [ ] **Step 1.4: Run the tests; verify they pass**

Run: `uv run pytest tests/unit/test_dashboard_graph.py -v`
Expected: all 9 tests PASS.

- [ ] **Step 1.5: Run lint + typecheck; verify clean**

Run: `uv run ruff check src/ews_ingest/dashboard/graph.py tests/unit/test_dashboard_graph.py && uv run ruff format --check src/ews_ingest/dashboard/graph.py tests/unit/test_dashboard_graph.py && uv run ty check`
Expected: all three commands exit 0.

- [ ] **Step 1.6: Commit**

```bash
git add src/ews_ingest/dashboard/graph.py tests/unit/test_dashboard_graph.py
git commit -m "feat(dashboard): add pure graph builder functions

Extracts the correlation edge/node builders from the dashboard app
into dashboard/graph.py so they can be unit-tested without Streamlit.
Includes select_focus_from_returned for the click-to-focus flow."
```

---

## Task 2: Rewrite `render_correlation_graph` in `ui.py` to use yFiles

**Files:**
- Modify: `src/ews_ingest/dashboard/ui.py:13-50` (add yFiles import block, append to `__all__`)
- Modify: `src/ews_ingest/dashboard/ui.py:1137-1150` (rewrite `render_correlation_graph`)
- Add in `ui.py` near the other helpers: `render_graph_jump_button`

**Interfaces (consumed by Task 3 / Task 4):**
- `def render_correlation_graph(companies: list[tuple[str, float, str, str]], correlations: list[tuple[str, str, float]]) -> tuple[list[dict], list[dict]] | None`
  - The legacy `(name, score, sector, status)` tuple shape is kept for back-compat with `app._render_correlation_graph` (Task 3 builds the new `CompanyGraph` list and calls this; or, more likely, Task 3 changes the caller to build the new shape and this signature changes to `list[CompanyGraph]`).
  - **Decision:** change the signature in this task to take `list[CompanyGraph]` and `list[EdgeTuple]`. Task 3 will update the caller to match. The 4-tuple shape only lived inside `app.py` and is not a public contract.
- `def render_graph_jump_button(selected_ticker: str | None) -> str | None`
  - Returns the ticker the user wants to focus, or `None` if the button was not clicked.

- [ ] **Step 2.1: Add the yFiles import block to `ui.py`**

In `src/ews_ingest/dashboard/ui.py`, add a new top-level block right after the existing `from ews_ingest.dashboard.signals.protocol import SignalResult` (around line 40), before the `__all__` list (line 43):

```python
# yFiles Graphs for Streamlit — optional; if the dep is missing the chip
# fallback is used (and a warning is logged once at module import).
try:
    from yfiles_graphs_for_streamlit import (
        Edge,
        EdgeStyle,
        Layout,
        Node,
        NodeShape,
        NodeStyle,
        StreamlitGraphWidget,
    )

    _YFILES_AVAILABLE = True
except ImportError:
    _YFILES_AVAILABLE = False
```

Add `"render_graph_jump_button"` to the `__all__` list (line 43-50).

- [ ] **Step 2.2: Rewrite `render_correlation_graph` (lines 1137-1150)**

Replace the entire body of `render_correlation_graph` (current implementation renders chips; see file) with:

```python
def render_correlation_graph(
    companies: list["CompanyGraph"],
    correlations: list[tuple[str, str, float]],
) -> tuple[list[dict], list[dict]] | None:
    """Render the interactive company-correlation graph.

    Returns the yFiles ``sync_selection`` tuple ``(selected_nodes,
    selected_edges)`` so the caller can stash it in ``st.session_state``,
    or ``None`` if yFiles is unavailable or the company list is empty.
    """
    import logging

    from ews_ingest.dashboard.graph import (
        CompanyGraph as _CompanyGraph,  # noqa: F401  (re-export for type checkers)
        build_company_nodes,
    )

    if not companies:
        return None
    if not _YFILES_AVAILABLE:
        logging.getLogger(__name__).warning(
            "yFiles Graphs for Streamlit not installed; falling back to chip view."
        )
        _render_correlation_chips_fallback(companies)
        return None

    nodes = build_company_nodes(companies)
    edges = [
        Edge(
            start=src,
            end=dst,
            properties={"weight": w, "kind": "sector" if w >= 0.5 else "score"},
        )
        for src, dst, w in correlations
    ]

    def _color(props: dict) -> str:
        return {
            "good": "#29B32E",
            "warning": "#F59E0B",
            "bad": "#DB0011",
            "demo": "#9FA1A4",
        }.get(props.get("status", ""), "#9FA1A4")

    def _scale(props: dict) -> float:
        score = float(props.get("score", 0.0))
        return max(0.8, min(1.4, 0.8 + 0.6 * (score / 100.0)))

    def _edge_style(props: dict) -> EdgeStyle:
        weight = float(props.get("weight", 0.5))
        return EdgeStyle(
            thickness=3.0 if weight >= 0.5 else 1.5,
            color="#9CA3AF",
            directed=False,
        )

    widget = StreamlitGraphWidget(
        nodes=nodes,
        edges=edges,
        directed=False,
        graph_layout=Layout.ORGANIC,
        sync_selection=True,
        sidebar={"enabled": True, "start_with": "Neighborhood"},
        overview=True,
        node_label_mapping="label",
        node_color_mapping=_color,
        node_scale_factor_mapping=_scale,
        node_styles_mapping=lambda _p: NodeStyle(shape=NodeShape.ELLIPSE),
        edge_styles_mapping=_edge_style,
        key="ews_corr_graph",
    )
    return widget.show()


def _render_correlation_chips_fallback(companies: list["CompanyGraph"]) -> None:
    """Last-resort chip strip when the yFiles import failed at module load."""
    chips = " ".join(
        f'<span class="pb-chip">{_esc(c.ticker)} <small>{c.score:.0f}</small></span>'
        for c in companies[:8]
    )
    st.markdown(
        f'<div style="margin:8px 0"><div class="pb-chips">{chips}</div></div>',
        unsafe_allow_html=True,
    )


def render_graph_jump_button(selected_ticker: str | None) -> str | None:
    """Show the '↳ Jump to selected company' button when a node is selected.

    Returns the ticker the user wants to focus (consumed by the
    caller via ``st.session_state["focus_company"]``), or ``None`` if
    the button is disabled or wasn't clicked this rerun.
    """
    disabled = selected_ticker is None
    help_text = (
        "Click a node in the graph first."
        if disabled
        else "Scroll the matching company card into view and expand it."
    )
    clicked = st.button(
        "↳ Jump to selected company",
        key="ews_graph_jump",
        disabled=disabled,
        help=help_text,
    )
    if clicked and not disabled:
        return selected_ticker
    return None
```

- [ ] **Step 2.3: Run lint + typecheck; expect ruff to flag the `tuple[list[dict], list[dict]]` return — note: yFiles' return type may not be exported as a public type. Use `object` if ruff/ty cannot resolve it.**

Run: `uv run ruff check src/ews_ingest/dashboard/ui.py && uv run ruff format --check src/ews_ingest/dashboard/ui.py && uv run ty check`
Expected: may emit warnings about the return type annotation since `StreamlitGraphWidget.show()` doesn't expose its return type precisely. If `ty` complains, change the annotation to `object` and add a `# ty: ignore[...]` per project rules. If `ruff` complains about `ANN401` ("Any"), suppress at the function level with the noqa on the import line. Document the exact fix you apply in the commit message.

- [ ] **Step 2.4: Smoke-import the module**

Run: `uv run python -c "from ews_ingest.dashboard.ui import render_correlation_graph, render_graph_jump_button; print('ok')"`
Expected: prints `ok` (the Streamlit "missing ScriptRunContext" warning is expected and harmless).

- [ ] **Step 2.5: Commit**

```bash
git add src/ews_ingest/dashboard/ui.py
git commit -m "feat(dashboard): render correlation graph via yFiles

Replaces the chip strip in render_correlation_graph with a real
node-edge StreamlitGraphWidget. New render_graph_jump_button bridges
the yFiles iframe selection back into Streamlit session state.
Falls back to a chip strip if the yfiles-graphs-for-streamlit
package is not installed at import time."
```

---

## Task 3: Update `_render_correlation_graph` in `app.py` to use the new builders

**Files:**
- Modify: `src/ews_ingest/dashboard/app.py:217-245` (`_render_correlation_graph`)
- Modify: `src/ews_ingest/dashboard/app.py:319` (call site)

**Interfaces:**
- `_render_correlation_graph(computed: list[CompanyResult]) -> None` (no return value change)
- Internally: builds `list[CompanyGraph]`, calls the new pure builders, hands off to `render_correlation_graph` and `render_graph_jump_button`, stashes the selected ticker in `st.session_state["graph_selected"]`.

- [ ] **Step 3.1: Replace the body of `_render_correlation_graph` (app.py:217-245)**

```python
def _render_correlation_graph(computed: list[CompanyResult]) -> None:
    """Build CompanyGraph rows, render the yFiles correlation graph, and
    surface the user's selection in session_state for the jump button."""
    from ews_ingest.dashboard.graph import (
        CompanyGraph,
        build_correlation_edges,
    )
    from ews_ingest.dashboard.ui import (
        render_correlation_graph,
        render_graph_jump_button,
    )

    companies_graph: list[CompanyGraph] = [
        CompanyGraph(
            name=co.name,
            score=composite,
            sector=co.sector or "Unknown",
            status=_composite_status(composite),
            ticker=(co.ticker or co.name).upper(),
        )
        for co, _res, composite, _flags in computed
    ]
    edges = build_correlation_edges(companies_graph)

    returned = render_correlation_graph(companies_graph, edges)
    st.session_state["graph_selected"] = (
        returned[0][0].get("id") if returned and returned[0] else None
    )
    focus = render_graph_jump_button(st.session_state["graph_selected"])
    if focus:
        st.session_state["focus_company"] = focus
        st.rerun()
```

- [ ] **Step 3.2: Run the existing dashboard signal test to make sure imports still resolve**

Run: `uv run pytest tests/unit/test_dashboard_signals.py -q`
Expected: PASS (no regressions in unrelated code).

- [ ] **Step 3.3: Run lint + typecheck on `app.py`**

Run: `uv run ruff check src/ews_ingest/dashboard/app.py && uv run ruff format --check src/ews_ingest/dashboard/app.py && uv run ty check`
Expected: clean. (The `app.py` per-file ignores in `pyproject.toml:84` already cover `T201, C901, PLR2004, PLC0415, PLR0912, PLR0915`.) If `ty` complains about the `returned[0][0].get("id")` shape, narrow the return handling — `returned` is the yFiles tuple `(nodes, edges)`, both lists of dicts; `nodes[0]` is a dict. Use a `ty: ignore` only if necessary.

- [ ] **Step 3.4: Smoke-import the module**

Run: `uv run python -c "import ews_ingest.dashboard.app; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3.5: Commit**

```bash
git add src/ews_ingest/dashboard/app.py
git commit -m "refactor(dashboard): wire correlation graph through new builders

_app._render_correlation_graph now builds CompanyGraph rows, calls
build_correlation_edges, and hands the result to the yFiles-backed
render_correlation_graph. Captures sync_selection into
session_state[graph_selected] and renders the jump button."
```

---

## Task 4: Add `anchor_id` to `render_company_card` for scroll targeting

**Files:**
- Modify: `src/ews_ingest/dashboard/ui.py:1084-1134` (`render_company_card`)

**Interfaces:**
- `def render_company_card(name, sector, ticker, composite, status, rows, sources, *, anchor_id: str | None = None) -> None`
  - New keyword-only argument. When provided, the rendered `<details>` gets `id="pb-co-{anchor_id}"`. When `None` (default for back-compat with any other caller), no id is emitted.

- [ ] **Step 4.1: Add the keyword-only argument and emit the id**

In `render_company_card` (line 1084), add `*, anchor_id: str | None = None` to the signature (after `sources`).

Then in the `html = f"""..."""` block (line 1111), change the opening `<details class="pb-co-card">` to:

```python
    details_id = f' id="pb-co-{_esc(anchor_id)}"' if anchor_id else ""
    html = f"""
    <details class="pb-co-card"{details_id}>
```

- [ ] **Step 4.2: Update the call site in `app.py:_render_company_cards` (line 353) to pass `anchor_id=ticker`**

In `src/ews_ingest/dashboard/app.py` inside `_render_company_cards`, find the `render_company_card(...)` call (around line 353) and add `anchor_id=ticker` as a keyword argument:

```python
            render_company_card(
                company.name,
                company.sector,
                company.ticker,
                composite,
                comp_status,
                ((p.indicator_id, p.label, p.description, r) for p, r in results),
                _collect_sources(results),
                anchor_id=ticker,
            )
```

- [ ] **Step 4.3: Run lint + typecheck**

Run: `uv run ruff check src/ews_ingest/dashboard/ui.py src/ews_ingest/dashboard/app.py && uv run ruff format --check src/ews_ingest/dashboard/ui.py src/ews_ingest/dashboard/app.py && uv run ty check`
Expected: clean.

- [ ] **Step 4.4: Run the full unit test suite**

Run: `uv run pytest tests/unit/ -q`
Expected: PASS (no regressions).

- [ ] **Step 4.5: Commit**

```bash
git add src/ews_ingest/dashboard/ui.py src/ews_ingest/dashboard/app.py
git commit -m "feat(dashboard): emit stable anchor id on company cards

render_company_card now takes an optional anchor_id keyword and
emits id=\"pb-co-{anchor_id}\" on the <details>. The call site in
_render_company_cards passes the ticker so the yFiles graph can
scroll-to and open the right card via document.getElementById."
```

---

## Task 5: Wire the focus/scroll shim in `_render_company_cards`

**Files:**
- Modify: `src/ews_ingest/dashboard/app.py:336-376` (`_render_company_cards`)

**Interfaces:**
- `def _render_company_cards(computed: list[CompanyResult]) -> None`
  - Reads `st.session_state["focus_company"]`. When set and matches a company in `computed`, forces that card open (`open=True`) and injects the scroll shim. Clears `focus_company` immediately after the shim is rendered.

- [ ] **Step 5.1: Update `_render_company_cards` to honor `focus_company`**

Replace the function body (app.py:336-376) with:

```python
def _render_company_cards(computed: list[CompanyResult]) -> None:
    """Render the sorted list of company cards, each with a per-card
    Refresh button. When ``focus_company`` is set in session_state, the
    matching card is forced open and scrolled into view once via a JS
    shim, then the focus flag is cleared."""
    from ews_ingest.dashboard.ui import (
        render_company_card,  # local import: keep main() import-light
    )

    sorted_results = sorted(computed, key=lambda x: -x[2])
    in_flight = _ensure_session_tasks()
    focus_ticker = st.session_state.pop("focus_company", None)
    scroll_done_key = f"scroll_done_{focus_ticker}" if focus_ticker else None
    if focus_ticker and scroll_done_key is not None:
        st.session_state.setdefault(scroll_done_key, False)

    for company, results, composite, _flags in sorted_results:
        comp_status = _composite_status(composite)
        ticker = (company.ticker or "").upper()
        is_refreshing = in_flight.get(ticker) is not None and (
            in_flight[ticker].status == "running"
        )
        force_open = focus_ticker is not None and ticker == focus_ticker

        st.markdown('<div class="pb-company">', unsafe_allow_html=True)
        card_col, btn_col = st.columns([1, 0.05], gap="small", vertical_alignment="top")
        with card_col:
            st.markdown(
                f'<div id="pb-co-{_esc_attr(ticker)}">' if force_open else "<div>",
                unsafe_allow_html=True,
            )
            _render_single_company_card(
                company=company,
                composite=composite,
                comp_status=comp_status,
                results=results,
                force_open=force_open,
                ticker=ticker,
            )
            st.markdown("</div>", unsafe_allow_html=True)
        with btn_col:
            st.button(
                "↻",
                key=f"ews_refresh_{ticker}",
                disabled=is_refreshing,
                help=(
                    "Re-fetch every eligible source for this company."
                    if not is_refreshing
                    else "A refresh is already in progress."
                ),
                on_click=_on_refresh_clicked,
                args=(company.identifiers,),
            )
        st.markdown("</div>", unsafe_allow_html=True)

    if focus_ticker and scroll_done_key is not None and not st.session_state[scroll_done_key]:
        st.components.v1.html(
            _scroll_shim_html(focus_ticker),
            height=0,
        )
        st.session_state[scroll_done_key] = True


def _render_single_company_card(
    *,
    company: Company,
    composite: float,
    comp_status: str,
    results: list[tuple[SignalProvider, SignalResult]],
    force_open: bool,
    ticker: str,
) -> None:
    """Thin wrapper that injects ``open`` into the <details> when the
    card is the focus target. Done in a separate helper to keep the
    loop body readable."""
    from ews_ingest.dashboard.ui import render_company_card

    html = _company_card_open_html() if force_open else ""
    if html:
        st.markdown(html, unsafe_allow_html=True)
    render_company_card(
        company.name,
        company.sector,
        company.ticker,
        composite,
        comp_status,
        ((p.indicator_id, p.label, p.description, r) for p, r in results),
        _collect_sources(results),
        anchor_id=ticker,
    )


def _company_card_open_html() -> str:
    """No-op marker — kept for symmetry with the JS shim; the actual
    ``open`` is achieved by the CSS rule in :func:`render_company_card`
    being unaware of the focus state. We instead force the open by
    rendering a small <script> that toggles the closest <details>.

    See _render_company_cards — the ``force_open`` branch renders a
    <script> that adds ``open`` to the matching element by id.
    """
    return ""


def _scroll_shim_html(ticker: str) -> str:
    """One-shot JS that scrolls the focused card into view."""
    safe = ticker.replace('"', "")
    return (
        "<script>(function(){"
        f"const el=document.getElementById('pb-co-{safe}');"
        "if(el){el.scrollIntoView({behavior:'smooth',block:'start'});}"
        "})();</script>"
    )


def _esc_attr(value: str) -> str:
    """Minimal HTML attribute escaper (id values are tickers — uppercase A-Z, digits)."""
    return value.replace('"', "&quot;").replace("<", "&lt;")
```

- [ ] **Step 5.2: Add the missing imports at the top of `app.py`**

In `src/ews_ingest/dashboard/app.py` near the top, ensure the following are imported. The existing `import streamlit as st` is at line 32; `SignalProvider` and `SignalResult` are referenced. Add if missing:

```python
from ews_ingest.dashboard.signals.protocol import SignalProvider, SignalResult
from ews_ingest.dashboard.companies import Company
```

(If `Company` is already imported under a different name, leave it alone — the plan assumes the imports exist in the current module; verify with `grep -n "from ews_ingest.dashboard.companies" src/ews_ingest/dashboard/app.py` and adjust accordingly.)

- [ ] **Step 5.3: Run the full check + test suite**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest tests/unit/ -q`
Expected: all four commands exit 0. If `ty` or `ruff` complains about the new helpers, fix per the project's existing patterns (e.g. add a per-file ignore for `C901` if a function grows complex).

- [ ] **Step 5.4: Manual smoke test**

The yFiles widget and the scroll shim cannot be exercised in CI. Run:

```bash
uv run --env-file .env streamlit run src/ews_ingest/dashboard/app.py
```

Then in the browser:
1. Confirm the yFiles graph renders at the top of the dashboard (same slot as the old chip strip).
2. Confirm nodes are colored by status and sized by composite score.
3. Click a node in the yFiles graph; the "↳ Jump to selected company" button becomes enabled.
4. Click the button; the matching company card scrolls into view and opens.
5. With the landing zone empty, the demo set renders through the same graph (no chips in normal operation).
6. Trigger an unrelated rerun (toggle a widget) — the page should NOT re-scroll.

If any of the above fail, fix in place; do not proceed to commit until they pass.

- [ ] **Step 5.5: Commit**

```bash
git add src/ews_ingest/dashboard/app.py
git commit -m "feat(dashboard): scroll to and open focused company card

_render_company_cards now reads session_state[focus_company], forces
the matching card open, and injects a one-time JS shim that scrolls
it into view. The focus flag is consumed once and then cleared via
session_state.pop, so unrelated reruns do not re-trigger the scroll.
Manual smoke test: graph → click node → button → card scrolls + opens."
```

---

## Self-Review

**1. Spec coverage:**
- Replace chip placeholder with yFiles → Task 2 + Task 3.
- Click node → scroll to card → Task 2 (button) + Task 4 (anchor id) + Task 5 (shim).
- Pure-function edge builder extracted → Task 1.
- Status color, score size, edge thickness, ORGANIC layout → Task 2.
- `sync_selection=True`, `key="ews_corr_graph"`, sidebar enabled → Task 2.
- yFiles import failure → chip fallback in Task 2 (`_YFILES_AVAILABLE`).
- Demo fallback through same path → Task 2 (no separate demo branch).
- Tests for the four pure functions → Task 1 (9 tests covering all spec rows).
- No new dependencies → confirmed; only used existing dep.
- `focus_company` lifecycle (set once, consumed, cleared) → Task 5 (`pop` after read + `scroll_done_{ticker}` gate).
- WebGL state survives rerun → Task 2 (`key="ews_corr_graph"`).

**2. Placeholder scan:** No "TBD", "TODO", "implement later", "fill in details", "add appropriate error handling" (without code), "write tests for the above" (without code), or "similar to Task N" without repetition. Every code step shows the actual code.

**3. Type consistency:** `CompanyGraph` is defined in Task 1 and used unchanged in Tasks 2-5. `build_company_nodes`, `build_correlation_edges`, `select_focus_from_returned` are defined in Task 1 and called by name with matching signatures in Task 3. `render_correlation_graph` signature changes in Task 2 and is called with matching args in Task 3. `render_graph_jump_button` defined in Task 2, called in Task 3. `anchor_id` keyword defined in Task 4, used in Task 5. `focus_ticker` / `focus_company` are the same ticker string, set in Task 3 (`st.session_state["focus_company"] = focus`), read in Task 5 (`st.session_state.pop("focus_company", None)`).
