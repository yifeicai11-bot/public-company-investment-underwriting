#!/usr/bin/env python3
"""Gate 4 private-input contracts and privacy-safe validation.

Raw portfolio values remain in memory. Validation results identify fields and
checks without copying policy values, holdings, or opportunity-set rows into
diagnostic output.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Callable

try:
    import yaml
except ImportError:  # pragma: no cover - exercised through dependency diagnostics
    yaml = None

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:  # pragma: no cover - exercised through dependency diagnostics
    Draft202012Validator = None
    FormatChecker = None

try:
    from openpyxl import load_workbook
except ImportError:  # pragma: no cover - exercised through dependency diagnostics
    load_workbook = None


SCRIPT_DIR = Path(__file__).resolve().parent
GATE4_DIR = SCRIPT_DIR.parent / "gate4"
SCHEMA_DIR = GATE4_DIR / "schemas"
PRIVATE_INPUT_CONTRACT_VERSION = "1.0.0"
FRAMEWORK_STATUS = "GATE_4_FRAMEWORK_READY"
INPUT_STATUS_REQUIRED = "GATE_4_PRIVATE_INPUTS_REQUIRED"
INPUT_STATUS_VALIDATED = "GATE_4_INPUTS_VALIDATED"
SUPPORTED_CLASSIFICATIONS = {"PRIVATE_PORTFOLIO", "SYNTHETIC_PUBLIC_EXAMPLE"}
ALLOWED_DECISIONS = {
    "PENDING",
    "APPROVED",
    "APPROVED_WITH_MODIFICATION",
    "REJECTED",
    "DEFERRED",
}


@dataclass
class PrivateInputCheck:
    check_id: str
    document: str
    status: str
    issue_class: str
    field: str
    row_number: int | None
    message: str
    remediation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PrivateInputBundle:
    manifest: dict[str, Any]
    policy: dict[str, Any]
    holdings: list[dict[str, Any]]
    opportunities: list[dict[str, Any]]
    approval: dict[str, Any]
    freshness_attestation: dict[str, Any]
    manifest_path: Path
    output_dir: Path


class PrivateInputLoadError(ValueError):
    """Raised with a sanitized message that contains no private values."""


if yaml is not None:
    class UniqueKeySafeLoader(yaml.SafeLoader):
        pass


    def _construct_unique_mapping(loader: Any, node: Any, deep: bool = False) -> dict[Any, Any]:
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in mapping:
                raise PrivateInputLoadError("The YAML mapping contains a duplicate key.")
            mapping[key] = loader.construct_object(value_node, deep=deep)
        return mapping


    UniqueKeySafeLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        _construct_unique_mapping,
    )


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    text = str(value).strip().replace(",", "")
    try:
        parsed = float(text)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def parse_ratio(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, str) and value.strip().endswith("%"):
        parsed = parse_number(value.strip()[:-1])
        return parsed / 100 if parsed is not None else None
    return parse_number(value)


def parse_integer(value: Any) -> int | None:
    parsed = parse_number(value)
    if parsed is None or not float(parsed).is_integer():
        return None
    return int(parsed)


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def read_mapping(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PrivateInputLoadError("The mapping file could not be read.") from exc
    try:
        if suffix == ".json":
            def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
                mapping: dict[str, Any] = {}
                for key, value in pairs:
                    if key in mapping:
                        raise PrivateInputLoadError(
                            "The JSON object contains a duplicate key."
                        )
                    mapping[key] = value
                return mapping

            payload = json.loads(text, object_pairs_hook=unique_pairs)
        elif suffix in {".yaml", ".yml"}:
            if yaml is None:
                raise PrivateInputLoadError(
                    "YAML support is unavailable; install requirements-gate4.txt."
                )
            payload = yaml.load(text, Loader=UniqueKeySafeLoader)
        else:
            raise PrivateInputLoadError("Only JSON and YAML mapping files are supported.")
    except PrivateInputLoadError:
        raise
    except (json.JSONDecodeError, getattr(yaml, "YAMLError", ValueError)) as exc:
        raise PrivateInputLoadError("The mapping file is not valid JSON or YAML.") from exc
    if not isinstance(payload, dict):
        raise PrivateInputLoadError("The mapping file must contain one object.")
    return payload


def _csv_rows(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise PrivateInputLoadError("The table has no header row.")
            headers = [str(value).strip() for value in reader.fieldnames]
            if any(not header for header in headers) or len(headers) != len(set(headers)):
                raise PrivateInputLoadError(
                    "Every CSV header must be populated and unique."
                )
            rows: list[dict[str, Any]] = []
            for row in reader:
                if None in row and any(
                    clean_text(value) is not None for value in (row.get(None) or [])
                ):
                    raise PrivateInputLoadError(
                        "A CSV row contains values beyond the declared header."
                    )
                cleaned = {
                    str(key).strip(): clean_text(value)
                    for key, value in row.items()
                    if key is not None
                }
                if any(value is not None for value in cleaned.values()):
                    rows.append(cleaned)
            return rows
    except UnicodeDecodeError as exc:
        raise PrivateInputLoadError("The CSV file must use UTF-8 encoding.") from exc
    except OSError as exc:
        raise PrivateInputLoadError("The CSV file could not be read.") from exc


def _xlsx_rows(path: Path) -> list[dict[str, Any]]:
    if load_workbook is None:
        raise PrivateInputLoadError(
            "Excel support is unavailable; install requirements-gate4.txt."
        )
    try:
        workbook = load_workbook(path, read_only=True, data_only=False)
    except (OSError, ValueError) as exc:
        raise PrivateInputLoadError("The Excel workbook could not be read.") from exc
    try:
        worksheet = workbook.active
        raw_rows = list(worksheet.iter_rows())
        if not raw_rows:
            raise PrivateInputLoadError("The table has no header row.")
        if any(
            getattr(cell, "data_type", None) == "f"
            for cells in raw_rows
            for cell in cells
        ):
            raise PrivateInputLoadError(
                "Spreadsheet formulas are prohibited in Gate 4 input tables."
            )
        headers = [clean_text(cell.value) for cell in raw_rows[0]]
        if (
            not headers
            or any(header is None for header in headers)
            or len(headers) != len(set(headers))
        ):
            raise PrivateInputLoadError(
                "Every Excel header cell must be populated and unique."
            )
        rows: list[dict[str, Any]] = []
        for cells in raw_rows[1:]:
            values = [cell.value for cell in cells]
            if not any(clean_text(value) is not None for value in values):
                continue
            rows.append(
                {
                    str(header): clean_text(value) if isinstance(value, str) else value
                    for header, value in zip(headers, values)
                }
            )
        return rows
    finally:
        workbook.close()


def read_table(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _csv_rows(path)
    if suffix == ".xlsx":
        return _xlsx_rows(path)
    raise PrivateInputLoadError("Only CSV and XLSX table files are supported.")


def normalize_holding_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    for field in (
        "position_weight",
        "market_value_base_currency",
        "average_daily_value_traded",
        "estimated_days_to_exit",
        "hedge_ratio",
    ):
        parser = parse_ratio if field in {"position_weight", "hedge_ratio"} else parse_number
        normalized[field] = parser(row.get(field))
    normalized["existing_hedge_identifier"] = clean_text(row.get("existing_hedge_identifier"))
    return normalized


def normalize_opportunity_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    for field in ("expected_return", "bear_case_downside"):
        normalized[field] = parse_ratio(row.get(field))
    normalized["holding_period_days"] = parse_integer(row.get("holding_period_days"))
    normalized["estimated_days_to_exit"] = parse_number(row.get("estimated_days_to_exit"))
    normalized["source_contract_hash"] = clean_text(row.get("source_contract_hash"))
    return normalized


def load_schema(name: str) -> dict[str, Any]:
    path = SCHEMA_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


def _field_path(error: Any) -> str:
    parts = [str(value) for value in error.absolute_path]
    if error.validator == "required" and isinstance(error.validator_value, list):
        missing = [
            str(field)
            for field in error.validator_value
            if not isinstance(error.instance, dict) or field not in error.instance
        ]
        if missing:
            parts.append(",".join(sorted(missing)))
    return ".".join(parts) or "<document>"


def schema_checks(
    document: str,
    instance: Any,
    schema_name: str,
    *,
    row_number: int | None = None,
) -> list[PrivateInputCheck]:
    if Draft202012Validator is None or FormatChecker is None:
        return [
            PrivateInputCheck(
                check_id=f"G4I-{document}-dependency",
                document=document,
                status="FAIL",
                issue_class="HARD_STOP",
                field="<dependency>",
                row_number=row_number,
                message="JSON Schema validation is unavailable.",
                remediation="Install requirements-gate4.txt before validating private inputs.",
            )
        ]
    schema = load_schema(schema_name)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(
        validator.iter_errors(instance),
        key=lambda error: (
            tuple(str(value) for value in error.absolute_path),
            str(error.validator),
        ),
    )
    if not errors:
        return [
            PrivateInputCheck(
                check_id=f"G4I-{document}-schema",
                document=document,
                status="PASS",
                issue_class="INFO",
                field="<document>",
                row_number=row_number,
                message="Schema validation passed.",
                remediation="None.",
            )
        ]
    checks: list[PrivateInputCheck] = []
    for index, error in enumerate(errors, start=1):
        field = _field_path(error)
        checks.append(
            PrivateInputCheck(
                check_id=f"G4I-{document}-schema-{row_number or 0}-{index}",
                document=document,
                status="FAIL",
                issue_class="HARD_STOP",
                field=field,
                row_number=row_number,
                message=f"Schema rule `{error.validator}` failed for `{field}`.",
                remediation="Correct the named field using the public field-definition guide.",
            )
        )
    return checks


def add_check(
    checks: list[PrivateInputCheck],
    *,
    check_id: str,
    document: str,
    passed: bool,
    field: str,
    message_pass: str,
    message_fail: str,
    remediation: str,
    row_number: int | None = None,
    issue_class: str = "HARD_STOP",
) -> None:
    checks.append(
        PrivateInputCheck(
            check_id=check_id,
            document=document,
            status="PASS" if passed else "FAIL",
            issue_class="INFO" if passed else issue_class,
            field=field,
            row_number=row_number,
            message=message_pass if passed else message_fail,
            remediation="None." if passed else remediation,
        )
    )


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def resolve_manifest_path(base: Path, relative_value: Any, *, output: bool = False) -> Path:
    text = clean_text(relative_value)
    if not text:
        raise PrivateInputLoadError("A required manifest file path is missing.")
    relative = Path(text)
    if relative.is_absolute() or ".." in relative.parts:
        raise PrivateInputLoadError("Manifest paths must be relative and cannot traverse directories.")
    resolved = (base / relative).resolve()
    if not _is_within(resolved, base.resolve()):
        raise PrivateInputLoadError("Manifest paths must remain inside the selected private workspace.")
    if not output and not resolved.is_file():
        raise PrivateInputLoadError("A required private input file is missing.")
    return resolved


def _load_bundle_documents(
    manifest_path: Path,
    manifest: dict[str, Any],
    checks: list[PrivateInputCheck],
) -> PrivateInputBundle | None:
    base = manifest_path.resolve().parent
    files = manifest.get("files")
    if not isinstance(files, dict):
        return None
    loaders: dict[str, tuple[str, Callable[[Path], Any]]] = {
        "portfolio_policy": ("policy", read_mapping),
        "current_holdings": ("holdings", read_table),
        "opportunity_set": ("opportunities", read_table),
        "approval_config": ("approval", read_mapping),
        "gate3_freshness_attestation": ("freshness_attestation", read_mapping),
    }
    loaded: dict[str, Any] = {}
    for manifest_field, (document, loader) in loaders.items():
        try:
            path = resolve_manifest_path(base, files.get(manifest_field))
            loaded[document] = loader(path)
        except PrivateInputLoadError as exc:
            checks.append(
                PrivateInputCheck(
                    check_id=f"G4I-{document}-load",
                    document=document,
                    status="FAIL",
                    issue_class="HARD_STOP",
                    field=f"files.{manifest_field}",
                    row_number=None,
                    message=str(exc),
                    remediation="Restore the required local file using the public template.",
                )
            )
    try:
        output_dir = resolve_manifest_path(base, files.get("private_output_dir"), output=True)
    except PrivateInputLoadError as exc:
        checks.append(
            PrivateInputCheck(
                check_id="G4I-private-output-dir",
                document="manifest",
                status="FAIL",
                issue_class="HARD_STOP",
                field="files.private_output_dir",
                row_number=None,
                message=str(exc),
                remediation="Use a relative private output directory inside the private workspace.",
            )
        )
        return None
    required_loaded = {
        "policy",
        "holdings",
        "opportunities",
        "approval",
        "freshness_attestation",
    }
    if not required_loaded.issubset(loaded):
        return None
    return PrivateInputBundle(
        manifest=manifest,
        policy=loaded["policy"],
        holdings=[normalize_holding_row(row) for row in loaded["holdings"]],
        opportunities=[normalize_opportunity_row(row) for row in loaded["opportunities"]],
        approval=loaded["approval"],
        freshness_attestation=loaded["freshness_attestation"],
        manifest_path=manifest_path.resolve(),
        output_dir=output_dir,
    )


def _validate_document_schemas(
    bundle: PrivateInputBundle,
    checks: list[PrivateInputCheck],
) -> None:
    checks.extend(schema_checks("policy", bundle.policy, "portfolio_policy.schema.json"))
    checks.extend(schema_checks("approval", bundle.approval, "approval_config.schema.json"))
    checks.extend(
        schema_checks(
            "freshness",
            bundle.freshness_attestation,
            "gate3_freshness_attestation.schema.json",
        )
    )
    if not bundle.holdings:
        checks.append(
            PrivateInputCheck(
                "G4I-holdings-empty",
                "holdings",
                "FAIL",
                "HARD_STOP",
                "<rows>",
                None,
                "The holdings table contains no positions.",
                "Provide the complete dated portfolio, including cash and hedges where applicable.",
            )
        )
    for index, row in enumerate(bundle.holdings, start=2):
        checks.extend(
            schema_checks(
                "holdings",
                row,
                "holding_row.schema.json",
                row_number=index,
            )
        )
    if not bundle.opportunities:
        checks.append(
            PrivateInputCheck(
                "G4I-opportunities-empty",
                "opportunities",
                "FAIL",
                "HARD_STOP",
                "<rows>",
                None,
                "The opportunity-set table contains no alternatives.",
                "Provide a dated local opportunity set; missing opportunity cost is NOT_EVALUATED.",
            )
        )
    for index, row in enumerate(bundle.opportunities, start=2):
        checks.extend(
            schema_checks(
                "opportunities",
                row,
                "opportunity_row.schema.json",
                row_number=index,
            )
        )


def _classification_and_date_checks(
    bundle: PrivateInputBundle,
    checks: list[PrivateInputCheck],
) -> None:
    classification = bundle.manifest.get("data_classification")
    documents: list[tuple[str, Any]] = [
        ("policy", bundle.policy),
        ("approval", bundle.approval),
        ("freshness", bundle.freshness_attestation),
    ]
    documents.extend(("holdings", row) for row in bundle.holdings)
    documents.extend(("opportunities", row) for row in bundle.opportunities)
    mismatches = [
        document
        for document, payload in documents
        if not isinstance(payload, dict) or payload.get("data_classification") != classification
    ]
    add_check(
        checks,
        check_id="G4I-classification-consistency",
        document="bundle",
        passed=classification in SUPPORTED_CLASSIFICATIONS and not mismatches,
        field="data_classification",
        message_pass="Data classification is consistent across all private-input documents.",
        message_fail="Data classification is missing, unsupported, or inconsistent across documents.",
        remediation="Use one classification across the manifest and every referenced document.",
    )

    as_of_date = bundle.manifest.get("as_of_date")
    date_mismatches = [
        document
        for document, payload in documents
        if not isinstance(payload, dict) or payload.get("as_of_date") != as_of_date
    ]
    add_check(
        checks,
        check_id="G4I-as-of-date-consistency",
        document="bundle",
        passed=parse_date(as_of_date) is not None and not date_mismatches,
        field="as_of_date",
        message_pass="All portfolio inputs use the manifest as-of date.",
        message_fail="One or more private inputs use a different or invalid as-of date.",
        remediation="Align policy, holdings, opportunity set, freshness attestation, and manifest dates.",
    )


def _policy_checks(bundle: PrivateInputBundle, checks: list[PrivateInputCheck]) -> None:
    policy = bundle.policy
    manifest = bundle.manifest
    as_of_date = parse_date(manifest.get("as_of_date"))
    expiration = parse_date(policy.get("expiration_review_date"))
    reviewed_at = parse_datetime(policy.get("reviewed_at"))
    chronology_valid = (
        as_of_date is not None
        and expiration is not None
        and expiration >= as_of_date
        and reviewed_at is not None
        and reviewed_at.date() <= as_of_date
    )
    add_check(
        checks,
        check_id="G4I-policy-chronology",
        document="policy",
        passed=chronology_valid,
        field="expiration_review_date,reviewed_at",
        message_pass="Policy review and expiration dates are chronologically valid.",
        message_fail="Policy review or expiration chronology is invalid.",
        remediation="Use a review timestamp no later than the as-of date and a non-expired review date.",
    )
    add_check(
        checks,
        check_id="G4I-policy-base-currency",
        document="policy",
        passed=policy.get("base_currency") == manifest.get("base_currency"),
        field="base_currency",
        message_pass="Policy and manifest base currencies match.",
        message_fail="Policy and manifest base currencies do not match.",
        remediation="Convert holdings to one base currency and use it consistently.",
    )
    hedge_instruments = policy.get("permitted_hedge_instruments")
    maximum_hedge_ratio = parse_ratio(policy.get("maximum_hedge_ratio"))
    hedge_policy_valid = (
        isinstance(hedge_instruments, list)
        and maximum_hedge_ratio is not None
        and (maximum_hedge_ratio == 0 or bool(hedge_instruments))
    )
    add_check(
        checks,
        check_id="G4I-hedge-policy-completeness",
        document="policy",
        passed=hedge_policy_valid,
        field="permitted_hedge_instruments,maximum_hedge_ratio",
        message_pass="Hedge permissions and maximum ratio are internally consistent.",
        message_fail="A positive hedge ratio requires at least one explicitly permitted instrument.",
        remediation="List permitted hedge instruments or set the maximum hedge ratio to zero.",
    )


def _holding_checks(bundle: PrivateInputBundle, checks: list[PrivateInputCheck]) -> None:
    manifest = bundle.manifest
    tolerance = parse_number(manifest.get("weight_reconciliation_tolerance"))
    nav = parse_number(manifest.get("portfolio_nav"))
    base_currency = manifest.get("base_currency")
    position_ids = [clean_text(row.get("position_id")) for row in bundle.holdings]
    duplicate_ids = len(position_ids) != len(set(position_ids))
    add_check(
        checks,
        check_id="G4I-holdings-position-id-uniqueness",
        document="holdings",
        passed=bool(position_ids) and not duplicate_ids and None not in position_ids,
        field="position_id",
        message_pass="Holding position IDs are present and unique.",
        message_fail="Holding position IDs are missing or duplicated.",
        remediation="Assign one stable unique position_id to every row.",
    )
    currency_consistent = all(row.get("base_currency") == base_currency for row in bundle.holdings)
    add_check(
        checks,
        check_id="G4I-holdings-base-currency",
        document="holdings",
        passed=currency_consistent,
        field="base_currency",
        message_pass="Every holding uses the manifest base currency.",
        message_fail="One or more holdings use a different base currency.",
        remediation="Convert every market value to the manifest base currency before validation.",
    )

    weights = [parse_ratio(row.get("position_weight")) for row in bundle.holdings]
    weight_total_valid = (
        tolerance is not None
        and all(value is not None for value in weights)
        and abs(sum(value for value in weights if value is not None) - 1.0) <= tolerance
    )
    add_check(
        checks,
        check_id="G4I-holdings-weight-reconciliation",
        document="holdings",
        passed=weight_total_valid,
        field="position_weight",
        message_pass="Full-portfolio weights reconcile to 100% within the explicit tolerance.",
        message_fail="Full-portfolio weights do not reconcile within the explicit tolerance.",
        remediation="Include all positions and cash, then reconcile signed weights to portfolio NAV.",
    )

    for index, row in enumerate(bundle.holdings, start=2):
        weight = parse_ratio(row.get("position_weight"))
        market_value = parse_number(row.get("market_value_base_currency"))
        row_reconciles = (
            nav is not None
            and nav > 0
            and tolerance is not None
            and weight is not None
            and market_value is not None
            and abs(market_value / nav - weight) <= tolerance
        )
        add_check(
            checks,
            check_id=f"G4I-holdings-nav-reconciliation-{index}",
            document="holdings",
            passed=row_reconciles,
            field="position_weight,market_value_base_currency",
            row_number=index,
            message_pass="The row weight reconciles to base-currency market value and NAV.",
            message_fail="The row weight does not reconcile to base-currency market value and NAV.",
            remediation="Correct the row weight or base-currency market value.",
        )
        side = row.get("position_side")
        sign_valid = (
            weight is not None
            and (
                (side in {"LONG", "CASH"} and weight >= 0)
                or (side == "SHORT" and weight <= 0)
                or side == "HEDGE"
            )
        )
        add_check(
            checks,
            check_id=f"G4I-holdings-side-sign-{index}",
            document="holdings",
            passed=sign_valid,
            field="position_side,position_weight",
            row_number=index,
            message_pass="Position side and signed weight are consistent.",
            message_fail="Position side and signed weight are inconsistent.",
            remediation="Use nonnegative LONG/CASH weights and nonpositive SHORT weights.",
        )
        hedge_ratio = parse_ratio(row.get("hedge_ratio"))
        hedge_reference_valid = (
            hedge_ratio is not None
            and (
                hedge_ratio == 0
                or clean_text(row.get("existing_hedge_identifier")) is not None
                or side == "HEDGE"
            )
        )
        add_check(
            checks,
            check_id=f"G4I-holdings-hedge-reference-{index}",
            document="holdings",
            passed=hedge_reference_valid,
            field="existing_hedge_identifier,hedge_ratio",
            row_number=index,
            message_pass="Hedge ratio and hedge reference are consistent.",
            message_fail="A nonzero hedge ratio lacks a hedge identifier.",
            remediation="Provide the existing hedge identifier or set hedge_ratio to zero.",
        )


def _opportunity_checks(bundle: PrivateInputBundle, checks: list[PrivateInputCheck]) -> None:
    opportunity_ids = [clean_text(row.get("opportunity_id")) for row in bundle.opportunities]
    unique_ids = len(opportunity_ids) == len(set(opportunity_ids)) and None not in opportunity_ids
    add_check(
        checks,
        check_id="G4I-opportunity-id-uniqueness",
        document="opportunities",
        passed=bool(opportunity_ids) and unique_ids,
        field="opportunity_id",
        message_pass="Opportunity IDs are present and unique.",
        message_fail="Opportunity IDs are missing or duplicated.",
        remediation="Assign one stable unique opportunity_id to every row.",
    )
    required_count = parse_integer(
        bundle.policy.get("opportunity_cost_requirement", {}).get(
            "minimum_comparable_opportunities"
        )
    )
    validated_active_count = sum(
        1
        for row in bundle.opportunities
        if row.get("opportunity_status") == "ACTIVE"
        and row.get("return_status") == "VALIDATED"
        and parse_ratio(row.get("expected_return")) is not None
        and parse_ratio(row.get("bear_case_downside")) is not None
    )
    comparable_set_ready = (
        required_count is not None and validated_active_count >= required_count
    )
    add_check(
        checks,
        check_id="G4I-opportunity-cost-readiness",
        document="opportunities",
        passed=comparable_set_ready,
        field="return_status,opportunity_status",
        message_pass="The opportunity set contains the required validated active alternatives.",
        message_fail="The opportunity set lacks the required validated active alternatives.",
        remediation="Add dated alternatives with validated return and downside inputs; otherwise opportunity cost is NOT_EVALUATED.",
    )


def _approval_checks(
    bundle: PrivateInputBundle,
    checks: list[PrivateInputCheck],
    *,
    system_assessment_ready: bool,
) -> None:
    approval = bundle.approval
    manifest_as_of = parse_date(bundle.manifest.get("as_of_date"))
    approval_reviewed_at = parse_datetime(approval.get("reviewed_at"))
    add_check(
        checks,
        check_id="G4I-approval-review-chronology",
        document="approval",
        passed=(
            manifest_as_of is not None
            and approval_reviewed_at is not None
            and approval_reviewed_at.date() <= manifest_as_of
        ),
        field="reviewed_at",
        message_pass="Approval configuration review date is valid for the manifest date.",
        message_fail="Approval configuration review date is invalid for the manifest date.",
        remediation="Use a review timestamp no later than the workspace as-of date.",
    )
    allowed = set(approval.get("allowed_decisions", []))
    add_check(
        checks,
        check_id="G4I-approval-decision-set",
        document="approval",
        passed=allowed == ALLOWED_DECISIONS,
        field="allowed_decisions",
        message_pass="The complete controlled Partner decision set is configured.",
        message_fail="The configured Partner decision set is incomplete or unsupported.",
        remediation="Use exactly PENDING, APPROVED, APPROVED_WITH_MODIFICATION, REJECTED, and DEFERRED.",
    )
    decision = approval.get("partner_decision", {})
    status = decision.get("status") if isinstance(decision, dict) else None
    approved_by = clean_text(decision.get("approved_by")) if isinstance(decision, dict) else None
    approved_at = parse_datetime(decision.get("approved_at")) if isinstance(decision, dict) else None
    rationale = clean_text(decision.get("decision_rationale")) if isinstance(decision, dict) else None
    minimum = parse_ratio(decision.get("approved_position_min")) if isinstance(decision, dict) else None
    maximum = parse_ratio(decision.get("approved_position_max")) if isinstance(decision, dict) else None
    if status == "PENDING":
        decision_valid = all(value is None for value in (approved_by, approved_at, rationale, minimum, maximum))
    elif status in {"APPROVED", "APPROVED_WITH_MODIFICATION"}:
        decision_valid = (
            approved_by is not None
            and approved_at is not None
            and rationale is not None
            and minimum is not None
            and maximum is not None
            and 0 <= minimum <= maximum <= 1
            and manifest_as_of is not None
            and approved_at.date() <= manifest_as_of
        )
    elif status in {"REJECTED", "DEFERRED"}:
        decision_valid = (
            approved_by is not None
            and approved_at is not None
            and rationale is not None
            and minimum is None
            and maximum is None
            and manifest_as_of is not None
            and approved_at.date() <= manifest_as_of
        )
    else:
        decision_valid = False
    add_check(
        checks,
        check_id="G4I-partner-decision-completeness",
        document="approval",
        passed=decision_valid,
        field="partner_decision",
        message_pass="Partner decision fields are complete for the selected status.",
        message_fail="Partner decision fields are inconsistent with the selected status.",
        remediation="Keep all approval details null while pending; otherwise provide the required named approval record.",
    )
    add_check(
        checks,
        check_id="G4I-preassessment-decision-boundary",
        document="approval",
        passed=system_assessment_ready or status == "PENDING",
        field="partner_decision.status",
        message_pass="Partner decision status is valid for the current workflow stage.",
        message_fail="A Partner decision cannot be approved before the system assessment is ready.",
        remediation="Keep partner_decision.status as PENDING until the Gate 4 system assessment is complete.",
    )
    add_check(
        checks,
        check_id="G4I-no-automatic-trade",
        document="approval",
        passed=approval.get("automatic_trade_execution") is False,
        field="automatic_trade_execution",
        message_pass="Automatic trade execution is disabled.",
        message_fail="Automatic trade execution must remain disabled.",
        remediation="Set automatic_trade_execution to false.",
    )
    add_check(
        checks,
        check_id="G4I-external-transmission-denied",
        document="approval",
        passed=approval.get("external_transmission_policy") == "DENY",
        field="external_transmission_policy",
        message_pass="External transmission is denied by default.",
        message_fail="External transmission must be DENY for the local Gate 4 workflow.",
        remediation="Set external_transmission_policy to DENY.",
    )


def validate_private_input_bundle(
    bundle: PrivateInputBundle,
    *,
    existing_checks: list[PrivateInputCheck] | None = None,
    system_assessment_ready: bool = False,
) -> dict[str, Any]:
    checks = list(existing_checks or [])
    _validate_document_schemas(bundle, checks)
    _classification_and_date_checks(bundle, checks)
    _policy_checks(bundle, checks)
    _holding_checks(bundle, checks)
    _opportunity_checks(bundle, checks)
    _approval_checks(
        bundle,
        checks,
        system_assessment_ready=system_assessment_ready,
    )
    failed = [check for check in checks if check.status in {"FAIL", "MISSING", "BLOCKED"}]
    status = INPUT_STATUS_VALIDATED if not failed else INPUT_STATUS_REQUIRED
    classification = bundle.manifest.get("data_classification")
    return {
        "private_input_contract_version": PRIVATE_INPUT_CONTRACT_VERSION,
        "framework_status": FRAMEWORK_STATUS,
        "status": status,
        "validated_at": utc_now(),
        "data_classification": classification,
        "privacy_safe_diagnostic": True,
        "raw_values_included": False,
        "system_portfolio_assessment": "NOT_EVALUATED",
        "partner_approval_state": "PARTNER_APPROVAL_PENDING",
        "check_summary": {
            "total": len(checks),
            "passed": sum(check.status == "PASS" for check in checks),
            "failed": len(failed),
            "warnings": sum(check.status == "WARNING" for check in checks),
        },
        "blocking_check_ids": [check.check_id for check in failed],
        "checks": [check.to_dict() for check in checks],
        "next_action": (
            "Proceed to the local Gate 4 entry check."
            if status == INPUT_STATUS_VALIDATED
            else "Complete or correct the named private-input fields locally."
        ),
    }


def load_and_validate_private_inputs(
    manifest_path: Path,
) -> tuple[PrivateInputBundle | None, dict[str, Any]]:
    checks: list[PrivateInputCheck] = []
    try:
        manifest = read_mapping(manifest_path)
    except PrivateInputLoadError as exc:
        checks.append(
            PrivateInputCheck(
                "G4I-manifest-load",
                "manifest",
                "FAIL",
                "HARD_STOP",
                "<document>",
                None,
                str(exc),
                "Create the manifest from the public template and keep it local.",
            )
        )
        return None, _diagnostic_without_bundle(checks)
    checks.extend(
        schema_checks(
            "manifest",
            manifest,
            "private_workspace_manifest.schema.json",
        )
    )
    if any(check.status == "FAIL" for check in checks):
        return None, _diagnostic_without_bundle(checks)
    bundle = _load_bundle_documents(manifest_path, manifest, checks)
    if bundle is None:
        return None, _diagnostic_without_bundle(checks)
    return bundle, validate_private_input_bundle(bundle, existing_checks=checks)


def _diagnostic_without_bundle(checks: list[PrivateInputCheck]) -> dict[str, Any]:
    failed = [check for check in checks if check.status in {"FAIL", "MISSING", "BLOCKED"}]
    return {
        "private_input_contract_version": PRIVATE_INPUT_CONTRACT_VERSION,
        "framework_status": FRAMEWORK_STATUS,
        "status": INPUT_STATUS_REQUIRED,
        "validated_at": utc_now(),
        "data_classification": "NOT_EVALUATED",
        "privacy_safe_diagnostic": True,
        "raw_values_included": False,
        "system_portfolio_assessment": "NOT_EVALUATED",
        "partner_approval_state": "PARTNER_APPROVAL_PENDING",
        "check_summary": {
            "total": len(checks),
            "passed": sum(check.status == "PASS" for check in checks),
            "failed": len(failed),
            "warnings": sum(check.status == "WARNING" for check in checks),
        },
        "blocking_check_ids": [check.check_id for check in failed],
        "checks": [check.to_dict() for check in checks],
        "next_action": "Complete or correct the named private-input fields locally.",
    }
