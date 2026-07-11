from __future__ import annotations

import logging
from typing import Any, NamedTuple

import numpy as np
import pandas as pd
from statsmodels.stats.multitest import multipletests
from statsmodels.tsa.stattools import grangercausalitytests
from yfiles_graphs_for_streamlit import Node

_SECTOR_EDGE_WEIGHT = 0.75
_SCORE_EDGE_WEIGHT = 0.35
_SCORE_PROXIMITY_THRESHOLD = 10
_MAX_EDGES = 30
_UNKNOWN_SECTOR = "Unknown"


def build_granger_edges(
    returns: dict[str, pd.Series],
    maxlag: int = 5,
    alpha: float = 0.05,
    min_obs: int = 40,
) -> list[tuple[str, str, float]]:
    """Pairwise Granger causality on returns (or earnings surprises).

    Returns directed edges (source, target, weight) where weight = Pearson
    correlation between the source and target return series (signed).
    Only edges whose Granger F-test survives FDR correction at ``alpha`` are kept.
    """
    tickers = list(returns.keys())
    raw_p: list[float] = []
    pairs: list[tuple[str, str, float, float]] = []  # (a, b, p, corr)

    for a in tickers:
        for b in tickers:
            if a == b:
                continue
            df = pd.concat(
                [returns[a].rename(a), returns[b].rename(b)],
                axis=1,
                join="inner",
            ).dropna()
            if len(df) < min_obs:
                continue
            try:
                gc = grangercausalitytests(df[[b, a]], maxlag=maxlag, verbose=False)
                ps = [gc[lag][0]["ssr_chi2test"][1] for lag in range(1, maxlag + 1)]
                p = min(ps)
                corr = float(df[a].corr(df[b]))
                raw_p.append(p)
                pairs.append((a, b, p, corr))
            except Exception as exc:
                logging.getLogger(__name__).debug("granger %s->%s failed: %s", a, b, exc)
                continue

    if not pairs:
        return []

    _, p_fdr, _, _ = multipletests(raw_p, alpha=alpha, method="fdr_bh")

    edges: list[tuple[str, str, float]] = []
    for (a, b, _p, corr), p_corr in zip(pairs, p_fdr, strict=True):
        if p_corr < alpha:
            edges.append((a, b, corr))

    edges.sort(key=lambda x: -abs(x[2]))
    return edges[:_MAX_EDGES]


class CompanyGraph(NamedTuple):
    name: str
    score: float
    sector: str
    status: str
    ticker: str


def build_correlation_edges(
    companies: list[CompanyGraph],
    returns: dict[str, pd.Series] | None = None,
) -> list[tuple[str, str, float]]:
    """Build directed edges.

    If `returns` (ticker -> return series) is provided, uses Granger causality
    for lead-lag / cascade detection. Otherwise falls back to simple heuristic.
    """
    if returns is not None:
        # filter to companies we have
        tickers = {c.ticker for c in companies}
        filtered_returns = {t: s for t, s in returns.items() if t in tickers}
        return build_granger_edges(filtered_returns)

    # heuristic fallback (current behavior)
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
