"""Industry-profitability indicator (role: ``financials.xbrl``).

Reads the most recent XBRL company-facts landed by the SEC company-facts
connector and computes a net-income margin proxy
(``NetIncomeLoss / Revenues`` -> percent). Industry profitability is a
single-company margin labeled by the company's seeded sector.

GAE concepts used (degrading to whatever tags are present):
* ``us-gaap/Revenues`` (or ``RevenueFromContractWithCustomerExcludingAssessedTax``)
* ``us-gaap/NetIncomeLoss``
"""

from __future__ import annotations

from typing import cast

from ews_ingest.core.models import Identifiers
from ews_ingest.dashboard.demo import DemoValues
from ews_ingest.dashboard.signals import (
    SignalContext,
    SignalResult,
    cast_status,
    demo_result,
    ok_result,
    register_provider,
)

__all__ = ["Provider", "compute"]

ROLE = "financials.xbrl"

_REVENUE_TAGS = (
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
)
_NET_INCOME_TAGS = ("NetIncomeLoss", "ProfitLoss")


def _latest_value(units: object) -> tuple[float | None, str]:
    """Pull the most-recent (value, end-date) from an XBRL ``units`` block."""
    if not isinstance(units, dict):
        return None, ""
    # prefer USD; fall back to first unit key (e.g. USD/shares)
    usd = units.get("USD")
    if not isinstance(usd, list) or not usd:
        usd = next((v for v in units.values() if isinstance(v, list) and v), [])
    if not usd:
        return None, ""
    best_end = ""
    best_val: float | None = None
    for entry in usd:
        if not isinstance(entry, dict):
            continue
        end = str(entry.get("end") or entry.get("fy") or "")
        val = entry.get("val")
        if not isinstance(val, (int, float)):
            continue
        if best_val is None or end > best_end:
            best_end = end
            best_val = float(val)
    return best_val, best_end


def _us_gaap_concepts(payload: dict[str, object]) -> dict[str, object]:
    """Descend into the companyfacts ``facts.us-gaap`` taxonomy."""
    facts = payload.get("facts")
    if not isinstance(facts, dict):
        return {}
    us_gaap = facts.get("us-gaap")
    if not isinstance(us_gaap, dict):
        return {}
    return cast("dict[str, object]", us_gaap)


def _concept_value(
    concepts: dict[str, object],
    tags: tuple[str, ...],
) -> tuple[float | None, str]:
    for tag in tags:
        node = concepts.get(tag)
        if isinstance(node, dict):
            v, end = _latest_value(node.get("units"))
            if v is not None:
                return v, end
    return None, ""


def _annual_or_latest(v_end: tuple[float | None, str]) -> float | None:
    return v_end[0]


def compute(company: Identifiers, ctx: SignalContext) -> SignalResult:
    source_id = ctx.source_for(ROLE)
    if source_id is None:
        return SignalResult(
            value="n/a",
            score=0.0,
            status=cast_status("unavailable"),
            detail={},
            source_ids=(),
            note="No financials source bound for this region.",
        )
    seed = company.name or company.ticker or company.cik or "company"
    demo = DemoValues.for_company(seed)
    if missing := ctx.missing_env(source_id):
        return demo_result(
            label_hint="profitability",
            value=rf"{demo.net_margin():+.1f}%",
            score=max(0.0, 60.0 - demo.net_margin() * 2.0),
            missing_env=tuple(missing),
            source_ids=(source_id,),
            note="Required env var(s) not set — showing demo margin.",
        )
    records = ctx.landing.read(source_id).records
    if not records:
        return demo_result(
            label_hint="profitability",
            value=rf"{demo.net_margin():+.1f}%",
            score=max(0.0, 60.0 - demo.net_margin() * 2.0),
            source_ids=(source_id,),
            note="No SEC company-facts records landed — showing demo margin.",
        )
    facts_for_company: dict[str, object] | None = None
    for rec in records:
        if _matches_entity(rec.entities, company):
            facts_for_company = rec.payload
            break
    if facts_for_company is None:
        return demo_result(
            label_hint="profitability",
            value=rf"{demo.net_margin():+.1f}%",
            score=max(0.0, 60.0 - demo.net_margin() * 2.0),
            source_ids=(source_id,),
            note="No company-facts for this borrower — showing demo margin.",
        )
    concepts = _us_gaap_concepts(facts_for_company)
    if not concepts:
        return demo_result(
            label_hint="profitability",
            value=rf"{demo.net_margin():+.1f}%",
            score=max(0.0, 60.0 - demo.net_margin() * 2.0),
            source_ids=(source_id,),
            note="No us-gaap facts found in landed record — showing demo margin.",
        )
    revenues, rev_end = _concept_value(concepts, _REVENUE_TAGS)
    net, net_end = _concept_value(concepts, _NET_INCOME_TAGS)
    if revenues is None and net is None:
        return demo_result(
            label_hint="profitability",
            value=rf"{demo.net_margin():+.1f}%",
            score=max(0.0, 60.0 - demo.net_margin() * 2.0),
            source_ids=(source_id,),
            note="Revenue + net-income tags not found in XBRL — showing demo margin.",
        )
    if revenues is None and net is not None:
        # Pre-revenue / SPAC-style filer: revenue tag absent but net income
        # is reported. Show the raw net income as a real number with a
        # clear note rather than a misleading demo margin.
        score = 50.0 if net >= 0 else 80.0
        return SignalResult(
            value=rf"{net:+,.0f}",
            score=score,
            status=cast_status("good" if net >= 0 else "warning"),
            detail={
                "revenues": None,
                "net_income": net,
                "revenue_period": "",
                "net_income_period": net_end,
                "pre_revenue": True,
            },
            source_ids=(source_id,),
            note="No revenue reported (likely SPAC / pre-revenue) — net income shown.",
        )
    if net is None:
        return demo_result(
            label_hint="profitability",
            value=rf"{demo.net_margin():+.1f}%",
            score=max(0.0, 60.0 - demo.net_margin() * 2.0),
            source_ids=(source_id,),
            note="NetIncome tags not found in XBRL — showing demo margin.",
        )
    if net is None:
        return demo_result(
            label_hint="profitability",
            value=rf"{demo.net_margin():+.1f}%",
            score=max(0.0, 60.0 - demo.net_margin() * 2.0),
            source_ids=(source_id,),
            note="NetIncome tags not found in XBRL — showing demo margin.",
        )
    margin = (net or 0) / (revenues or 1) * 100.0
    score = max(0.0, min(100.0, 50.0 - margin * 2.0))
    status = "good" if margin > 10 else "warning" if margin > 0 else "bad"
    return ok_result(
        value=rf"{margin:+.1f}%",
        score=score,
        status=status,
        detail={
            "revenues": revenues,
            "net_income": net,
            "revenue_period": rev_end,
            "net_income_period": net_end,
            "net_margin_pct": round(margin, 2),
        },
        source_ids=(source_id,),
    )


def _matches_entity(entities: list[Identifiers], company: Identifiers) -> bool:
    if not entities:
        return True
    return any(
        (e.cik and e.cik == company.cik) or (e.name and e.name == company.name) for e in entities
    )


class _Provider:
    indicator_id = "profitability"
    label = "Industry Profitability"

    description = "Net income margin from SEC XBRL companyfacts (NetIncomeLoss / Revenues). Higher means healthier."
    roles: tuple[str, ...] = (ROLE,)

    def compute(self, company: Identifiers, ctx: SignalContext) -> SignalResult:
        return compute(company, ctx)


Provider = _Provider()
register_provider(Provider)
