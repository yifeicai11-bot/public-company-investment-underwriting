#!/usr/bin/env python3
"""One supported entry point from ticker to validated bilingual delivery."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional


ROOT = Path(__file__).resolve().parent
SCRIPT_DIR = ROOT / "partner-demo" / "investment_decision_v2" / "scripts"
RELEASE_SCRIPT_DIR = ROOT / "scripts"
for path in (SCRIPT_DIR, RELEASE_SCRIPT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from release_doctor import RELEASE_CANDIDATE, run_doctor  # noqa: E402


Builder = Callable[[str, Path, Optional[Path]], Path]
Renderer = Callable[..., dict[str, Any]]
Validator = Callable[[dict[str, Any], Optional[Path]], dict[str, Any]]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def public_research_input_issues(path: Path | None) -> list[str]:
    if path is None:
        return []
    try:
        payload = read_json(path)
    except (OSError, json.JSONDecodeError):
        return ["PUBLIC_RESEARCH_INPUT_UNREADABLE"]
    if not isinstance(payload, dict):
        return ["PUBLIC_RESEARCH_INPUT_NOT_AN_OBJECT"]
    issues: list[str] = []
    prohibited_keys = {
        "portfolio_policy",
        "holdings",
        "current_holdings",
        "exposure_summary",
        "opportunity_set",
        "approval_config",
        "portfolio_constraint_inputs",
        "partner_decision",
    }
    for key in sorted(prohibited_keys.intersection(payload)):
        issues.append(f"PRIVATE_GATE4_FIELD_PRESENT:{key}")
    portfolio_context = payload.get("portfolio_context")
    if isinstance(portfolio_context, dict) and portfolio_context.get("status") not in {
        None,
        "",
        "DISABLED",
        "NOT_PROVIDED",
    }:
        issues.append("PRIVATE_GATE4_PORTFOLIO_CONTEXT_ENABLED")
    if payload.get("position_sizing") not in (None, {}, []):
        issues.append("PRIVATE_GATE4_POSITION_SIZING_PRESENT")
    if payload.get("portfolio_action") not in (None, "", "Not Evaluated"):
        issues.append("PRIVATE_GATE4_PORTFOLIO_ACTION_PRESENT")
    human_approval = payload.get("human_approval")
    if isinstance(human_approval, dict) and human_approval.get("status") == "APPROVED":
        issues.append("PRIVATE_GATE4_HUMAN_APPROVAL_PRESENT")
    return issues


def portable_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return path.name


def portable_manifest(payload: Any, root: Path) -> Any:
    if isinstance(payload, dict):
        return {key: portable_manifest(value, root) for key, value in payload.items()}
    if isinstance(payload, list):
        return [portable_manifest(value, root) for value in payload]
    if isinstance(payload, str):
        for root_text in (str(root), str(root.resolve())):
            if payload.startswith(root_text):
                return payload[len(root_text) :].lstrip("/")
    return payload


def safe_error_message(error: Exception) -> str:
    message = str(error)
    for value, replacement in (
        (str(ROOT), "<REPO_ROOT>"),
        (str(Path.home()), "~"),
    ):
        message = message.replace(value, replacement)
    return message


def delivery_eligibility(contract: dict[str, Any]) -> dict[str, Any]:
    gate = float(contract.get("data_gate", {}).get("level", 0))
    hard_stops = contract.get("hard_stops", [])
    render_blockers = contract.get("render_blockers", [])
    contract_status = contract.get("contract_validation", {}).get("status")
    blockers: list[str] = []
    if contract_status != "PASS":
        blockers.append(f"contract_validation={contract_status or 'MISSING'}")
    if hard_stops:
        blockers.append(f"hard_stops={len(hard_stops)}")
    if render_blockers:
        blockers.append(f"render_blockers={len(render_blockers)}")
    if gate < 3:
        blockers.append(f"data_gate={gate:g}; Gate 3 required for partner-ready formal delivery")
    return {
        "eligible": not blockers,
        "data_gate": gate,
        "blockers": blockers,
    }


def summarize_contract(contract: dict[str, Any]) -> dict[str, Any]:
    confidence = contract.get("decision_confidence", {})
    if isinstance(confidence, dict):
        confidence = confidence.get("level")
    return {
        "company": contract.get("company"),
        "report_id": contract.get("report_id"),
        "contract_hash": contract.get("contract_hash"),
        "schema_version": contract.get("schema_version"),
        "data_gate": contract.get("data_gate", {}).get("level"),
        "decision_confidence": confidence,
        "current_action": contract.get("current_action"),
        "hard_stop_count": len(contract.get("hard_stops", [])),
        "warning_count": len(contract.get("warnings", [])),
        "contract_validation": contract.get("contract_validation", {}).get("status"),
    }


def run_analyze(
    company: str,
    output_root: Path,
    *,
    research_input: Path | None = None,
    pdf: bool = False,
    builder: Builder | None = None,
    renderer: Renderer | None = None,
    validator: Validator | None = None,
    skip_environment_check: bool = False,
) -> tuple[int, dict[str, Any]]:
    public_input_issues = public_research_input_issues(research_input)
    if public_input_issues:
        manifest = {
            "pipeline_schema_version": "1.0.0",
            "release_candidate": RELEASE_CANDIDATE,
            "generated_at": utc_now(),
            "status": "PUBLIC_INPUT_BLOCKED",
            "company_query": company,
            "issues": public_input_issues,
            "private_values_logged": False,
            "remediation": "Use only sourced public research assumptions here; process portfolio inputs through the repo-external Gate 4 workspace.",
        }
        diagnostic_path = output_root / "_diagnostics" / "public_input_diagnostic.json"
        write_json(diagnostic_path, manifest)
        manifest["manifest_path"] = portable_path(diagnostic_path, output_root)
        return 4, manifest

    environment = run_doctor(require_live=True, require_pdf=pdf)
    if environment["status"] == "FAIL" and not skip_environment_check:
        manifest = {
            "pipeline_schema_version": "1.0.0",
            "release_candidate": RELEASE_CANDIDATE,
            "generated_at": utc_now(),
            "status": "ENVIRONMENT_BLOCKED",
            "company_query": company,
            "environment": environment,
        }
        diagnostic_path = output_root / "_diagnostics" / "environment_diagnostic.json"
        write_json(diagnostic_path, manifest)
        manifest["manifest_path"] = portable_path(diagnostic_path, output_root)
        return 2, manifest

    if builder is None:
        from build_public_company_investment_layer import build_investment_layer

        builder = build_investment_layer
    if renderer is None:
        from render_public_company_artifacts import render

        renderer = render
    if validator is None:
        from validate_friday_v1_delivery import validate_delivery

        validator = validate_delivery

    try:
        step3_dir = builder(company, output_root, research_input)
    except Exception as exc:  # Public pipeline diagnostic; no private values are accepted above.
        manifest = {
            "pipeline_schema_version": "1.0.0",
            "release_candidate": RELEASE_CANDIDATE,
            "generated_at": utc_now(),
            "status": "BUILD_FAILED",
            "company_query": company,
            "error_type": type(exc).__name__,
            "error": safe_error_message(exc),
            "private_values_logged": False,
        }
        diagnostic_path = output_root / "_diagnostics" / "build_diagnostic.json"
        write_json(diagnostic_path, manifest)
        manifest["manifest_path"] = portable_path(diagnostic_path, output_root)
        return 4, manifest
    contract_path = step3_dir / "underwriting_output_contract.json"
    contract = read_json(contract_path)
    eligibility = delivery_eligibility(contract)
    delivery_dir = step3_dir.parent / "delivery"
    validation_path = delivery_dir / "validation_report.json"
    render_manifest: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None
    status = "RESEARCH_INPUT_REQUIRED"
    exit_code = 3

    if eligibility["eligible"]:
        try:
            validation = validator(contract, None)
        except Exception as exc:  # Defensive boundary around independent QA.
            validation = {
                "status": "ERROR",
                "failure_count": 1,
                "checks": [],
                "error_type": type(exc).__name__,
                "error": safe_error_message(exc),
            }
        write_json(validation_path, portable_manifest(validation, output_root))
        if validation.get("status") == "PASS":
            try:
                render_manifest = renderer(contract_path, delivery_dir, pdf=pdf)
                validation = validator(contract, delivery_dir)
            except Exception as exc:
                validation = {
                    "status": "ERROR",
                    "failure_count": 1,
                    "checks": [],
                    "error_type": type(exc).__name__,
                    "error": safe_error_message(exc),
                }
            write_json(validation_path, portable_manifest(validation, output_root))
            if render_manifest and render_manifest.get("manifest"):
                write_json(
                    Path(render_manifest["manifest"]),
                    portable_manifest(render_manifest, output_root),
                )
            status = "DELIVERY_READY" if validation.get("status") == "PASS" else "VALIDATION_FAILED"
            exit_code = 0 if status == "DELIVERY_READY" else 4
        else:
            status = "VALIDATION_FAILED"
            exit_code = 4
    else:
        diagnostic = {
            "status": "FORMAL_DELIVERY_BLOCKED",
            "reason": "The shared contract is preserved, but partner-ready reports require Gate 3 and passing validation.",
            "reason_zh": "共享 contract 已保存，但正式 Partner 报告必须达到 Gate 3 并通过验证。",
            "eligibility": eligibility,
            "analyst_input_template": portable_path(step3_dir / "analyst_input_template.json", output_root),
            "next_command": f"python underwrite.py analyze {shlex.quote(company)} --output-root <OUTPUT_ROOT> --research-input <COMPLETED_PUBLIC_RESEARCH_INPUT.json>",
        }
        write_json(delivery_dir / "pipeline_diagnostic.json", diagnostic)
        if contract.get("hard_stops") or contract.get("contract_validation", {}).get("status") != "PASS":
            status = "DATA_VALIDATION_BLOCKED"
            exit_code = 4

    manifest = {
        "pipeline_schema_version": "1.0.0",
        "release_candidate": RELEASE_CANDIDATE,
        "generated_at": utc_now(),
        "status": status,
        "company_query": company,
        "command": (
            f"python underwrite.py analyze {shlex.quote(company)} --output-root <OUTPUT_ROOT>"
            + (" --research-input <PUBLIC_RESEARCH_INPUT.json>" if research_input else "")
            + (" --pdf" if pdf else "")
        ),
        "public_only_boundary": "Gate 4 portfolio inputs are not accepted by this entry point.",
        "contract_path": portable_path(contract_path, output_root),
        "analyst_input_template": portable_path(step3_dir / "analyst_input_template.json", output_root),
        "delivery_dir": portable_path(delivery_dir, output_root),
        "eligibility": eligibility,
        "contract_summary": summarize_contract(contract),
        "render_manifest": portable_manifest(render_manifest, output_root),
        "validation_report": portable_path(validation_path, output_root) if validation is not None else None,
        "environment_status": environment["status"],
    }
    manifest_path = delivery_dir / "pipeline_manifest.json"
    write_json(manifest_path, manifest)
    manifest["manifest_path"] = portable_path(manifest_path, output_root)
    return exit_code, manifest


def run_render(contract_path: Path, out_dir: Path, *, pdf: bool = False) -> tuple[int, dict[str, Any]]:
    from render_public_company_artifacts import render
    from validate_friday_v1_delivery import validate_delivery

    contract = read_json(contract_path)
    eligibility = delivery_eligibility(contract)
    if not eligibility["eligible"]:
        payload = {"status": "FORMAL_DELIVERY_BLOCKED", "eligibility": eligibility}
        write_json(out_dir / "pipeline_diagnostic.json", payload)
        return 3, payload
    try:
        precheck = validate_delivery(contract, None)
    except Exception as exc:
        precheck = {
            "status": "ERROR",
            "failure_count": 1,
            "checks": [],
            "error_type": type(exc).__name__,
            "error": safe_error_message(exc),
        }
    if precheck.get("status") != "PASS":
        payload = {"status": "VALIDATION_FAILED", "validation": precheck}
        write_json(out_dir / "validation_report.json", portable_manifest(precheck, out_dir))
        return 4, payload
    try:
        manifest = render(contract_path, out_dir, pdf=pdf)
        validation = validate_delivery(contract, out_dir)
    except Exception as exc:
        validation = {
            "status": "ERROR",
            "failure_count": 1,
            "checks": [],
            "error_type": type(exc).__name__,
            "error": safe_error_message(exc),
        }
        write_json(out_dir / "validation_report.json", portable_manifest(validation, out_dir))
        return 4, {"status": "VALIDATION_FAILED", "validation": validation}
    if manifest.get("manifest"):
        write_json(Path(manifest["manifest"]), portable_manifest(manifest, out_dir))
    write_json(out_dir / "validation_report.json", portable_manifest(validation, out_dir))
    portable_render = portable_manifest(manifest, out_dir)
    portable_validation = portable_manifest(validation, out_dir)
    return (0 if validation.get("status") == "PASS" else 4), {
        "status": "DELIVERY_READY" if validation.get("status") == "PASS" else "VALIDATION_FAILED",
        "render_manifest": portable_render,
        "validation": portable_validation,
    }


def run_validate(contract_path: Path, html_dir: Path | None, output: Path | None) -> tuple[int, dict[str, Any]]:
    from validate_friday_v1_delivery import validate_delivery

    report = validate_delivery(read_json(contract_path), html_dir)
    portable_root = html_dir or (output.parent if output else ROOT)
    portable_report = portable_manifest(report, portable_root)
    if output:
        write_json(output, portable_report)
    return (0 if report.get("status") == "PASS" else 4), portable_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build, gate, render, and validate public-company underwriting outputs."
    )
    parser.add_argument("--version", action="version", version=RELEASE_CANDIDATE)
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Check environment and installation readiness.")
    doctor.add_argument("--live", action="store_true", help="Require SEC_USER_AGENT.")
    doctor.add_argument("--pdf", action="store_true", help="Require Chrome or Chromium.")
    doctor.add_argument("--ci", action="store_true", help="Use offline CI requirements.")
    doctor.add_argument("--output", type=Path)

    analyze = subparsers.add_parser("analyze", help="Build from ticker/company name and produce only gate-allowed outputs.")
    analyze.add_argument("company", help="Ticker or SEC company name, e.g. AAPL.")
    analyze.add_argument("--output-root", type=Path, default=ROOT / "outputs")
    analyze.add_argument("--research-input", type=Path, help="Completed public research-input JSON; never a private Gate 4 file.")
    analyze.add_argument("--pdf", action="store_true", help="Generate PDFs after Gate 3 and independent validation pass.")

    render = subparsers.add_parser("render", help="Render one already validated Gate 3 contract.")
    render.add_argument("contract", type=Path)
    render.add_argument("--out-dir", type=Path, required=True)
    render.add_argument("--pdf", action="store_true")

    validate = subparsers.add_parser("validate", help="Independently validate a contract and optional rendered directory.")
    validate.add_argument("contract", type=Path)
    validate.add_argument("--html-dir", type=Path)
    validate.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "doctor":
        result = run_doctor(require_live=args.live, require_pdf=args.pdf, ci=args.ci)
        if args.output:
            write_json(args.output, result)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["status"] != "FAIL" else 1
    if args.command == "analyze":
        code, result = run_analyze(
            args.company,
            args.output_root,
            research_input=args.research_input,
            pdf=args.pdf,
        )
    elif args.command == "render":
        code, result = run_render(args.contract, args.out_dir, pdf=args.pdf)
    else:
        code, result = run_validate(args.contract, args.html_dir, args.output)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
