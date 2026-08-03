#!/usr/bin/env python3
"""Validate the public synthetic S14 package before delivery."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from pypdf import PdfReader


RESTRICTED_POSITION_TERMS = (
    "suggested position",
    "recommended position",
    "建议仓位",
    "推荐仓位",
)
REQUIRED_REPORT_STEMS = (
    "Gate4_One_Page_Summary_Bilingual",
    "Gate4_Full_Report_Bilingual",
    "Gate4_Evidence_Appendix_Bilingual",
    "Gate4_Validation_Report_Bilingual",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path.name}")
    return value


def validate_delivery(directory: Path) -> list[str]:
    directory = directory.resolve(strict=True)
    errors: list[str] = []
    manifests = sorted(directory.glob("*_Gate4_Delivery_Manifest.json"))
    contracts = sorted(directory.glob("*_Gate4_Assessment_Contract.json"))
    if len(manifests) != 1:
        return ["DELIVERY_MANIFEST_COUNT_INVALID"]
    if len(contracts) != 1:
        return ["ASSESSMENT_CONTRACT_COUNT_INVALID"]
    manifest = _read_json(manifests[0])
    contract = _read_json(contracts[0])

    if manifest.get("data_classification") != "SYNTHETIC_PUBLIC_EXAMPLE":
        errors.append("DELIVERY_CLASSIFICATION_INVALID")
    if contract.get("data_classification") != "SYNTHETIC_PUBLIC_EXAMPLE":
        errors.append("CONTRACT_CLASSIFICATION_INVALID")
    if manifest.get("automatic_trade_execution") is not False:
        errors.append("MANIFEST_AUTO_TRADE_NOT_DISABLED")
    if contract.get("automatic_trade_execution") is not False:
        errors.append("CONTRACT_AUTO_TRADE_NOT_DISABLED")
    if contract.get("contract_validation", {}).get("status") != "PASS":
        errors.append("ASSESSMENT_CONTRACT_NOT_VALIDATED")
    if manifest.get("assessment_hash") != contract.get("assessment_hash"):
        errors.append("ASSESSMENT_HASH_MISMATCH")

    public_files = manifest.get("public_files")
    file_hashes = manifest.get("file_hashes")
    if not isinstance(public_files, list) or not isinstance(file_hashes, dict):
        errors.append("DELIVERY_FILE_INDEX_INVALID")
        public_files = []
        file_hashes = {}
    if sorted(public_files) != sorted(file_hashes):
        errors.append("DELIVERY_FILE_INDEX_MISMATCH")
    for name, expected_hash in sorted(file_hashes.items()):
        path = directory / str(name)
        if not path.is_file():
            errors.append(f"DELIVERY_FILE_MISSING:{name}")
        elif _sha256(path) != expected_hash:
            errors.append(f"DELIVERY_HASH_MISMATCH:{name}")

    for stem in REQUIRED_REPORT_STEMS:
        matches = sorted(directory.glob(f"*_{stem}.pdf"))
        if len(matches) != 1:
            errors.append(f"PDF_COUNT_INVALID:{stem}")
            continue
        reader = PdfReader(matches[0])
        if stem == "Gate4_One_Page_Summary_Bilingual" and len(reader.pages) != 1:
            errors.append("ONE_PAGE_SUMMARY_PAGE_COUNT_INVALID")
        if not reader.pages:
            errors.append(f"PDF_EMPTY:{stem}")
            continue
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        if "SYNTHETIC DATA ONLY" not in text:
            errors.append(f"SYNTHETIC_BANNER_MISSING:{stem}")
        if not any(value in text for value in ("系统", "约束", "验证", "证据")):
            errors.append(f"CHINESE_OUTPUT_MISSING:{stem}")
        lowered = text.lower()
        for term in RESTRICTED_POSITION_TERMS:
            haystack = lowered if term.isascii() else text
            if term in haystack:
                errors.append(f"RESTRICTED_POSITION_TERM:{stem}:{term}")
        for page_number, page in enumerate(reader.pages, start=1):
            width = float(page.mediabox.width)
            height = float(page.mediabox.height)
            if abs(width - 595.0) > 2.0 or abs(height - 842.0) > 2.0:
                errors.append(f"PDF_PAGE_NOT_A4:{stem}:{page_number}")

    decision_reports = (
        "Gate4_One_Page_Summary_Bilingual",
        "Gate4_Full_Report_Bilingual",
    )
    expected_assessment = contract.get("system_portfolio_assessment", {}).get(
        "assessment_label_en"
    )
    expected_decision = contract.get("partner_decision", {}).get("decision")
    for stem in decision_reports:
        path = next(iter(sorted(directory.glob(f"*_{stem}.pdf"))), None)
        if path is None:
            continue
        text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
        if (
            not isinstance(expected_assessment, str)
            or expected_assessment not in text
        ):
            errors.append(f"ASSESSMENT_NOT_RENDERED:{stem}")
        if not isinstance(expected_decision, str) or expected_decision not in text:
            errors.append(f"PARTNER_DECISION_NOT_RENDERED:{stem}")
    return sorted(set(errors))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate hashes, contract controls, and PDFs in an S14 synthetic delivery."
    )
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        errors = validate_delivery(args.directory)
    except Exception as exc:
        print("status=GATE_4_SYNTHETIC_DELIVERY_VALIDATION_FAILED")
        print(f"error={type(exc).__name__}")
        return 2
    if errors:
        print("status=GATE_4_SYNTHETIC_DELIVERY_VALIDATION_FAILED")
        for error in errors:
            print(f"error={error}")
        return 1
    print("status=GATE_4_SYNTHETIC_DELIVERY_VALIDATED")
    print("automatic_trade_execution=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
