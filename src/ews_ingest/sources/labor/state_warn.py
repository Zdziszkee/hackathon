"""State WARN Act mass-layoff notices (spec §9): per-state DOL sites (Scrape).

No unified API; formats vary by state. A generic ``StateWarnBase`` extracts
table rows; high-value industrial states (TX, LA, CA, NY, IL, PA, OH) are
registered individually. Add a new state by subclassing with a ``WARN_URL``.
"""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = [
    "StateWarnBase",
    "StateWarnCa",
    "StateWarnIl",
    "StateWarnLa",
    "StateWarnNy",
    "StateWarnOh",
    "StateWarnPa",
    "StateWarnTx",
    "parse",
]

ROW_SELECTOR = "table tr"


def _cell_text(node: object) -> str:
    text = getattr(node, "text", "")
    return str(text).strip() if text else ""


def parse(adaptor: object, *, columns: list[str]) -> list[RecordInput]:
    """Extract WARN table rows; map cells to ``columns`` names."""
    css = getattr(adaptor, "css", None)
    if css is None:
        return []
    out: list[RecordInput] = []
    for row in css(ROW_SELECTOR):
        cells = row.css("td") if hasattr(row, "css") else []
        texts = [_cell_text(c) for c in cells]
        if not texts or all(t == "" for t in texts):
            continue
        record: dict[str, object] = {}
        pad = columns + [""] * (len(texts) - len(columns))
        for name, value in zip(pad, texts, strict=False):
            if name:
                record[name] = value
        out.append(RecordInput(payload={"warn_row": record}, raw_format=RawFormat.HTML))
    return out


_COLUMNS = ["company", "location", "num_employees", "notice_date", "effective_date"]


class StateWarnBase:
    """Base WARN-layoff scraper; subclasses set ``WARN_URL`` and ``source_id``."""

    source_id = "labor.state_warn_base"
    source_type = SourceType.SCRAPE
    WARN_URL: str = ""

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        if not self.WARN_URL:
            return
        adaptor = ctx.scraper.fetch_html(self.WARN_URL, policy=ctx.rate_policy)
        for spec in parse(adaptor, columns=_COLUMNS):
            spec.url = self.WARN_URL
            yield build_record(ctx, self.source_id, self.source_type, spec)


def _register_state(state: str, url: str) -> type[StateWarnBase]:
    cls = type(
        "StateWarn" + state.upper(),
        (StateWarnBase,),
        {
            "source_id": f"labor.state_warn_{state}",
            "source_type": SourceType.SCRAPE,
            "WARN_URL": url,
        },
    )
    return register_source(
        cls.source_id,
        scope=Scope.SECTOR_AGGREGATE,
    )(cls)


_States = {
    "tx": "https://www.twc.state.tx.us/files/seasonal/warn-act-notices.html",
    "la": "https://www.laworks.net/Downloads/WARN/WARN.html",
    "ca": "https://edd.ca.gov/en/Jobs_and_Training/Layoff_Services_Warn",
    "ny": "https://dol.ny.gov/warn-notices",
    "il": "https://www2.illinois.gov/ides/claims/Pages/WARN.aspx",
    "pa": "https://www.dli.pa.gov/Individuals/workforce-development/warn-notices",
    "oh": "https://jfs.ohio.gov/warn/",
}

StateWarnTx = _register_state("tx", _States["tx"])
StateWarnLa = _register_state("la", _States["la"])
StateWarnCa = _register_state("ca", _States["ca"])
StateWarnNy = _register_state("ny", _States["ny"])
StateWarnIl = _register_state("il", _States["il"])
StateWarnPa = _register_state("pa", _States["pa"])
StateWarnOh = _register_state("oh", _States["oh"])
