"""Tests for the dashboard signal layer (read-side parsing + demo fallback).

Builds a tmp landing zone, writes sample landed JSONL per source_id, and asserts
each indicator computes from real data; asserts demo fallback when the landing
zone is empty; asserts the ISM page-text parser and GSCPI CSV parser.
"""

from __future__ import annotations

import json
import math
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import cast, override

from ews_ingest.core.hashing import content_hash
from ews_ingest.core.models import Identifiers, RawFormat, RawRecord, SourceType
from ews_ingest.dashboard.bindings import IndicatorBindings, load_bindings
from ews_ingest.dashboard.companies import Company, load_companies
from ews_ingest.dashboard.env import EnvResolver
from ews_ingest.dashboard.landing import LandingReader
from ews_ingest.dashboard.signals import SignalContext, list_providers
from ews_ingest.dashboard.signals.country import compute as country_compute
from ews_ingest.dashboard.signals.industry import compute as industry_compute
from ews_ingest.dashboard.signals.ism import parse_ism
from ews_ingest.dashboard.signals.macro_health import compute as macro_compute
from ews_ingest.dashboard.signals.news_sentiment import compute as news_compute
from ews_ingest.dashboard.signals.profitability import compute as profitability_compute
from ews_ingest.dashboard.signals.protocol import SignalProvider, SignalResult
from ews_ingest.dashboard.signals.regulation import compute as regulation_compute
from ews_ingest.dashboard.signals.supply_chain import _gscpi_series, _zscore
from ews_ingest.dashboard.signals.volatility import _closes, _realized_vol

CONFIG = Path(__file__).resolve().parents[2] / "src" / "ews_ingest" / "config"

UPS = Identifiers(
    name="United Parcel Service",
    ticker="UPS",
    cik="0001090727",
    extra_ids={"sector": "transport_logistics"},
)


def _rec(
    source_id: str,
    payload: dict[str, object],
    *,
    entities: list[Identifiers] | None = None,
) -> RawRecord:
    return RawRecord(
        source=source_id,
        source_type=SourceType.API,
        fetched_at=datetime.now(UTC),
        fetch_run_id=uuid.uuid4().hex[:8],
        payload=payload,
        raw_format=RawFormat.JSON,
        content_hash=content_hash(payload),
        entities=entities or [],
    )


def _write_landing(base: Path, source_id: str, records: list[RawRecord]) -> None:
    part = base / source_id / f"dt={datetime.now(UTC).date().isoformat()}"
    part.mkdir(parents=True, exist_ok=True)
    target = part / "test.jsonl"
    with target.open("a", encoding="utf-8") as fh:
        for r in records:
            fh.write(r.model_dump_json() + "\n")


def _ctx(tmp_path: Path) -> tuple[SignalContext, Path]:
    landing_dir = tmp_path / "landing"
    landing_dir.mkdir(parents=True, exist_ok=True)
    bindings = load_bindings(CONFIG / "indicators.yaml")
    resolver = EnvResolver.from_required_map({})
    ctx = SignalContext(
        bindings=bindings,
        landing=LandingReader(landing_dir),
        env_present=resolver.is_present,
        missing_env=resolver.missing_for,
    )
    return ctx, landing_dir


def test_list_providers_discovers_all_indicators() -> None:
    ids = {p.indicator_id for p in list_providers()}
    missing = {
        "country",
        "industry",
        "volatility",
        "geopolitical",
        "general_demand",
        "regulation",
        "supply_chain",
        "profitability",
        "macro_health",
        "news_sentiment",
    } - ids
    assert not missing


def test_load_companies_is_empty_without_json(tmp_path: Path) -> None:
    # no json, no yaml (hardcoded removed)
    path = tmp_path / "companies.json"
    companies = load_companies(path)
    assert companies == []


def test_load_companies_reads_from_json(tmp_path: Path) -> None:
    path = tmp_path / "companies.json"
    data = [
        {
            "ticker": "UPS",
            "name": "United Parcel Service",
            "cik": "0001090727",
            "extra_ids": {"sector": "transport_logistics"},
        }
    ]
    path.write_text(json.dumps(data))
    companies = load_companies(path)
    assert len(companies) == 1
    assert companies[0].identifiers.ticker == "UPS"
    assert companies[0].sector == "transport_logistics"


def test_bindings_resolve_roles() -> None:
    b = load_bindings(CONFIG / "indicators.yaml")
    # macro.ism_pmi is Cloudflare/SSO-walled & not mirrored to FRED. The
    # role is bound to macro.fred_macro (INDPRO z-score as a PMI proxy)
    # so the signal can produce real numbers.
    assert b.source_for("macro.mfg_pmi") == "macro.fred_macro"
    assert b.source_for("macro.mfg_pmi") != "macro.ism_pmi"
    assert b.source_for("credit.ohlcv") == "credit_market.yahoo"
    assert b.source_for("demand.truck") == "macro.fred_macro"
    assert b.source_for("news.distress") == "news.hackernews"
    assert b.source_for("supply_chain.pressure") == "transport.cass_freight"


def test_ism_parser_extracts_subindices() -> None:
    page = (
        "ISM Report on Business. The PMI registered 49.2 percent. "
        "New Orders registered 52.1 percent. "
        "Supplier Deliveries registered 50.6 percent."
    )
    ism = parse_ism(page)
    assert ism["headline"] == 49.2
    assert ism["new_orders"] == 52.1
    assert ism["supplier_deliveries"] == 50.6


def test_ism_parser_returns_none_on_drift() -> None:
    ism = parse_ism("page with no figures at all")
    assert ism["headline"] is None
    assert ism["new_orders"] is None


def test_gscpi_series_and_zscore() -> None:
    rows = [
        "2020-01,-1.0",
        "2020-02,-0.5",
        "2020-03,0.0",
        "2020-04,0.2",
        "2020-05,0.5",
        "2020-06,1.0",
    ]
    csv = "date,gscpi\n" + "\n".join(rows) + "\n"
    series = _gscpi_series(csv)
    assert len(series) == 6
    assert series[-1] == 1.0
    assert _zscore(series) is not None
    assert _zscore([1.0]) is None


def _ctx_with_bindings(tmp_path: Path, roles: dict[str, str | None]) -> tuple[SignalContext, Path]:
    """Test helper: bindings are config, so build a ctx with explicit role->source
    bindings so a unit test of the *signal logic* does not break when production
    config unbinds a role for honesty (e.g. ``macro.mfg_pmi: ~``)."""
    landing_dir = tmp_path / "landing"
    landing_dir.mkdir(parents=True, exist_ok=True)
    ctx = SignalContext(
        bindings=IndicatorBindings(roles),
        landing=LandingReader(landing_dir),
        env_present=lambda _sid: True,
        missing_env=lambda _sid: [],
    )
    return ctx, landing_dir


def test_macro_health_uses_landed_pmi(tmp_path: Path) -> None:
    # Production config binds macro.mfg_pmi -> macro.fred_macro (ISM is
    # paywalled). The signal maps FRED INDPRO z-scores onto a PMI-like
    # scale. Here we land a short INDPRO series with the last point
    # well above the mean -> pmi_like > 52 -> status good.
    ctx, landing = _ctx_with_bindings(tmp_path, {"macro.mfg_pmi": "macro.fred_macro"})
    obs = [
        {"date": "2021-01-01", "value": "100.0"},
        {"date": "2022-01-01", "value": "100.0"},
        {"date": "2023-01-01", "value": "100.0"},
        {"date": "2024-01-01", "value": "100.0"},
        {"date": "2025-01-01", "value": "100.0"},
        {"date": "2026-01-01", "value": "105.0"},
    ]
    rec = RawRecord(
        source="macro.fred_macro",
        source_type=SourceType.API,
        fetched_at=datetime.now(UTC),
        fetch_run_id=uuid.uuid4().hex[:8],
        payload={"observations": obs},
        raw_format=RawFormat.JSON,
        content_hash=content_hash({"observations": obs}),
        entities=[UPS],
        extra={"series_id": "INDPRO", "label": "industrial_production"},
    )
    _write_landing(landing, "macro.fred_macro", [rec])
    result = macro_compute(UPS, ctx)
    assert result.status == "good"  # last point is 5 z above mean -> pmi_like ~ 55
    assert float(str(result.value)) > 52.0


def test_macro_health_demo_when_empty(tmp_path: Path) -> None:
    ctx, _ = _ctx_with_bindings(tmp_path, {"macro.mfg_pmi": "macro.ism_pmi"})
    result = macro_compute(UPS, ctx)
    assert result.status == "demo"
    assert isinstance(result.note, str)
    assert "no data" in result.note.lower()


def test_macro_health_unavailable_when_unbound(tmp_path: Path) -> None:
    # Production config: macro.mfg_pmi -> ~. The indicator reports
    # ``unavailable`` (no binding), not ``demo``.
    ctx, _ = _ctx_with_bindings(tmp_path, {"macro.mfg_pmi": None})
    result = macro_compute(UPS, ctx)
    assert result.status == "unavailable"


def test_news_sentiment_aggregates_tone(tmp_path: Path) -> None:
    ctx, landing = _ctx(tmp_path)
    ident = Identifiers(name="United Parcel Service", ticker="UPS")
    # Use Hacker News payload shape (title at top level) — the role
    # ``news.distress`` is now bound to ``news.hackernews``. VADER is
    # deterministic on these short titles.
    _write_landing(
        landing,
        "news.hackernews",
        [
            _rec(
                "news.hackernews",
                {"title": "UPS layoffs hit thousands of workers"},
                entities=[ident],
            ),
            _rec(
                "news.hackernews", {"title": "UPS fined for antitrust violations"}, entities=[ident]
            ),
            _rec(
                "news.hackernews", {"title": "UPS union strike ends in agreement"}, entities=[ident]
            ),
        ],
    )
    result = news_compute(UPS, ctx)
    assert result.status in {"warning", "bad"}  # net negative tone
    assert result.detail["stories"] == 3


def test_regulation_counts_regulation_themed_titles(tmp_path: Path) -> None:
    ctx, landing = _ctx(tmp_path)
    ident = Identifiers(name="United Parcel Service", ticker="UPS")
    _write_landing(
        landing,
        "news.hackernews",
        [
            _rec(
                "news.hackernews",
                {"title": "EPA fines carrier over emissions"},
                entities=[ident],
            ),
            _rec(
                "news.hackernews",
                {"title": "Weather delays shipments"},
                entities=[ident],
            ),
            _rec(
                "news.hackernews",
                {"title": "New regulation targets logistics tariffs"},
                entities=[ident],
            ),
        ],
    )
    result = regulation_compute(UPS, ctx)
    assert result.value == "2 articles"
    assert result.detail["regulation_articles"] == 2


def test_all_providers_demo_fallback_when_empty(tmp_path: Path) -> None:
    ctx, _ = _ctx(tmp_path)
    for provider in list_providers():
        result = provider.compute(UPS, ctx)
        # ``industry`` no longer falls back to ``demo`` when a sector is seeded
        # at onboarding time — that sector is real, authoritative source data,
        # so it returns ``good``/``warning`` with honest medium confidence.
        if provider.indicator_id == "industry":
            expected = {"demo", "unavailable", "good", "warning"}
        else:
            expected = {"demo", "unavailable"}
        assert result.status in expected, (
            f"{provider.indicator_id}: {result.status} notes={result.note}"
        )


def test_volatility_computes_from_yahoo_ohlcv() -> None:
    closes = [100.0 * math.exp(0.01 * i + 0.005 * ((-1) ** i)) for i in range(80)]
    payload: dict[str, object] = {
        "chart": {"result": [{"indicators": {"quote": [{"close": closes}]}}]}
    }
    assert _realized_vol(_closes(payload), 60) is not None


def test_env_resolver_marks_missing_keys() -> None:
    resolver = EnvResolver.from_required_map({"credit_market.fred_credit": ("FRED_API_KEY",)})
    assert not resolver.is_present("credit_market.fred_credit")
    assert resolver.missing_for("credit_market.fred_credit") == ["FRED_API_KEY"]
    assert resolver.is_present("macro.ism_pmi")  # no env required


def test_profitability_descends_into_facts_us_gaap(tmp_path: Path) -> None:
    company = Identifiers(
        name="Acme", ticker="ACME", cik="0000000001", extra_ids={"sector": "petrochemical"}
    )
    ctx, landing = _ctx(tmp_path)
    payload: dict[str, object] = {
        "cik": "1",
        "entityName": "Acme",
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [{"end": "2023-12-31", "val": 1_000_000}]}},
                "NetIncomeLoss": {"units": {"USD": [{"end": "2023-12-31", "val": 120_000}]}},
            },
        },
    }
    _write_landing(
        landing,
        "company_financials.company_facts",
        [
            _rec(
                "company_financials.company_facts",
                payload,
                entities=[Identifiers(cik="0000000001", ticker="ACME")],
            )
        ],
    )
    result = profitability_compute(company, ctx)
    assert result.status == "good"  # 12% margin -> >10
    assert result.value == "+12.0%"
    assert result.detail["revenues"] == 1_000_000
    assert result.detail["net_income"] == 120_000


def test_country_uses_seeded_extra_ids(tmp_path: Path) -> None:
    company = Identifiers(
        name="United Parcel Service",
        ticker="UPS",
        cik="0001090727",
        extra_ids={"sector": "transport_logistics", "country": "US"},
    )
    ctx, _ = _ctx(tmp_path)
    result = country_compute(company, ctx)
    assert result.status == "good"
    assert result.value == "United States"
    assert result.detail["source"] == "seeded"
    ctx, landing = _ctx(tmp_path)
    _write_landing(
        landing,
        "company_financials.submissions",
        [
            _rec(
                "company_financials.submissions",
                {"sicDescription": "Courier Services, Except by Air"},
                entities=[Identifiers(cik="0001090727", ticker="UPS")],
            ),
        ],
    )
    result = industry_compute(UPS, ctx)
    assert "Courier" in str(result.value)


def test_unbound_role_returns_unavailable(tmp_path: Path) -> None:
    # Empty bindings: every role is unbound -> providers report unavailable.
    landing_dir = tmp_path / "landing"
    landing_dir.mkdir(parents=True, exist_ok=True)
    ctx = SignalContext(
        bindings=IndicatorBindings({}),
        landing=LandingReader(landing_dir),
        env_present=lambda _sid: True,
        missing_env=lambda _sid: [],
    )
    result = macro_compute(UPS, ctx)
    assert result.status == "unavailable"


# ---------------------------------------------------------------------------
# Portfolio stats aggregation tests
# ---------------------------------------------------------------------------

from ews_ingest.dashboard.app import _portfolio_stats  # noqa: E402


def _fake_company(name: str, sector: str, country: str = "US") -> Company:
    return Company(
        Identifiers(
            name=name, ticker=name[:4].upper(), extra_ids={"sector": sector, "country": country}
        )
    )


def test_portfolio_stats_sector_hhi() -> None:
    computed = [
        (_fake_company("A", "petrochemical", "US"), [], 70.0, 0),
        (_fake_company("B", "petrochemical", "US"), [], 65.0, 0),
        (_fake_company("C", "airlines", "US"), [], 40.0, 0),
        (_fake_company("D", "airlines", "US"), [], 30.0, 0),
    ]
    stats = _portfolio_stats(computed)
    assert stats.n_companies == 4
    assert stats.mean_risk == 51.25
    # 2 sectors at 50% each -> HHI = 5000 + 5000 = ... wait: share * 100 squared
    # 50% -> 50^2 = 2500, two of them -> 5000
    assert stats.hhi == 5000.0
    assert stats.hhi_label == "high"
    assert len(stats.sectors) == 2
    petro = next(s for s in stats.sectors if s.sector == "petrochemical")
    assert petro.count == 2
    assert petro.share_pct == 50.0
    assert petro.mean_risk == 67.5


def test_portfolio_stats_country_concentration() -> None:
    computed = [
        (_fake_company("A", "petrochemical", "US"), [], 50.0, 0),
        (_fake_company("B", "airlines", "US"), [], 40.0, 0),
        (_fake_company("C", "airlines", "EU"), [], 30.0, 0),
    ]
    stats = _portfolio_stats(computed)
    assert stats.n_distinct_countries == 2
    assert stats.country_concentration_pct > 60.0
    assert "US" in stats.countries
    assert stats.countries["US"] == 2


def test_portfolio_stats_top_risk() -> None:
    computed = [
        (_fake_company("Low", "petrochemical"), [], 10.0, 0),
        (_fake_company("High", "airlines"), [], 90.0, 0),
        (_fake_company("Mid", "airlines"), [], 50.0, 0),
        (_fake_company("High2", "petrochemical"), [], 85.0, 0),
    ]
    stats = _portfolio_stats(computed)
    assert len(stats.top_risk) == 3
    assert stats.top_risk[0][0] == "High"
    assert stats.top_risk[0][1] == 90.0
    assert stats.top_risk[1][0] == "High2"
    # ordered descending
    assert stats.top_risk[0][1] >= stats.top_risk[1][1] >= stats.top_risk[2][1]


def test_portfolio_stats_risk_distribution() -> None:
    computed = [
        (_fake_company("A", "petrochemical"), [], 10.0, 0),
        (_fake_company("B", "petrochemical"), [], 40.0, 0),
        (_fake_company("C", "airlines"), [], 70.0, 0),
    ]
    stats = _portfolio_stats(computed)
    assert stats.n_good == 1
    assert stats.n_warning == 1
    assert stats.n_bad == 1


def test_portfolio_stats_worst_indicator() -> None:
    fake_results_a = [
        (
            FakeProvider("low", "Low Indicator", "desc", ("role",)),
            SignalResult(value="1", score=10.0, status="good"),
        ),
        (
            FakeProvider("high", "High Indicator", "desc", ("role",)),
            SignalResult(value="2", score=80.0, status="bad"),
        ),
    ]
    fake_results_b = [
        (
            FakeProvider("low", "Low Indicator", "desc", ("role",)),
            SignalResult(value="1", score=20.0, status="good"),
        ),
        (
            FakeProvider("high", "High Indicator", "desc", ("role",)),
            SignalResult(value="2", score=90.0, status="bad"),
        ),
    ]
    # ``_portfolio_stats`` is typed against the runtime-checkable ``SignalProvider``
    # Protocol; ``FakeProvider`` satisfies it structurally. ty needs an explicit
    # cast to accept the test double as a real provider.
    computed = cast(
        "list[tuple[Company, list[tuple[SignalProvider, SignalResult]], float, int]]",
        [
            (_fake_company("A", "petrochemical"), fake_results_a, 45.0, 0),
            (_fake_company("B", "airlines"), fake_results_b, 55.0, 0),
        ],
    )
    stats = _portfolio_stats(computed)
    assert stats.worst_indicator_id == "high"
    assert stats.worst_indicator_label == "High Indicator"
    # mean of (80, 90) = 85
    assert stats.worst_indicator_mean == 85.0


class FakeProvider(SignalProvider):
    """Minimal provider stub for stats tests."""

    def __init__(self, iid: str, label: str, description: str, roles: tuple[str, ...]) -> None:
        self.indicator_id = iid
        self.label = label
        self.description = description
        self.roles = roles

    @override
    def compute(self, company: Identifiers, ctx: SignalContext) -> SignalResult:
        return SignalResult(value="0", score=0.0, status="demo")
