"""Country + country-confidence indicator (role: ``identity.country``).

Heuristic confidence: how cleanly a company maps to a single country (a
multi-country conglomerate gets a lower score). For the seeded US-only universe
this is always the US with high confidence; once Wikidata landing records
arrive, the indicator reads them for richer per-subsidiary country counts.
"""

from __future__ import annotations

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

ROLE = "identity.country"

_TITLE = {
    "united states": "United States",
    "usa": "United States",
    "us": "United States",
    "germany": "Germany",
    "france": "France",
    "china": "China",
    "japan": "Japan",
    "netherlands": "Netherlands",
    "united kingdom": "United Kingdom",
}


def _country_from_record(payload: dict[str, object]) -> str | None:
    lower = repr(payload).lower()
    for marker, title in _TITLE.items():
        if marker in lower:
            return title
    return None


def compute(company: Identifiers, ctx: SignalContext) -> SignalResult:
    source_id = ctx.source_for(ROLE)
    if source_id is None:
        return SignalResult(
            value="n/a",
            score=0.0,
            status=cast_status("unavailable"),
            detail={},
            source_ids=(),
            note="No identity source bound.",
        )
    seed = company.name or company.ticker or company.cik or "company"
    demo = DemoValues.for_company(seed)

    # A country seeded on the entity (via entities.yaml extra_ids.country) is a
    # real, authoritative assignment — use it directly with high confidence.
    seeded = company.extra_ids.get("country")
    if isinstance(seeded, str) and seeded.strip():
        primary = _TITLE.get(seeded.lower(), seeded)
        countries: set[str] = {primary}
        # corroborate with any landed records
        for rec in ctx.landing.read(source_id).records:
            if _matches_entity(rec.entities, company):
                c = _country_from_record(rec.payload)
                if c:
                    countries.add(c)
        confidence = max(0.0, min(100.0, 100.0 - (len(countries) - 1) * 25.0))
        return ok_result(
            value=primary,
            score=100.0 - confidence,
            status="good" if confidence >= 70 else "warning",
            detail={
                "country_confidence": confidence,
                "distinct_countries": sorted(countries),
                "source": "seeded",
            },
            source_ids=(source_id,),
        )

    records = ctx.landing.read(source_id).records
    if not records:
        return demo_result(
            label_hint="country",
            value=demo.country(),
            score=100.0 - demo.country_confidence(),
            source_ids=(source_id,),
            note="No country seeded or Wikidata records landed — showing demo.",
        )
    countries = set()
    for rec in records:
        if not _matches_entity(rec.entities, company):
            continue
        c = _country_from_record(rec.payload)
        if c:
            countries.add(c)
    if not countries:
        return demo_result(
            label_hint="country",
            value=demo.country(),
            score=100.0 - demo.country_confidence(),
            source_ids=(source_id,),
            note="No country signal found in landed records — showing demo.",
        )
    primary = next(iter(countries))
    confidence = max(0.0, min(100.0, round(100.0 - (len(countries) - 1) * 25.0, 1)))
    return ok_result(
        value=primary,
        score=100.0 - confidence,
        status="good" if confidence >= 70 else "warning" if confidence >= 40 else "bad",
        detail={"country_confidence": confidence, "distinct_countries": sorted(countries)},
        source_ids=(source_id,),
    )


def _matches_entity(entities: list[Identifiers], company: Identifiers) -> bool:
    if not entities:
        return True
    return any(
        (e.cik and e.cik == company.cik)
        or (e.ticker and e.ticker == company.ticker)
        or (e.name and e.name == company.name)
        for e in entities
    )


class _Provider:
    indicator_id = "country"
    label = "Country & Confidence"

    description = "Country of primary operations and confidence in that assignment. Multi-country exposure lowers confidence."
    roles: tuple[str, ...] = (ROLE,)

    def compute(self, company: Identifiers, ctx: SignalContext) -> SignalResult:
        return compute(company, ctx)


Provider = _Provider()
register_provider(Provider)
