#!/usr/bin/env python3
"""Machine-readable environment diagnostics for the public-company workflow."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE_CANDIDATE = "v1.1.0-rc.1"
MINIMUM_PYTHON = (3, 11)
CHROME_CANDIDATES = (
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
)
LOCK_PATTERN = re.compile(r"^([A-Za-z0-9_.-]+)==([^;\s]+)")


def _check(check_id: str, status: str, detail: str, remediation: str = "") -> dict[str, str]:
    return {
        "check_id": check_id,
        "status": status,
        "detail": detail,
        "remediation": remediation,
    }


def _locked_requirements(path: Path) -> dict[str, str]:
    requirements: dict[str, str] = {}
    if not path.exists():
        return requirements
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = LOCK_PATTERN.match(line)
        if match:
            requirements[match.group(1)] = match.group(2)
    return requirements


def _git_value(repo_root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return result.stdout.strip()


def run_doctor(
    repo_root: Path = REPO_ROOT,
    *,
    require_live: bool = False,
    require_pdf: bool = False,
    ci: bool = False,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    checks: list[dict[str, str]] = []
    required_paths = (
        "public-firm-credit-liquidity-skill/SKILL.md",
        "partner-demo/investment_decision_v2/scripts/build_public_company_investment_layer.py",
        "partner-demo/investment_decision_v2/scripts/render_public_company_artifacts.py",
        "partner-demo/investment_decision_v2/scripts/validate_friday_v1_delivery.py",
        "requirements.lock",
    )
    missing_paths = [value for value in required_paths if not (repo_root / value).exists()]
    checks.append(
        _check(
            "repository-layout",
            "PASS" if not missing_paths else "FAIL",
            "Required repository files are present." if not missing_paths else f"Missing: {missing_paths}",
            "Clone or download the entire repository, not only the skill subfolder." if missing_paths else "",
        )
    )

    python_ok = sys.version_info[:2] >= MINIMUM_PYTHON
    checks.append(
        _check(
            "python-version",
            "PASS" if python_ok else "FAIL",
            platform.python_version(),
            "Install Python 3.11 or newer." if not python_ok else "",
        )
    )

    lock_path = repo_root / "requirements.lock"
    locked = _locked_requirements(lock_path)
    checks.append(
        _check(
            "dependency-lock",
            "PASS" if locked else "FAIL",
            f"{len(locked)} exact package versions in {lock_path.name}." if locked else "No exact dependency lock found.",
            "Install from the repository root requirements.lock." if not locked else "",
        )
    )
    mismatches: list[str] = []
    for package, expected in sorted(locked.items()):
        try:
            actual = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            actual = "MISSING"
        if actual != expected:
            mismatches.append(f"{package}: expected {expected}, found {actual}")
    checks.append(
        _check(
            "dependency-versions",
            "PASS" if not mismatches else "FAIL",
            "Installed packages match requirements.lock." if not mismatches else "; ".join(mismatches),
            "Run: python3 -m pip install -r requirements.lock" if mismatches else "",
        )
    )

    git_binary = shutil.which("git")
    checks.append(
        _check(
            "git",
            "PASS" if git_binary else "FAIL",
            git_binary or "Git is not available.",
            "Install Git before using release and privacy checks." if not git_binary else "",
        )
    )
    if git_binary:
        hook_path = _git_value(repo_root, "config", "--get", "core.hooksPath")
        hook_status = "PASS" if hook_path == ".githooks" else ("WARNING" if not ci else "PASS")
        checks.append(
            _check(
                "privacy-hook",
                hook_status,
                hook_path or "core.hooksPath is not configured in this clone.",
                "Run: git config core.hooksPath .githooks" if hook_status == "WARNING" else "",
            )
        )

    sec_user_agent = os.environ.get("SEC_USER_AGENT", "").strip()
    sec_status = "PASS" if sec_user_agent else ("FAIL" if require_live else "WARNING")
    if ci and not require_live:
        sec_status = "PASS"
    checks.append(
        _check(
            "sec-user-agent",
            sec_status,
            "Configured; value intentionally not displayed." if sec_user_agent else "SEC_USER_AGENT is not configured.",
            'Set SEC_USER_AGENT="Your Name your.email@example.com" before live ticker retrieval.' if not sec_user_agent and not ci else "",
        )
    )

    chrome = next((str(path) for path in CHROME_CANDIDATES if path.exists()), "") or (shutil.which("google-chrome") or shutil.which("chromium") or "")
    chrome_status = "PASS" if chrome else ("FAIL" if require_pdf else "WARNING")
    if ci and not require_pdf:
        chrome_status = "PASS"
    checks.append(
        _check(
            "pdf-browser",
            chrome_status,
            chrome or "Chrome or Chromium was not found.",
            "Install Google Chrome/Chromium or omit --pdf." if not chrome else "",
        )
    )

    output_root = repo_root / "outputs"
    writable_parent = output_root if output_root.exists() else output_root.parent
    writable = os.access(writable_parent, os.W_OK)
    checks.append(
        _check(
            "output-path",
            "PASS" if writable else "FAIL",
            "outputs/",
            "Choose a writable --output-root directory." if not writable else "",
        )
    )

    failures = [row for row in checks if row["status"] == "FAIL"]
    warnings = [row for row in checks if row["status"] == "WARNING"]
    return {
        "diagnostic_schema_version": "1.0.0",
        "release_candidate": RELEASE_CANDIDATE,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "repository_root": ".",
        "mode": "CI" if ci else "LIVE" if require_live else "LOCAL",
        "status": "FAIL" if failures else "PASS_WITH_WARNINGS" if warnings else "PASS",
        "failure_count": len(failures),
        "warning_count": len(warnings),
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check whether this checkout can run the underwriting workflow.")
    parser.add_argument("--live", action="store_true", help="Require SEC_USER_AGENT for live ticker retrieval.")
    parser.add_argument("--pdf", action="store_true", help="Require Chrome or Chromium for PDF generation.")
    parser.add_argument("--ci", action="store_true", help="Run offline CI checks without live-data or PDF requirements.")
    parser.add_argument("--output", type=Path, help="Optional JSON diagnostic path.")
    args = parser.parse_args()
    result = run_doctor(require_live=args.live, require_pdf=args.pdf, ci=args.ci)
    serialized = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized)
    return 0 if result["status"] != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
