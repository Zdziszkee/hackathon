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

from ews_ingest.core.models import Identifiers
from ews_ingest.dashboard.demo import DemoValues
from ews_ingest.dashboard.signals import (
    SignalContext,
    SignalResult,
    demo_result,
    ok_result,
    register_provider,
)
from ews_ingest.dashboard.signals.ism import parse_ism

__all__ = ["Provider", "compute"]

ROLES: tuple[str, ...] = (
    "supply_chain.pressure",
    "supply_chain.new_orders",
    "supply_chain.supplier_deliveries",
)


def _gscpi_series(csv_text: str) -> list[float]:
    """Parse the NY Fed GSCPI CSV: date column + a value column (last)."""
    out: list[float] = []
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
            note="No supply-chain source bound — showing demo.",
        )

    gscpi_sid = ctx.source_for("supply_chain.pressure")
    pmi_sid = ctx.source_for("supply_chain.new_orders")

    missing_env: list[str] = []
    for sid in source_ids:
        missing_env.extend(ctx.missing_env(sid))

    gscpi_z: float | None = None
    if gscpi_sid and not ctx.missing_env(gscpi_sid):
        for payload in ctx.landing.iter_payloads(gscpi_sid):
            csv_text = str(payload.get("csv") or "")
            if csv_text:
                gscpi_z = _zscore(_gscpi_series(csv_text))
                break

    new_orders: float | None = None
    supp_del: float | None = None
    if pmi_sid and not ctx.missing_env(pmi_sid):
        store = ctx.landing.read(pmi_sid)
        latest = store.latest()
        if latest is not None:
            page_text = str(latest.payload.get("page_text") or "")
            ism = parse_ism(page_text)
            new_orders = ism["new_orders"]
            supp_del = ism["supplier_deliveries"]

    partial_missing = (gscpi_z is None) or (new_orders is None and supp_del is None)
    if missing_env and partial_missing:
        return demo_result(
            label_hint="supply_chain",
            value=f"GSCPI {demo.gscpi():+.2f}",
            score=50.0 + demo.gscpi() * 20.0,
            missing_env=tuple(missing_env),
            source_ids=source_ids,
            note="API key(s) missing and not enough landed data — showing demo.",
        )
    if partial_missing:
        return demo_result(
            label_hint="supply_chain",
            value=f"GSCPI {demo.gscpi():+.2f}",
            score=50.0 + demo.gscpi() * 20.0,
            source_ids=source_ids,
            note="GSCPI or ISM sub-indices not found in landed data — showing demo.",
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

    def compute(self, company: Identifiers, ctx: SignalContext) -> SignalResult:
        return compute(company, ctx)


Provider = _Provider()
register_provider(Provider)
