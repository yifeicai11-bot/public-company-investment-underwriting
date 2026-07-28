#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
INVESTMENT_ROOT = TEST_DIR.parent
SCRIPT_DIR = INVESTMENT_ROOT / "scripts"
REPO_ROOT = INVESTMENT_ROOT.parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from regression_governance import (  # noqa: E402
    MATRIX_PATH,
    TAXONOMY_PATH,
    assert_contract_safety,
    build_governance_report,
    classify_contract_outcomes,
    load_json,
    scan_fixture_specific_branches,
    validate_matrix,
    validate_taxonomy,
)
from run_company_regression import run, select_active_cases  # noqa: E402


ODFL_CONTRACT = (
    INVESTMENT_ROOT
    / "blind_tests"
    / "s05_odfl"
    / "post_fix"
    / "builder_output"
    / "odfl_old_dominion_freight_line_inc"
    / "step3"
    / "underwriting_output_contract.json"
)


class CrossIndustryRegressionGovernanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.matrix = load_json(MATRIX_PATH)
        cls.taxonomy = load_json(TAXONOMY_PATH)

    def test_governance_files_and_anti_hardcoding_scan_pass(self) -> None:
        report = build_governance_report(self.matrix, self.taxonomy, REPO_ROOT)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["anti_hardcoding"]["findings"], [])

    def test_taxonomy_has_all_six_safe_outcomes(self) -> None:
        report = validate_taxonomy(self.taxonomy)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(
            set(report["outcome_ids"]),
            {
                "VALIDATED_RESULT",
                "MISSING",
                "NOT_APPLICABLE",
                "SUPPRESSED",
                "WARNING",
                "HARD_STOP",
            },
        )
        index = {
            row["outcome_id"]: row
            for row in self.taxonomy["outcomes"]
        }
        self.assertTrue(index["HARD_STOP"]["blocks_formal_report"])
        self.assertFalse(index["WARNING"]["blocks_formal_report"])

    def test_matrix_distinguishes_active_from_planned_coverage(self) -> None:
        report = validate_matrix(self.matrix, self.taxonomy)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["active_case_count"], 6)
        self.assertEqual(report["active_industry_count"], 6)
        self.assertGreater(len(report["active_coverage_gaps"]), 0)
        for stress_id in report["active_coverage_gaps"]:
            self.assertEqual(
                report["coverage"][stress_id]["active_cases"],
                [],
            )
            self.assertGreater(
                len(report["coverage"][stress_id]["planned_cases"]),
                0,
            )

    def test_planned_slots_do_not_preselect_future_companies(self) -> None:
        planned = [
            row
            for row in self.matrix["cases"]
            if row["fixture_status"] == "PLANNED"
        ]
        self.assertGreater(len(planned), 0)
        for row in planned:
            self.assertIsNone(row["ticker"])
            self.assertIsNone(row["company_name"])
            self.assertEqual(row["fixture_role"], "planned_slot")
            self.assertIn("future session", row["selection_rule"])

    def test_unknown_ticker_subset_cannot_pass_as_zero_case_run(self) -> None:
        selected, unknown = select_active_cases(
            self.matrix,
            {"CROX", "NOT-A-FIXTURE"},
        )
        self.assertEqual([row["ticker"] for row in selected], ["CROX"])
        self.assertEqual(unknown, ["NOT-A-FIXTURE"])

    def test_unknown_ticker_run_fails_before_network_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = run(
                Path(tmp),
                tickers={"NOT-A-FIXTURE"},
                render_artifacts=False,
            )
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["active_case_count"], 0)
        self.assertIn("NOT-A-FIXTURE", report["errors"][0])

    def test_ast_scan_catches_fixture_specific_branch(self) -> None:
        matrix = copy.deepcopy(self.matrix)
        matrix["shared_analytical_files"] = ["shared.py"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "shared.py").write_text(
                "def analyze(ticker):\n"
                "    if ticker.upper() == 'CROX':\n"
                "        return 'special case'\n"
                "    return 'shared'\n",
                encoding="utf-8",
            )
            report = scan_fixture_specific_branches(matrix, root)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["findings"][0]["kind"], "if")
        self.assertIn("crox", report["findings"][0]["fixture_values"])

    def test_ast_scan_catches_indirect_fixture_configuration(self) -> None:
        matrix = copy.deepcopy(self.matrix)
        matrix["shared_analytical_files"] = ["shared.py"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "shared.py").write_text(
                "SPECIAL_CASES = {'CROX': {'risk': 'high'}}\n"
                "def analyze(ticker):\n"
                "    return SPECIAL_CASES.get(ticker, {})\n",
                encoding="utf-8",
            )
            report = scan_fixture_specific_branches(matrix, root)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(
            report["findings"][0]["kind"],
            "fixture_configuration",
        )
        self.assertIn("crox", report["findings"][0]["fixture_values"])

    def test_ast_scan_ignores_nonconditional_cli_example(self) -> None:
        matrix = copy.deepcopy(self.matrix)
        matrix["shared_analytical_files"] = ["shared.py"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "shared.py").write_text(
                "HELP = \"Ticker or company name, e.g. AAPL or Apple Inc.\"\n"
                "def analyze(ticker):\n"
                "    return ticker.upper()\n",
                encoding="utf-8",
            )
            report = scan_fixture_specific_branches(matrix, root)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["findings"], [])

    def test_contract_outcomes_preserve_missing_and_suppression(self) -> None:
        contract = {
            "contract_validation": {"status": "PASS"},
            "data_gate": {
                "prohibited_outputs": [
                    "expected_return",
                    "target_price",
                    "position_sizing",
                ]
            },
            "probability_weighted_return": None,
            "target_price": None,
            "position_sizing": None,
            "warnings": [
                {
                    "status": "MISSING",
                    "issue_class": "WARNING",
                }
            ],
            "hard_stops": [],
            "probability_validation": {
                "freshness_status": "NOT_APPLICABLE"
            },
        }
        self.assertEqual(
            classify_contract_outcomes(contract),
            {
                "VALIDATED_RESULT",
                "MISSING",
                "NOT_APPLICABLE",
                "SUPPRESSED",
                "WARNING",
            },
        )

    def test_hard_stop_is_classified_separately(self) -> None:
        contract = {
            "contract_validation": {"status": "FAIL"},
            "data_gate": {"prohibited_outputs": []},
            "warnings": [],
            "hard_stops": [
                {
                    "check_id": "P0-period-integrity",
                    "status": "FAIL",
                    "issue_class": "HARD_STOP",
                }
            ],
        }
        outcomes = classify_contract_outcomes(contract)
        self.assertIn("HARD_STOP", outcomes)
        self.assertNotIn("VALIDATED_RESULT", outcomes)

    def test_preserved_odfl_contract_passes_matrix_assertions(self) -> None:
        contract = json.loads(ODFL_CONTRACT.read_text(encoding="utf-8"))
        case = next(
            row
            for row in self.matrix["cases"]
            if row.get("ticker") == "ODFL"
        )
        self.assertEqual(assert_contract_safety(contract, case), [])


if __name__ == "__main__":
    unittest.main()
