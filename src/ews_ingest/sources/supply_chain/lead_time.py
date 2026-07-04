"""Lead time proxy (spec extension): NY Fed Global Supply Chain Pressure Index (GSCPI).

Free, no key. GSCPI is a monthly index of global supply chain pressure; rising
values = longer lead times / disruption. CSV from newyorkfed.org. Endpoint is
best-effort (URL may change); flagged for verification.
"""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["LeadTime", "parse"]

URL = "https://www.newyorkfed.org/medialibrary/media/research/policy/gscpi/gscpi_data.csv"


def parse(text: str) -> list[RecordInput]:
    """Wrap the GSCPI CSV body as one record (parse rows in feature-engineering)."""
    return [RecordInput(payload={"csv": text}, raw_format=RawFormat.CSV)]


@register_source("supply_chain.lead_time")
class LeadTime:
    """Pull the NY Fed GSCPI CSV as a lead-time / supply-chain-pressure proxy."""

    source_id = "supply_chain.lead_time"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        text = ctx.http.get_text(URL, policy=ctx.rate_policy)
        for spec in parse(text):
            spec.url = URL
            spec.extra = {"index": "GSCPI", "label": "global_supply_chain_pressure_index"}
            yield build_record(ctx, self.source_id, self.source_type, spec)
