#!/usr/bin/env python3
"""Independently validate a Friday V1 contract and its rendered artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import date
from pathlib import Path
from typing import Any

from underwriting_contract import canonical_json, validate_output_contract


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def close_enough(actual: Any, expected: Any, *, relative: float = 1e-9, absolute: float = 0.01) -> bool:
    try:
        return math.isclose(float(actual), float(expected), rel_tol=relative, abs_tol=absolute)
    except (TypeError, ValueError):
        return False


def is_iso_date(value: Any) -> bool:
    try:
        date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return False
    return True


def validate_delivery(contract: dict[str, Any], html_dir: Path | None = None) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(check_id: str, passed: bool, detail: str) -> None:
        checks.append({"check_id": check_id, "status": "PASS" if passed else "FAIL", "detail": detail})

    contract_errors = validate_output_contract(contract)
    check("contract-schema", not contract_errors, "; ".join(contract_errors) or "Shared contract validation passed.")
    check("hard-stops", not contract.get("hard_stops"), f"Hard Stops={len(contract.get('hard_stops', []))}.")

    hash_input = {key: value for key, value in contract.items() if key not in {"contract_hash", "contract_validation"}}
    expected_hash = hashlib.sha256(canonical_json(hash_input).encode("utf-8")).hexdigest()
    check("contract-hash", contract.get("contract_hash") == expected_hash, "Stored hash matches the canonical validated object.")

    dates = contract.get("report_dates", {})
    for field in (
        "financial_statement_date",
        "market_price_date",
        "share_count_date",
        "subsequent_event_index_review_through",
    ):
        check(f"date-{field}", is_iso_date(dates.get(field)), f"{field}={dates.get(field)}")

    valuation = contract.get("valuation", {})
    share_basis = contract.get("share_count_basis", {})
    price = valuation.get("price")
    shares = share_basis.get("share_count_value")
    expected_market_cap = float(price) * float(shares) if price is not None and shares is not None else None
    check(
        "market-cap-reproduction",
        close_enough(valuation.get("market_cap"), expected_market_cap),
        f"market_cap={valuation.get('market_cap')}; price={price}; shares={shares}",
    )
    check(
        "market-price-date-alignment",
        valuation.get("price_date") == dates.get("market_price_date"),
        f"valuation={valuation.get('price_date')}; registry={dates.get('market_price_date')}",
    )
    check(
        "share-date-alignment",
        share_basis.get("share_count_date") == valuation.get("shares_as_of_date") == dates.get("share_count_date"),
        f"basis={share_basis.get('share_count_date')}; valuation={valuation.get('shares_as_of_date')}; registry={dates.get('share_count_date')}",
    )
    proxy_required = (
        share_basis.get("share_count_date") != dates.get("market_price_date")
        and share_basis.get("forward_share_count_bridge_status") != "COMPLETED"
    )
    check(
        "share-proxy",
        not proxy_required or share_basis.get("proxy_status") == "PROXY",
        f"proxy_required={proxy_required}; proxy_status={share_basis.get('proxy_status')}",
    )

    metric_map = {
        str(row.get("metric_name")): row
        for row in contract.get("evidence_records", [])
        if row.get("metric_name")
    }
    fcf = contract.get("fcf_underwriting_base", {})
    reported_fcf = metric_map.get("reported_ltm_fcf", {}).get("value")
    adjustments = sum(float(row.get("amount") or 0) for row in fcf.get("bridge_lines", []))
    check(
        "fcf-bridge-reproduction",
        close_enough(fcf.get("value"), float(reported_fcf) + adjustments if reported_fcf is not None else None),
        f"reported={reported_fcf}; adjustments={adjustments}; base={fcf.get('value')}",
    )
    check(
        "fcf-period-alignment",
        fcf.get("period_end") == dates.get("financial_statement_date"),
        f"FCF={fcf.get('period_end')}; financials={dates.get('financial_statement_date')}",
    )

    reverse = contract.get("valuation_framework", {}).get("reverse_valuation", {})
    required_fcf = float(valuation.get("market_cap")) / float(reverse.get("selected_multiple"))
    check(
        "reverse-valuation-reproduction",
        close_enough(reverse.get("required_metric_value"), required_fcf),
        f"required={reverse.get('required_metric_value')}; recomputed={required_fcf}",
    )
    priced = contract.get("what_is_priced_in", {})
    check(
        "priced-in-reproduction",
        close_enough(priced.get("required_fcf"), required_fcf)
        and close_enough(priced.get("difference"), required_fcf - float(fcf.get("value"))),
        f"priced_required={priced.get('required_fcf')}; priced_difference={priced.get('difference')}",
    )

    for scenario in contract.get("scenarios", []):
        name = str(scenario.get("name") or "").lower()
        metric_value = metric_map.get(f"scenario_{name}_metric_value", {}).get("value")
        implied = float(metric_value) * float(scenario.get("exit_multiple")) / float(shares)
        change = implied / float(price) - 1
        check(
            f"scenario-{name}-implied-price",
            close_enough(scenario.get("implied_price"), implied),
            f"stored={scenario.get('implied_price')}; recomputed={implied}",
        )
        check(
            f"scenario-{name}-price-change",
            close_enough(scenario.get("price_change_vs_current"), change),
            f"stored={scenario.get('price_change_vs_current')}; recomputed={change}",
        )
        check(
            f"scenario-{name}-legacy-fields",
            "target_price" not in scenario and "total_return" not in scenario,
            "Only implied_price and price_change_vs_current are permitted without a horizon.",
        )

    legacy_metrics = [
        name
        for name in metric_map
        if name == "normalized_fcf_analyst_validated"
        or (name.startswith("scenario_") and name.endswith("_target_price"))
        or (name.startswith("scenario_") and name.endswith("_total_return"))
    ]
    check("legacy-metric-names", not legacy_metrics, f"legacy={legacy_metrics}")
    return_context = contract.get("return_context", {})
    if not return_context.get("formal_return_language_allowed"):
        check(
            "formal-return-suppression",
            contract.get("probability_weighted_expected_return") is None and contract.get("target_price") is None,
            "Formal expected-return and target outputs are null without a validated horizon.",
        )
    check(
        "portfolio-boundary",
        contract.get("position_sizing") is None
        and contract.get("portfolio_action") == "Not Evaluated"
        and contract.get("portfolio_context", {}).get("status") == "DISABLED",
        "Portfolio overlay remains disabled and no sizing is present.",
    )

    raw_ids = {str(row.get("evidence_id")) for row in contract.get("evidence_records", []) if row.get("evidence_id")}
    mapped_ids = {str(row.get("evidence_id")) for row in contract.get("evidence_display_index", []) if row.get("evidence_id")}
    check("evidence-alias-completeness", raw_ids == mapped_ids, f"raw={len(raw_ids)}; mapped={len(mapped_ids)}")

    if html_dir:
        ticker = str(contract.get("company", {}).get("ticker") or "").upper()
        one = html_dir / f"{ticker}_One_Page_Summary_Bilingual.html"
        full = html_dir / f"{ticker}_Full_Report_Bilingual.html"
        appendix = html_dir / f"{ticker}_Evidence_Audit_Appendix_Bilingual.html"
        for label, path in (("one-page", one), ("full-report", full), ("evidence-appendix", appendix)):
            check(f"artifact-{label}-exists", path.exists(), str(path))
        if one.exists() and full.exists() and appendix.exists():
            one_text = one.read_text(encoding="utf-8")
            full_text = full.read_text(encoding="utf-8")
            appendix_text = appendix.read_text(encoding="utf-8")
            check("one-page-no-raw-evidence", "EV-" not in one_text, "One-Page contains no raw evidence IDs.")
            check("full-report-no-raw-evidence", "EV-" not in full_text, "Full Report contains no raw evidence IDs.")
            check("appendix-preserves-raw-evidence", "EV-" in appendix_text, "Audit appendix contains raw evidence IDs.")
            for artifact_name, text in (("one-page", one_text), ("full-report", full_text)):
                check(
                    f"{artifact_name}-contract-identity",
                    str(contract.get("report_id")) in text and str(contract.get("contract_hash")) in text,
                    "Report ID and full contract hash are embedded.",
                )

    failures = [row for row in checks if row["status"] == "FAIL"]
    return {
        "status": "PASS" if not failures else "FAIL",
        "company": contract.get("company"),
        "report_id": contract.get("report_id"),
        "contract_hash": contract.get("contract_hash"),
        "check_count": len(checks),
        "failure_count": len(failures),
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a Friday V1 contract and optional rendered HTML directory.")
    parser.add_argument("contract", help="Friday V1 underwriting_output_contract.json")
    parser.add_argument("--html-dir", help="Optional rendered artifact directory")
    parser.add_argument("--output", help="Optional JSON validation-report path")
    args = parser.parse_args()
    report = validate_delivery(read_json(Path(args.contract)), Path(args.html_dir) if args.html_dir else None)
    serialized = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding="utf-8")
    print(serialized)
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
