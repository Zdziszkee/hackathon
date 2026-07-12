from __future__ import annotations

import numpy as np
import pandas as pd

from ews_ingest.dashboard.graph import (
    CompanyGraph,
    build_correlation_edges,
    build_correlation_edges_from_returns,
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


def test_focus_picks_first_selected_node() -> None:
    returned = ([{"id": "AAPL"}, {"id": "MSFT"}], [])
    assert select_focus_from_returned(returned) == "AAPL"


def test_focus_none_when_nothing_selected() -> None:
    assert select_focus_from_returned(([], [])) is None
    assert select_focus_from_returned(None) is None


def test_correlation_edges_from_returns_every_to_every() -> None:
    rng = np.random.default_rng(0)
    n = 200
    a = rng.standard_normal(n)
    b = np.zeros(n)
    b[0] = rng.standard_normal()
    for i in range(1, n):
        b[i] = 0.7 * a[i - 1] + 0.3 * b[i - 1] + 0.1 * rng.standard_normal()
    c = rng.standard_normal(n)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    series = {
        "A": pd.Series(a, index=idx, name="A"),
        "B": pd.Series(b, index=idx, name="B"),
        "C": pd.Series(c, index=idx, name="C"),
    }
    edges = build_correlation_edges_from_returns(series)
    # every-to-every: A->B, A->C, B->A, B->C, C->A, C->B
    assert len(edges) == 6
    assert any(src == "A" and tgt == "B" for src, tgt, _ in edges)
    # weight is signed Pearson correlation; A->B should be positive (synthetic lead-lag)
    a_to_b = next((w for s, t, w in edges if s == "A" and t == "B"), None)
    assert a_to_b is not None
    assert a_to_b > 0
