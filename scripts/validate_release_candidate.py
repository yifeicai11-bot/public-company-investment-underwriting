#!/usr/bin/env python3
"""Validate the static contents of the S16 release candidate."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from release_doctor import RELEASE_CANDIDATE, _locked_requirements


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_PATHS = (
    "underwrite.py",
    "requirements.in",
    "requirements.lock",
    ".github/workflows/ci.yml",
    "CHANGELOG.md",
    "docs/TROUBLESHOOTING.md",
    "docs/MIGRATION.md",
    "docs/PRIVATE_DATA.md",
    f"release-candidates/{RELEASE_CANDIDATE}/release_manifest.json",
    f"release-candidates/{RELEASE_CANDIDATE}/RELEASE_NOTES.md",
    "public-firm-credit-liquidity-skill/agents/openai.yaml",
)


def _result(check_id: str, passed: bool, detail: str) -> dict[str, str]:
    return {"check_id": check_id, "status": "PASS" if passed else "FAIL", "detail": detail}


def validate_release_candidate(root: Path = ROOT) -> dict[str, Any]:
    checks: list[dict[str, str]] = []
    missing = [path for path in REQUIRED_PATHS if not (root / path).exists()]
    checks.append(_result("required-files", not missing, f"missing={missing}"))

    locked = _locked_requirements(root / "requirements.lock")
    direct = {
        line.strip().lower()
        for line in (root / "requirements.in").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    normalized_lock = {name.lower().replace("_", "-") for name in locked}
    checks.append(
        _result(
            "direct-dependencies-locked",
            all(name.replace("_", "-") in normalized_lock for name in direct),
            f"direct={sorted(direct)}; locked={sorted(normalized_lock)}",
        )
    )

    workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    workflow_text = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    checks.append(_result("ci-yaml", isinstance(workflow, dict) and bool(workflow.get("jobs")), "GitHub Actions YAML parsed."))
    for command in (
        "underwrite.py doctor --ci",
        "unittest discover",
        "validate_cross_industry_regression.py",
        "run_s12_valuation_cross_company_acceptance.py",
        "verify_baseline.py",
        "validate_gate4_synthetic_delivery.py",
        "check_private_data_boundaries.py",
        "--tracked",
        "validate_skill_structure.py",
    ):
        checks.append(_result(f"ci-command:{command}", command in workflow_text, command))

    manifest_path = root / f"release-candidates/{RELEASE_CANDIDATE}/release_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        checks.append(_result("rc-version", manifest.get("release_candidate") == RELEASE_CANDIDATE, str(manifest.get("release_candidate"))))
        checks.append(_result("s17-not-started", manifest.get("s17_status") == "NOT_STARTED", str(manifest.get("s17_status"))))
        forbidden = re.compile(r"held.?out.*(?:ticker|company)|(?:ticker|company).*held.?out", re.IGNORECASE)
        checks.append(_result("no-held-out-selection", not forbidden.search(json.dumps(manifest)), "S17 company remains unselected."))

    readme = (root / "README.md").read_text(encoding="utf-8")
    for phrase in ("underwrite.py doctor", "underwrite.py analyze", "requirements.lock"):
        checks.append(_result(f"readme:{phrase}", phrase in readme, phrase))
    failures = [row for row in checks if row["status"] == "FAIL"]
    return {
        "status": "PASS" if not failures else "FAIL",
        "release_candidate": RELEASE_CANDIDATE,
        "check_count": len(checks),
        "failure_count": len(failures),
        "checks": checks,
    }


def main() -> int:
    report = validate_release_candidate()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
