"""Deterministic demo fallback values for the dashboard.

Used only when a source has not landed data yet (or its required env vars are
unset). Values are seeded from the company name so they are stable across
reloads and demonstrably synthetic. Real landed data always takes precedence.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

__all__ = ["DemoValues"]


@dataclass(frozen=True)
class DemoValues:
    """Per-company synthetic indicator values, derived deterministically."""

    _seed: str

    @classmethod
    def for_company(cls, seed: str) -> DemoValues:
        return cls(_seed=seed)

    def _hash(self, salt: str) -> int:
        return int.from_bytes(
            hashlib.sha256(f"{self._seed}|{salt}".encode()).digest()[:4],
            "little",
        )

    def _unit(self, salt: str) -> float:
        return self._hash(salt) / 2**32

    def pmi(self) -> float:
        return round(48.0 + 4.0 * self._unit("pmi"), 1)  # 48..52

    def new_orders(self) -> float:
        return round(48.0 + 6.0 * self._unit("new_orders"), 1)

    def supplier_deliveries(self) -> float:
        return round(48.0 + 8.0 * self._unit("supplier_deliveries"), 1)

    def gscpi(self) -> float:
        return round(-0.5 + 2.0 * (self._unit("gscpi") * 2 - 1), 3)  # -1.5..1.5

    def volatility(self) -> float:
        # Annualized realized vol (%) — risk-ish band 18..45
        return round(18.0 + 27.0 * self._unit("volatility"), 2)

    def sentiment(self) -> float:
        return round(-10.0 + 20.0 * (self._unit("sentiment") * 2 - 1), 2)  # -10..10 tone

    def regulation_count(self) -> int:
        return 1 + (self._hash("regulation") % 9)

    def sanctions_count(self) -> int:
        return self._hash("sanctions") % 3

    def net_margin(self) -> float:
        return round(-5.0 + 25.0 * self._unit("net_margin"), 2)  # -5..20 %

    def country(self) -> str:
        return "United States"

    def country_confidence(self) -> float:
        return round(60.0 + 35.0 * self._unit("country_conf"), 1)

    def industry(self) -> str:
        return "Diversified Industrials"

    def industry_confidence(self) -> float:
        return round(55.0 + 40.0 * self._unit("industry_conf"), 1)

    def demand_trend(self) -> float:
        return round(-5.0 + 10.0 * (self._unit("demand") * 2 - 1), 2)
