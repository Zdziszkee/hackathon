from __future__ import annotations

from typing import Any, NamedTuple

from yfiles_graphs_for_streamlit import Node

_SECTOR_EDGE_WEIGHT = 0.75
_SCORE_EDGE_WEIGHT = 0.35
_SCORE_PROXIMITY_THRESHOLD = 10
_MAX_EDGES = 30
_UNKNOWN_SECTOR = "Unknown"


class CompanyGraph(NamedTuple):
    name: str
    score: float
    sector: str
    status: str
    ticker: str


def build_correlation_edges(
    companies: list[CompanyGraph],
) -> list[tuple[str, str, float]]:
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
    return [
        Node(
            id=c.ticker.upper(),
            properties={
                "label": c.ticker.upper(),
                "name": c.name,
                "sector": c.sector,
                "score": c.score,
                "status": c.status,
                "anchor_id": c.ticker.upper(),
            },
        )
        for c in companies
    ]


def select_focus_from_returned(
    returned: tuple[list[dict[str, Any]], list[dict[str, Any]]] | None,
) -> str | None:
    if not returned:
        return None
    nodes, _edges = returned
    if not nodes:
        return None
    first = nodes[0]
    if isinstance(first, dict):
        val = first.get("id")
        if isinstance(val, str):
            return val
    return None
