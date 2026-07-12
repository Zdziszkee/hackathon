"""Industry classification + confidence indicator.

Roles: ``industry.filer_sic`` (per-company SIC from SEC submissions) +
``industry.sic`` (SIC code -> industry title map) + ``industry.naics``
(NAICS code -> title map, corroboration).

The card displays the raw ``sicDescription`` from SEC submissions
("Services-Prepackaged Software", "National Commercial Banks", …) or
the bare SIC code if the description isn't landed. Confidence is the
number of corroborating classifications (filer SIC, NAICS map, any
non-empty extra_ids sector).
"""

from __future__ import annotations

from ews_ingest.core.models import Identifiers
from ews_ingest.dashboard.demo import DemoValues
from ews_ingest.dashboard.signals import (
    SignalContext,
    SignalResult,
    cast_status,
    demo_result,
    has_rate_limit_record,
    ok_result,
    rate_limited_result,
    register_provider,
)

__all__ = ["Provider", "compute"]

ROLES: tuple[str, ...] = ("industry.filer_sic", "industry.sic", "industry.naics")


def _sic_info_from_submissions(
    submissions: list[dict[str, object]],
) -> tuple[list[str], str | None]:
    """Return (numeric SIC codes, sicDescription) from landed submission payloads.

    The SEC submissions connector fetches per-CIK, so any field present
    belongs to this company. The newer API exposes ``sicDescription`` (a
    label) without always exposing the numeric ``sic`` code; we use
    whichever is present.
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
    seed = company.name or company.ticker or company.cik or "company"
    demo = DemoValues.for_company(seed)
    source_ids = tuple(filter(None, (ctx.source_for(r) for r in ROLES)))
    if not source_ids:
        return demo_result(
            label_hint="industry",
            value=demo.industry(),
            score=demo.industry_confidence(),
            source_ids=(),
            note="No industry sources bound — no data found.",
        )

    sic_map_sid = ctx.source_for("industry.sic")
    filer_sid = ctx.source_for("industry.filer_sic")
    naics_sid = ctx.source_for("industry.naics")

    sic_map_rows: list[dict[str, object]] = []
    if sic_map_sid:
        for p in ctx.landing.iter_payloads(sic_map_sid):
            sic_map_rows.append(p)

    filer_payloads: list[dict[str, object]] = []
    if filer_sid:
        filer_records = ctx.landing.read(filer_sid).records
        if has_rate_limit_record(filer_records):
            return rate_limited_result(filer_sid)
        for rec in filer_records:
            if _matches_entity(rec.entities, company):
                filer_payloads.append(rec.payload)

    sic_codes, sic_description = _sic_info_from_submissions(filer_payloads)
    if not sic_codes and not sic_description:
        # No filer data yet — fall back to the seeded sector string or a
        # demo value. The sector is a free-form Yahoo string (not the
        # legacy taxonomy), so we use it as a display label rather than
        # as a routing key.
        seeded_sector = str(company.extra_ids.get("sector", ""))
        if seeded_sector:
            industry_title = seeded_sector
            confidence = 80.0
            status = "good" if confidence >= 70 else "warning"
            return SignalResult(
                value=industry_title,
                score=100.0 - confidence,
                status=cast_status(status),
                detail={
                    "sic": "",
                    "confidence": confidence,
                    "corroborations": 1,
                    "source": "seeded_sector",
                },
                source_ids=source_ids,
                note=("No SEC submissions landed yet — using the sector set at onboarding."),
            )
        return demo_result(
            label_hint="industry",
            value=demo.industry(),
            score=100.0 - demo.industry_confidence(),
            source_ids=source_ids,
            note="No SEC submissions landed and no seeded sector — no data found.",
        )

    primary_sic = sic_codes[0] if sic_codes else ""
    title_from_map = None
    if primary_sic:
        for row in sic_map_rows:
            if str(row.get("sic_code") or row.get("code") or "") == primary_sic:
                title_from_map = str(row.get("industry") or row.get("title") or "")

    industry_title = (
        title_from_map
        or sic_description
        or (f"SIC {primary_sic}" if primary_sic else demo.industry())
    )

    corroborations = 1
    if title_from_map:
        corroborations += 1
    if naics_sid:
        naics_recs = ctx.landing.read(naics_sid).records
        if has_rate_limit_record(naics_recs):
            return rate_limited_result(naics_sid)
        if naics_recs:
            corroborations += 1
    # A non-empty seeded sector counts as a corroboration.
    if company.extra_ids.get("sector"):
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

    description = (
        "Industry classification and confidence in that mapping. Based on "
        "SEC SIC, Census NAICS corroboration, and the sector set at "
        "onboarding."
    )
    roles: tuple[str, ...] = ROLES

    def compute(self, company: Identifiers, ctx: SignalContext) -> SignalResult:
        return compute(company, ctx)


Provider = _Provider()
register_provider(Provider)
