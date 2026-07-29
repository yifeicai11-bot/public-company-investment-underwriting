#!/usr/bin/env python3
"""Shared filing-note and subsequent-event controls for the SEC data engine."""

from __future__ import annotations

import re
from typing import Any, Iterable


S07_NOTES_EVENTS_CONTROL_VERSION = "1.1.0"

SAFE_STATUSES = {
    "VALIDATED",
    "MISSING",
    "NOT_APPLICABLE",
    "WARNING",
    "HARD_STOP",
}

NOTE_MODULE_ORDER = (
    "debt",
    "revolver",
    "leases",
    "covenants",
    "receivables",
    "bad_debt",
    "supplier_finance",
    "acquisitions",
    "amendments",
    "restatements",
    "subsequent_events",
)

MATERIAL_EVENT_ITEMS = {
    "1.01": "material_agreement",
    "1.02": "termination_of_material_agreement",
    "2.01": "acquisition_or_disposition",
    "2.03": "new_or_direct_financial_obligation",
    "2.05": "exit_or_disposal_plan",
    "2.06": "material_impairment",
    "3.02": "unregistered_equity_sale",
    "7.01": "regulation_fd_disclosure",
    "8.01": "other_material_event",
}

HARD_STOP_EVENT_ITEMS = {
    "1.03": "bankruptcy_or_receivership",
    "2.04": "triggering_event_or_acceleration",
    "4.02": "non_reliance_on_previously_issued_financial_statements",
}

EVENT_TEXT_PATTERNS: dict[str, tuple[str, ...]] = {
    "debt_issuance": (
        r"\bissued\s+(?:senior|subordinated|convertible)?\s*notes\b",
        r"\bnew\s+(?:term loan|credit facility|debt financing)\b",
    ),
    "refinancing": (
        r"\brefinanc(?:e|ed|ing)\b",
        r"\bamended and restated credit agreement\b",
        r"\brepaid.*(?:notes|term loan|credit facility)\b",
    ),
    "acquisition_or_disposition": (
        r"\bacqui(?:re|red|sition)\b",
        r"\bdisposition\b",
        r"\bdivest(?:ed|iture)?\b",
    ),
    "major_repurchase": (
        r"\baccelerated share repurchase\b",
        r"\brepurchase authorization\b",
        r"\bshare repurchase program\b",
    ),
    "guidance_change": (
        r"\b(?:raises?|lowers?|withdraws?|updates?)\s+(?:its\s+)?(?:financial\s+)?guidance\b",
        r"\boutlook\b",
    ),
    "covenant_or_default": (
        r"\bcovenant breach\b",
        r"\bevent of default\b",
        r"\bwaiver\b",
        r"\bforbearance\b",
    ),
}

NOTE_PATTERNS: dict[str, tuple[str, ...]] = {
    "debt": (
        r"\blong[- ]term debt\b",
        r"\bcredit facilit(?:y|ies)\b",
        r"\brevolving credit\b",
        r"\bborrowings\b",
        r"\bsenior notes\b",
    ),
    "debt_maturity": (
        r"\bdebt maturit(?:y|ies)\b",
        r"\bcurrent maturities of long[- ]term debt\b",
        r"\btotal maturities due after one year\b",
        r"\bprincipal payments? (?:due|required)\b",
        r"\bmatur(?:e|es|ing)\s+in\s+20\d{2}\b",
        r"\bcontractual maturit(?:y|ies)\b",
    ),
    "debt_amendment_or_waiver": (
        r"\bamended and restated (?:credit|loan|note) agreement\b",
        r"\b(?:credit|loan|note) agreement (?:was|has been) amended\b",
        r"\bdebt covenant waiver\b",
        r"\bforbearance agreement\b",
    ),
    "revolver": (
        r"\brevolving credit facilit(?:y|ies)\b",
        r"\brevolving facilit(?:y|ies)\b",
        r"\bcredit agreement\b",
        r"\basset[- ]based (?:lending |credit )?facilit(?:y|ies)\b",
    ),
    "revolver_capacity": (
        r"\baggregate commitments?\b",
        r"\bborrowing availability\b",
        r"\bavailable borrowing capacity\b",
        r"\bexcess availability\b",
        r"\boutstanding borrowings\b",
        r"\bletters? of credit\b",
    ),
    "revolver_maturity": (
        r"\b(?:revolving credit facility|revolving facility|credit agreement)\b.{0,240}\b(?:matures?|expires?|terminates?)\b",
        r"\b(?:matures?|expires?|terminates?)\b.{0,240}\b(?:revolving credit facility|revolving facility|credit agreement)\b",
    ),
    "revolver_restrictions": (
        r"\bborrowing base\b",
        r"\bspringing covenant\b",
        r"\bavailability block\b",
        r"\blender reserves?\b",
        r"\bconditions? to borrowing\b",
    ),
    "lease": (
        r"\boperating lease liabilit(?:y|ies)\b",
        r"\bfinance lease liabilit(?:y|ies)\b",
        r"\blease obligations?\b",
        r"\blease liabilities\b",
    ),
    "lease_schedule": (
        r"\bmaturit(?:y|ies) of (?:our )?lease liabilit(?:y|ies)\b",
        r"\bfuture minimum lease payments\b",
        r"\bundiscounted (?:lease )?payments\b",
        r"\bremaining lease payments\b",
    ),
    "covenant": (
        r"\bfinancial covenants?\b",
        r"\bcovenants? under\b",
        r"\bfixed charge coverage\b",
        r"\bleverage ratio\b",
        r"\bborrowing base\b",
    ),
    "covenant_compliance": (
        r"\b(?:was|were|are|remained) in compliance with\b",
        r"\bcomplied with all\b",
        r"\bno event of default\b",
    ),
    "covenant_headroom": (
        r"\b(?:covenant )?headroom\b",
        r"\bactual (?:leverage|coverage) ratio\b.{0,120}\b(?:maximum|minimum|required)\b",
        r"\b(?:leverage|coverage) ratio was [0-9.]+\b.{0,120}\b(?:maximum|minimum|required)\b",
    ),
    "receivable": (
        r"\baccounts receivable\b",
        r"\btrade receivables\b",
        r"\breceivables, net\b",
        r"\bcontract assets\b",
    ),
    "receivable_risk_detail": (
        r"\baging\b",
        r"\bpast due\b",
        r"\bcustomer concentration\b",
        r"\bcredit risk\b",
        r"\bunbilled receivables\b",
        r"\bfactoring\b",
        r"\bsecuritization\b",
    ),
    "bad_debt_methodology": (
        r"\ballowance for (?:credit losses|doubtful accounts)\b",
        r"\bexpected credit losses\b",
        r"\bcredit loss methodology\b",
        r"\bcurrent expected credit losses\b",
        r"\bCECL\b",
    ),
    "bad_debt_activity": (
        r"\bcredit loss expense\b",
        r"\bbad debt expense\b",
        r"\bwrite[- ]offs?\b",
        r"\brecoveries\b",
        r"\bprovision for (?:credit losses|doubtful accounts)\b",
    ),
    "supplier_finance": (
        r"\bsupplier finance programs?\b",
        r"\bsupply chain finance\b",
        r"\breverse factoring\b",
        r"\bstructured payable arrangements?\b",
    ),
    "supplier_finance_not_applicable": (
        r"\bwe do not (?:have|participate in|use) (?:a |any )?supplier finance programs?\b",
        r"\bno supplier finance program(?:s)?\b",
        r"\bdoes not (?:have|participate in|use) (?:a |any )?supplier finance programs?\b",
    ),
    "acquisition": (
        r"\bbusiness combinations?\b",
        r"\bacquisition(?:s)?\b",
        r"\bacquired (?:all|substantially all|a controlling|the outstanding|the business)\b",
        r"\bpurchase of (?:a |the )?business\b",
    ),
    "acquisition_terms": (
        r"\bpurchase price\b",
        r"\bpurchase consideration\b",
        r"\btotal consideration\b",
        r"\bcash consideration\b",
        r"\bconsideration transferred\b",
    ),
    "acquisition_accounting": (
        r"\bgoodwill\b",
        r"\bidentifiable intangible assets?\b",
        r"\bpurchase price allocation\b",
        r"\bpro forma (?:revenue|net income|results)\b",
        r"\bmeasurement period\b",
    ),
    "restatement_high_confidence": (
        r"\bshould no longer be relied upon\b",
        r"\bnon[- ]reliance on previously issued financial statements\b",
        r"\bwe (?:are restating|have restated) (?:our|the) (?:previously issued )?financial statements\b",
        r"\brestatement of previously issued financial statements\b",
    ),
    "restatement_incorporated": (
        r"\brestated financial statements\b",
        r"\brestated amounts\b",
        r"\bimmaterial error correction\b",
        r"\brevision of prior[- ]period financial statements\b",
    ),
    "administrative_amendment": (
        r"\bsole purpose of this amendment\b.{0,240}\bpart iii\b",
        r"\bamends? .* solely to include\b",
        r"\bdoes not amend or update .*financial statements\b",
        r"\bno changes? (?:have been|were) made to the financial statements\b",
    ),
}


def _normalized_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _patterns_found(text: str, patterns: Iterable[str]) -> list[str]:
    return [pattern for pattern in patterns if re.search(pattern, text, flags=re.I | re.S)]


def _snippet(text: str, patterns: Iterable[str], window: int = 260) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I | re.S)
        if match:
            start = max(0, match.start() - window)
            end = min(len(text), match.end() + window)
            return _normalized_text(text[start:end])
    return ""


def _recent_filing_rows(submissions: dict[str, Any]) -> list[dict[str, str]]:
    recent = submissions.get("filings", {}).get("recent", {})
    forms = list(recent.get("form", []))

    def value(key: str, index: int) -> str:
        values = recent.get(key, [])
        return str(values[index]) if index < len(values) and values[index] is not None else ""

    cik = str(submissions.get("cik", "")).lstrip("0")
    rows: list[dict[str, str]] = []
    for index, form in enumerate(forms):
        accession = value("accessionNumber", index)
        primary_doc = value("primaryDocument", index)
        accession_path = accession.replace("-", "")
        source_url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_path}/{primary_doc}"
            if cik and accession and primary_doc
            else ""
        )
        rows.append(
            {
                "form": str(form),
                "filing_date": value("filingDate", index),
                "report_date": value("reportDate", index),
                "items": value("items", index),
                "accession": accession,
                "primary_document": primary_doc,
                "source_url": source_url,
            }
        )
    return rows


def index_financial_amendments(
    submissions: dict[str, Any],
    selected_filing: dict[str, Any],
) -> list[dict[str, str]]:
    selected_form = str(selected_filing.get("form", "")).replace("/A", "")
    selected_period = str(selected_filing.get("period", ""))
    selected_filed = str(selected_filing.get("filed", ""))
    rows = []
    for row in _recent_filing_rows(submissions):
        if row["form"] != f"{selected_form}/A":
            continue
        if selected_period and row["report_date"] != selected_period:
            continue
        if selected_filed and row["filing_date"] < selected_filed:
            continue
        rows.append({**row, "review_status": "REVIEW_REQUIRED"})
    return sorted(rows, key=lambda row: (row["filing_date"], row["accession"]))


def index_subsequent_events(
    submissions: dict[str, Any],
    after_date: str,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for row in _recent_filing_rows(submissions):
        if row["form"] not in {"8-K", "8-K/A"}:
            continue
        if not row["filing_date"] or row["filing_date"] <= after_date:
            continue
        item_codes = sorted(
            {
                match.group(0)
                for match in re.finditer(r"\b\d\.\d{2}\b", row.get("items", ""))
            }
        )
        events.append(
            {
                **row,
                "item_codes": item_codes,
                "review_status": "REVIEW_REQUIRED",
            }
        )
    return sorted(events, key=lambda row: (row["filing_date"], row["accession"]))


def supplier_finance_facts(
    companyfacts: dict[str, Any],
    *,
    period_end: str,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for taxonomy, concepts in companyfacts.get("facts", {}).items():
        if not isinstance(concepts, dict):
            continue
        for tag, concept in concepts.items():
            normalized_tag = re.sub(r"[^a-z]", "", str(tag).lower())
            if "supplierfinance" not in normalized_tag and "supplychainfinance" not in normalized_tag:
                continue
            for unit, facts in concept.get("units", {}).items():
                for fact in facts:
                    if fact.get("end") != period_end:
                        continue
                    matches.append(
                        {
                            "taxonomy": taxonomy,
                            "tag": tag,
                            "unit": unit,
                            "value": fact.get("val"),
                            "period_end": fact.get("end", ""),
                            "filing_date": fact.get("filed", ""),
                            "form": fact.get("form", ""),
                            "accession": fact.get("accn", ""),
                        }
                    )
    matches.sort(key=lambda row: (row["filing_date"], row["tag"], row["unit"]))
    return matches


def acquisition_facts(
    companyfacts: dict[str, Any],
    *,
    selected_filing: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return one period-matched acquisition fact per taxonomy/tag/unit.

    The selected filing accession is preferred so a later filing cannot silently
    replace the period under review. If accession metadata is unavailable, only
    facts published no later than the selected filing are eligible.
    """

    period_end = str(selected_filing.get("period", ""))
    selected_accession = str(selected_filing.get("accession", ""))
    selected_filed = str(selected_filing.get("filed", ""))
    candidates: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for taxonomy, concepts in companyfacts.get("facts", {}).items():
        if not isinstance(concepts, dict):
            continue
        for tag, concept in concepts.items():
            normalized_tag = re.sub(r"[^a-z]", "", str(tag).lower())
            if not any(
                marker in normalized_tag
                for marker in (
                    "paymentstoacquirebusiness",
                    "businesscombination",
                    "acquisitionrelated",
                )
            ):
                continue
            for unit, facts in concept.get("units", {}).items():
                for fact in facts:
                    if fact.get("end") != period_end:
                        continue
                    accession = str(fact.get("accn", ""))
                    filing_date = str(fact.get("filed", ""))
                    if selected_accession and accession and accession != selected_accession:
                        continue
                    if selected_filed and filing_date and filing_date > selected_filed:
                        continue
                    key = (str(taxonomy), str(tag), str(unit))
                    candidates.setdefault(key, []).append(
                        {
                            "taxonomy": taxonomy,
                            "tag": tag,
                            "unit": unit,
                            "value": fact.get("val"),
                            "period_start": fact.get("start", ""),
                            "period_end": fact.get("end", ""),
                            "filing_date": filing_date,
                            "form": fact.get("form", ""),
                            "accession": accession,
                        }
                    )

    matches: list[dict[str, Any]] = []
    for rows in candidates.values():
        rows.sort(
            key=lambda row: (
                row["accession"] == selected_accession,
                row["filing_date"],
                row["period_start"],
            ),
            reverse=True,
        )
        matches.append(rows[0])
    matches.sort(key=lambda row: (row["taxonomy"], row["tag"], row["unit"]))
    return matches


def _evidence_row(
    metric_name: str,
    value: Any,
    selected_filing: dict[str, Any],
    *,
    source_url: str | None = None,
    source_location: str,
    source_tag: str,
    filing_type: str | None = None,
    filing_date: str | None = None,
    period_end: str | None = None,
    unit: str = "text",
    currency: str = "",
    confidence: str = "Medium",
    validation_status: str = "review-required",
) -> dict[str, Any]:
    return {
        "metric_name": metric_name,
        "value": value,
        "unit": unit,
        "currency": currency,
        "period_end": period_end or str(selected_filing.get("period", "")),
        "period_type": "filing-note",
        "fiscal_period": str(selected_filing.get("period", "")),
        "filing_type": filing_type or str(selected_filing.get("form", "")),
        "filing_date": filing_date or str(selected_filing.get("filed", "")),
        "source_location": source_location,
        "source_tag": source_tag,
        "source_url": source_url or str(selected_filing.get("url", "")),
        "confidence": confidence,
        "validation_status": validation_status,
    }


def _module(
    module_id: str,
    status: str,
    summary: str,
    *,
    required_elements: dict[str, str],
    evidence_metric_names: list[str] | None = None,
    missing_information: list[str] | None = None,
) -> dict[str, Any]:
    if status not in SAFE_STATUSES:
        raise ValueError(f"Unsupported note/event status: {status}")
    return {
        "module_id": module_id,
        "status": status,
        "summary": summary,
        "required_elements": required_elements,
        "evidence_metric_names": evidence_metric_names or [],
        "evidence_ids": [],
        "missing_information": missing_information or [],
    }


def _metric_present(metric_names: set[str], *names: str) -> bool:
    return any(name in metric_names for name in names)


def _build_note_modules(
    filing_text: str,
    selected_filing: dict[str, Any],
    metric_names: set[str],
    supplier_facts: list[dict[str, Any]],
    acquisition_fact_rows: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    modules: dict[str, dict[str, Any]] = {}
    evidence_rows: list[dict[str, Any]] = []

    debt_found = bool(_patterns_found(filing_text, NOTE_PATTERNS["debt"]))
    debt_maturity_found = bool(_patterns_found(filing_text, NOTE_PATTERNS["debt_maturity"]))
    debt_amendment_found = bool(
        _patterns_found(filing_text, NOTE_PATTERNS["debt_amendment_or_waiver"])
    )
    debt_balance_found = _metric_present(metric_names, "current_debt", "long_term_debt")
    debt_evidence: list[str] = []
    if debt_found:
        debt_evidence.append("note_debt_disclosure")
        evidence_rows.append(
            _evidence_row(
                "note_debt_disclosure",
                _snippet(filing_text, NOTE_PATTERNS["debt"]),
                selected_filing,
                source_location="Latest financial filing; debt/borrowings disclosure",
                source_tag="note-keyword:debt",
            )
        )
    debt_status = (
        "VALIDATED"
        if debt_balance_found
        and debt_found
        and debt_maturity_found
        and not debt_amendment_found
        else "WARNING"
        if debt_balance_found and debt_found
        else "MISSING"
    )
    modules["debt"] = _module(
        "debt",
        debt_status,
        (
            "Debt balance, note disclosure, and maturity language were located."
            if debt_status == "VALIDATED"
            else "Debt is present, but maturity evidence is incomplete or an amendment, waiver, or forbearance signal requires agreement-level review."
            if debt_status == "WARNING"
            else "A complete debt balance and note package was not located; absence is not treated as zero debt."
        ),
        required_elements={
            "carrying_value": "FOUND" if debt_balance_found else "MISSING",
            "note_disclosure": "FOUND" if debt_found else "MISSING",
            "contractual_maturity_schedule": "FOUND" if debt_maturity_found else "MISSING",
            "amendment_waiver_or_forbearance_signal_review": "SIGNAL_FOUND"
            if debt_amendment_found
            else "CLEAR",
        },
        evidence_metric_names=debt_evidence,
        missing_information=[
            label
            for label, found in (
                ("Debt carrying value", debt_balance_found),
                ("Debt note disclosure", debt_found),
                ("Contractual maturity schedule", debt_maturity_found),
            )
            if not found
        ],
    )

    revolver_text_found = bool(
        _patterns_found(filing_text, NOTE_PATTERNS["revolver"])
    )
    revolver_capacity_text_found = bool(
        _patterns_found(filing_text, NOTE_PATTERNS["revolver_capacity"])
    )
    revolver_maturity_found = bool(
        _patterns_found(filing_text, NOTE_PATTERNS["revolver_maturity"])
    )
    revolver_restrictions_found = bool(
        _patterns_found(filing_text, NOTE_PATTERNS["revolver_restrictions"])
    )
    revolver_commitment_found = _metric_present(
        metric_names,
        "facility_commitment",
    )
    revolver_usage_or_availability_found = _metric_present(
        metric_names,
        "facility_availability_reported",
        "facility_borrowings",
        "facility_letters_of_credit",
        "facility_lender_reserves",
    )
    revolver_metric_signal = _metric_present(
        metric_names,
        "facility_note_snippet",
        "facility_commitment",
        "facility_availability_reported",
        "facility_borrowings",
        "facility_letters_of_credit",
        "facility_lender_reserves",
    )
    revolver_evidence: list[str] = []
    if revolver_text_found:
        revolver_evidence.append("note_revolver_disclosure")
        evidence_rows.append(
            _evidence_row(
                "note_revolver_disclosure",
                _snippet(
                    filing_text,
                    NOTE_PATTERNS["revolver"]
                    + NOTE_PATTERNS["revolver_capacity"]
                    + NOTE_PATTERNS["revolver_maturity"],
                ),
                selected_filing,
                source_location="Latest financial filing; revolver or credit-facility disclosure",
                source_tag="note-keyword:revolver",
            )
        )
    revolver_signal = revolver_text_found or revolver_metric_signal
    if not filing_text and not revolver_metric_signal:
        revolver_status = "MISSING"
        revolver_summary = "The filing text was unavailable, so revolver applicability and terms could not be established."
    elif not revolver_signal:
        revolver_status = "NOT_APPLICABLE"
        revolver_summary = "The reviewed filing and structured liquidity evidence contained no revolver or committed credit-facility signal."
    elif (
        revolver_text_found
        and revolver_commitment_found
        and revolver_usage_or_availability_found
        and revolver_maturity_found
    ):
        revolver_status = "VALIDATED"
        revolver_summary = "Revolver disclosure, commitment, usage or availability, and maturity evidence were located."
    else:
        revolver_status = "WARNING"
        revolver_summary = "A revolver or credit-facility signal was located, but commitment, usage or availability, maturity, or restriction evidence is incomplete."
    modules["revolver"] = _module(
        "revolver",
        revolver_status,
        revolver_summary,
        required_elements={
            "facility_disclosure": "FOUND" if revolver_text_found else "MISSING",
            "commitment_or_capacity": "FOUND"
            if revolver_commitment_found or revolver_capacity_text_found
            else "MISSING",
            "borrowings_or_availability": "FOUND"
            if revolver_usage_or_availability_found or revolver_capacity_text_found
            else "MISSING",
            "maturity_or_expiration": "FOUND"
            if revolver_maturity_found
            else "MISSING",
            "borrowing_base_reserves_or_conditions": "FOUND"
            if revolver_restrictions_found
            else "MISSING",
            "availability_not_equated_to_covenant_headroom": "ENFORCED",
        },
        evidence_metric_names=revolver_evidence,
        missing_information=[]
        if revolver_status == "NOT_APPLICABLE"
        else [
            label
            for label, found in (
                ("Revolver or credit-facility disclosure", revolver_text_found),
                (
                    "Commitment or stated capacity",
                    revolver_commitment_found or revolver_capacity_text_found,
                ),
                (
                    "Borrowings or available capacity",
                    revolver_usage_or_availability_found
                    or revolver_capacity_text_found,
                ),
                ("Maturity or expiration", revolver_maturity_found),
                (
                    "Borrowing-base, reserve, or borrowing-condition detail",
                    revolver_restrictions_found,
                ),
            )
            if not found
        ],
    )

    lease_found = bool(_patterns_found(filing_text, NOTE_PATTERNS["lease"]))
    lease_schedule_found = bool(_patterns_found(filing_text, NOTE_PATTERNS["lease_schedule"]))
    lease_balance_found = _metric_present(
        metric_names,
        "finance_lease_current",
        "finance_lease_noncurrent",
        "operating_lease_current",
        "operating_lease_noncurrent",
    )
    lease_evidence: list[str] = []
    if lease_found:
        lease_evidence.append("note_lease_disclosure")
        evidence_rows.append(
            _evidence_row(
                "note_lease_disclosure",
                _snippet(filing_text, NOTE_PATTERNS["lease"]),
                selected_filing,
                source_location="Latest financial filing; lease disclosure",
                source_tag="note-keyword:lease",
            )
        )
    lease_status = (
        "VALIDATED"
        if lease_balance_found and lease_found and lease_schedule_found
        else "WARNING"
        if lease_balance_found or lease_found
        else "MISSING"
    )
    modules["leases"] = _module(
        "leases",
        lease_status,
        (
            "Lease carrying values and contractual payment language were located and remain separately classified."
            if lease_status == "VALIDATED"
            else "Lease evidence is partial; carrying values must not be presented as contractual cash payments."
            if lease_status == "WARNING"
            else "Lease liabilities and contractual payments were not established; missing tags are not treated as no leases."
        ),
        required_elements={
            "lease_carrying_value": "FOUND" if lease_balance_found else "MISSING",
            "lease_note_disclosure": "FOUND" if lease_found else "MISSING",
            "contractual_payment_schedule": "FOUND" if lease_schedule_found else "MISSING",
            "carrying_value_separated_from_contractual_payments": "ENFORCED",
        },
        evidence_metric_names=lease_evidence,
        missing_information=[
            label
            for label, found in (
                ("Lease carrying value", lease_balance_found),
                ("Lease note disclosure", lease_found),
                ("Undiscounted contractual payment schedule", lease_schedule_found),
            )
            if not found
        ],
    )

    covenant_found = bool(_patterns_found(filing_text, NOTE_PATTERNS["covenant"]))
    compliance_found = bool(_patterns_found(filing_text, NOTE_PATTERNS["covenant_compliance"]))
    headroom_found = bool(_patterns_found(filing_text, NOTE_PATTERNS["covenant_headroom"]))
    covenant_evidence: list[str] = []
    if covenant_found or compliance_found:
        covenant_evidence.append("note_covenant_disclosure")
        evidence_rows.append(
            _evidence_row(
                "note_covenant_disclosure",
                _snippet(
                    filing_text,
                    NOTE_PATTERNS["covenant_compliance"] + NOTE_PATTERNS["covenant"],
                ),
                selected_filing,
                source_location="Latest financial filing; covenant disclosure",
                source_tag="note-keyword:covenant",
            )
        )
    covenant_status = (
        "VALIDATED"
        if covenant_found and compliance_found and headroom_found
        else "WARNING"
        if covenant_found or compliance_found
        else "MISSING"
    )
    modules["covenants"] = _module(
        "covenants",
        covenant_status,
        (
            "Covenant, compliance, and numerical headroom evidence were located."
            if covenant_status == "VALIDATED"
            else "Covenant compliance language was located without complete numerical headroom; compliance is not treated as adequate headroom."
            if covenant_status == "WARNING"
            else "Covenant applicability, compliance, and headroom were not established."
        ),
        required_elements={
            "covenant_terms_or_trigger": "FOUND" if covenant_found else "MISSING",
            "compliance_statement": "FOUND" if compliance_found else "MISSING",
            "numerical_headroom_or_availability": "FOUND" if headroom_found else "MISSING",
            "compliance_not_equated_to_headroom": "ENFORCED",
        },
        evidence_metric_names=covenant_evidence,
        missing_information=[
            label
            for label, found in (
                ("Covenant terms or trigger", covenant_found),
                ("Compliance statement", compliance_found),
                ("Numerical headroom or availability", headroom_found),
            )
            if not found
        ],
    )

    receivable_found = bool(_patterns_found(filing_text, NOTE_PATTERNS["receivable"]))
    receivable_detail_found = bool(
        _patterns_found(filing_text, NOTE_PATTERNS["receivable_risk_detail"])
    )
    receivable_balance_found = "accounts_receivable_net" in metric_names
    receivable_evidence: list[str] = []
    if receivable_found:
        receivable_evidence.append("note_receivable_disclosure")
        evidence_rows.append(
            _evidence_row(
                "note_receivable_disclosure",
                _snippet(filing_text, NOTE_PATTERNS["receivable"]),
                selected_filing,
                source_location="Latest financial filing; receivable disclosure",
                source_tag="note-keyword:receivables",
            )
        )
    receivable_status = (
        "VALIDATED"
        if receivable_balance_found and receivable_found and receivable_detail_found
        else "WARNING"
        if receivable_balance_found and receivable_found
        else "MISSING"
    )
    modules["receivables"] = _module(
        "receivables",
        receivable_status,
        (
            "Receivable balance, note disclosure, and at least one risk-detail disclosure were located."
            if receivable_status == "VALIDATED"
            else "Receivables are present, but aging, concentration, factoring, or other risk detail is incomplete."
            if receivable_status == "WARNING"
            else "Receivable balance or note evidence was not established; the module remains missing."
        ),
        required_elements={
            "net_receivable_balance": "FOUND" if receivable_balance_found else "MISSING",
            "receivable_note_disclosure": "FOUND" if receivable_found else "MISSING",
            "aging_concentration_or_transfer_detail": "FOUND"
            if receivable_detail_found
            else "MISSING",
        },
        evidence_metric_names=receivable_evidence,
        missing_information=[
            label
            for label, found in (
                ("Net receivable balance", receivable_balance_found),
                ("Receivable note disclosure", receivable_found),
                ("Aging, concentration, or receivable-transfer detail", receivable_detail_found),
            )
            if not found
        ],
    )

    bad_debt_methodology_found = bool(
        _patterns_found(filing_text, NOTE_PATTERNS["bad_debt_methodology"])
    )
    bad_debt_activity_found = bool(
        _patterns_found(filing_text, NOTE_PATTERNS["bad_debt_activity"])
    )
    allowance_balance_found = "allowance_for_credit_losses_ar" in metric_names
    bad_debt_evidence: list[str] = []
    if bad_debt_methodology_found or bad_debt_activity_found:
        bad_debt_evidence.append("note_bad_debt_disclosure")
        evidence_rows.append(
            _evidence_row(
                "note_bad_debt_disclosure",
                _snippet(
                    filing_text,
                    NOTE_PATTERNS["bad_debt_methodology"]
                    + NOTE_PATTERNS["bad_debt_activity"],
                ),
                selected_filing,
                source_location="Latest financial filing; credit-loss or bad-debt disclosure",
                source_tag="note-keyword:bad-debt-credit-loss",
            )
        )
    bad_debt_status = (
        "VALIDATED"
        if allowance_balance_found
        and bad_debt_methodology_found
        and bad_debt_activity_found
        else "WARNING"
        if allowance_balance_found
        or bad_debt_methodology_found
        or bad_debt_activity_found
        else "MISSING"
    )
    modules["bad_debt"] = _module(
        "bad_debt",
        bad_debt_status,
        (
            "Allowance balance, credit-loss methodology, and provision/write-off activity were located."
            if bad_debt_status == "VALIDATED"
            else "Bad-debt evidence is partial; allowance, methodology, and activity must remain separately identified."
            if bad_debt_status == "WARNING"
            else "Allowance, provision, write-off, and methodology evidence was not located; missing is not zero."
        ),
        required_elements={
            "allowance_balance": "FOUND" if allowance_balance_found else "MISSING",
            "credit_loss_methodology": "FOUND"
            if bad_debt_methodology_found
            else "MISSING",
            "provision_writeoff_or_recovery_activity": "FOUND"
            if bad_debt_activity_found
            else "MISSING",
            "missing_allowance_not_zero": "ENFORCED",
        },
        evidence_metric_names=bad_debt_evidence,
        missing_information=[
            label
            for label, found in (
                ("Allowance balance", allowance_balance_found),
                ("Credit-loss methodology", bad_debt_methodology_found),
                ("Provision, write-off, or recovery activity", bad_debt_activity_found),
            )
            if not found
        ],
    )

    supplier_text_found = bool(
        _patterns_found(filing_text, NOTE_PATTERNS["supplier_finance"])
    )
    explicit_not_applicable = bool(
        _patterns_found(filing_text, NOTE_PATTERNS["supplier_finance_not_applicable"])
    )
    supplier_evidence: list[str] = []
    if supplier_text_found:
        supplier_evidence.append("note_supplier_finance_disclosure")
        evidence_rows.append(
            _evidence_row(
                "note_supplier_finance_disclosure",
                _snippet(filing_text, NOTE_PATTERNS["supplier_finance"]),
                selected_filing,
                source_location="Latest financial filing; supplier-finance disclosure",
                source_tag="note-keyword:supplier-finance",
            )
        )
    for index, fact in enumerate(supplier_facts, start=1):
        metric_name = f"supplier_finance_fact_{index}"
        supplier_evidence.append(metric_name)
        unit = str(fact.get("unit", ""))
        currency = unit if re.fullmatch(r"[A-Z]{3}", unit) else ""
        evidence_rows.append(
            _evidence_row(
                metric_name,
                fact.get("value"),
                selected_filing,
                source_location="SEC companyfacts; supplier-finance concept",
                source_tag=f"{fact.get('taxonomy')}:{fact.get('tag')}",
                filing_type=str(fact.get("form", "")),
                filing_date=str(fact.get("filing_date", "")),
                period_end=str(fact.get("period_end", "")),
                unit=unit,
                currency=currency,
                confidence="High",
                validation_status="auto-checked",
            )
        )
    if explicit_not_applicable:
        supplier_status = "NOT_APPLICABLE"
        supplier_summary = "The filing explicitly states that no supplier-finance program applies."
    elif supplier_facts and supplier_text_found:
        supplier_status = "VALIDATED"
        supplier_summary = "Supplier-finance disclosure and a period-matched structured fact were located."
    elif supplier_facts or supplier_text_found:
        supplier_status = "WARNING"
        supplier_summary = "A supplier-finance signal was located, but amount, balance-sheet location, or roll-forward evidence is incomplete."
    else:
        supplier_status = "MISSING"
        supplier_summary = "No supplier-finance disclosure was located; silence is not treated as NOT_APPLICABLE."
    modules["supplier_finance"] = _module(
        "supplier_finance",
        supplier_status,
        supplier_summary,
        required_elements={
            "program_disclosure": "FOUND"
            if supplier_text_found
            else "EXPLICIT_NOT_APPLICABLE"
            if explicit_not_applicable
            else "MISSING",
            "period_matched_obligation_fact": "FOUND" if supplier_facts else "MISSING",
            "absence_not_assumed_not_applicable": "ENFORCED",
        },
        evidence_metric_names=supplier_evidence,
        missing_information=[]
        if supplier_status == "NOT_APPLICABLE"
        else [
            label
            for label, found in (
                ("Supplier-finance program disclosure", supplier_text_found),
                ("Period-matched supplier-finance obligation", bool(supplier_facts)),
            )
            if not found
        ],
    )

    acquisition_text_found = bool(
        _patterns_found(filing_text, NOTE_PATTERNS["acquisition"])
    )
    acquisition_terms_found = bool(
        _patterns_found(filing_text, NOTE_PATTERNS["acquisition_terms"])
    )
    acquisition_accounting_found = bool(
        _patterns_found(filing_text, NOTE_PATTERNS["acquisition_accounting"])
    )
    acquisition_cash_metrics = sorted(
        name
        for name in metric_names
        if name.endswith("_business_acquisitions")
    )
    acquisition_evidence: list[str] = list(acquisition_cash_metrics)
    if acquisition_text_found:
        acquisition_evidence.append("note_acquisition_disclosure")
        evidence_rows.append(
            _evidence_row(
                "note_acquisition_disclosure",
                _snippet(
                    filing_text,
                    NOTE_PATTERNS["acquisition"]
                    + NOTE_PATTERNS["acquisition_terms"]
                    + NOTE_PATTERNS["acquisition_accounting"],
                ),
                selected_filing,
                source_location="Latest financial filing; acquisition or business-combination disclosure",
                source_tag="note-keyword:acquisition",
            )
        )
    for index, fact in enumerate(acquisition_fact_rows, start=1):
        metric_name = f"acquisition_unselected_fact_signal_{index}"
        acquisition_evidence.append(metric_name)
        evidence_rows.append(
            _evidence_row(
                metric_name,
                (
                    f"tag={fact.get('taxonomy')}:{fact.get('tag')}; "
                    f"accession={fact.get('accession')}; "
                    "amount not duplicated; use the shared S06 period selector"
                ),
                selected_filing,
                source_location="SEC companyfacts; unselected acquisition concept signal",
                source_tag=f"{fact.get('taxonomy')}:{fact.get('tag')}",
                filing_type=str(fact.get("form", "")),
                filing_date=str(fact.get("filing_date", "")),
                period_end=str(fact.get("period_end", "")),
                unit="text",
                currency="",
                confidence="Medium",
                validation_status="review-required",
            )
        )
    acquisition_structured_found = bool(acquisition_cash_metrics)
    acquisition_unselected_fact_signal = bool(acquisition_fact_rows)
    acquisition_signal = (
        acquisition_text_found
        or acquisition_structured_found
        or acquisition_unselected_fact_signal
    )
    if (
        not filing_text
        and not acquisition_structured_found
        and not acquisition_unselected_fact_signal
    ):
        acquisition_status = "MISSING"
        acquisition_summary = "The filing text and period-matched acquisition evidence were unavailable, so acquisition applicability could not be established."
    elif not acquisition_signal:
        acquisition_status = "NOT_APPLICABLE"
        acquisition_summary = "The completed selected-filing and structured-fact scan found no acquisition signal for the reviewed period."
    elif (
        acquisition_text_found
        and acquisition_structured_found
        and acquisition_terms_found
        and acquisition_accounting_found
    ):
        acquisition_status = "VALIDATED"
        acquisition_summary = "Period-matched acquisition amount, transaction terms, and acquisition-accounting disclosure were located."
    else:
        acquisition_status = "WARNING"
        acquisition_summary = "An acquisition signal was located, but the period-matched amount, transaction consideration, purchase accounting, or pro forma impact is incomplete."
    modules["acquisitions"] = _module(
        "acquisitions",
        acquisition_status,
        acquisition_summary,
        required_elements={
            "selected_filing_scan": "COMPLETED"
            if filing_text
            else "MISSING",
            "period_matched_cash_flow_or_structured_fact": "FOUND"
            if acquisition_structured_found
            else "UNSELECTED_SIGNAL"
            if acquisition_unselected_fact_signal
            else "MISSING",
            "transaction_consideration_or_purchase_price": "FOUND"
            if acquisition_terms_found
            else "MISSING",
            "purchase_accounting_or_pro_forma_impact": "FOUND"
            if acquisition_accounting_found
            else "MISSING",
            "absence_requires_completed_scan": "ENFORCED",
            "unselected_fact_not_promoted_to_amount": "ENFORCED",
            "post_period_events_separately_bridged": "ENFORCED",
        },
        evidence_metric_names=acquisition_evidence,
        missing_information=[]
        if acquisition_status == "NOT_APPLICABLE"
        else [
            label
            for label, found in (
                ("Selected financial filing acquisition review", bool(filing_text)),
                (
                    "Period-matched acquisition cash flow or structured fact",
                    acquisition_structured_found,
                ),
                (
                    "Transaction consideration or purchase price",
                    acquisition_terms_found,
                ),
                (
                    "Purchase accounting or pro forma impact",
                    acquisition_accounting_found,
                ),
            )
            if not found
        ],
    )

    return modules, evidence_rows


def _build_amendment_module(
    amendments: list[dict[str, str]],
    document_texts: dict[str, str],
    selected_filing: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    if not amendments:
        return (
            _module(
                "amendments",
                "NOT_APPLICABLE",
                "No later amendment for the selected financial period was listed in SEC submissions.",
                required_elements={
                    "same_period_amendment_index_review": "CLEAR",
                    "amendment_scope_review": "NOT_APPLICABLE",
                },
            ),
            [],
            False,
        )

    evidence_rows: list[dict[str, Any]] = []
    high_risk = False
    unresolved = False
    administrative_only = True
    metric_names: list[str] = []
    for index, amendment in enumerate(amendments, start=1):
        text = document_texts.get(amendment["accession"], "")
        restatement_signal = bool(
            _patterns_found(text, NOTE_PATTERNS["restatement_high_confidence"])
        )
        administrative_signal = bool(
            _patterns_found(text, NOTE_PATTERNS["administrative_amendment"])
        )
        high_risk = high_risk or restatement_signal
        unresolved = unresolved or not text
        administrative_only = administrative_only and administrative_signal and not restatement_signal
        metric_name = f"financial_filing_amendment_{index}"
        metric_names.append(metric_name)
        evidence_rows.append(
            _evidence_row(
                metric_name,
                (
                    _snippet(
                        text,
                        NOTE_PATTERNS["restatement_high_confidence"]
                        + NOTE_PATTERNS["administrative_amendment"],
                    )
                    or f"Indexed amendment {amendment['form']} {amendment['accession']}"
                ),
                selected_filing,
                source_url=amendment.get("source_url"),
                source_location=f"SEC amendment; accession {amendment['accession']}",
                source_tag=f"SEC:{amendment['form']}:{amendment['accession']}",
                filing_type=amendment.get("form"),
                filing_date=amendment.get("filing_date"),
                period_end=amendment.get("report_date"),
                confidence="High" if text else "Medium",
                validation_status="hard-stop" if restatement_signal else "review-required",
            )
        )

    if high_risk:
        status = "HARD_STOP"
        summary = "A same-period amendment contains a high-confidence restatement or non-reliance signal; pre-amendment conclusions are blocked."
    elif administrative_only and not unresolved:
        status = "VALIDATED"
        summary = "Every same-period amendment was reviewed as administrative and did not indicate a financial-statement change."
    else:
        status = "WARNING"
        summary = "A same-period amendment exists, but its financial-statement effect is not fully resolved."
    return (
        _module(
            "amendments",
            status,
            summary,
            required_elements={
                "same_period_amendment_index_review": "FOUND",
                "amendment_scope_review": "FINANCIAL_RESTATEMENT"
                if high_risk
                else "ADMINISTRATIVE"
                if administrative_only and not unresolved
                else "REVIEW_REQUIRED",
                "pre_amendment_values_blocked_when_financial": "ENFORCED",
            },
            evidence_metric_names=metric_names,
            missing_information=[]
            if status in {"VALIDATED", "HARD_STOP"}
            else ["Complete amendment scope and financial-statement impact review"],
        ),
        evidence_rows,
        high_risk,
    )


def _classify_event(
    event: dict[str, Any],
    text: str,
) -> dict[str, Any]:
    item_codes = set(event.get("item_codes", []))
    hard_stop_categories = sorted(
        {HARD_STOP_EVENT_ITEMS[item] for item in item_codes if item in HARD_STOP_EVENT_ITEMS}
    )
    categories = sorted(
        {MATERIAL_EVENT_ITEMS[item] for item in item_codes if item in MATERIAL_EVENT_ITEMS}
    )
    for category, patterns in EVENT_TEXT_PATTERNS.items():
        if _patterns_found(text, patterns):
            categories.append(category)
    categories = sorted(set(categories))
    if hard_stop_categories:
        status = "HARD_STOP"
    elif categories or item_codes:
        status = "WARNING"
    else:
        status = "WARNING"
    return {
        **event,
        "status": status,
        "hard_stop_categories": hard_stop_categories,
        "event_categories": categories,
        "content_review_status": "TEXT_RETRIEVED_AND_SCANNED"
        if text
        else "TEXT_NOT_AVAILABLE",
    }


def _build_event_module(
    events: list[dict[str, Any]],
    document_texts: dict[str, str],
    selected_filing: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], bool]:
    if not events:
        return (
            _module(
                "subsequent_events",
                "VALIDATED",
                "No later 8-K or 8-K/A was listed after the selected financial filing as of the index review date.",
                required_elements={
                    "subsequent_filing_index_review": "CLEAR",
                    "historical_balance_bridge": "NOT_REQUIRED",
                },
            ),
            [],
            [],
            False,
        )

    classified: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    metric_names: list[str] = []
    for index, event in enumerate(events, start=1):
        text = document_texts.get(event["accession"], "")
        classified_event = _classify_event(event, text)
        classified.append(classified_event)
        metric_name = f"subsequent_event_filing_{index}"
        metric_names.append(metric_name)
        patterns = tuple(
            pattern
            for category in classified_event["event_categories"]
            for pattern in EVENT_TEXT_PATTERNS.get(category, ())
        )
        evidence_rows.append(
            _evidence_row(
                metric_name,
                (
                    _snippet(text, patterns)
                    if patterns
                    else (
                        f"Items {event.get('items') or 'not supplied'}; "
                        + (
                            "filing text retrieved and scanned; quantified bridge required"
                            if text
                            else "filing text unavailable; content review required"
                        )
                    )
                ),
                selected_filing,
                source_url=event.get("source_url"),
                source_location=f"SEC subsequent filing; accession {event['accession']}",
                source_tag=f"SEC:{event['form']}:{event['accession']}",
                filing_type=event.get("form"),
                filing_date=event.get("filing_date"),
                period_end=event.get("report_date") or event.get("filing_date"),
                confidence="High" if text else "Medium",
                validation_status="hard-stop"
                if classified_event["status"] == "HARD_STOP"
                else "review-required",
            )
        )

    hard_stop = any(event["status"] == "HARD_STOP" for event in classified)
    status = "HARD_STOP" if hard_stop else "WARNING"
    summary = (
        "A later filing reports bankruptcy, acceleration/default, or non-reliance; the displayed current state is blocked pending a validated bridge."
        if hard_stop
        else "Later filings may change debt, liquidity, acquisition, repurchase, guidance, or other current-state conclusions and require an explicit bridge."
    )
    return (
        _module(
            "subsequent_events",
            status,
            summary,
            required_elements={
                "subsequent_filing_index_review": "FOUND",
                "material_event_classification": "INDEX_AND_KEYWORD_CLASSIFIED",
                "historical_balance_bridge": "REQUIRED",
                "events_not_mixed_into_historical_balances": "ENFORCED",
            },
            evidence_metric_names=metric_names,
            missing_information=[
                "Quantified bridge from historical balances to each material subsequent event"
            ],
        ),
        evidence_rows,
        classified,
        hard_stop,
    )


def _build_restatement_module(
    filing_text: str,
    selected_filing: dict[str, Any],
    *,
    amendment_hard_stop: bool,
    event_hard_stop: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    high_confidence_current = bool(
        _patterns_found(filing_text, NOTE_PATTERNS["restatement_high_confidence"])
    )
    incorporated_current = bool(
        _patterns_found(filing_text, NOTE_PATTERNS["restatement_incorporated"])
    )
    evidence_rows: list[dict[str, Any]] = []
    metric_names: list[str] = []
    if high_confidence_current or incorporated_current:
        metric_names.append("restatement_disclosure")
        evidence_rows.append(
            _evidence_row(
                "restatement_disclosure",
                _snippet(
                    filing_text,
                    NOTE_PATTERNS["restatement_high_confidence"]
                    + NOTE_PATTERNS["restatement_incorporated"],
                ),
                selected_filing,
                source_location="Selected financial filing; restatement or revision disclosure",
                source_tag="note-keyword:restatement",
                confidence="High",
                validation_status="review-required",
            )
        )

    if amendment_hard_stop or event_hard_stop:
        status = "HARD_STOP"
        summary = "A later amendment or subsequent filing contains a non-reliance/restatement signal; affected historical conclusions are blocked."
    elif high_confidence_current or incorporated_current:
        status = "WARNING"
        summary = "The selected filing contains restatement or revision language; affected periods and fact accession lineage require review."
    else:
        status = "NOT_APPLICABLE"
        summary = "No high-confidence restatement, non-reliance, or prior-period revision signal was identified in the reviewed filing set."
    return (
        _module(
            "restatements",
            status,
            summary,
            required_elements={
                "selected_filing_text_review": "SIGNAL_FOUND"
                if high_confidence_current or incorporated_current
                else "CLEAR",
                "later_amendment_or_event_review": "HARD_STOP_SIGNAL"
                if amendment_hard_stop or event_hard_stop
                else "CLEAR",
                "affected_period_bridge": "REQUIRED"
                if status in {"WARNING", "HARD_STOP"}
                else "NOT_APPLICABLE",
            },
            evidence_metric_names=metric_names,
            missing_information=[
                "Affected periods, corrected values, and old-to-new evidence bridge"
            ]
            if status in {"WARNING", "HARD_STOP"}
            else [],
        ),
        evidence_rows,
    )


def validation_issue_for_module(module: dict[str, Any]) -> dict[str, Any]:
    status = str(module["status"])
    result = {
        "VALIDATED": "PASS",
        "NOT_APPLICABLE": "NOT_APPLICABLE",
        "MISSING": "MISSING",
        "WARNING": "WARNING",
        "HARD_STOP": "FAIL",
    }[status]
    issue_class = (
        "HARD_STOP"
        if status == "HARD_STOP"
        else "WARNING"
        if status in {"MISSING", "WARNING"}
        else "INFO"
    )
    severity = (
        "Critical"
        if status == "HARD_STOP"
        else "High"
        if status in {"MISSING", "WARNING"}
        else "Info"
    )
    module_id = str(module["module_id"])
    compatibility_ids = {
        "amendments": "P0-filing-amendment-review",
        "restatements": "P0-restatement-review",
        "subsequent_events": "P1-subsequent-event-review",
    }
    check_id = compatibility_ids.get(
        module_id,
        f"P1-note-{module_id.replace('_', '-')}",
    )
    return {
        "id": check_id,
        "check_id": check_id,
        "category": "notes_and_events",
        "result": result,
        "status": result,
        "issue_class": issue_class,
        "severity": severity,
        "evidence": module["summary"],
        "message": module["summary"],
        "impact": (
            "Formal report generation is blocked until the conflicting current-state evidence is bridged."
            if status == "HARD_STOP"
            else "The affected underwriting conclusion must remain qualified."
            if status in {"MISSING", "WARNING"}
            else "The control does not constrain the current output."
        ),
        "decision_impact": (
            "Formal report generation is blocked until the conflicting current-state evidence is bridged."
            if status == "HARD_STOP"
            else "The affected underwriting conclusion must remain qualified."
            if status in {"MISSING", "WARNING"}
            else "The control does not constrain the current output."
        ),
        "remediation": (
            "; ".join(module.get("missing_information", []))
            or "Preserve the source and rerun after the next filing."
        ),
        "evidence_ids": list(module.get("evidence_ids", [])),
        "scope": "shared_data_engine",
    }


def build_notes_and_events_assessment(
    *,
    submissions: dict[str, Any],
    companyfacts: dict[str, Any],
    selected_filing: dict[str, Any],
    filing_text: str,
    metric_names: set[str],
    document_texts: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a conservative, source-linked note and event control object."""

    filing_text = _normalized_text(filing_text)
    document_texts = {
        accession: _normalized_text(text)
        for accession, text in (document_texts or {}).items()
    }
    amendments = index_financial_amendments(submissions, selected_filing)
    events = index_subsequent_events(
        submissions,
        str(selected_filing.get("filed", "")),
    )
    supplier_facts = supplier_finance_facts(
        companyfacts,
        period_end=str(selected_filing.get("period", "")),
    )
    acquisition_fact_rows = acquisition_facts(
        companyfacts,
        selected_filing=selected_filing,
    )
    modules, evidence_rows = _build_note_modules(
        filing_text,
        selected_filing,
        metric_names,
        supplier_facts,
        acquisition_fact_rows,
    )
    amendment_module, amendment_rows, amendment_hard_stop = _build_amendment_module(
        amendments,
        document_texts,
        selected_filing,
    )
    event_module, event_rows, classified_events, event_hard_stop = _build_event_module(
        events,
        document_texts,
        selected_filing,
    )
    restatement_module, restatement_rows = _build_restatement_module(
        filing_text,
        selected_filing,
        amendment_hard_stop=amendment_hard_stop,
        event_hard_stop=any(
            "non_reliance_on_previously_issued_financial_statements"
            in event.get("hard_stop_categories", [])
            for event in classified_events
        ),
    )
    modules["amendments"] = amendment_module
    modules["restatements"] = restatement_module
    modules["subsequent_events"] = event_module
    evidence_rows.extend(amendment_rows)
    evidence_rows.extend(restatement_rows)
    evidence_rows.extend(event_rows)

    ordered_modules = {module_id: modules[module_id] for module_id in NOTE_MODULE_ORDER}
    statuses = {module["status"] for module in ordered_modules.values()}
    overall_status = (
        "HARD_STOP"
        if "HARD_STOP" in statuses
        else "WARNING"
        if statuses & {"MISSING", "WARNING"}
        else "VALIDATED"
    )
    return {
        "control_version": S07_NOTES_EVENTS_CONTROL_VERSION,
        "status": overall_status,
        "selected_filing": {
            key: selected_filing.get(key)
            for key in ("form", "filed", "period", "accession", "url")
        },
        "modules": ordered_modules,
        "amendment_filings": amendments,
        "subsequent_event_filings": classified_events,
        "safe_outcomes_observed": sorted(statuses),
        "validation_issues": [
            validation_issue_for_module(module)
            for module in ordered_modules.values()
        ],
        "_evidence_rows": evidence_rows,
    }


def link_assessment_evidence(
    assessment: dict[str, Any],
    evidence_ids_by_metric: dict[str, str],
) -> None:
    for module in assessment.get("modules", {}).values():
        module["evidence_ids"] = [
            evidence_ids_by_metric[name]
            for name in module.get("evidence_metric_names", [])
            if name in evidence_ids_by_metric
        ]
    for issue in assessment.get("validation_issues", []):
        check_id = str(issue["check_id"])
        compatibility_modules = {
            "P0-filing-amendment-review": "amendments",
            "P0-restatement-review": "restatements",
            "P1-subsequent-event-review": "subsequent_events",
        }
        module_id = compatibility_modules.get(
            check_id,
            check_id.split("P1-note-", 1)[-1].replace("-", "_"),
        )
        module = assessment.get("modules", {}).get(module_id, {})
        issue["evidence_ids"] = list(module.get("evidence_ids", []))
