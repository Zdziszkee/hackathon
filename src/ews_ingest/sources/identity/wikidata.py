"""Wikidata SPARQL (spec §12): supplementary ownership/exec graph (no key)."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["Wikidata", "parse"]

SPARQL = "https://query.wikidata.org/sparql"

OWNERSHIP_QUERY = """
SELECT ?company ?companyLabel ?parent ?parentLabel WHERE {{
  ?company rdfs:label "{}"@en .
  ?company wdt:P749 ?parent .
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
""".strip()


def _query(text: str) -> str:
    return OWNERSHIP_QUERY.format(text.replace('"', ""))


def parse(raw: list[object]) -> list[RecordInput]:
    """Split a SPARQL JSON result list into one record per binding row."""
    return [RecordInput(payload={"row": r}, raw_format=RawFormat.JSON) for r in raw]


@register_source("identity.wikidata")
class Wikidata:
    """Per-entity ownership/exec graph via Wikidata SPARQL."""

    source_id = "identity.wikidata"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for entity in ctx.resolver.all():
            if not entity.name:
                continue
            params: dict[str, str | int] = {"query": _query(entity.name), "format": "json"}
            data = ctx.http.get_json_list(
                SPARQL,
                policy=ctx.rate_policy,
                params=params,
                headers={"Accept": "application/sparql-results+json"},
            )
            for spec in parse(data):
                spec.entities = [entity]
                spec.url = SPARQL
                yield build_record(ctx, self.source_id, self.source_type, spec)
