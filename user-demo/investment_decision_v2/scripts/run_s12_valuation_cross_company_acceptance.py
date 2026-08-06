#!/usr/bin/env python3
"""Run the frozen S12 cross-business-model valuation acceptance protocol.

The controlled fixtures in this module are synthetic and exist only to exercise
the shared S09-S11 contracts. They are never public-company research inputs or
investment conclusions.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
INVESTMENT_ROOT = SCRIPT_DIR.parent
REPO_ROOT = INVESTMENT_ROOT.parents[1]
REGRESSION_ROOT = INVESTMENT_ROOT / "regression"
DEFAULT_MANIFEST = (
    REGRESSION_ROOT / "s12_valuation_cross_company_acceptance_manifest.json"
)

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_public_company_investment_layer import (  # noqa: E402
    build_share_count_basis,
    build_valuation_scope_status,
    scenario_set,
)
from equity_valuation_contract import (  # noqa: E402
    build_shared_valuation_contract,
    legacy_return_context,
    validate_shared_valuation_contract,
)
from forward_operating_model import (  # noqa: E402
    CASH_FLOW_MEASUREMENT_BASES,
    DRIVER_MODULE_REGISTRY,
    FORWARD_FCF_BASIS,
    build_forward_valuation_contract,
    validate_forward_valuation_contract,
)
from regression_governance import (  # noqa: E402
    load_json,
    scan_fixture_specific_branches,
)
from valuation_cross_checks import (  # noqa: E402
    build_probability_governance,
    build_valuation_cross_check_contract,
    validate_probability_governance,
    validate_valuation_cross_check_contract,
    valuation_cross_check_calculation_records,
)


AS_OF_DATE = "2026-07-31"
TARGET_DATE = "2027-07-31"
FORECAST_START = "2026-08-01"
SYNTHETIC_LABEL = "SYNTHETIC_ACCEPTANCE_ONLY"
ASSUMPTION_ID = "EV-S12-ASSUMPTION"
BUSINESS_MODEL_ID = "EV-S12-BUSINESS-MODEL"
SHARES_ID = "EV-S12-SHARES"

REAL_CONTRACT_PATHS = {
    "CROX": (
        INVESTMENT_ROOT
        / "v1_0_0_outputs/crox_crocs_inc/step3/underwriting_output_contract.json"
    ),
    "AZO": (
        INVESTMENT_ROOT
        / "v1_0_0_outputs/azo_autozone_inc/step3/underwriting_output_contract.json"
    ),
    "CRM": (
        INVESTMENT_ROOT
        / "v1_0_0_outputs/crm_salesforce_inc/step3/underwriting_output_contract.json"
    ),
    "ODFL": (
        INVESTMENT_ROOT
        / "blind_tests/s05_odfl/post_fix/builder_output/"
        "odfl_old_dominion_freight_line_inc/step3/underwriting_output_contract.json"
    ),
    "ITT": (
        INVESTMENT_ROOT
        / "blind_tests/s08_itt/post_fix/builder_output/"
        "itt_itt_inc/step3/underwriting_output_contract.json"
    ),
}


def _unique(values: Any) -> list[str]:
    return sorted({str(value) for value in values or [] if value})


def _periods() -> dict[str, dict[str, Any]]:
    return {
        "forecast_period": {
            "status": "VALIDATED",
            "start_date": FORECAST_START,
            "end_date": TARGET_DATE,
            "label": "Forward operating forecast to target date",
            "period_type": "FORECAST",
            "basis": "HOLDING_PERIOD_FORECAST",
            "evidence_ids": [],
        },
        "metric_period": {
            "status": "VALIDATED",
            "start_date": FORECAST_START,
            "end_date": TARGET_DATE,
            "label": "Forward twelve-month FCF at exit",
            "period_type": "FORWARD_METRIC",
            "basis": "FORWARD_PERIOD_ENDING_AT_TARGET",
            "evidence_ids": [],
        },
    }


def _evidence(
    evidence_id: str,
    value: float,
    *,
    metric_name: str,
    currency: str = "USD",
    unit: str = "USD",
    evidence_class: str = "FACT",
    source_level: int = 1,
    as_of_date: str = AS_OF_DATE,
    period_start: str = "",
    period_end: str | None = None,
) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "metric_name": metric_name,
        "value": value,
        "scale": 1.0,
        "currency": currency,
        "unit": unit,
        "period_start": period_start,
        "period_end": period_end or as_of_date,
        "as_of_date": as_of_date,
        "publication_date": as_of_date,
        "retrieval_date": AS_OF_DATE,
        "evidence_class": evidence_class,
        "evidence_type": evidence_class,
        "validation_status": "PASS",
        "source_level": source_level,
        "source_id": f"SRC-{evidence_id}",
        "source_type": "synthetic_acceptance_fixture",
        "source_name": SYNTHETIC_LABEL,
        "source_locator": evidence_id,
        "measurement_basis": SYNTHETIC_LABEL,
    }


def _base_parent(case_id: str) -> dict[str, Any]:
    revenue_records = [
        _evidence(
            f"EV-S12-BASE-REVENUE-{value:g}",
            value,
            metric_name="valuation_basis_revenue",
            evidence_class="CALC",
            source_level=0,
            period_start="2025-08-01",
            period_end=AS_OF_DATE,
        )
        for value in (20.0, 40.0, 60.0, 80.0, 100.0)
    ]
    return {
        "schema_version": "5.1.0",
        "fixture_classification": SYNTHETIC_LABEL,
        "company": {
            "ticker": case_id,
            "name": SYNTHETIC_LABEL,
        },
        "data_gate": {"level": 3},
        "report_dates": {
            "analysis_date": AS_OF_DATE,
            "market_price_date": AS_OF_DATE,
        },
        "valuation": {
            "price": 10.0,
            "price_date": AS_OF_DATE,
            "price_currency": "USD",
            "shares": 100.0,
            "shares_as_of_date": AS_OF_DATE,
            "market_cap": 1000.0,
            "enterprise_value_proxy": 1200.0,
            "shares_source": {
                "form": "SYNTHETIC",
                "accn": "S12",
                "filed": AS_OF_DATE,
            },
        },
        "evidence_records": [
            _evidence(
                ASSUMPTION_ID,
                1.0,
                metric_name="synthetic_assumption_support",
                currency="",
                unit="PURE",
                source_level=2,
            ),
            _evidence(
                BUSINESS_MODEL_ID,
                1.0,
                metric_name="synthetic_business_model_support",
                currency="",
                unit="PURE",
                source_level=2,
            ),
            _evidence(
                SHARES_ID,
                100.0,
                metric_name="shares_outstanding_point_in_time",
                currency="",
                unit="SHARES",
            ),
            *revenue_records,
        ],
    }


def _assumption(
    value: float,
    *,
    evidence_id: str = ASSUMPTION_ID,
    evidence_class: str = "JUDGMENT",
    unit: str = "RATIO",
    currency: str = "",
) -> dict[str, Any]:
    return {
        "value": value,
        "evidence_class": evidence_class,
        "evidence_ids": [evidence_id],
        "reviewed_by": "S12 Valuation Reviewer",
        "rationale": "Controlled assumption for cross-business-model acceptance.",
        "unit": unit,
        "currency": currency,
    }


def _base_revenue(value: float) -> dict[str, Any]:
    line = _assumption(
        value,
        evidence_id=f"EV-S12-BASE-REVENUE-{value:g}",
        evidence_class="CALC",
        unit="USD",
        currency="USD",
    )
    line["formula"] = "Reconciled synthetic acceptance revenue."
    return line


def _revenue_driver(module: str) -> dict[str, Any]:
    if module == "RETAIL":
        return {
            "base_revenue": _base_revenue(100.0),
            "comparable_sales_growth": _assumption(0.05),
            "net_store_growth": _assumption(0.02),
            "other_revenue_growth": _assumption(0.01),
        }
    if module == "CONSUMER_BRAND":
        return {
            "brand_segments": [
                {
                    "name": "Core Brand",
                    "base_revenue": _base_revenue(60.0),
                    "revenue_growth": _assumption(0.05),
                },
                {
                    "name": "Growth Brand",
                    "base_revenue": _base_revenue(40.0),
                    "revenue_growth": _assumption(-0.02),
                },
            ]
        }
    if module == "SUBSCRIPTION_SOFTWARE":
        return {
            "revenue_streams": [
                {
                    "name": "Subscription",
                    "base_revenue": _base_revenue(80.0),
                    "revenue_growth": _assumption(0.10),
                },
                {
                    "name": "Services",
                    "base_revenue": _base_revenue(20.0),
                    "revenue_growth": _assumption(0.00),
                },
            ]
        }
    if module == "INDUSTRIAL":
        return {
            "base_revenue": _base_revenue(100.0),
            "volume_growth": _assumption(0.03),
            "price_mix_growth": _assumption(0.02),
            "acquisition_revenue": _assumption(
                5.0,
                unit="USD",
                currency="USD",
            ),
            "divestiture_revenue": _assumption(
                2.0,
                unit="USD",
                currency="USD",
            ),
        }
    if module == "ACQUISITION_HEAVY":
        return {
            "base_revenue": _base_revenue(100.0),
            "organic_growth": _assumption(0.03),
            "acquired_revenue": _assumption(
                10.0,
                unit="USD",
                currency="USD",
            ),
            "divested_revenue": _assumption(
                2.0,
                unit="USD",
                currency="USD",
            ),
        }
    if module == "DISTRIBUTION":
        return {
            "base_revenue": _base_revenue(100.0),
            "volume_growth": _assumption(0.03),
            "price_mix_growth": _assumption(0.02),
        }
    raise ValueError(f"Unsupported controlled S12 driver module: {module}")


def _cash_flow_driver() -> dict[str, Any]:
    values = {
        "operating_margin": _assumption(0.30),
        "cash_interest": _assumption(5.0),
        "cash_taxes": _assumption(5.0),
        "depreciation_and_amortization": _assumption(15.0),
        "stock_based_compensation": _assumption(5.0),
        "other_non_cash_items": _assumption(0.0),
        "working_capital_investment": _assumption(5.0),
        "capex": _assumption(10.0),
        "restructuring_cash": _assumption(0.0),
        "acquisition_integration_cash": _assumption(0.0),
        "other_cash_adjustments": _assumption(0.0),
    }
    for field, line in values.items():
        line["measurement_basis"] = CASH_FLOW_MEASUREMENT_BASES[field]
        if field != "operating_margin":
            line["unit"] = "USD"
            line["currency"] = "USD"
    return values


def _forward_research(module: str) -> dict[str, Any]:
    return {
        "valuation_contract": {
            "valuation_as_of_date": AS_OF_DATE,
            "target_date": TARGET_DATE,
            **copy.deepcopy(_periods()),
        },
        "forward_valuation": {
            "status": "ANALYST_VALIDATED",
            "driver_module": module,
            "module_selection": {
                "status": "ANALYST_VALIDATED",
                "rationale": (
                    "The controlled module matches the synthetic acceptance "
                    "business-model classification."
                ),
                "evidence_ids": [BUSINESS_MODEL_ID],
                "reviewed_by": "S12 Module Reviewer",
            },
            "currency": "USD",
            "unit": "USD",
            "amount_scale": 1.0,
            "fcf_basis": FORWARD_FCF_BASIS,
            "reviewed_by": "S12 Forward Model Reviewer",
            "scenarios": [
                {
                    "name": name,
                    "scenario_rationale": f"{name} controlled operating path.",
                    "revenue_driver": copy.deepcopy(_revenue_driver(module)),
                    "cash_flow_driver": _cash_flow_driver(),
                    "reviewed_by": "S12 Forward Model Reviewer",
                }
                for name in ("Bear", "Base", "Bull")
            ],
            "share_count_bridge": {
                "status": "ANALYST_VALIDATED",
                "target_date": TARGET_DATE,
                "known_subsequent_event_status": "REVIEWED_CHANGE_REFLECTED",
                "known_subsequent_event_note": (
                    "Controlled repurchase and issuance assumptions were reviewed."
                ),
                "reviewed_by": "S12 Share Reviewer",
                "changes": {
                    "repurchases": _assumption(
                        5.0,
                        unit="SHARES",
                        currency="SHARES",
                    ),
                    "stock_based_compensation_issuance": _assumption(
                        2.0,
                        unit="SHARES",
                        currency="SHARES",
                    ),
                    "employee_plan_issuance": _assumption(
                        1.0,
                        unit="SHARES",
                        currency="SHARES",
                    ),
                    "convertible_dilution": _assumption(
                        0.0,
                        unit="SHARES",
                        currency="SHARES",
                    ),
                    "acquisition_share_issuance": _assumption(
                        0.0,
                        unit="SHARES",
                        currency="SHARES",
                    ),
                    "other_net_change": _assumption(
                        0.0,
                        unit="SHARES",
                        currency="SHARES",
                    ),
                },
            },
        },
    }


def _scenario_input(
    *,
    probabilities: tuple[float | None, float | None, float | None],
) -> dict[str, Any]:
    return {
        "status": "ANALYST_VALIDATED",
        "metric": "Forward FCF",
        "reviewed_by": "S12 Scenario Reviewer",
        "scenarios": [
            {
                "name": name,
                "probability": probability,
                "metric_value_total": None,
                "growth_assumption": None,
                "exit_multiple": multiple,
                "key_driver": f"{name} controlled forward operating bridge",
                "falsification_trigger": f"{name} controlled bridge fails",
                "assumption_sources": [],
                "probability_rationale": (
                    f"{name} probability rationale."
                    if probability is not None
                    else ""
                ),
            }
            for name, probability, multiple in zip(
                ("Bear", "Base", "Bull"),
                probabilities,
                (30.0, 35.0, 40.0),
                strict=True,
            )
        ],
    }


def _normalize_scenarios(rows: list[Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for source in rows:
        row = asdict(source)
        row["implied_price"] = row.pop("target_price")
        row["price_change_vs_current"] = row.pop("total_return")
        row["formula"] = (
            "implied_price = scenario_metric_value / share_count_basis * "
            "scenario_multiple; price_change_vs_current = "
            "implied_price / dated_market_price - 1"
        )
        output.append(row)
    return output


def _build_forward_path(
    parent: dict[str, Any],
    module: str,
    *,
    probabilities: tuple[float | None, float | None, float | None],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    research = _forward_research(module)
    research["normalized_fcf"] = {
        "status": "VALIDATED",
        "value": 30.0,
        "reviewed_by": "S12 FCF Reviewer",
    }
    research["scenario_model"] = _scenario_input(probabilities=probabilities)
    forward = build_forward_valuation_contract(parent, research)
    share_basis = build_share_count_basis(parent, research, forward)
    scenarios, scenario_status = scenario_set(
        parent["valuation"],
        {},
        {},
        research,
        share_basis,
        forward,
    )
    if scenario_status != "scenario_assumptions_validated":
        raise ValueError(f"Shared scenario engine blocked the fixture: {scenario_status}")
    parent["forward_valuation_contract"] = forward
    parent["share_count_basis"] = share_basis
    parent["scenarios"] = _normalize_scenarios(scenarios)
    return research, forward, share_basis


def _build_range_path(
    parent: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    research = {
        "normalized_fcf": {
            "status": "VALIDATED",
            "value": 100.0,
            "reviewed_by": "S12 FCF Reviewer",
        },
        "scenario_model": {
            "status": "ANALYST_VALIDATED",
            "metric": "Public-Data FCF Underwriting Base",
            "metric_currency": "USD",
            "metric_unit": "USD",
            "reviewed_by": "S12 Scenario Reviewer",
            "scenarios": [
                {
                    "name": name,
                    "probability": None,
                    "metric_value_total": value,
                    "growth_assumption": growth,
                    "exit_multiple": multiple,
                    "key_driver": f"{name} controlled price sensitivity",
                    "falsification_trigger": f"{name} sensitivity fails",
                    "assumption_sources": [],
                }
                for name, value, growth, multiple in (
                    ("Bear", 80.0, -0.20, 8.0),
                    ("Base", 100.0, 0.00, 10.0),
                    ("Bull", 120.0, 0.20, 12.0),
                )
            ],
        },
    }
    forward = build_forward_valuation_contract(parent, research)
    share_basis = build_share_count_basis(parent, research, forward)
    scenarios, scenario_status = scenario_set(
        parent["valuation"],
        {},
        {},
        research,
        share_basis,
        forward,
    )
    if scenario_status != "scenario_assumptions_validated":
        raise ValueError(f"Range-only scenario path failed: {scenario_status}")
    parent["forward_valuation_contract"] = forward
    parent["share_count_basis"] = share_basis
    parent["scenarios"] = _normalize_scenarios(scenarios)
    return research, forward, share_basis


def _add_dcf_evidence(parent: dict[str, Any]) -> None:
    parent["evidence_records"].extend(
        [
            _evidence("EV-S12-NET-DEBT", 200.0, metric_name="net_debt"),
            _evidence(
                "EV-S12-NONOPERATING",
                0.0,
                metric_name="non_operating_assets",
            ),
            _evidence(
                "EV-S12-MINORITY",
                0.0,
                metric_name="minority_interest",
            ),
        ]
    )


def _add_s11_evidence(parent: dict[str, Any]) -> None:
    _add_dcf_evidence(parent)
    base_forward_fcf = next(
        row["forward_fcf"]
        for row in parent["forward_valuation_contract"]["scenarios"]
        if row["name"] == "Base"
    )
    records = [
        _evidence(
            "EV-S12-MARKET-CAP",
            1000.0,
            metric_name="market_cap_point_in_time",
        ),
        _evidence(
            "EV-S12-ENTERPRISE-VALUE",
            1200.0,
            metric_name="enterprise_value_proxy",
        ),
        _evidence(
            "EV-S12-SUBJECT-FCF",
            base_forward_fcf,
            metric_name="forward_fcf_comparison",
            evidence_class="CALC",
            source_level=0,
            period_start=FORECAST_START,
            period_end=TARGET_DATE,
        ),
        _evidence(
            "EV-S12-FORWARD-SHARES",
            98.0,
            metric_name="forward_diluted_share_count",
            currency="SHARES",
            unit="SHARES",
            evidence_class="CALC",
            source_level=0,
            as_of_date=TARGET_DATE,
            period_end=TARGET_DATE,
        ),
    ]
    for label, multiple in (
        ("SUBJECT", 35.0),
        ("PEER-A", 30.0),
        ("PEER-B", 35.0),
        ("PEER-C", 40.0),
    ):
        records.extend(
            [
                _evidence(
                    f"EV-S12-{label}-CAPITAL",
                    multiple * base_forward_fcf,
                    metric_name=f"{label.lower()}_market_cap",
                ),
                _evidence(
                    f"EV-S12-{label}-FCF",
                    base_forward_fcf,
                    metric_name=f"{label.lower()}_forward_fcf",
                    period_start=FORECAST_START,
                    period_end=TARGET_DATE,
                ),
            ]
        )
    for index, (year, multiple) in enumerate(
        (
            (2021, 25.0),
            (2022, 30.0),
            (2023, 35.0),
            (2024, 40.0),
            (2025, 45.0),
        ),
        start=1,
    ):
        history_date = f"{year}-07-31"
        records.extend(
            [
                _evidence(
                    f"EV-S12-HIST-{index}-CAPITAL",
                    multiple * base_forward_fcf,
                    metric_name=f"historical_{index}_market_cap",
                    as_of_date=history_date,
                    period_end=history_date,
                ),
                _evidence(
                    f"EV-S12-HIST-{index}-FCF",
                    base_forward_fcf,
                    metric_name=f"historical_{index}_forward_fcf",
                    as_of_date=history_date,
                    period_start=f"{year + 1}-08-01",
                    period_end=f"{year + 2}-07-31",
                ),
            ]
        )
    base_price = next(
        row["implied_price"] for row in parent["scenarios"] if row["name"] == "Base"
    )
    records.append(
        _evidence(
            "EV-S12-BASE-PRICE",
            base_price,
            metric_name="scenario_base_implied_price",
            unit="USD/SHARE",
            evidence_class="CALC",
            source_level=0,
        )
    )
    parent["evidence_records"].extend(records)


def _observation(
    label: str,
    capital: float,
    fundamental: float,
    *,
    as_of_date: str = AS_OF_DATE,
    fiscal_period_end: str = TARGET_DATE,
) -> dict[str, Any]:
    return {
        "metric": "P/FCF",
        "value": capital / fundamental,
        "capital_value": capital,
        "fundamental_value": fundamental,
        "currency": "USD",
        "as_of_date": as_of_date,
        "fiscal_period_end": fiscal_period_end,
        "period_basis": "NTM",
        "accounting_definition": "MARKET_CAP/NTM_CFO_MINUS_CAPEX",
        "capital_evidence_ids": [f"EV-S12-{label}-CAPITAL"],
        "fundamental_evidence_ids": [f"EV-S12-{label}-FCF"],
    }


def _judgment(value: float, *, unit: str = "RATIO") -> dict[str, Any]:
    return {
        "value": value,
        "unit": unit,
        "evidence_class": "JUDGMENT",
        "evidence_ids": [ASSUMPTION_ID],
        "reviewed_by": "S12 Valuation Reviewer",
        "rationale": "Controlled, evidenced S12 valuation assumption.",
    }


def _fact_line(
    value: float,
    evidence_id: str,
    *,
    currency: str = "USD",
    unit: str = "USD",
) -> dict[str, Any]:
    return {
        "value": value,
        "currency": currency,
        "unit": unit,
        "evidence_class": "FACT",
        "evidence_ids": [evidence_id],
        "reviewed_by": "S12 Valuation Reviewer",
    }


def _independent_cross_check() -> dict[str, Any]:
    return {
        "status": "VALIDATED",
        "as_of_date": AS_OF_DATE,
        "method": "DISCOUNTED_CASH_FLOW_GORDON_GROWTH",
        "cash_flow_basis": "UNLEVERED_FCFF",
        "discount_rate_basis": "WACC",
        "reviewed_by": "S12 DCF Reviewer",
        "forecast_cash_flows": [
            {
                "year_index": year,
                "period_end": f"{2027 + year - 1}-07-31",
                "currency": "USD",
                **_judgment(value, unit="USD"),
            }
            for year, value in ((1, 30.0), (2, 32.0), (3, 34.0))
        ],
        "discount_rate": _judgment(0.10),
        "terminal_growth": _judgment(0.03),
        "net_debt": _fact_line(200.0, "EV-S12-NET-DEBT"),
        "non_operating_assets": _fact_line(
            0.0,
            "EV-S12-NONOPERATING",
        ),
        "minority_interest": _fact_line(
            0.0,
            "EV-S12-MINORITY",
        ),
        "shares": _fact_line(
            100.0,
            SHARES_ID,
            currency="SHARES",
            unit="SHARES",
        ),
        "share_basis": {
            "status": "VALIDATED",
            "basis_type": "POINT_IN_TIME_OUTSTANDING",
            "basis_date": AS_OF_DATE,
            "rationale": "Use the dated point-in-time shares for this independent check.",
            "reviewed_by": "S12 DCF Reviewer",
        },
        "sensitivity": {
            "discount_rate_step": 0.01,
            "terminal_growth_step": 0.005,
            "evidence_class": "JUDGMENT",
            "evidence_ids": [ASSUMPTION_ID],
            "rationale": "Test a symmetric controlled valuation range.",
            "reviewed_by": "S12 DCF Reviewer",
        },
    }


def _s11_input(parent: dict[str, Any], *, full: bool) -> dict[str, Any]:
    if not full:
        return {
            "status": "PARTIALLY_VALIDATED",
            "as_of_date": AS_OF_DATE,
            "reviewed_by": "S12 Valuation Reviewer",
            "independent_cross_check": _independent_cross_check(),
        }
    base_forward_fcf = next(
        row["forward_fcf"]
        for row in parent["forward_valuation_contract"]["scenarios"]
        if row["name"] == "Base"
    )
    history = [
        _observation(
            f"HIST-{index}",
            multiple * base_forward_fcf,
            base_forward_fcf,
            as_of_date=f"{year}-07-31",
            fiscal_period_end=f"{year + 2}-07-31",
        )
        for index, (year, multiple) in enumerate(
            (
                (2021, 25.0),
                (2022, 30.0),
                (2023, 35.0),
                (2024, 40.0),
                (2025, 45.0),
            ),
            start=1,
        )
    ]
    reference = {
        "value": 35.0,
        **_judgment(35.0),
    }
    reference["value"] = 35.0
    return {
        "status": "VALIDATED",
        "as_of_date": AS_OF_DATE,
        "reviewed_by": "S12 Valuation Reviewer",
        "peer_comparison": {
            "status": "VALIDATED",
            "as_of_date": AS_OF_DATE,
            "selection_rationale": (
                "Controlled fixtures use aligned NTM FCF definitions and currencies."
            ),
            "reviewed_by": "S12 Peer Reviewer",
            "minimum_comparable_peers": 3,
            "subject_metrics": [
                _observation(
                    "SUBJECT",
                    35.0 * base_forward_fcf,
                    base_forward_fcf,
                )
            ],
            "peers": [
                {
                    "ticker": ticker,
                    "business_model_fit": "COMPARABLE",
                    "metrics": [
                        _observation(
                            label,
                            multiple * base_forward_fcf,
                            base_forward_fcf,
                        )
                    ],
                }
                for ticker, label, multiple in (
                    ("S12PA", "PEER-A", 30.0),
                    ("S12PB", "PEER-B", 35.0),
                    ("S12PC", "PEER-C", 40.0),
                )
            ],
        },
        "historical_valuation": {
            "status": "VALIDATED",
            "as_of_date": AS_OF_DATE,
            "reviewed_by": "S12 History Reviewer",
            "comparability_rationale": (
                "The controlled history uses the same NTM FCF definition."
            ),
            "minimum_observations": 5,
            "minimum_span_days": 365,
            "current_observation": _observation(
                "SUBJECT",
                35.0 * base_forward_fcf,
                base_forward_fcf,
            ),
            "observations": history,
        },
        "reverse_valuation": {
            "status": "VALIDATED",
            "as_of_date": AS_OF_DATE,
            "method": "EQUITY_FCF_MULTIPLE",
            "capital_evidence_ids": ["EV-S12-MARKET-CAP"],
            "selected_reference": reference,
            "reference_basis": {
                "metric": "P/FCF",
                "currency": "USD",
                "period_basis": "NTM",
                "accounting_definition": "MARKET_CAP/NTM_CFO_MINUS_CAPEX",
            },
            "metric_period": {
                "status": "VALIDATED",
                "period_type": "FORWARD_METRIC",
                "start_date": FORECAST_START,
                "end_date": TARGET_DATE,
            },
            "comparison_metric": {
                "value": base_forward_fcf,
                "metric_name": "forward_fcf_comparison",
                "currency": "USD",
                "period_basis": "NTM",
                "accounting_definition": "MARKET_CAP/NTM_CFO_MINUS_CAPEX",
                "evidence_ids": ["EV-S12-SUBJECT-FCF"],
            },
        },
        "independent_cross_check": _independent_cross_check(),
        "method_agreement": {
            "tolerance": {
                "value": 0.25,
                **_judgment(0.25),
            }
        },
    }


def _probability_input() -> dict[str, Any]:
    return {
        "status": "VALIDATED",
        "method_type": "SCENARIO_JUDGMENT",
        "methodology": (
            "Allocate weights from explicit controlled operating signposts and "
            "test alternative distributions."
        ),
        "method_details": {
            "allocation_rationale": "The controlled base path has the strongest support.",
            "sensitivity_completed": True,
        },
        "evidence_ids": [ASSUMPTION_ID],
        "scenario_rationales": {
            "Bear": "Controlled downside path.",
            "Base": "Controlled central path.",
            "Bull": "Controlled upside path.",
        },
        "as_of_date": AS_OF_DATE,
        "probability_expiration_review_date": "2026-10-31",
        "review_triggers": ["NEW_EARNINGS_OR_GUIDANCE"],
        "reviewed_by": "S12 Probability Owner",
        "approval": {
            "status": "APPROVED",
            "approved_by": "S12 Independent Research Reviewer",
            "approval_date": AS_OF_DATE,
            "approval_scope": "PROBABILITY_METHODOLOGY_AND_WEIGHTS",
            "independent_research_review": True,
        },
        "sensitivity_cases": [
            {
                "label": "Downside heavy",
                "probabilities": {"Bear": 0.50, "Base": 0.35, "Bull": 0.15},
            },
            {
                "label": "Central",
                "probabilities": {"Bear": 0.20, "Base": 0.50, "Bull": 0.30},
            },
            {
                "label": "Upside heavy",
                "probabilities": {"Bear": 0.10, "Base": 0.30, "Bull": 0.60},
            },
        ],
    }


def _valuation_input() -> dict[str, Any]:
    return {
        "status": "VALIDATED",
        "valuation_as_of_date": AS_OF_DATE,
        "target_date": TARGET_DATE,
        "holding_period_days": 365,
        **copy.deepcopy(_periods()),
        "dividend_assumption": {
            "status": "VALIDATED",
            "amount_per_share": 0.0,
            "currency": "USD",
            "basis": "CUMULATIVE_CASH_DIVIDENDS_THROUGH_TARGET_DATE",
            "payment_timing": "DURING_HOLDING_PERIOD",
            "reinvestment": False,
            "reviewed_by": "S12 Valuation Reviewer",
        },
        "exit_basis": {
            "status": "VALIDATED",
            "method": "SCENARIO_EXIT_MULTIPLE",
            "metric": "Forward FCF",
            "terminal_or_exit": "EXIT",
            "reviewed_by": "S12 Valuation Reviewer",
        },
        "reviewed_by": "S12 Valuation Reviewer",
    }


def _incomplete_valuation_input() -> dict[str, Any]:
    supplied = _valuation_input()
    supplied["dividend_assumption"] = {"status": "NOT_DEFINED"}
    return supplied


def _persist_s11(
    parent: dict[str, Any],
    supplied: dict[str, Any],
) -> dict[str, Any]:
    contract = build_valuation_cross_check_contract(parent, supplied)
    parent["valuation_cross_check_contract"] = contract
    existing = {
        str(row.get("evidence_id"))
        for row in parent.get("evidence_records", [])
        if row.get("evidence_id")
    }
    parent["evidence_records"].extend(
        row
        for row in valuation_cross_check_calculation_records(contract, parent)
        if row.get("evidence_id") not in existing
    )
    return contract


def _finish_status_case(
    parent: dict[str, Any],
    research: dict[str, Any],
    forward: dict[str, Any],
    share_basis: dict[str, Any],
    *,
    valuation_input: dict[str, Any],
    probability_input: dict[str, Any] | None,
) -> dict[str, Any]:
    probability = build_probability_governance(
        probability_input or {},
        parent.get("scenarios", []),
        parent.get("evidence_records", []),
        AS_OF_DATE,
    )
    parent["probability_validation"] = probability
    valuation_contract = build_shared_valuation_contract(
        parent,
        valuation_input,
    )
    parent["valuation_contract"] = valuation_contract
    formal_weighted_allowed = (
        valuation_contract.get("outputs", {})
        .get("probability_weighted_return", {})
        .get("status")
        == "VALIDATED"
    )
    probability["weighted_return_allowed"] = formal_weighted_allowed
    probability["formal_probability_weighted_expected_return_status"] = (
        "VALIDATED" if formal_weighted_allowed else "NOT_EVALUATED"
    )
    for row in probability.get("sensitivity_table", []):
        row.pop("probability_weighted_return", None)
        row["formal_weighted_expected_return"] = None
    parent["probability_validation"] = probability
    scope = build_valuation_scope_status(
        parent,
        research,
        share_basis,
        legacy_return_context(valuation_contract),
        forward,
    )
    return {
        "parent": parent,
        "forward": forward,
        "share_basis": share_basis,
        "s11": parent.get("valuation_cross_check_contract", {}),
        "probability": probability,
        "valuation_contract": valuation_contract,
        "scope": scope,
    }


def build_status_case(case_id: str) -> dict[str, Any]:
    parent = _base_parent(case_id)
    if case_id == "S12-RANGE-CONSUMER-BRAND":
        research, forward, share_basis = _build_range_path(parent)
        _persist_s11(parent, {})
        return _finish_status_case(
            parent,
            research,
            forward,
            share_basis,
            valuation_input={},
            probability_input=None,
        )
    if case_id == "S12-PARTIAL-RETAIL":
        research, forward, share_basis = _build_forward_path(
            parent,
            "RETAIL",
            probabilities=(None, None, None),
        )
        _add_dcf_evidence(parent)
        _persist_s11(parent, _s11_input(parent, full=False))
        return _finish_status_case(
            parent,
            research,
            forward,
            share_basis,
            valuation_input=_valuation_input(),
            probability_input=None,
        )
    if case_id == "S12-MULTI-INDUSTRIAL":
        research, forward, share_basis = _build_forward_path(
            parent,
            "INDUSTRIAL",
            probabilities=(0.20, 0.50, 0.30),
        )
        _add_s11_evidence(parent)
        _persist_s11(parent, _s11_input(parent, full=True))
        return _finish_status_case(
            parent,
            research,
            forward,
            share_basis,
            valuation_input=_valuation_input(),
            probability_input=_probability_input(),
        )
    raise ValueError(f"Unknown frozen S12 status case: {case_id}")


def build_guard_case(guard_id: str) -> dict[str, Any]:
    if guard_id == "S12-GUARD-INDEPENDENT-ONLY":
        parent = _base_parent(guard_id)
        research, forward, share_basis = _build_range_path(parent)
        _add_dcf_evidence(parent)
        _persist_s11(parent, _s11_input(parent, full=False))
        return _finish_status_case(
            parent,
            research,
            forward,
            share_basis,
            valuation_input={},
            probability_input=None,
        )
    if guard_id == "S12-GUARD-FORWARD-ONLY":
        parent = _base_parent(guard_id)
        research, forward, share_basis = _build_forward_path(
            parent,
            "SUBSCRIPTION_SOFTWARE",
            probabilities=(None, None, None),
        )
        _persist_s11(parent, {})
        return _finish_status_case(
            parent,
            research,
            forward,
            share_basis,
            valuation_input=_valuation_input(),
            probability_input=None,
        )
    if guard_id == "S12-GUARD-MULTI-WITHOUT-HORIZON":
        parent = _base_parent(guard_id)
        research, forward, share_basis = _build_forward_path(
            parent,
            "INDUSTRIAL",
            probabilities=(None, None, None),
        )
        _add_s11_evidence(parent)
        _persist_s11(parent, _s11_input(parent, full=True))
        return _finish_status_case(
            parent,
            research,
            forward,
            share_basis,
            valuation_input=_incomplete_valuation_input(),
            probability_input=None,
        )
    raise ValueError(f"Unknown S12 guard case: {guard_id}")


def _validation_errors(result: dict[str, Any]) -> list[str]:
    parent = result["parent"]
    errors: list[str] = []
    errors.extend(validate_forward_valuation_contract(parent))
    errors.extend(validate_valuation_cross_check_contract(parent))
    errors.extend(validate_probability_governance(parent))
    errors.extend(validate_shared_valuation_contract(parent))
    return _unique(errors)


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if manifest.get("phase") != "C" or manifest.get("session") != "S12":
        errors.append("Manifest must identify Phase C / S12.")
    if manifest.get("pre_run_commit") != (
        "2a3eeaee1abb2d536f4f36001dc7ef5f0caee229"
    ):
        errors.append("The S12 pre-run commit is not the frozen S11 acceptance baseline.")
    modules = [
        row.get("business_model")
        for row in manifest.get("controlled_business_model_cases", [])
    ]
    if modules != list(DRIVER_MODULE_REGISTRY):
        errors.append("Frozen S12 driver-module order does not match the registry.")
    status_cases = [
        (row.get("case_id"), row.get("expected_status"))
        for row in manifest.get("valuation_status_cases", [])
    ]
    if status_cases != [
        ("S12-RANGE-CONSUMER-BRAND", "RANGE_ONLY"),
        ("S12-PARTIAL-RETAIL", "PARTIALLY_VALIDATED"),
        ("S12-MULTI-INDUSTRIAL", "MULTI_METHOD_VALIDATED"),
    ]:
        errors.append("Frozen S12 valuation status cases were changed.")
    if manifest.get("first_run_policy") != {
        "preserve_first_output": True,
        "do_not_replace_case_after_failure": True,
        "record_all_failures": True,
        "fix_only_shared_logic": True,
        "rerun_entire_matrix_after_any_fix": True,
    }:
        errors.append("Frozen S12 first-run policy was changed.")
    return errors


def _run_driver_case(module: str) -> dict[str, Any]:
    parent = _base_parent(f"S12-MODULE-{module}")
    research = _forward_research(module)
    parent["valuation_contract"] = copy.deepcopy(
        research["valuation_contract"]
    )
    forward = build_forward_valuation_contract(parent, research)
    parent["forward_valuation_contract"] = forward
    share_basis = build_share_count_basis(parent, research, forward)
    errors = validate_forward_valuation_contract(parent)
    if forward.get("status") != "VALIDATED":
        errors.append(f"forward status={forward.get('status')}")
    if share_basis.get("forward_share_count_bridge_status") != "COMPLETED":
        errors.append(
            "forward share bridge status="
            f"{share_basis.get('forward_share_count_bridge_status')}"
        )
    if forward.get("driver_module") != module:
        errors.append("driver module changed in shared output")
    return {
        "case_id": f"S12-MODULE-{module}",
        "fixture_classification": SYNTHETIC_LABEL,
        "business_model": module,
        "status": "PASS" if not errors else "FAIL",
        "forward_status": forward.get("status"),
        "share_bridge_status": share_basis.get(
            "forward_share_count_bridge_status"
        ),
        "scenario_count": len(forward.get("scenarios", [])),
        "errors": _unique(errors),
    }


def _status_case_result(
    case: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    expected = str(case.get("expected_status"))
    actual = str(result["scope"].get("status"))
    outputs = result["valuation_contract"].get("outputs", {})
    errors = _validation_errors(result)
    if actual != expected:
        errors.append(f"expected status={expected}; actual status={actual}")
    price_status = outputs.get("price_sensitivity", {}).get("status")
    base_status = outputs.get("base_case_return", {}).get("status")
    weighted_status = outputs.get("probability_weighted_return", {}).get("status")
    if price_status != "VALIDATED":
        errors.append(f"price sensitivity status={price_status}")
    if expected == "RANGE_ONLY":
        if base_status != "NOT_EVALUATED" or weighted_status != "NOT_EVALUATED":
            errors.append("RANGE_ONLY exposed a formal return.")
    elif expected == "PARTIALLY_VALIDATED":
        if base_status != "VALIDATED" or weighted_status != "NOT_EVALUATED":
            errors.append("PARTIALLY_VALIDATED return permissions are incorrect.")
    elif expected == "MULTI_METHOD_VALIDATED":
        if base_status != "VALIDATED" or weighted_status != "VALIDATED":
            errors.append("MULTI_METHOD_VALIDATED return permissions are incorrect.")
    partner_status = outputs.get("partner_internal_return", {}).get("status")
    if partner_status != "DISABLED_PRIVATE_GATE_4_ONLY":
        errors.append("User Internal Return was not disabled.")
    prohibited_keys = {
        "target_price",
        "position_sizing",
        "portfolio_action",
        "trade_action",
    }
    leaked = sorted(prohibited_keys & set(result["valuation_contract"]))
    if leaked:
        errors.append(f"prohibited output keys present: {', '.join(leaked)}")
    return {
        "case_id": case.get("case_id"),
        "fixture_classification": SYNTHETIC_LABEL,
        "business_model": case.get("business_model"),
        "status": "PASS" if not errors else "FAIL",
        "expected_valuation_status": expected,
        "actual_valuation_status": actual,
        "s10_status": result["forward"].get("status"),
        "s11_status": result["s11"].get("status"),
        "s09_status": result["valuation_contract"].get("status"),
        "price_sensitivity_status": price_status,
        "base_case_return_status": base_status,
        "probability_weighted_return_status": weighted_status,
        "partner_internal_return_status": partner_status,
        "errors": _unique(errors),
    }


def _guard_case_result(
    guard_id: str,
    expected: str,
) -> dict[str, Any]:
    result = build_guard_case(guard_id)
    actual = str(result["scope"].get("status"))
    errors = _validation_errors(result)
    if actual != expected:
        errors.append(f"expected status={expected}; actual status={actual}")
    return {
        "case_id": guard_id,
        "fixture_classification": SYNTHETIC_LABEL,
        "status": "PASS" if not errors else "FAIL",
        "expected_valuation_status": expected,
        "actual_valuation_status": actual,
        "s10_status": result["forward"].get("status"),
        "s11_status": result["s11"].get("status"),
        "s09_status": result["valuation_contract"].get("status"),
        "errors": _unique(errors),
    }


def _real_contract_result(case: dict[str, Any]) -> dict[str, Any]:
    ticker = str(case.get("ticker"))
    path = REAL_CONTRACT_PATHS[ticker]
    errors: list[str] = []
    if not path.exists():
        return {
            "ticker": ticker,
            "status": "FAIL",
            "errors": [f"Missing frozen contract: {path}"],
        }
    contract = load_json(path)
    forward = build_forward_valuation_contract(contract, {})
    s11 = build_valuation_cross_check_contract(contract, {})
    share_basis = contract.get("share_count_basis", {})
    scope = build_valuation_scope_status(
        contract | {"valuation_cross_check_contract": s11},
        {},
        share_basis if isinstance(share_basis, dict) else {},
        {"formal_return_language_allowed": False},
        forward,
    )
    if forward.get("status") != "DRIVER_MODEL_NOT_AVAILABLE":
        errors.append(f"no-input S10 status={forward.get('status')}")
    if s11.get("status") != "NOT_PROVIDED":
        errors.append(f"no-input S11 status={s11.get('status')}")
    if s11.get("calculation_evidence_ids"):
        errors.append("no-input S11 created calculation evidence")
    if scope.get("status") != "RANGE_ONLY":
        errors.append(f"no-input valuation scope={scope.get('status')}")
    return {
        "ticker": ticker,
        "business_model": case.get("business_model"),
        "role": case.get("role"),
        "status": "PASS" if not errors else "FAIL",
        "contract_path": str(path.relative_to(REPO_ROOT)),
        "stored_schema_version": contract.get("schema_version"),
        "no_input_s10_status": forward.get("status"),
        "no_input_s11_status": s11.get("status"),
        "no_input_valuation_scope": scope.get("status"),
        "synthetic_valuation_backfill": False,
        "errors": errors,
    }


def _anti_hardcoding_result() -> dict[str, Any]:
    matrix = load_json(REGRESSION_ROOT / "cross_industry_matrix.json")
    matrix = copy.deepcopy(matrix)
    shared_files = list(matrix.get("shared_analytical_files", []))
    for path in (
        "user-demo/investment_decision_v2/scripts/forward_operating_model.py",
        "user-demo/investment_decision_v2/scripts/valuation_cross_checks.py",
    ):
        if path not in shared_files:
            shared_files.append(path)
    matrix["shared_analytical_files"] = shared_files
    return scan_fixture_specific_branches(matrix, REPO_ROOT)


def run_acceptance(
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    manifest_errors = validate_manifest(manifest)
    driver_results: list[dict[str, Any]] = []
    status_results: list[dict[str, Any]] = []
    guard_results: list[dict[str, Any]] = []
    real_results: list[dict[str, Any]] = []
    execution_errors: list[str] = []
    try:
        driver_results = [
            _run_driver_case(str(case["business_model"]))
            for case in manifest.get("controlled_business_model_cases", [])
        ]
        status_results = [
            _status_case_result(
                case,
                build_status_case(str(case["case_id"])),
            )
            for case in manifest.get("valuation_status_cases", [])
        ]
        guard_results = [
            _guard_case_result(case_id, expected)
            for case_id, expected in (
                ("S12-GUARD-INDEPENDENT-ONLY", "RANGE_ONLY"),
                ("S12-GUARD-FORWARD-ONLY", "RANGE_ONLY"),
                ("S12-GUARD-MULTI-WITHOUT-HORIZON", "PARTIALLY_VALIDATED"),
            )
        ]
        real_results = [
            _real_contract_result(case)
            for case in manifest.get("real_contract_observation_cases", [])
        ]
    except Exception as exc:  # pragma: no cover - diagnostic boundary
        execution_errors.append(f"{type(exc).__name__}: {exc}")
    anti_hardcoding = _anti_hardcoding_result()
    case_failures = [
        row
        for row in (
            driver_results + status_results + guard_results + real_results
        )
        if row.get("status") != "PASS"
    ]
    errors = [
        *manifest_errors,
        *execution_errors,
        *[
            f"{row.get('case_id') or row.get('ticker')}: "
            + "; ".join(row.get("errors", []))
            for row in case_failures
        ],
        *[
            (
                f"{row.get('file')}:{row.get('line')}: "
                f"fixture-specific {row.get('kind')} branch"
            )
            for row in anti_hardcoding.get("findings", [])
        ],
    ]
    try:
        reported_manifest_path = str(manifest_path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        reported_manifest_path = manifest_path.name
    return {
        "schema_version": "1.0.0",
        "document_type": "s12_valuation_cross_company_acceptance_result",
        "phase": "C",
        "session": "S12",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest_path": reported_manifest_path,
        "pre_run_commit": manifest.get("pre_run_commit"),
        "fixture_classification": SYNTHETIC_LABEL,
        "status": "PASS" if not errors else "FAIL",
        "manifest_validation": {
            "status": "PASS" if not manifest_errors else "FAIL",
            "errors": manifest_errors,
        },
        "driver_model_acceptance": driver_results,
        "valuation_status_acceptance": status_results,
        "status_guard_acceptance": guard_results,
        "real_contract_no_backfill_acceptance": real_results,
        "anti_hardcoding": anti_hardcoding,
        "summary": {
            "driver_cases": len(driver_results),
            "valuation_status_cases": len(status_results),
            "status_guard_cases": len(guard_results),
            "real_contract_cases": len(real_results),
            "failed_cases": len(case_failures),
        },
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_acceptance(args.manifest.resolve())
    serialized = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
