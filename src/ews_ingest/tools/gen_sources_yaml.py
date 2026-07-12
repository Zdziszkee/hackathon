"""Generate ``config/sources.yaml`` from the live registry.

Run: ``uv run python -m ews_ingest.tools.gen_sources_yaml``.

Keeps the registry in sync with registered connectors. Edits per-source Host→
rate policy, required env vars, and backfill windows live here as the single
source of truth for transport configuration.

Run with ``--check`` to verify the committed file is in sync with the live
registry; exits non-zero on drift so CI can guard against manual edits to
``config/sources.yaml``.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

import ews_ingest.sources  # noqa: F401 - triggers registration
from ews_ingest.core.registry import (
    SourceProfile,
    all_source_ids,
    get_source_profile,
)

# Per-source overrides: host, env_required, backfill, rps, burst, retries.
# Sources not listed get sensible category defaults.
_OVERRIDES: dict[str, dict[str, object]] = {
    # SEC (share data.sec.gov limiter; SEC_USER_AGENT required header).
    "company_financials.company_facts": {
        "host": "data.sec.gov",
        "rps": 8.0,
        "backfill": "full",
        "env_required": ["SEC_USER_AGENT"],
    },
    "company_financials.submissions": {
        "host": "data.sec.gov",
        "rps": 8.0,
        "backfill": "full",
        "env_required": ["SEC_USER_AGENT"],
    },
    "company_financials.concept_frames": {
        "host": "data.sec.gov",
        "rps": 8.0,
        "backfill": "full",
        "env_required": ["SEC_USER_AGENT"],
    },
    "company_financials.dera_bulk": {
        "host": "www.sec.gov",
        "rps": 8.0,
        "backfill": "full",
        "env_required": ["SEC_USER_AGENT"],
    },
    "company_financials.fulltext_search": {
        "host": "efts.sec.gov",
        "rps": 8.0,
        "backfill": "full",
        "env_required": ["SEC_USER_AGENT"],
    },
    "news.eight_k": {
        "host": "data.sec.gov",
        "rps": 8.0,
        "backfill": "full",
        "env_required": ["SEC_USER_AGENT"],
    },
    "credit_market.sec_form4_13f": {
        "host": "efts.sec.gov",
        "rps": 8.0,
        "backfill": "5y",
        "env_required": ["SEC_USER_AGENT"],
    },
    "credit_market.sec_ocr": {
        "host": "www.sec.gov",
        "rps": 8.0,
        "backfill": "full",
        "env_required": ["SEC_USER_AGENT"],
    },
    "default_truth.sec_8k_bankruptcy": {
        "host": "data.sec.gov",
        "rps": 8.0,
        "backfill": "full",
        "env_required": ["SEC_USER_AGENT"],
    },
    "identity.sec_identity": {
        "host": "data.sec.gov",
        "rps": 8.0,
        "backfill": "full",
        "env_required": ["SEC_USER_AGENT"],
    },
    "identity.sec_proxy_forms": {
        "host": "efts.sec.gov",
        "rps": 8.0,
        "backfill": "full",
        "env_required": ["SEC_USER_AGENT"],
    },
    "universe.sec_company_tickers": {
        "host": "www.sec.gov",
        "rps": 8.0,
        "backfill": "full",
        "env_required": ["SEC_USER_AGENT"],
    },
    # FRED (shared host).
    "credit_market.fred_credit": {
        "host": "api.stlouisfed.org",
        "rps": 5.0,
        "backfill": "5y",
        "env_required": ["FRED_API_KEY"],
    },
    "macro.fred_macro": {
        "host": "api.stlouisfed.org",
        "rps": 5.0,
        "backfill": "5y",
        "env_required": ["FRED_API_KEY"],
    },
    "transport.cass_freight": {
        "host": "api.stlouisfed.org",
        "rps": 5.0,
        "backfill": "5y",
        "env_required": ["FRED_API_KEY"],
    },
    "pricing.fred_pricing": {
        "host": "api.stlouisfed.org",
        "rps": 5.0,
        "backfill": "5y",
        "env_required": ["FRED_API_KEY"],
    },
    # EIA (shared host/key).
    "commodity.eia": {
        "host": "api.eia.gov",
        "rps": 4.0,
        "backfill": "5y",
        "env_required": ["EIA_API_KEY"],
    },
    "petrochem.eia_refinery": {
        "host": "api.eia.gov",
        "rps": 4.0,
        "backfill": "5y",
        "env_required": ["EIA_API_KEY"],
    },
    # BLS (shared host/key).
    "labor.bls": {
        "host": "api.bls.gov",
        "rps": 1.0,
        "backfill": "5y",
        "env_required": ["BLS_API_KEY"],
    },
    "pricing.bls_ppi": {
        "host": "api.bls.gov",
        "rps": 1.0,
        "backfill": "5y",
        "env_required": ["BLS_API_KEY"],
    },
    "pricing.bls_cpi": {
        "host": "api.bls.gov",
        "rps": 1.0,
        "backfill": "5y",
        "env_required": ["BLS_API_KEY"],
    },
    # Other keyed providers.
    "macro.bea": {
        "host": "apps.bea.gov",
        "rps": 1.0,
        "backfill": "5y",
        "env_required": ["BEA_API_KEY"],
    },
    "macro.census": {
        "host": "api.census.gov",
        "rps": 1.0,
        "backfill": "5y",
        "env_required": ["CENSUS_API_KEY"],
    },
    "universe.census_cbp": {
        "host": "api.census.gov",
        "rps": 1.0,
        "backfill": "full",
        "env_required": ["CENSUS_API_KEY"],
    },
    "commodity.usda_nass": {
        "host": "quickstats.nass.usda.gov",
        "rps": 1.0,
        "backfill": "5y",
        "env_required": ["USDA_API_KEY"],
    },
    "credit_market.finra_trace": {
        "host": "api.finra.org",
        "rps": 1.0,
        "backfill": "5y",
        "env_required": ["FINRA_API_KEY"],
    },
    "sanctions.opensanctions": {
        "host": "api.opensanctions.org",
        "rps": 1.0,
        "backfill": "full",
        "env_required": ["OPENSANCTIONS_API_KEY"],
    },
    # GLEIF / GDELT / EPA / BTS / Treasury / NWS / NHC — no key.
    "news.gdelt": {"host": "api.gdeltproject.org", "rps": 0.2, "backfill": "18mo"},
    "news.hackernews": {"host": "hn.algolia.com", "rps": 1.0, "backfill": "12mo"},
    "petrochem.epa_echo": {
        "host": "ofmpub.epa.gov",
        "rps": 2.0,
        "backfill": "5y",
        "enabled": False,
    },
    "petrochem.epa_frs": {"host": "frsquery.epa.gov", "rps": 2.0, "backfill": "5y"},
    "universe.epa_tri_universe": {"host": "data.epa.gov", "rps": 2.0, "backfill": "full"},
    "transport.bts_ftsi": {"host": "data.transportation.gov", "rps": 2.0, "backfill": "5y"},
    "transport.bts_air_consumer": {
        "host": "data.transportation.gov",
        "rps": 2.0,
        "backfill": "5y",
        "enabled": False,
    },
    "transport.bts_transtats": {"host": "transtats.bts.gov", "rps": 1.0, "backfill": "5y"},
    "transport.ntsb_carol": {
        "host": "data.ntsb.gov",
        "rps": 1.0,
        "backfill": "5y",
        "enabled": False,
    },
    "credit_market.treasury_fiscaldata": {
        "host": "api.fiscaldata.treasury.gov",
        "rps": 2.0,
        "backfill": "5y",
    },
    "macro.fed_releases": {"host": "www.federalreserve.gov", "rps": 1.0, "backfill": "5y"},
    "weather.nws": {"host": "api.weather.gov", "rps": 2.0, "backfill": "18mo"},
    "weather.noaa_nhc": {"host": "www.nhc.noaa.gov", "rps": 1.0, "backfill": "18mo"},
    "weather.noaa_ncei_storm": {"host": "www.ncei.noaa.gov", "rps": 1.0, "backfill": "5y"},
    "default_truth.courtlistener": {
        "host": "www.courtlistener.com",
        "rps": 1.0,
        "backfill": "full",
        "env_required": ["COURTLISTENER_API_KEY"],
    },
    "identity.wikidata": {"host": "query.wikidata.org", "rps": 1.0, "backfill": "full"},
    # Market data (unofficial / scrape).
    "credit_market.yahoo": {"host": "query1.finance.yahoo.com", "rps": 1.0, "backfill": "5y"},
    "news.common_crawl_news": {"host": "index.commoncrawl.org", "rps": 1.0, "backfill": "full"},
    "news.presswire": {"host": "www.globenewswire.com", "rps": 1.0, "backfill": "18mo"},
    "news.bluesky": {"host": "public.api.bsky.app", "rps": 1.0, "backfill": "18mo"},
    "news.mastodon": {"host": "mastodon.social", "rps": 1.0, "backfill": "18mo"},
    # Macro scrape.
    "macro.ism_pmi": {
        "host": "www.ismworld.org",
        "rps": 0.5,
        "backfill": "5y",
        "enabled": False,
    },
    "macro.regional_fed": {"host": "www.philadelphiafed.org", "rps": 1.0, "backfill": "5y"},
    "transport.ata_tonnage": {"host": "www.trucking.org", "rps": 0.5, "backfill": "18mo"},
    # Bulk manifests (no key, low rate).
    "sanctions.world_bank_debarred": {"host": "www.worldbank.org", "rps": 1.0, "backfill": "full"},
    "transport.fmcsa_census": {
        "host": "ai.fmcsa.dot.gov",
        "rps": 1.0,
        "backfill": "full",
        "enabled": False,
    },
    "transport.fmcsa_li_insurance": {"host": "ai.fmcsa.dot.gov", "rps": 1.0, "backfill": "full"},
    "transport.fmcsa_mcmis": {"host": "ai.fmcsa.dot.gov", "rps": 1.0, "backfill": "full"},
    "transport.fmcsa_new_entrant": {"host": "ai.fmcsa.dot.gov", "rps": 1.0, "backfill": "full"},
    "transport.fmcsa_sms": {
        "host": "ai.fmcsa.dot.gov",
        "rps": 1.0,
        "backfill": "5y",
        "enabled": False,
    },
    "transport.fmcsa_safer": {"host": "safer.fmcsa.dot.gov", "rps": 1.0, "backfill": "full"},
    "petrochem.osha_psm": {"host": "www.osha.gov", "rps": 1.0, "backfill": "5y"},
    "petrochem.phmsa_pipeline": {"host": "www.phmsa.dot.gov", "rps": 1.0, "backfill": "5y"},
    "petrochem.csb_reports": {"host": "www.csb.gov", "rps": 0.5, "backfill": "full"},
    "commodity.worldbank_pinksheet": {"host": "www.worldbank.org", "rps": 1.0, "backfill": "5y"},
    "commodity.imf_pcps": {"host": "www.imf.org", "rps": 1.0, "backfill": "5y"},
    "transport.usace_nav": {"host": "navigationdatacenter.us", "rps": 1.0, "backfill": "5y"},
    "universe.wikipedia_lists": {"host": "en.wikipedia.org", "rps": 1.0, "backfill": "full"},
    "universe.sec_sic_codes": {
        "host": "www.sec.gov",
        "rps": 8.0,
        "backfill": "full",
        "env_required": ["SEC_USER_AGENT"],
    },
    "universe.naics_census": {"host": "www.census.gov", "rps": 1.0, "backfill": "full"},
    # Supply chain (spec extension).
    "supply_chain.port_congestion": {"host": "api.worldbank.org", "rps": 2.0, "backfill": "5y"},
    "supply_chain.lead_time": {"host": "www.newyorkfed.org", "rps": 1.0, "backfill": "5y"},
    "supply_chain.logistics_disruption": {
        "host": "api.gdeltproject.org",
        "rps": 1.0,
        "backfill": "18mo",
    },
    "supply_chain.imf_port_watch": {"host": "portwatch.imf.org", "rps": 1.0, "backfill": "5y"},
    "supply_chain.un_comtrade": {
        "host": "comtradeapi.un.org",
        "rps": 1.0,
        "backfill": "5y",
        "env_required": ["UN_COMTRADE_API_KEY"],
    },
    "weather.noaa_gdacs": {"host": "www.gdacs.org", "rps": 1.0, "backfill": "18mo"},
    "default_truth.state_sos_ucc": {
        "host": "www.sos.state.tx.us",
        "rps": 0.3,
        "backfill": "full",
    },
    # News scrape + IR.
    "news.company_ir": {"host": "ir-site.local", "rps": 0.5, "backfill": "18mo"},
    # Stubs (fragile/fee) — registered but raise NotImplementedError.
    "credit_market.rating_agencies": {
        "host": "rating-agencies.local",
        "rps": 0.3,
        "backfill": "18mo",
        "enabled": False,
    },
    "transport.baltic_dry": {
        "host": "baltic.local",
        "rps": 0.3,
        "backfill": "18mo",
        "enabled": False,
    },
    "default_truth.pacer": {
        "host": "pacer.uscourts.gov",
        "rps": 0.3,
        "backfill": "full",
        "enabled": False,
    },
}

# Category-default backfill windows keyed by source_id prefix.
_CATEGORY_BACKFILL: dict[str, str] = {
    "company_financials": "full",
    "news": "18mo",
    "sanctions": "full",
    "credit_market": "5y",
    "macro": "5y",
    "commodity": "5y",
    "transport": "5y",
    "petrochem": "5y",
    "weather": "18mo",
    "labor": "18mo",
    "pricing": "5y",
    "default_truth": "full",
    "identity": "full",
    "universe": "full",
    "supply_chain": "5y",
}


def _backfill(source_id: str) -> str:
    cat = source_id.split(".", 1)[0]
    return _CATEGORY_BACKFILL.get(cat, "5y")


def main() -> None:
    args = _parse_args()
    text = _render()
    out = Path(__file__).resolve().parents[1] / "config" / "sources.yaml"
    if args.check:
        existing = out.read_text(encoding="utf-8") if out.exists() else ""
        if existing != text:
            diff = "".join(
                difflib.unified_diff(
                    existing.splitlines(keepends=True),
                    text.splitlines(keepends=True),
                    fromfile=f"{out} (committed)",
                    tofile=f"{out} (live registry)",
                )
            )
            sys.stderr.write(
                f"config/sources.yaml is out of sync with the live registry. "
                f"Re-run `uv run python -m ews_ingest.tools.gen_sources_yaml` to fix.\n\n"
                f"{diff}"
            )
            raise SystemExit(1)
        print(f"{out} is in sync with the live registry ({len(all_source_ids())} sources)")
        return
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out} ({len(all_source_ids())} sources)")


def _parse_args() -> argparse.Namespace:
    doc = __doc__ or ""
    parser = argparse.ArgumentParser(description=doc.splitlines()[0] if doc else "")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if config/sources.yaml is out of sync with the live registry.",
    )
    return parser.parse_args()


def _render() -> str:
    """Render the YAML for the current registry; returned as one string."""
    lines: list[str] = [
        "# Source registry — generated by `uv run python -m ews_ingest.tools.gen_sources_yaml`."
    ]
    lines.append("# Re-run after adding connectors to keep this in sync with the live registry.")
    lines.append(
        "# Per-host rate policies, required env vars, and backfill windows are declared here."
    )
    lines.append("# `scope` comes from each connector's @register_source decorator")
    lines.append("# and reflects the live registry.")
    lines.append("")
    for source_id in all_source_ids():
        profile: SourceProfile = get_source_profile(source_id)
        ov = _OVERRIDES.get(source_id, {})
        host = str(ov.get("host", source_id))
        rps = ov.get("rps", 1.0)
        burst = ov.get("burst", 1)
        retries = ov.get("retries", 3)
        backfill = str(ov.get("backfill", _backfill(source_id)))
        enabled = ov.get("enabled", True)
        env_required = ov.get("env_required", [])
        lines.append(f"- source_id: {source_id}")
        lines.append(f"  host: {host}")
        lines.append(f"  rps: {rps}")
        lines.append(f"  burst: {burst}")
        lines.append(f"  retries: {retries}")
        lines.append(f"  enabled: {str(enabled).lower()}")
        lines.append(f"  backfill: {backfill}")
        lines.append(f"  scope: {profile.scope.value}")
        if env_required:
            envs = env_required if isinstance(env_required, list) else []
            env_list = ", ".join(f'"{e}"' for e in envs)
            lines.append(f"  env_required: [{env_list}]")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
