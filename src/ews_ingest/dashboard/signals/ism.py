"""Regex parser for the ISM Report on Business page text landed by
``macro.ism_pmi``.

The connector stores the first 5000 chars of the page as ``payload.page_text``.
The headline PMI and the New Orders / Supplier Deliveries sub-indices are short,
labeled numbers ("PMI® registered 49.2 percent", "New Orders ... 52.1 percent",
"Supplier Deliveries ... 50.6 percent"). This helper extracts them by named
pattern, degrading gracefully to ``None`` when the page shape changes — the
caller then falls back to a demo value.
"""

from __future__ import annotations

import re

__all__ = ["parse_ism"]


_PMI = re.compile(r"PMI[^.\d]{0,40}?(\d{1,2}\.\d)", re.I)
_NEW_ORDERS = re.compile(r"New Orders[^.\d]{0,80}?(\d{1,2}\.\d)", re.I)
_SUPP_DEL = re.compile(
    r"Supplier Deliveries[^.\d]{0,80}?(\d{1,2}\.\d)",
    re.I,
)
_BACKLOG = re.compile(r"Backlog[^.\d]{0,60}?(\d{1,2}\.\d)", re.I)


def _first(pattern: re.Pattern[str], text: str) -> float | None:
    m = pattern.search(text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def parse_ism(page_text: str) -> dict[str, float | None]:
    """Return a dict with ``headline``, ``new_orders``, ``supplier_deliveries``.

    Each value is ``None`` when not found in the text (caller falls back to demo).
    """
    return {
        "headline": _first(_PMI, page_text),
        "new_orders": _first(_NEW_ORDERS, page_text),
        "supplier_deliveries": _first(_SUPP_DEL, page_text),
        "backlog": _first(_BACKLOG, page_text),
    }
