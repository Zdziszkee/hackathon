"""Country macro-health indicator (role: ``macro.mfg_pmi``).

Originally: headline ISM Manufacturing PMI parsed from the landed page text.
ISM is now paywalled and the page returns HTML; the role is bound to
``macro.fred_macro`` as a proxy. We pick the FRED ``INDPRO`` (Industrial
Production Index) series and show a PMI-like score: the recent z-score of
the 5-year monthly series, mapped onto a 0..100 scale where 50 = neutral
(``good`` >=52, ``warning`` 50..52, ``bad`` <50).

Note: this is *not* the literal ISM Manufacturing PMI; it's a manufacturing
health proxy. The role is repurposed (rename in YAML if a dedicated
``macro.ism`` source ever lands).
"""

from __future__ import annotations

from collections.abc import Iterable

from ews_ingest.core.models import Identifiers
from ews_ingest.dashboard.demo import DemoValues
from ews_ingest.dashboard.signals import (
    SignalContext,
    SignalResult,
    cast_status,
    demo_result,
    register_provider,
)

__all__ = ["Provider", "compute"]

ROLE = "macro.mfg_pmi"

_INDPRO_SERIES_ID = "INDPRO"
_PMI_LIKE_NEUTRAL = 50.0
_PMI_LIKE_SCALE = 5.0  # 1 z-score -> 5 PMI-like points


def _read_indpro_points(records: Iterable[object]) -> list[float]:
    """Pull INDPRO values (chronological) from a list of FRED RawRecord."""
    out: list[tuple[str, float]] = []
    for rec in records:
        extra = getattr(rec, "extra", None)
        if not isinstance(extra, dict):
            continue
        if extra.get("series_id") != _INDPRO_SERIES_ID:
            continue
        payload = getattr(rec, "payload", None)
        if not isinstance(payload, dict):
            continue
        for row in payload.get("observations", []) or []:
            if not isinstance(row, dict):
                continue
            v = row.get("value")
            date = row.get("date") or ""
            if isinstance(v, (int, float)):
                out.append((str(date), float(v)))
            elif isinstance(v, str) and v not in {"", ".", "nan", "NaN"}:
                try:
                    out.append((str(date), float(v)))
                except ValueError:
                    continue
    out.sort(key=lambda x: x[0])
    return [v for _, v in out]


def _zscore(series: list[float]) -> float | None:
    if len(series) < 5:
        return None
    mean = sum(series) / len(series)
    var = sum((x - mean) ** 2 for x in series) / (len(series) - 1)
    if var <= 0:
        return 0.0
    return (series[-1] - mean) / var**0.5


def compute(company: Identifiers, ctx: SignalContext) -> SignalResult:
    seed = company.name or company.ticker or company.cik or "company"
    demo = DemoValues.for_company(seed)
    source_id = ctx.source_for(ROLE)
    if source_id is None:
        return SignalResult(
            value="n/a",
            score=0.0,
            status=cast_status("unavailable"),
            detail={},
            source_ids=(),
            note="No PMI source bound for this portfolio.",
        )
    if missing := ctx.missing_env(source_id):
        return demo_result(
            label_hint="macro_health",
            value=f"{demo.pmi():.1f}",
            score=abs(_PMI_LIKE_NEUTRAL - demo.pmi()) * _PMI_LIKE_SCALE,
            missing_env=tuple(missing),
            source_ids=(source_id,),
            note="API key not configured — showing demo PMI.",
        )
    records = ctx.landing.read(source_id).records
    points = _read_indpro_points(records)
    z = _zscore(points)
    if z is None:
        return demo_result(
            label_hint="macro_health",
            value=f"{demo.pmi():.1f}",
            score=abs(_PMI_LIKE_NEUTRAL - demo.pmi()) * _PMI_LIKE_SCALE,
            source_ids=(source_id,),
            note="Not enough FRED INDPRO points landed — showing demo PMI.",
        )
    pmi_like = _PMI_LIKE_NEUTRAL + z * _PMI_LIKE_SCALE
    pmi_like = max(0.0, min(100.0, pmi_like))
    score = abs(_PMI_LIKE_NEUTRAL - pmi_like) * 2.0
    status = "good" if pmi_like >= 52 else "warning" if pmi_like >= 50 else "bad"
    return SignalResult(
        value=f"{pmi_like:.1f}",
        score=min(100.0, max(0.0, score)),
        status=status,
        detail={"pmi_like": round(pmi_like, 2), "z_score": round(z, 3), "points": len(points)},
        source_ids=(source_id,),
        note="FRED INDPRO z-score mapped to PMI-like scale (ISM is paywalled).",
    )


class _Provider:
    indicator_id = "macro_health"
    label = "Country Macro Health (PMI)"

    description = (
        "Manufacturing-health proxy: FRED INDPRO z-score mapped to a PMI-like "
        "scale (50 = neutral). Above 50 means expansion, below 50 means contraction."
    )
    roles: tuple[str, ...] = (ROLE,)

    def compute(self, company: Identifiers, ctx: SignalContext) -> SignalResult:
        return compute(company, ctx)


Provider = _Provider()
register_provider(Provider)
