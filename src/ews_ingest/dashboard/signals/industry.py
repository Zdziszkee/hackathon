"""Industry classification + confidence indicator.

Roles: ``industry.filer_sic`` (per-company SIC from SEC submissions) +
``industry.sic`` (SIC code -> industry title map) + ``industry.naics``
(NAICS code -> title map, corroboration).

Confidence: how cleanly the company maps to a single industry — based on the
number of corroborating classifications (filer SIC, NAICS map, seeded sector).
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

ROLES: tuple[str, ...] = ("industry.filer_sic", "industry.sic", "industry.naics")

_SIC_TO_SECTOR: dict[str, str] = {
    "1311": "petrochemical (Oil & Gas Extraction)",
    "1389": "petrochemical (Oil & Gas Field Services)",
    "2820": "petrochemical (Chemicals)",
    "2860": "petrochemical (Industrial Chemicals)",
    "2911": "petrochemical (Petroleum Refining)",
    "3080": "petrochemical (Plastics Products)",
    "4011": "transport_logistics (Railroads)",
    "4210": "transport_logistics (Trucking)",
    "4213": "transport_logistics (Trucking)",
    "4490": "transport_logistics (Marine Cargo)",
    "4512": "airlines (Air Transport)",
    "4522": "airlines (Air Transport)",
    "4731": "transport_logistics (Freight Arrangement)",
    "4700": "transport_logistics (Transport Services)",
}


def _sic_title_from_map(rows: list[dict[str, object]], code: str) -> str | None:
    for r in rows:
        sic = str(r.get("sic_code") or r.get("code") or "")
        if sic == code:
            return str(r.get("industry") or r.get("title") or "")
    return None


def _sic_info_from_submissions(
    submissions: list[dict[str, object]],
) -> tuple[list[str], str | None]:
    """Return (numeric SIC codes, sicDescription) from landed submission payloads.

    The SEC submissions connector fetches per-CIK, so any field present belongs
    to this company. The newer API exposes ``sicDescription`` (a label) without
    always exposing the numeric ``sic`` code; we use whichever is present.
    """
    codes: list[str] = []
    description: str | None = None
    for r in submissions:
        sic = r.get("sic")
        if isinstance(sic, list):
            for s in sic:
                if isinstance(s, (int, str)):
                    codes.append(str(s).zfill(4))
        elif isinstance(sic, (int, str)):
            codes.append(str(sic).zfill(4))
        desc = r.get("sicDescription")
        if isinstance(desc, str) and not description:
            description = desc
    return codes, description


def compute(company: Identifiers, ctx: SignalContext) -> SignalResult:
    source_ids = tuple(filter(None, (ctx.source_for(r) for r in ROLES)))
    if not source_ids:
        return SignalResult(
            value="n/a",
            score=0.0,
            status=cast_status("unavailable"),
            detail={},
            source_ids=(),
            note="No industry sources bound for this region.",
        )
    seed = company.name or company.ticker or company.cik or "company"
    demo = DemoValues.for_company(seed)

    sic_map_sid = ctx.source_for("industry.sic")
    filer_sid = ctx.source_for("industry.filer_sic")
    naics_sid = ctx.source_for("industry.naics")

    sic_map_rows: list[dict[str, object]] = []
    if sic_map_sid:
        for p in ctx.landing.iter_payloads(sic_map_sid):
            sic_map_rows.append(p)

    filer_payloads: list[dict[str, object]] = []
    if filer_sid:
        # records are per-company; only keep ones for this company
        for rec in ctx.landing.read(filer_sid).records:
            if _matches_entity(rec.entities, company):
                filer_payloads.append(rec.payload)

    sic_codes, sic_description = _sic_info_from_submissions(filer_payloads)
    if not sic_codes and not sic_description:
        # No filer data — but maybe a seeded sector mapping exists.
        sector = str(company.extra_ids.get("sector", ""))
        industry_title = sector.replace("_", " ").title() if sector else demo.industry()
        confidence = demo.industry_confidence() if not sector else 80.0
        note = (
            "No SEC submissions landed — using seeded sector from entities.yaml."
            if sector
            else "No SEC submissions landed — showing demo industry."
        )
        return demo_result(
            label_hint="industry",
            value=industry_title,
            score=100.0 - confidence,
            source_ids=source_ids,
            note=note,
        )

    primary_sic = sic_codes[0] if sic_codes else ""
    title_from_map = None
    if primary_sic:
        for row in sic_map_rows:
            if str(row.get("sic_code") or row.get("code") or "") == primary_sic:
                title_from_map = str(row.get("industry") or row.get("title") or "")

    industry_title = (
        title_from_map
        or (_SIC_TO_SECTOR.get(primary_sic) if primary_sic else None)
        or sic_description
        or (f"SIC {primary_sic}" if primary_sic else demo.industry())
    )

    corroborations = 1
    if title_from_map:
        corroborations += 1
    if str(company.extra_ids.get("sector", "")) and (
        industry_title.lower().startswith(str(company.extra_ids["sector"]).split("_")[0])
        or industry_title == _SIC_TO_SECTOR.get(primary_sic)
    ):
        corroborations += 1
    if naics_sid and ctx.landing.read(naics_sid).records:
        corroborations += 1

    confidence = min(100.0, 40.0 + corroborations * 20.0)
    return ok_result(
        value=industry_title,
        score=100.0 - confidence,
        status="good" if confidence >= 70 else "warning" if confidence >= 40 else "bad",
        detail={"sic": primary_sic, "confidence": confidence, "corroborations": corroborations},
        source_ids=source_ids,
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
    indicator_id = "industry"
    label = "Industry & Confidence"

    description = "Industry classification and confidence in that mapping. Based on SEC SIC and Census NAICS corroboration."
    roles: tuple[str, ...] = ROLES

    def compute(self, company: Identifiers, ctx: SignalContext) -> SignalResult:
        return compute(company, ctx)


Provider = _Provider()
register_provider(Provider)
