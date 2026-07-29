#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
SCRIPT_DIR = TEST_DIR.parent / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from notes_events_controls import (  # noqa: E402
    NOTE_MODULE_ORDER,
    build_notes_and_events_assessment,
    index_financial_amendments,
    index_subsequent_events,
    link_assessment_evidence,
    supplier_finance_facts,
)


SELECTED = {
    "form": "10-Q",
    "filed": "2026-05-01",
    "period": "2026-03-31",
    "accession": "0000000000-26-000001",
    "url": "https://www.sec.gov/base.htm",
}

CORE_METRICS = {
    "current_debt",
    "long_term_debt",
    "operating_lease_current",
    "operating_lease_noncurrent",
    "accounts_receivable_net",
    "allowance_for_credit_losses_ar",
}

COMPLETE_NOTE_TEXT = """
Accounts receivable are evaluated for credit risk using an aging analysis and
customer concentration information. The allowance for credit losses includes
provisions and write-offs. Long-term debt includes senior notes and a revolving
credit facility. Contractual debt maturities include principal payments due in
2027. We were in compliance with all financial covenants and disclosed covenant
headroom under the facility. Operating lease liabilities are supported by
a schedule of future minimum lease payments. Our supplier finance program
obligation is included in accounts payable.
"""


def submissions(*extra: dict[str, str]) -> dict[str, object]:
    rows = [
        {
            "form": "10-Q",
            "filingDate": "2026-05-01",
            "reportDate": "2026-03-31",
            "accessionNumber": "0000000000-26-000001",
            "primaryDocument": "base.htm",
            "items": "",
        },
        *extra,
    ]
    recent = {
        key: [row.get(key, "") for row in rows]
        for key in (
            "form",
            "filingDate",
            "reportDate",
            "accessionNumber",
            "primaryDocument",
            "items",
        )
    }
    return {"cik": "0000000000", "filings": {"recent": recent}}


def supplier_facts_payload() -> dict[str, object]:
    return {
        "facts": {
            "us-gaap": {
                "SupplierFinanceProgramObligation": {
                    "units": {
                        "USD": [
                            {
                                "val": 125,
                                "end": "2026-03-31",
                                "filed": "2026-05-01",
                                "form": "10-Q",
                                "accn": "0000000000-26-000001",
                            }
                        ]
                    }
                }
            }
        }
    }


def assess(
    text: str = COMPLETE_NOTE_TEXT,
    *,
    submissions_payload: dict[str, object] | None = None,
    facts: dict[str, object] | None = None,
    metrics: set[str] | None = None,
    document_texts: dict[str, str] | None = None,
) -> dict[str, object]:
    return build_notes_and_events_assessment(
        submissions=submissions_payload or submissions(),
        companyfacts=facts or supplier_facts_payload(),
        selected_filing=SELECTED,
        filing_text=text,
        metric_names=metrics if metrics is not None else CORE_METRICS,
        document_texts=document_texts,
    )


class S07NoteModuleTests(unittest.TestCase):
    def test_complete_note_set_covers_all_required_modules(self) -> None:
        result = assess()
        modules = result["modules"]
        self.assertEqual(tuple(modules), NOTE_MODULE_ORDER)
        for module_id in (
            "debt",
            "leases",
            "covenants",
            "receivables",
            "bad_debt",
            "supplier_finance",
        ):
            self.assertEqual(modules[module_id]["status"], "VALIDATED", module_id)
        self.assertEqual(modules["amendments"]["status"], "NOT_APPLICABLE")
        self.assertEqual(modules["restatements"]["status"], "NOT_APPLICABLE")
        self.assertEqual(modules["subsequent_events"]["status"], "VALIDATED")

    def test_debt_requires_contractual_maturity_evidence(self) -> None:
        result = assess(text="Long-term debt includes a revolving credit facility.")
        debt = result["modules"]["debt"]
        self.assertEqual(debt["status"], "WARNING")
        self.assertEqual(debt["required_elements"]["contractual_maturity_schedule"], "MISSING")

    def test_lease_carrying_value_is_not_contractual_payment_schedule(self) -> None:
        result = assess(text="We report operating lease liabilities.")
        leases = result["modules"]["leases"]
        self.assertEqual(leases["status"], "WARNING")
        self.assertEqual(
            leases["required_elements"]["carrying_value_separated_from_contractual_payments"],
            "ENFORCED",
        )
        self.assertEqual(leases["required_elements"]["contractual_payment_schedule"], "MISSING")

    def test_covenant_compliance_without_headroom_is_warning(self) -> None:
        result = assess(
            text="The revolving credit facility has financial covenants. We were in compliance with all covenants."
        )
        covenant = result["modules"]["covenants"]
        self.assertEqual(covenant["status"], "WARNING")
        self.assertEqual(covenant["required_elements"]["compliance_statement"], "FOUND")
        self.assertEqual(
            covenant["required_elements"]["numerical_headroom_or_availability"],
            "MISSING",
        )

    def test_receivable_and_bad_debt_missing_are_not_zero(self) -> None:
        result = assess(text="", facts={"facts": {}}, metrics={"accounts_receivable_net"})
        self.assertEqual(result["modules"]["receivables"]["status"], "MISSING")
        bad_debt = result["modules"]["bad_debt"]
        self.assertEqual(bad_debt["status"], "MISSING")
        self.assertEqual(bad_debt["required_elements"]["missing_allowance_not_zero"], "ENFORCED")

    def test_supplier_finance_silence_is_missing_not_not_applicable(self) -> None:
        result = assess(text="", facts={"facts": {}}, metrics=set())
        supplier = result["modules"]["supplier_finance"]
        self.assertEqual(supplier["status"], "MISSING")
        self.assertEqual(
            supplier["required_elements"]["absence_not_assumed_not_applicable"],
            "ENFORCED",
        )

    def test_supplier_finance_requires_explicit_basis_for_not_applicable(self) -> None:
        result = assess(
            text="We do not have any supplier finance programs.",
            facts={"facts": {}},
            metrics=set(),
        )
        self.assertEqual(
            result["modules"]["supplier_finance"]["status"],
            "NOT_APPLICABLE",
        )

    def test_supplier_finance_fact_scan_is_taxonomy_generic(self) -> None:
        rows = supplier_finance_facts(
            {
                "facts": {
                    "custom-taxonomy": {
                        "SupplyChainFinanceObligation": {
                            "units": {
                                "EUR": [
                                    {
                                        "val": 7,
                                        "end": "2026-03-31",
                                        "filed": "2026-05-01",
                                        "form": "10-Q",
                                        "accn": "x",
                                    }
                                ]
                            }
                        }
                    }
                }
            },
            period_end="2026-03-31",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["taxonomy"], "custom-taxonomy")
        self.assertEqual(rows[0]["unit"], "EUR")


class S07AmendmentAndRestatementTests(unittest.TestCase):
    def test_same_period_amendment_index_does_not_capture_other_period(self) -> None:
        payload = submissions(
            {
                "form": "10-Q/A",
                "filingDate": "2026-05-10",
                "reportDate": "2026-03-31",
                "accessionNumber": "0000000000-26-000002",
                "primaryDocument": "amend.htm",
                "items": "",
            },
            {
                "form": "10-Q/A",
                "filingDate": "2026-05-11",
                "reportDate": "2025-12-31",
                "accessionNumber": "0000000000-26-000003",
                "primaryDocument": "old.htm",
                "items": "",
            },
        )
        rows = index_financial_amendments(payload, SELECTED)
        self.assertEqual([row["accession"] for row in rows], ["0000000000-26-000002"])

    def test_administrative_amendment_can_be_validated_without_overriding_financials(self) -> None:
        accession = "0000000000-26-000002"
        payload = submissions(
            {
                "form": "10-Q/A",
                "filingDate": "2026-05-10",
                "reportDate": "2026-03-31",
                "accessionNumber": accession,
                "primaryDocument": "amend.htm",
                "items": "",
            }
        )
        result = assess(
            submissions_payload=payload,
            document_texts={
                accession: "The sole purpose of this amendment is to include Part III. No changes were made to the financial statements."
            },
        )
        self.assertEqual(result["modules"]["amendments"]["status"], "VALIDATED")

    def test_financial_restatement_amendment_is_hard_stop(self) -> None:
        accession = "0000000000-26-000002"
        payload = submissions(
            {
                "form": "10-Q/A",
                "filingDate": "2026-05-10",
                "reportDate": "2026-03-31",
                "accessionNumber": accession,
                "primaryDocument": "amend.htm",
                "items": "",
            }
        )
        result = assess(
            submissions_payload=payload,
            document_texts={
                accession: "We are restating our previously issued financial statements, which should no longer be relied upon."
            },
        )
        self.assertEqual(result["status"], "HARD_STOP")
        self.assertEqual(result["modules"]["amendments"]["status"], "HARD_STOP")
        self.assertEqual(result["modules"]["restatements"]["status"], "HARD_STOP")
        issues = {row["check_id"]: row for row in result["validation_issues"]}
        self.assertEqual(issues["P0-filing-amendment-review"]["issue_class"], "HARD_STOP")
        self.assertEqual(issues["P0-filing-amendment-review"]["status"], "FAIL")

    def test_restatement_language_in_selected_filing_requires_period_review(self) -> None:
        result = assess(
            text=COMPLETE_NOTE_TEXT
            + " The comparative table contains restated amounts for an immaterial error correction."
        )
        self.assertEqual(result["modules"]["restatements"]["status"], "WARNING")


class S07SubsequentEventTests(unittest.TestCase):
    def test_event_index_uses_strictly_later_filing_date(self) -> None:
        payload = submissions(
            {
                "form": "8-K",
                "filingDate": "2026-05-01",
                "reportDate": "2026-05-01",
                "accessionNumber": "same-day",
                "primaryDocument": "same.htm",
                "items": "1.01",
            },
            {
                "form": "8-K",
                "filingDate": "2026-05-02",
                "reportDate": "2026-05-02",
                "accessionNumber": "later",
                "primaryDocument": "later.htm",
                "items": "1.01",
            },
        )
        rows = index_subsequent_events(payload, "2026-05-01")
        self.assertEqual([row["accession"] for row in rows], ["later"])

    def test_material_event_is_warning_and_classified(self) -> None:
        accession = "0000000000-26-000004"
        payload = submissions(
            {
                "form": "8-K",
                "filingDate": "2026-05-12",
                "reportDate": "2026-05-12",
                "accessionNumber": accession,
                "primaryDocument": "event.htm",
                "items": "1.01, 2.03",
            }
        )
        result = assess(
            submissions_payload=payload,
            document_texts={
                accession: "The company entered into an amended and restated credit agreement to refinance its term loan."
            },
        )
        event_module = result["modules"]["subsequent_events"]
        self.assertEqual(event_module["status"], "WARNING")
        event = result["subsequent_event_filings"][0]
        self.assertIn("material_agreement", event["event_categories"])
        self.assertIn("refinancing", event["event_categories"])
        self.assertEqual(
            event_module["required_elements"]["events_not_mixed_into_historical_balances"],
            "ENFORCED",
        )

    def test_non_reliance_event_is_hard_stop(self) -> None:
        accession = "0000000000-26-000005"
        payload = submissions(
            {
                "form": "8-K",
                "filingDate": "2026-05-15",
                "reportDate": "2026-05-15",
                "accessionNumber": accession,
                "primaryDocument": "nonreliance.htm",
                "items": "4.02",
            }
        )
        result = assess(submissions_payload=payload)
        self.assertEqual(result["status"], "HARD_STOP")
        self.assertEqual(result["modules"]["subsequent_events"]["status"], "HARD_STOP")
        self.assertEqual(result["modules"]["restatements"]["status"], "HARD_STOP")

    def test_evidence_ids_are_linked_to_modules_and_issues(self) -> None:
        result = assess()
        evidence_rows = result.pop("_evidence_rows")
        ids = {
            row["metric_name"]: f"EVID-{index:03d}"
            for index, row in enumerate(evidence_rows, start=1)
        }
        link_assessment_evidence(result, ids)
        debt = result["modules"]["debt"]
        self.assertEqual(debt["evidence_ids"], [ids["note_debt_disclosure"]])
        issues = {row["check_id"]: row for row in result["validation_issues"]}
        self.assertEqual(
            issues["P1-note-debt"]["evidence_ids"],
            debt["evidence_ids"],
        )

    def test_fixture_set_exercises_every_safe_status(self) -> None:
        observed = set(assess()["safe_outcomes_observed"])
        observed.update(assess(text="", facts={"facts": {}}, metrics=set())["safe_outcomes_observed"])
        observed.update(
            assess(text="Long-term debt includes a revolving credit facility.")[
                "safe_outcomes_observed"
            ]
        )
        accession = "0000000000-26-000006"
        hard_stop = assess(
            submissions_payload=submissions(
                {
                    "form": "8-K",
                    "filingDate": "2026-05-20",
                    "reportDate": "2026-05-20",
                    "accessionNumber": accession,
                    "primaryDocument": "default.htm",
                    "items": "2.04",
                }
            )
        )
        observed.update(hard_stop["safe_outcomes_observed"])
        self.assertEqual(
            observed,
            {"VALIDATED", "MISSING", "NOT_APPLICABLE", "WARNING", "HARD_STOP"},
        )


if __name__ == "__main__":
    unittest.main()
