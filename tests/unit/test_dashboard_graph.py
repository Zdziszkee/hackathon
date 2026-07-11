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
