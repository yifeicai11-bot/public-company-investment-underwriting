#!/usr/bin/env python3
"""Validate the immutable evidence and published boundaries for v1.1.0."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v1.1.0"
MANIFEST_PATH = ROOT / "releases" / RELEASE / "release_manifest.json"
RPM_ADJUDICATION_PATH = (
    ROOT
    / "partner-demo/investment_decision_v2/blind_tests/s17_final_validator_after_fix"
    / "post_fix_live_after_facility_parser_fix_adjudication.json"
)
RPM_RUN_PATH = (
    ROOT
    / "partner-demo/investment_decision_v2/blind_tests/s17_final_validator_after_fix"
    / "post_fix_live_after_facility_parser_fix"
)
TNL_ACCEPTANCE_PATH = (
    ROOT
    / "partner-demo/investment_decision_v2/blind_tests/s17_final_evidence_after_fix"
    / "s17_acceptance_result.json"
)
TNL_RUN_PATH = TNL_ACCEPTANCE_PATH.parent / "first_run"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_final_release(root: Path = ROOT) -> dict[str, Any]:
    import sys

    scripts = root / "partner-demo/investment_decision_v2/scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from run_blind_company_forward_test import verify_preserved_run

    errors: list[str] = []
    required = (
        root / "releases" / RELEASE / "RELEASE_NOTES.md",
        root / "CHANGELOG.md",
        root / "README.md",
        MANIFEST_PATH,
        RPM_ADJUDICATION_PATH,
        TNL_ACCEPTANCE_PATH,
    )
    missing = [str(path.relative_to(root)) for path in required if not path.is_file()]
    if missing:
        errors.append(f"REQUIRED_RELEASE_FILES_MISSING:{missing}")

    manifest = read_json(MANIFEST_PATH) if MANIFEST_PATH.is_file() else {}
    rpm = read_json(RPM_ADJUDICATION_PATH) if RPM_ADJUDICATION_PATH.is_file() else {}
    tnl = read_json(TNL_ACCEPTANCE_PATH) if TNL_ACCEPTANCE_PATH.is_file() else {}

    if manifest.get("release") != RELEASE:
        errors.append("RELEASE_VERSION_MISMATCH")
    if manifest.get("status") != "FINAL_RELEASE_ACCEPTED":
        errors.append("FINAL_RELEASE_STATUS_NOT_ACCEPTED")
    if manifest.get("s17_status") != "ACCEPTED":
        errors.append("S17_STATUS_NOT_ACCEPTED")
    if rpm.get("status") != "SHARED_FIX_VALIDATED_SECOND_HELD_OUT_REQUIRED":
        errors.append("RPM_SHARED_FIX_NOT_VALIDATED")
    facility = rpm.get("facility_parser_validation", {})
    if facility.get("prior_false_metric_present_after_fix") is not False:
        errors.append("RPM_FALSE_FACILITY_METRIC_NOT_CLEARED")
    if facility.get("misleading_total_liquidity_sentence_promoted_to_facility_availability") is not False:
        errors.append("RPM_TOTAL_LIQUIDITY_PROMOTED_TO_FACILITY")

    if tnl.get("status") != "S17_HELD_OUT_ACCEPTED":
        errors.append("FINAL_HELD_OUT_NOT_ACCEPTED")
    if tnl.get("errors"):
        errors.append("FINAL_HELD_OUT_HAS_ERRORS")
    if tnl.get("selected_issuer", {}).get("ticker") != "TNL":
        errors.append("FINAL_HELD_OUT_IDENTITY_MISMATCH")
    if tnl.get("selection_integrity", {}).get("status") != "PASS":
        errors.append("FINAL_SELECTION_INTEGRITY_FAILED")
    if tnl.get("diagnostic_summary", {}).get("contract_validation_status") != "PASS":
        errors.append("FINAL_CONTRACT_VALIDATION_FAILED")
    if tnl.get("diagnostic_summary", {}).get("hard_stop_count") != 0:
        errors.append("FINAL_HELD_OUT_HAS_HARD_STOPS")

    preserved: dict[str, Any] = {}
    for label, path in (("rpm", RPM_RUN_PATH), ("tnl", TNL_RUN_PATH)):
        try:
            preserved[label] = verify_preserved_run(path)
        except Exception as exc:
            preserved[label] = {"status": "FAIL", "error": type(exc).__name__}
            errors.append(f"{label.upper()}_PRESERVED_RUN_INTEGRITY_FAILED")

    readme = (root / "README.md").read_text(encoding="utf-8")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"**Release:** `{RELEASE}`" not in readme:
        errors.append("README_RELEASE_VERSION_MISSING")
    if f"## {RELEASE} -" not in changelog:
        errors.append("CHANGELOG_FINAL_RELEASE_MISSING")

    return {
        "status": "PASS" if not errors else "FAIL",
        "release": RELEASE,
        "s17_status": manifest.get("s17_status"),
        "rpm_shared_fix_status": rpm.get("status"),
        "final_held_out_status": tnl.get("status"),
        "preserved_run_integrity": preserved,
        "failure_count": len(errors),
        "errors": sorted(errors),
        "automatic_investment_approval": False,
        "automatic_trade_execution": False,
    }


def main() -> int:
    result = validate_final_release()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
