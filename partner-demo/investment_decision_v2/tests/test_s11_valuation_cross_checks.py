#!/usr/bin/env python3
"""S11 valuation cross-check and probability-governance acceptance tests."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from valuation_cross_checks import (  # noqa: E402
    build_probability_governance,
    build_valuation_cross_check_contract,
    validate_probability_governance,
    validate_valuation_cross_check_contract,
    valuation_cross_check_calculation_records,
)
from render_public_company_artifacts import (  # noqa: E402
    peer_valuation_html,
    valuation_cross_checks_html,
)


class S11Fixture:
    @staticmethod
    def evidence(
        evidence_id: str,
        value: float,
        *,
        as_of_date: str = "2026-07-31",
        currency: str = "USD",
        unit: str = "USD",
        evidence_class: str = "FACT",
        source_level: int = 1,
        metric_name: str | None = None,
        publication_date: str | None = None,
        period_end: str | None = None,
    ) -> dict[str, object]:
        return {
            "evidence_id": evidence_id,
            "metric_name": metric_name or evidence_id.lower(),
            "value": value,
            "currency": currency,
            "unit": unit,
            "evidence_class": evidence_class,
            "validation_status": "PASS",
            "as_of_date": as_of_date,
            "period_end": period_end or as_of_date,
            "publication_date": publication_date or as_of_date,
            "source_level": source_level,
        }

    @classmethod
    def parent(cls) -> dict[str, object]:
        records = [
            cls.evidence(
                "EV-MARKET-CAP",
                1000.0,
                metric_name="market_cap_point_in_time",
            ),
            cls.evidence(
                "EV-ENTERPRISE-VALUE",
                1200.0,
                metric_name="enterprise_value_proxy",
            ),
            cls.evidence("EV-CONTEXT", 1.0, unit="PURE", currency=""),
            cls.evidence("EV-NET-DEBT", 200.0),
            cls.evidence("EV-NONOPERATING", 0.0),
            cls.evidence("EV-MINORITY", 0.0),
            cls.evidence(
                "EV-SHARES",
                100.0,
                currency="",
                unit="SHARES",
                metric_name="shares_outstanding_point_in_time",
            ),
            cls.evidence(
                "EV-BASE-PRICE",
                12.0,
                currency="USD",
                unit="USD/SHARE",
                evidence_class="CALC",
                source_level=0,
                metric_name="scenario_base_implied_price",
            ),
        ]
        for label, capital, fundamental in (
            ("SUBJECT", 1000.0, 100.0),
            ("PEER-A", 800.0, 100.0),
            ("PEER-B", 1000.0, 100.0),
            ("PEER-C", 1200.0, 100.0),
        ):
            records.extend(
                [
                    cls.evidence(f"EV-{label}-CAPITAL", capital),
                    cls.evidence(
                        f"EV-{label}-FCF",
                        fundamental,
                        period_end="2027-07-31",
                        metric_name=(
                            "forward_fcf_comparison"
                            if label == "SUBJECT"
                            else None
                        ),
                    ),
                ]
            )
        for index, (as_of_date, capital) in enumerate(
            (
                ("2021-07-31", 700.0),
                ("2022-07-31", 800.0),
                ("2023-07-31", 900.0),
                ("2024-07-31", 1100.0),
                ("2025-07-31", 1300.0),
            ),
            start=1,
        ):
            records.extend(
                [
                    cls.evidence(
                        f"EV-HIST-{index}-CAPITAL",
                        capital,
                        as_of_date=as_of_date,
                        publication_date=as_of_date,
                    ),
                    cls.evidence(
                        f"EV-HIST-{index}-FCF",
                        100.0,
                        as_of_date=as_of_date,
                        publication_date=as_of_date,
                        period_end=f"{int(as_of_date[:4]) + 1}-07-31",
                    ),
                ]
            )
        return {
            "schema_version": "5.1.0",
            "valuation": {
                "price": 10.0,
                "price_currency": "USD",
                "price_date": "2026-07-31",
                "market_cap": 1000.0,
                "enterprise_value_proxy": 1200.0,
                "shares": 100.0,
            },
            "report_dates": {"market_price_date": "2026-07-31"},
            "scenarios": [
                {"name": "Bear", "implied_price": 8.0, "probability": 0.2},
                {"name": "Base", "implied_price": 12.0, "probability": 0.5},
                {"name": "Bull", "implied_price": 16.0, "probability": 0.3},
            ],
            "evidence_records": records,
        }

    @staticmethod
    def observation(
        label: str,
        capital: float,
        fundamental: float,
        *,
        as_of_date: str = "2026-07-31",
        fiscal_period_end: str = "2027-07-31",
    ) -> dict[str, object]:
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
            "capital_evidence_ids": [f"EV-{label}-CAPITAL"],
            "fundamental_evidence_ids": [f"EV-{label}-FCF"],
        }

    @classmethod
    def cross_check_input(cls) -> dict[str, object]:
        history = []
        for index, (as_of_date, capital) in enumerate(
            (
                ("2021-07-31", 700.0),
                ("2022-07-31", 800.0),
                ("2023-07-31", 900.0),
                ("2024-07-31", 1100.0),
                ("2025-07-31", 1300.0),
            ),
            start=1,
        ):
            history.append(
                cls.observation(
                    f"HIST-{index}",
                    capital,
                    100.0,
                    as_of_date=as_of_date,
                    fiscal_period_end=f"{int(as_of_date[:4]) + 1}-07-31",
                )
            )
        judgment = {
            "evidence_class": "JUDGMENT",
            "evidence_ids": ["EV-CONTEXT"],
            "reviewed_by": "Model Owner",
            "rationale": "Explicit analyst assumption supported by the dated operating evidence.",
        }
        return {
            "status": "VALIDATED",
            "as_of_date": "2026-07-31",
            "reviewed_by": "Valuation Reviewer",
            "peer_comparison": {
                "status": "VALIDATED",
                "as_of_date": "2026-07-31",
                "selection_rationale": "Comparable cash-flow definitions and operating models.",
                "reviewed_by": "Peer Reviewer",
                "minimum_comparable_peers": 3,
                "subject_metrics": [
                    cls.observation("SUBJECT", 1000.0, 100.0)
                ],
                "peers": [
                    {
                        "ticker": ticker,
                        "business_model_fit": "COMPARABLE",
                        "metrics": [cls.observation(label, capital, 100.0)],
                    }
                    for ticker, label, capital in (
                        ("PA", "PEER-A", 800.0),
                        ("PB", "PEER-B", 1000.0),
                        ("PC", "PEER-C", 1200.0),
                    )
                ],
            },
            "historical_valuation": {
                "status": "VALIDATED",
                "as_of_date": "2026-07-31",
                "reviewed_by": "History Reviewer",
                "comparability_rationale": "Same NTM FCF definition through the tested history.",
                "minimum_observations": 5,
                "minimum_span_days": 365,
                "current_observation": cls.observation(
                    "SUBJECT", 1000.0, 100.0
                ),
                "observations": history,
            },
            "reverse_valuation": {
                "status": "VALIDATED",
                "as_of_date": "2026-07-31",
                "method": "EQUITY_FCF_MULTIPLE",
                "capital_evidence_ids": ["EV-MARKET-CAP"],
                "selected_reference": {
                    "value": 10.0,
                    **judgment,
                },
                "reference_basis": {
                    "metric": "P/FCF",
                    "currency": "USD",
                    "period_basis": "NTM",
                    "accounting_definition": "MARKET_CAP/NTM_CFO_MINUS_CAPEX",
                },
                "metric_period": {
                    "status": "VALIDATED",
                    "period_type": "FORWARD_METRIC",
                    "start_date": "2026-08-01",
                    "end_date": "2027-07-31",
                },
                "comparison_metric": {
                    "value": 100.0,
                    "metric_name": "forward_fcf_comparison",
                    "currency": "USD",
                    "period_basis": "NTM",
                    "accounting_definition": "MARKET_CAP/NTM_CFO_MINUS_CAPEX",
                    "evidence_ids": ["EV-SUBJECT-FCF"],
                },
            },
            "independent_cross_check": {
                "status": "VALIDATED",
                "as_of_date": "2026-07-31",
                "method": "DISCOUNTED_CASH_FLOW_GORDON_GROWTH",
                "cash_flow_basis": "UNLEVERED_FCFF",
                "discount_rate_basis": "WACC",
                "reviewed_by": "DCF Reviewer",
                "forecast_cash_flows": [
                    {
                        "year_index": year,
                        "period_end": f"{2026 + year}-07-31",
                        "value": value,
                        "currency": "USD",
                        "unit": "USD",
                        **judgment,
                    }
                    for year, value in ((1, 100.0), (2, 110.0), (3, 120.0))
                ],
                "discount_rate": {
                    "value": 0.10,
                    "unit": "RATIO",
                    **judgment,
                },
                "terminal_growth": {
                    "value": 0.03,
                    "unit": "RATIO",
                    **judgment,
                },
                "net_debt": {
                    "value": 200.0,
                    "currency": "USD",
                    "unit": "USD",
                    "evidence_class": "FACT",
                    "evidence_ids": ["EV-NET-DEBT"],
                    "reviewed_by": "DCF Reviewer",
                },
                "non_operating_assets": {
                    "value": 0.0,
                    "currency": "USD",
                    "unit": "USD",
                    "evidence_class": "FACT",
                    "evidence_ids": ["EV-NONOPERATING"],
                    "reviewed_by": "DCF Reviewer",
                },
                "minority_interest": {
                    "value": 0.0,
                    "currency": "USD",
                    "unit": "USD",
                    "evidence_class": "FACT",
                    "evidence_ids": ["EV-MINORITY"],
                    "reviewed_by": "DCF Reviewer",
                },
                "shares": {
                    "value": 100.0,
                    "currency": "SHARES",
                    "unit": "SHARES",
                    "evidence_class": "FACT",
                    "evidence_ids": ["EV-SHARES"],
                    "reviewed_by": "DCF Reviewer",
                },
                "share_basis": {
                    "status": "VALIDATED",
                    "basis_type": "POINT_IN_TIME_OUTSTANDING",
                    "basis_date": "2026-07-31",
                    "rationale": (
                        "Use the dated point-in-time outstanding share count "
                        "for this independent current-value cross-check."
                    ),
                    "reviewed_by": "DCF Reviewer",
                },
                "sensitivity": {
                    "discount_rate_step": 0.01,
                    "terminal_growth_step": 0.005,
                    "evidence_class": "JUDGMENT",
                    "evidence_ids": ["EV-CONTEXT"],
                    "rationale": (
                        "Test a symmetric, decision-relevant rate and "
                        "terminal-growth range."
                    ),
                    "reviewed_by": "DCF Reviewer",
                },
            },
            "method_agreement": {
                "tolerance": {
                    "value": 0.25,
                    "unit": "RATIO",
                    **judgment,
                }
            },
        }

    @staticmethod
    def probability_input() -> dict[str, object]:
        return {
            "status": "VALIDATED",
            "method_type": "SCENARIO_JUDGMENT",
            "methodology": "Allocate weights from explicit operating signposts and test alternative distributions.",
            "method_details": {
                "allocation_rationale": "Base has the strongest current operating support.",
                "sensitivity_completed": True,
            },
            "evidence_ids": ["EV-CONTEXT"],
            "scenario_rationales": {
                "Bear": "Demand and cash conversion miss the central case.",
                "Base": "Operating evidence remains near the central case.",
                "Bull": "Demand and cash conversion exceed the central case.",
            },
            "as_of_date": "2026-07-31",
            "probability_expiration_review_date": "2026-10-01",
            "review_triggers": ["NEW_EARNINGS_OR_GUIDANCE"],
            "reviewed_by": "Probability Owner",
            "approval": {
                "status": "APPROVED",
                "approved_by": "Independent Research Reviewer",
                "approval_date": "2026-07-31",
                "approval_scope": "PROBABILITY_METHODOLOGY_AND_WEIGHTS",
                "independent_research_review": True,
            },
            "sensitivity_cases": [
                {
                    "label": "Downside heavy",
                    "probabilities": {"Bear": 0.5, "Base": 0.35, "Bull": 0.15},
                },
                {
                    "label": "Central",
                    "probabilities": {"Bear": 0.2, "Base": 0.5, "Bull": 0.3},
                },
                {
                    "label": "Upside heavy",
                    "probabilities": {"Bear": 0.1, "Base": 0.3, "Bull": 0.6},
                },
            ],
        }


class S11ValuationCrossCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parent = S11Fixture.parent()
        self.supplied = S11Fixture.cross_check_input()

    def test_full_contract_is_multi_method_validated(self) -> None:
        result = build_valuation_cross_check_contract(self.parent, self.supplied)
        self.assertEqual(result["status"], "MULTI_METHOD_VALIDATED")
        self.assertTrue(
            all(value == "VALIDATED" for value in result["components"].values())
        )
        self.assertEqual(
            result["peer_comparison"]["metric_summaries"][0]["median"],
            10.0,
        )
        self.assertEqual(
            result["historical_valuation"]["summary"]["median"],
            9.0,
        )
        self.assertEqual(
            result["reverse_valuation"]["required_metric_value"],
            100.0,
        )
        self.assertEqual(
            len(result["independent_cross_check"]["sensitivity_table"]),
            9,
        )
        self.assertIn(
            result["method_agreement"]["status"],
            {"WITHIN_TOLERANCE", "DIVERGENT"},
        )
        self.assertEqual(
            result["method_agreement"][
                "s09_base_implied_price_evidence_ids"
            ],
            ["EV-BASE-PRICE"],
        )
        rendered = valuation_cross_checks_html(
            {"valuation_cross_check_contract": result}
        )
        self.assertIn("Multi-method validated / 多方法已验证", rendered)
        self.assertIn(
            "Point-in-time outstanding shares / 时点流通股数",
            rendered,
        )
        self.assertNotIn("MULTI_METHOD_VALIDATED", rendered)

    def test_peer_negative_fcf_is_suppressed(self) -> None:
        self.supplied["peer_comparison"]["peers"][0]["metrics"][0][
            "fundamental_value"
        ] = -100.0
        result = build_valuation_cross_check_contract(self.parent, self.supplied)
        row = result["peer_comparison"]["rows"][0]
        self.assertEqual(row["comparability_status"], "NOT_COMPARABLE")
        self.assertIn("negative_fcf", row["comparability_flags"])
        self.assertIsNone(
            result["peer_comparison"]["metric_summaries"][0]["median"]
        )
        rendered = peer_valuation_html(
            {"valuation_cross_check_contract": result}
        )
        self.assertIn("Suppressed / 已抑制", rendered)
        self.assertNotIn("> -8.0x<", rendered)

    def test_peer_period_currency_and_definition_mismatches_are_suppressed(self) -> None:
        row = self.supplied["peer_comparison"]["peers"][0]["metrics"][0]
        row["as_of_date"] = "2026-06-30"
        row["fiscal_period_end"] = "2025-12-31"
        row["currency"] = "EUR"
        row["accounting_definition"] = "ADJUSTED_FCF"
        result = build_valuation_cross_check_contract(self.parent, self.supplied)
        flags = result["peer_comparison"]["rows"][0]["comparability_flags"]
        self.assertIn("different_fiscal_period", flags)
        self.assertIn("currency_mismatch", flags)
        self.assertIn("accounting_definition_mismatch", flags)

    def test_peer_value_formula_mismatch_is_suppressed(self) -> None:
        self.supplied["peer_comparison"]["peers"][0]["metrics"][0]["value"] = 99.0
        result = build_valuation_cross_check_contract(self.parent, self.supplied)
        self.assertIn(
            "value_formula_mismatch",
            result["peer_comparison"]["rows"][0]["comparability_flags"],
        )

    def test_peer_fact_from_unapproved_source_level_is_suppressed(self) -> None:
        peer_capital = next(
            row
            for row in self.parent["evidence_records"]
            if row["evidence_id"] == "EV-PEER-A-CAPITAL"
        )
        peer_capital["source_level"] = 5
        result = build_valuation_cross_check_contract(self.parent, self.supplied)
        self.assertIn(
            "missing_or_mismatched_evidence",
            result["peer_comparison"]["rows"][0]["comparability_flags"],
        )

    def test_duplicate_peer_does_not_count_twice(self) -> None:
        duplicate = copy.deepcopy(
            self.supplied["peer_comparison"]["peers"][0]
        )
        self.supplied["peer_comparison"]["peers"].append(duplicate)
        result = build_valuation_cross_check_contract(self.parent, self.supplied)
        duplicate_rows = [
            row
            for row in result["peer_comparison"]["rows"]
            if row.get("ticker") == "PA"
        ]
        self.assertTrue(
            all(
                "duplicate_peer_metric" in row["comparability_flags"]
                for row in duplicate_rows
            )
        )
        self.assertEqual(
            result["peer_comparison"]["metric_summaries"][0][
                "ranking_status"
            ],
            "SUPPRESSED_INSUFFICIENT_COMPARABLE_PEERS",
        )

    def test_unsupported_period_bridge_marker_does_not_force_comparability(
        self,
    ) -> None:
        row = self.supplied["peer_comparison"]["peers"][0]["metrics"][0]
        row["as_of_date"] = "2026-06-30"
        row["fiscal_period_end"] = "2026-03-31"
        row["period_alignment_status"] = "VALIDATED_BRIDGE"
        result = build_valuation_cross_check_contract(self.parent, self.supplied)
        self.assertIn(
            "different_fiscal_period",
            result["peer_comparison"]["rows"][0]["comparability_flags"],
        )

    def test_historical_look_ahead_observation_is_suppressed(self) -> None:
        row = self.supplied["historical_valuation"]["observations"][0]
        row["as_of_date"] = "2027-07-31"
        result = build_valuation_cross_check_contract(self.parent, self.supplied)
        self.assertIn(
            "look_ahead_date",
            result["historical_valuation"]["observations"][0][
                "comparability_flags"
            ],
        )
        self.assertNotEqual(
            result["historical_valuation"]["status"],
            "VALIDATED",
        )

    def test_historical_short_series_is_suppressed(self) -> None:
        self.supplied["historical_valuation"]["observations"] = self.supplied[
            "historical_valuation"
        ]["observations"][:4]
        result = build_valuation_cross_check_contract(self.parent, self.supplied)
        self.assertEqual(
            result["historical_valuation"]["summary"]["comparison_status"],
            "SUPPRESSED_INSUFFICIENT_OR_INCOMPARABLE_HISTORY",
        )

    def test_historical_value_published_later_is_not_backfilled(self) -> None:
        historical_fcf = next(
            row
            for row in self.parent["evidence_records"]
            if row["evidence_id"] == "EV-HIST-1-FCF"
        )
        historical_fcf["publication_date"] = "2026-07-31"
        result = build_valuation_cross_check_contract(self.parent, self.supplied)
        first = result["historical_valuation"]["observations"][0]
        self.assertIn(
            "missing_or_mismatched_evidence",
            first["comparability_flags"],
        )
        self.assertEqual(
            result["historical_valuation"]["summary"][
                "comparison_status"
            ],
            "SUPPRESSED_INSUFFICIENT_OR_INCOMPARABLE_HISTORY",
        )

    def test_reverse_valuation_uses_authoritative_market_cap(self) -> None:
        self.supplied["reverse_valuation"]["capital_value"] = 5000.0
        result = build_valuation_cross_check_contract(self.parent, self.supplied)
        self.assertEqual(result["reverse_valuation"]["capital_value"], 1000.0)
        self.assertEqual(
            result["reverse_valuation"]["formula"],
            "authoritative_capital_value / selected_reference_multiple",
        )

    def test_reverse_capital_evidence_must_match_metric_and_date(self) -> None:
        market_cap = next(
            row
            for row in self.parent["evidence_records"]
            if row["evidence_id"] == "EV-MARKET-CAP"
        )
        market_cap["as_of_date"] = "2026-06-30"
        result = build_valuation_cross_check_contract(self.parent, self.supplied)
        self.assertEqual(result["reverse_valuation"]["status"], "INVALID")
        self.assertFalse(
            result["reverse_valuation"]["capital_evidence_ids"]
        )

    def test_enterprise_reverse_valuation_uses_exact_enterprise_evidence(
        self,
    ) -> None:
        reverse = self.supplied["reverse_valuation"]
        reverse["method"] = "ENTERPRISE_VALUE_EBITDA_MULTIPLE"
        reverse["capital_evidence_ids"] = ["EV-ENTERPRISE-VALUE"]
        reverse["selected_reference"]["value"] = 12.0
        reverse["reference_basis"] = {
            "metric": "EV/EBITDA",
            "currency": "USD",
            "period_basis": "NTM",
            "accounting_definition": "ENTERPRISE_VALUE/NTM_EBITDA",
        }
        reverse["comparison_metric"] = {
            "value": None,
            "metric_name": "",
            "evidence_ids": [],
        }
        result = build_valuation_cross_check_contract(self.parent, self.supplied)
        self.assertEqual(
            result["reverse_valuation"]["capital_basis"],
            "ENTERPRISE_VALUE",
        )
        self.assertEqual(
            result["reverse_valuation"]["capital_evidence_ids"],
            ["EV-ENTERPRISE-VALUE"],
        )
        self.assertEqual(
            result["reverse_valuation"]["required_metric_value"],
            100.0,
        )
        self.assertEqual(
            result["reverse_valuation"]["status"],
            "PARTIALLY_VALIDATED",
        )

    def test_reverse_reference_outside_validated_ranges_is_partial(self) -> None:
        self.supplied["reverse_valuation"]["selected_reference"]["value"] = 30.0
        result = build_valuation_cross_check_contract(self.parent, self.supplied)
        self.assertEqual(
            result["reverse_valuation"]["status"],
            "PARTIALLY_VALIDATED",
        )
        self.assertEqual(
            result["reverse_valuation"]["reference_support"]["status"],
            "NOT_SUPPORTED",
        )

    def test_reverse_reference_cannot_mix_accounting_or_period_basis(
        self,
    ) -> None:
        self.supplied["reverse_valuation"]["reference_basis"][
            "accounting_definition"
        ] = "MARKET_CAP/LTM_REPORTED_FCF"
        result = build_valuation_cross_check_contract(self.parent, self.supplied)
        reverse = result["reverse_valuation"]
        self.assertEqual(reverse["status"], "PARTIALLY_VALIDATED")
        self.assertEqual(
            reverse["reference_support"]["status"],
            "NOT_SUPPORTED",
        )
        self.assertTrue(
            reverse["reference_support"]["incompatible_reference_ranges"]
        )

    def test_dcf_rate_must_exceed_terminal_growth(self) -> None:
        self.supplied["independent_cross_check"]["discount_rate"]["value"] = 0.02
        result = build_valuation_cross_check_contract(self.parent, self.supplied)
        self.assertEqual(
            result["independent_cross_check"]["status"],
            "INVALID",
        )
        codes = {
            row["code"]
            for row in result["independent_cross_check"]["validation_issues"]
        }
        self.assertIn("S11_DCF_RATE_NOT_ABOVE_GROWTH", codes)

    def test_enterprise_dcf_rejects_levered_fcf_basis(self) -> None:
        self.supplied["independent_cross_check"][
            "cash_flow_basis"
        ] = "CFO_MINUS_CAPEX"
        result = build_valuation_cross_check_contract(self.parent, self.supplied)
        self.assertEqual(
            result["independent_cross_check"]["status"],
            "INVALID",
        )
        self.assertIn(
            "S11_DCF_CASH_FLOW_BASIS_INVALID",
            {
                row["code"]
                for row in result["independent_cross_check"][
                    "validation_issues"
                ]
            },
        )

    def test_dcf_does_not_infer_missing_zero(self) -> None:
        self.supplied["independent_cross_check"].pop("minority_interest")
        result = build_valuation_cross_check_contract(self.parent, self.supplied)
        self.assertEqual(
            result["independent_cross_check"]["status"],
            "INVALID",
        )
        self.assertIsNone(
            result["independent_cross_check"]["implied_price_range"]["central"]
        )

    def test_dcf_fact_line_requires_matching_fact_evidence(self) -> None:
        net_debt = next(
            row
            for row in self.parent["evidence_records"]
            if row["evidence_id"] == "EV-NET-DEBT"
        )
        net_debt["evidence_class"] = "CALC"
        result = build_valuation_cross_check_contract(self.parent, self.supplied)
        self.assertEqual(
            result["independent_cross_check"]["status"],
            "INVALID",
        )
        self.assertIn(
            "S11_MODEL_EVIDENCE_BINDING_FAILED",
            {
                row["code"]
                for row in result["independent_cross_check"][
                    "validation_issues"
                ]
            },
        )

    def test_dcf_fact_line_rejects_evidence_published_after_valuation_date(
        self,
    ) -> None:
        net_debt = next(
            row
            for row in self.parent["evidence_records"]
            if row["evidence_id"] == "EV-NET-DEBT"
        )
        net_debt["publication_date"] = "2026-08-01"
        result = build_valuation_cross_check_contract(self.parent, self.supplied)
        independent = result["independent_cross_check"]
        self.assertEqual(independent["status"], "INVALID")
        self.assertEqual(
            independent["net_debt"]["matching_evidence_ids"],
            [],
        )
        self.assertIn(
            "S11_MODEL_EVIDENCE_UNRESOLVED_OR_FUTURE",
            {row["code"] for row in independent["validation_issues"]},
        )

    def test_dcf_fact_line_rejects_unresolved_extra_evidence(self) -> None:
        self.supplied["independent_cross_check"]["net_debt"][
            "evidence_ids"
        ].append("EV-UNKNOWN")
        result = build_valuation_cross_check_contract(self.parent, self.supplied)
        self.assertEqual(
            result["independent_cross_check"]["status"],
            "INVALID",
        )
        self.assertIn(
            "S11_MODEL_EVIDENCE_UNRESOLVED_OR_FUTURE",
            {
                row["code"]
                for row in result["independent_cross_check"][
                    "validation_issues"
                ]
            },
        )

    def test_dcf_share_basis_is_mandatory(self) -> None:
        self.supplied["independent_cross_check"].pop("share_basis")
        result = build_valuation_cross_check_contract(self.parent, self.supplied)
        independent = result["independent_cross_check"]
        self.assertEqual(independent["status"], "INVALID")
        self.assertEqual(independent["share_basis"]["status"], "INVALID")
        self.assertIn(
            "S11_DCF_SHARE_BASIS_NOT_VALIDATED",
            {row["code"] for row in independent["validation_issues"]},
        )

    def test_dcf_share_basis_date_must_match_exact_share_evidence(
        self,
    ) -> None:
        self.supplied["independent_cross_check"]["share_basis"][
            "basis_date"
        ] = "2026-07-30"
        result = build_valuation_cross_check_contract(self.parent, self.supplied)
        independent = result["independent_cross_check"]
        self.assertEqual(independent["status"], "INVALID")
        self.assertEqual(
            independent["share_basis"]["matching_evidence_ids"],
            [],
        )

    def test_dcf_accepts_dated_forward_diluted_share_bridge(self) -> None:
        self.parent["evidence_records"].append(
            S11Fixture.evidence(
                "EV-FORWARD-SHARES",
                98.0,
                as_of_date="2027-07-31",
                publication_date="2026-07-31",
                period_end="2027-07-31",
                currency="",
                unit="SHARES",
                evidence_class="CALC",
                source_level=0,
                metric_name="forward_share_count_basis",
            )
        )
        shares = self.supplied["independent_cross_check"]["shares"]
        shares.update(
            {
                "value": 98.0,
                "evidence_class": "CALC",
                "evidence_ids": ["EV-FORWARD-SHARES"],
                "formula": "reported shares plus validated forward share bridge",
            }
        )
        self.supplied["independent_cross_check"]["share_basis"].update(
            {
                "basis_type": "FORWARD_DILUTED",
                "basis_date": "2027-07-31",
                "rationale": (
                    "Use the validated target-date diluted share bridge for "
                    "the independent per-share cross-check."
                ),
            }
        )
        result = build_valuation_cross_check_contract(self.parent, self.supplied)
        independent = result["independent_cross_check"]
        self.assertEqual(independent["status"], "VALIDATED")
        self.assertEqual(
            independent["share_basis"]["matching_evidence_ids"],
            ["EV-FORWARD-SHARES"],
        )

    def test_dcf_forecast_periods_must_be_annual_and_forward(self) -> None:
        self.supplied["independent_cross_check"]["forecast_cash_flows"][0][
            "period_end"
        ] = "2026-09-30"
        result = build_valuation_cross_check_contract(self.parent, self.supplied)
        self.assertEqual(
            result["independent_cross_check"]["status"],
            "INVALID",
        )
        self.assertIn(
            "S11_DCF_FORECAST_INTERVAL_INVALID",
            {
                row["code"]
                for row in result["independent_cross_check"][
                    "validation_issues"
                ]
            },
        )

    def test_dcf_sensitivity_steps_require_evidence_and_rationale(
        self,
    ) -> None:
        sensitivity = self.supplied["independent_cross_check"][
            "sensitivity"
        ]
        sensitivity["evidence_ids"] = []
        sensitivity["rationale"] = ""
        result = build_valuation_cross_check_contract(self.parent, self.supplied)
        self.assertEqual(
            result["independent_cross_check"]["status"],
            "INVALID",
        )
        self.assertIn(
            "S11_DCF_SENSITIVITY_NOT_VALIDATED",
            {
                row["code"]
                for row in result["independent_cross_check"][
                    "validation_issues"
                ]
            },
        )

    def test_missing_s11_calculation_evidence_is_detected(self) -> None:
        result = build_valuation_cross_check_contract(self.parent, self.supplied)
        persisted_parent = copy.deepcopy(self.parent)
        persisted_parent["valuation_cross_check_contract"] = result
        errors = validate_valuation_cross_check_contract(persisted_parent)
        self.assertTrue(
            any(
                "Missing or inconsistent S11 CALC evidence" in error
                for error in errors
            )
        )

    def test_s11_calculation_evidence_ids_are_stable(self) -> None:
        first = build_valuation_cross_check_contract(self.parent, self.supplied)
        second = build_valuation_cross_check_contract(self.parent, self.supplied)
        self.assertEqual(
            first["calculation_evidence_ids"],
            second["calculation_evidence_ids"],
        )

    def test_unexpected_s11_calculation_evidence_is_detected(self) -> None:
        result = build_valuation_cross_check_contract(self.parent, self.supplied)
        persisted_parent = copy.deepcopy(self.parent)
        persisted_parent["evidence_records"].extend(
            valuation_cross_check_calculation_records(
                result,
                persisted_parent,
            )
        )
        extra = copy.deepcopy(persisted_parent["evidence_records"][-1])
        extra["evidence_id"] = "EV-S11-UNEXPECTED"
        extra["metric_name"] = "s11_injected_output"
        persisted_parent["evidence_records"].append(extra)
        persisted_parent["valuation_cross_check_contract"] = result
        self.assertTrue(
            any(
                "Unexpected S11 CALC evidence" in error
                for error in validate_valuation_cross_check_contract(
                    persisted_parent
                )
            )
        )

    def test_persisted_contract_tampering_is_detected(self) -> None:
        result = build_valuation_cross_check_contract(self.parent, self.supplied)
        persisted_parent = copy.deepcopy(self.parent)
        persisted_parent["evidence_records"].extend(
            valuation_cross_check_calculation_records(
                result,
                persisted_parent,
            )
        )
        persisted_parent["valuation_cross_check_contract"] = result
        self.assertEqual(
            validate_valuation_cross_check_contract(persisted_parent),
            [],
        )
        persisted_parent["valuation_cross_check_contract"]["reverse_valuation"][
            "required_metric_value"
        ] = 999.0
        self.assertTrue(
            validate_valuation_cross_check_contract(persisted_parent)
        )

    def test_status_label_cannot_upgrade_partial_contract(self) -> None:
        self.supplied["peer_comparison"]["peers"] = []
        result = build_valuation_cross_check_contract(self.parent, self.supplied)
        result["status"] = "MULTI_METHOD_VALIDATED"
        persisted_parent = copy.deepcopy(self.parent)
        persisted_parent["evidence_records"].extend(
            valuation_cross_check_calculation_records(
                result,
                persisted_parent,
            )
        )
        persisted_parent["valuation_cross_check_contract"] = result
        self.assertTrue(
            validate_valuation_cross_check_contract(persisted_parent)
        )


class S11ProbabilityGovernanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parent = S11Fixture.parent()
        self.supplied = S11Fixture.probability_input()

    def build(self) -> dict[str, object]:
        return build_probability_governance(
            self.supplied,
            self.parent["scenarios"],
            self.parent["evidence_records"],
            "2026-07-31",
        )

    def test_probability_requires_method_evidence_sensitivity_and_independent_approval(
        self,
    ) -> None:
        result = self.build()
        self.assertEqual(result["status"], "VALIDATED")
        self.assertTrue(result["weighted_return_allowed"])
        self.assertEqual(
            set(result["sensitivity_categories"]),
            {"CENTRAL", "DOWNSIDE_HEAVY", "UPSIDE_HEAVY"},
        )

    def test_same_owner_approval_is_invalid(self) -> None:
        self.supplied["approval"]["approved_by"] = "Probability Owner"
        result = self.build()
        self.assertEqual(result["status"], "INVALID")
        self.assertFalse(result["weighted_return_allowed"])

    def test_case_variant_of_owner_is_not_independent(self) -> None:
        self.supplied["approval"]["approved_by"] = "probability owner"
        self.assertEqual(self.build()["status"], "INVALID")

    def test_approval_scope_is_mandatory(self) -> None:
        self.supplied["approval"]["approval_scope"] = "GENERAL_RESEARCH"
        self.assertEqual(self.build()["status"], "INVALID")

    def test_central_sensitivity_must_match_actual_probabilities(self) -> None:
        self.supplied["sensitivity_cases"][1]["probabilities"] = {
            "Bear": 0.25,
            "Base": 0.5,
            "Bull": 0.25,
        }
        result = self.build()
        self.assertEqual(result["status"], "INVALID")
        self.assertNotIn("CENTRAL", result["sensitivity_categories"])

    def test_expired_probability_is_stale(self) -> None:
        self.supplied["probability_expiration_review_date"] = "2026-07-31"
        result = build_probability_governance(
            self.supplied,
            self.parent["scenarios"],
            self.parent["evidence_records"],
            "2026-08-01",
        )
        self.assertEqual(result["status"], "STALE")

    def test_later_primary_evidence_supersedes_probability(self) -> None:
        self.parent["evidence_records"].append(
            S11Fixture.evidence(
                "EV-NEW-EARNINGS",
                1.0,
                as_of_date="2026-08-01",
                unit="PURE",
                currency="",
                publication_date="2026-08-01",
                source_level=2,
            )
        )
        result = build_probability_governance(
            self.supplied,
            self.parent["scenarios"],
            self.parent["evidence_records"],
            "2026-08-01",
        )
        self.assertEqual(result["status"], "STALE")
        self.assertEqual(result["freshness_status"], "SUPERSEDED")

    def test_probabilities_must_total_one(self) -> None:
        self.parent["scenarios"][0]["probability"] = 0.4
        self.assertEqual(self.build()["status"], "INVALID")

    def test_probability_evidence_must_be_external_source_level_one_to_four(
        self,
    ) -> None:
        context = next(
            row
            for row in self.parent["evidence_records"]
            if row["evidence_id"] == "EV-CONTEXT"
        )
        context["source_level"] = 5
        result = self.build()
        self.assertEqual(result["status"], "INVALID")
        self.assertFalse(result["weighted_return_allowed"])

    def test_probability_tampering_is_detected(self) -> None:
        result = self.build()
        parent = copy.deepcopy(self.parent)
        parent["probability_validation"] = result
        self.assertEqual(validate_probability_governance(parent), [])
        parent["probability_validation"]["status"] = "ILLUSTRATIVE"
        self.assertTrue(validate_probability_governance(parent))

    def test_weighted_return_permission_tampering_is_detected(self) -> None:
        result = self.build()
        result["weighted_return_allowed"] = False
        parent = copy.deepcopy(self.parent)
        parent["probability_validation"] = result
        self.assertTrue(validate_probability_governance(parent))

    def test_valid_probability_governance_cannot_override_incomplete_formal_return(
        self,
    ) -> None:
        result = self.build()
        self.assertEqual(result["status"], "VALIDATED")
        parent = copy.deepcopy(self.parent)
        parent["valuation_contract"] = {
            "outputs": {
                "probability_weighted_return": {
                    "status": "NOT_EVALUATED",
                }
            }
        }
        result["weighted_return_allowed"] = False
        result[
            "formal_probability_weighted_expected_return_status"
        ] = "NOT_EVALUATED"
        parent["probability_validation"] = result
        self.assertEqual(validate_probability_governance(parent), [])

        parent["probability_validation"]["weighted_return_allowed"] = True
        self.assertTrue(validate_probability_governance(parent))


if __name__ == "__main__":
    unittest.main()
