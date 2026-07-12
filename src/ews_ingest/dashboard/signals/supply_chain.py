"""Supply-chain-stability indicator.

Roles: ``supply_chain.pressure`` (NY Fed GSCPI CSV) +
``supply_chain.new_orders`` + ``supply_chain.supplier_deliveries``
(both ISM sub-indices parsed from the landed macro.ism_pmi page text).

Risk score blends:
* GSCPI z-score > 0 (pressure) -> higher risk;
* ISM New Orders < 50 (contraction) -> higher risk;
* ISM Supplier Deliveries > 50 (slower) -> higher risk.

Degrades gracefully when any source is unavailable (partial demo fallback).
"""

from __future__ import annotations

import csv
import io
import json

from ews_ingest.core.models import Identifiers
from ews_ingest.dashboard.demo import DemoValues
from ews_ingest.dashboard.signals import (
    SignalContext,
    SignalResult,
    demo_result,
    has_rate_limit_record,
    ok_result,
    rate_limited_result,
    register_provider,
)
from ews_ingest.dashboard.signals.ism import parse_ism

__all__ = ["Provider", "compute"]

ROLES: tuple[str, ...] = (
    "supply_chain.pressure",
    "supply_chain.new_orders",
    "supply_chain.supplier_deliveries",
)


def _gscpi_series_from_fred_payload(payload: object) -> list[float]:
    """Extract a numeric series from a FRED-style payload (``observations``)."""
    if not isinstance(payload, dict):
        return []
    obs = payload.get("observations")
    if not isinstance(obs, list):
        return []
    out: list[float] = []
    for row in obs:
        if not isinstance(row, dict):
            continue
        v = row.get("value")
        if isinstance(v, (int, float)):
            out.append(float(v))
        elif isinstance(v, str) and v not in {"", ".", "nan", "NaN"}:
            try:
                out.append(float(v))
            except ValueError:
                continue
    return out


def _gscpi_series(csv_text: str) -> list[float]:
    """Parse a supply-chain pressure series from either CSV (NY Fed GSCPI)
    or FRED-style ``observations`` JSON.
    """
    out: list[float] = []
    # FRED-style: payload has "observations": [{date, value}, ...]
    if not csv_text:
        return out
    try:
        doc = json.loads(csv_text)
    except ValueError, TypeError:
        doc = None
    if isinstance(doc, dict):
        obs = doc.get("observations")
        if isinstance(obs, list):
            for row in obs:
                if not isinstance(row, dict):
                    continue
                v = row.get("value")
                if isinstance(v, (int, float)):
                    out.append(float(v))
                elif isinstance(v, str) and v not in {"", ".", "nan", "NaN"}:
                    try:
                        out.append(float(v))
                    except ValueError:
                        continue
            if out:
                return out
    # CSV fallback: date column + value column (last cell).
    for row in csv.reader(io.StringIO(csv_text)):
        if not row:
            continue
        cell = row[-1].strip()
        try:
            out.append(float(cell))
        except ValueError:
            continue
    return out


def _zscore(series: list[float]) -> float | None:
    if len(series) < 5:
        return None
    mean = sum(series) / len(series)
    var = sum((x - mean) ** 2 for x in series) / (len(series) - 1)
    if var <= 0:
        return 0.0
    sd = var**0.5
    return (series[-1] - mean) / sd


def compute(company: Identifiers, ctx: SignalContext) -> SignalResult:
    seed = company.name or company.ticker or company.cik or "company"
    demo = DemoValues.for_company(seed)
    source_ids = tuple(filter(None, (ctx.source_for(r) for r in ROLES)))
    if not source_ids:
        return demo_result(
            label_hint="supply_chain",
            value=f"GSCPI {demo.gscpi():+.2f}",
            score=50.0 + demo.gscpi() * 20.0,
            source_ids=(),
            note="No supply-chain source bound — no data found.",
        )

    gscpi_sid = ctx.source_for("supply_chain.pressure")
    pmi_sid = ctx.source_for("supply_chain.new_orders")

    missing_env: list[str] = []
    for sid in source_ids:
        missing_env.extend(ctx.missing_env(sid))

    gscpi_z: float | None = None
    if gscpi_sid and has_rate_limit_record(list(ctx.landing.read(gscpi_sid).records)):
        return rate_limited_result(gscpi_sid)
    if gscpi_sid and not ctx.missing_env(gscpi_sid):
        for payload in ctx.landing.iter_payloads(gscpi_sid):
            # Two payload shapes are accepted:
            #   * GSCPI-style:  {"csv": "<csv text>"}
            #   * FRED-style:   {"observations": [{"date": ..., "value": ...}, ...]}
            csv_text = str(payload.get("csv") or "")
            if csv_text:
                gscpi_z = _zscore(_gscpi_series(csv_text))
                if gscpi_z is not None:
                    break
                continue
            # Try FRED observations directly.
            series = _gscpi_series_from_fred_payload(payload)
            if series:
                gscpi_z = _zscore(series)
                if gscpi_z is not None:
                    break

    new_orders: float | None = None
    supp_del: float | None = None
    if pmi_sid and not ctx.missing_env(pmi_sid):
        pmi_recs = ctx.landing.read(pmi_sid).records
        if has_rate_limit_record(pmi_recs):
            return rate_limited_result(pmi_sid)
        store = ctx.landing.read(pmi_sid)
        latest = store.latest()
        if latest is not None:
            page_text = str(latest.payload.get("page_text") or "")
            ism = parse_ism(page_text)
            new_orders = ism["new_orders"]
            supp_del = ism["supplier_deliveries"]

    # Need at least GSCPI to produce a real value; ISM sub-indices are
    # best-effort enhancements on top.
    if gscpi_z is None:
        if missing_env:
            return demo_result(
                label_hint="supply_chain",
                value=f"GSCPI {demo.gscpi():+.2f}",
                score=50.0 + demo.gscpi() * 20.0,
                missing_env=tuple(missing_env),
                source_ids=source_ids,
                note="API key(s) missing and no GSCPI data landed — no data found.",
            )
        return demo_result(
            label_hint="supply_chain",
            value=f"GSCPI {demo.gscpi():+.2f}",
            score=50.0 + demo.gscpi() * 20.0,
            source_ids=source_ids,
            note="No GSCPI data landed — no data found.",
        )

    pieces: list[float] = []
    if gscpi_z is not None:
        pieces.append(max(0.0, min(50.0, (gscpi_z + 1.5) / 3.0 * 50.0)))
    if new_orders is not None:
        pieces.append(max(0.0, min(50.0, (55.0 - new_orders) / 10.0 * 50.0)))
    if supp_del is not None:
        pieces.append(max(0.0, min(50.0, (supp_del - 45.0) / 10.0 * 50.0)))
    score = sum(pieces) / len(pieces) if pieces else 50.0
    score = max(0.0, min(100.0, score))
    status = "good" if score < 35 else "warning" if score < 65 else "bad"

    label_parts: list[str] = []
    if gscpi_z is not None:
        label_parts.append(f"GSCPI z={gscpi_z:+.2f}")
    if new_orders is not None:
        label_parts.append(f"NO={new_orders:.1f}")
    if supp_del is not None:
        label_parts.append(f"SD={supp_del:.1f}")
    return ok_result(
        value=" | ".join(label_parts) or "n/a",
        score=score,
        status=status,
        detail={
            "gscpi_z": gscpi_z,
            "ism_new_orders": new_orders,
            "ism_supplier_deliveries": supp_del,
        },
        source_ids=source_ids,
    )


class _Provider:
    indicator_id = "supply_chain"
    label = "Supply Chain Stability"

    description = "Blends NY Fed GSCPI pressure score with ISM New Orders and Supplier Deliveries sub-indices."
    roles: tuple[str, ...] = ROLES
    weight: float = 0.08

    def compute(self, company: Identifiers, ctx: SignalContext) -> SignalResult:
        return compute(company, ctx)


Provider = _Provider()
register_provider(Provider)
