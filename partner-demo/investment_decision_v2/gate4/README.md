# Gate 4 Private Input Contract

This directory contains public schemas, empty templates, and synthetic examples
for the local portfolio overlay. It contains no real fund or Partner data.

## Documents

| Document | Supported format | Purpose |
|---|---|---|
| Workspace manifest | JSON or YAML | Binds one dated local input set and names relative files |
| Portfolio policy | JSON or YAML | Stores explicit return, downside, horizon, concentration, liquidity, risk, opportunity-cost, hedge, escalation, reviewer, and Gate 3 eligibility rules |
| Exposure summary | CSV or XLSX | Stores reviewed issuer, sector, country, correlation, gross, net, cash, or hedge exposures |
| Current holdings | CSV or XLSX | Stores issuer-level aggregate positions or complete security-level holdings, depending on the selected mode |
| Opportunity set | CSV or XLSX | Stores locally reviewed alternatives for later opportunity-cost comparison |
| Portfolio constraint inputs | JSON or YAML | Binds the candidate and dated return, downside, liquidity, hedge, risk-budget, and liquid-weight inputs to one Gate 3 contract |
| Approval config | JSON or YAML | Separates system assessment from the Partner-owned decision and disables automatic trading |
| Gate 3 freshness attestation | JSON or YAML | Binds a dated public-source review to one exact Gate 3 report ID and contract hash |

## Input Modes

The manifest must select exactly one mode. The validator never silently upgrades
a lower-granularity mode.

| Mode | Required position data | Available after input validation | Explicit limitation |
|---|---|---|---|
| `EXPOSURE_ONLY` | Exposure summary; holdings prohibited | Aggregate exposure validation | Holdings reconciliation and security-level liquidity are `NOT_EVALUATED` |
| `AGGREGATED_PORTFOLIO` | Exposure summary plus issuer-level aggregate holdings | Aggregate exposure and NAV/weight reconciliation | Security-level liquidity is `NOT_EVALUATED` |
| `FULL_HOLDINGS` | Complete security-level holdings; independent exposure summary optional | Full NAV/weight and security-level input validation | System portfolio assessment still remains `NOT_EVALUATED` |

The same policy, opportunity-set, portfolio-constraint, approval, and Gate 3
freshness documents are required in all three modes.

## Field Governance

[`field_governance.json`](field_governance.json) is the shared, machine-readable
contract. Every JSON-Schema-required field is `CORE_REQUIRED` unless an explicit
mode rule classifies it as:

- `CONDITIONAL`
- `OPTIONAL`
- `REVIEWER_CONFIRMED_NOT_APPLICABLE`

A core field cannot be waived. A reviewer-confirmed not-applicable field may be
blank only when the manifest carries one matching row-specific exception with a
rationale, reviewer, and review timestamp no later than the as-of date. A
supplied value and a not-applicable record cannot coexist.

## Value Conventions

- Ratios and returns use decimals in JSON/YAML: `0.20` means 20%.
- CSV/XLSX ratio cells may use either `0.20` or `20%`.
- Dates use ISO `YYYY-MM-DD`.
- Timestamps use ISO 8601 with timezone, preferably `Z`.
- Holdings market values must already be converted to the manifest base currency.
- Aggregated and full-holdings position weights must reconcile to 100% of
  portfolio NAV within the explicit manifest tolerance.
- LONG and CASH weights are nonnegative; SHORT weights are nonpositive.
- A nonzero hedge ratio requires an existing hedge identifier or a HEDGE row.
- Active opportunity-set rows need validated return and downside data before
  opportunity cost can be evaluated.
- Exposure-only and aggregated modes require reviewed GROSS and NET rows.
- Exposure dimensions overlap and must not be summed across issuer, sector,
  country, or correlation buckets.
- Issuer, sector, country, and correlation exposure rows must explicitly use
  `GROSS_LONG_WEIGHT`; aggregate gross, net, cash, and hedge rows use their
  controlled measurement bases.
- Candidate ADVT must be in portfolio base currency and within the policy's
  explicit maximum age.
- In full-holdings mode, an exposure summary is optional and can be used as an
  independent reconciliation input.

No default policy values are supplied. Empty templates are intentionally
invalid until the Partner completes them locally.

## Workflow Status

- `GATE_4_FRAMEWORK_READY`: public schemas, templates, and validation logic exist.
- `GATE_4_PRIVATE_INPUTS_REQUIRED`: one or more required private fields or files are missing or invalid.
- `GATE_4_INPUTS_VALIDATED`: the local input set is structurally complete and reconciled.
- `GATE_4_CONSTRAINTS_CALCULATED`: every required S13 constraint ceiling is reproducible.
- `GATE_4_CONSTRAINTS_INCOMPLETE`: at least one required S13 input or ceiling is missing.
- `GATE_4_SYSTEM_ASSESSMENT_READY`: S14 produced a reproducible System Portfolio Assessment.
- `PARTNER_APPROVAL_PENDING`: no Partner decision may be treated as approved before the system assessment.
- `GATE_4_APPROVED`: a named Partner decision is validated against the current assessment hash and constraint ceiling.
- `GATE_4_MODIFIED`, `GATE_4_REJECTED`, and `GATE_4_DEFERRED`: other validated Partner-owned outcomes.

Input validation does not calculate a recommended position and never places a
trade. It emits only a privacy-safe diagnostic containing check IDs, field
names, statuses, and remediation.

## Local Private Workflow

Do not paste real policy, holdings, opportunity-set, approval, or position data
into Codex, Claude, another hosted model, an external API, or a remote log.
Initialize the files locally and select the least-granular mode that still
supports the intended decision:

```bash
python3 partner-demo/investment_decision_v2/scripts/initialize_gate4_private_workspace.py \
  --input-mode EXPOSURE_ONLY
```

Use `AGGREGATED_PORTFOLIO` or `FULL_HOLDINGS` only when those data are approved
for local use. Omitting `--input-mode` leaves the manifest intentionally
incomplete.

The default workspace is `~/investment_private`. It is created outside Git with
directory mode `0700` and file mode `0600`. No return target, risk limit,
holding, or approval value is invented.

After completing the local files, validate the exact Gate 3 contract and the
private bundle:

```bash
python3 partner-demo/investment_decision_v2/scripts/run_gate4_local_entry.py \
  path/to/step3/underwriting_output_contract.json \
  --manifest ~/investment_private/gate4_private_workspace_manifest.json
```

The local entry writes only
`~/investment_private/private_outputs/gate4_local_entry_diagnostic.json`.
It omits raw holdings, policy values, opportunity rows, reviewer names, and
approval rationales. S04 validates inputs and the Gate 3 entry boundary only.

After completing `portfolio_constraint_inputs.yaml`, run S13 locally:

```bash
python3 partner-demo/investment_decision_v2/scripts/run_gate4_constraint_engine.py \
  path/to/step3/underwriting_output_contract.json \
  --manifest ~/investment_private/gate4_private_workspace_manifest.json
```

The runner reloads and rechecks Gate 3 immediately before calculation, writes
the private result to `gate4_constraint_engine_result.json`, and does not print
private values or the calculated ceiling. It separately records every limit,
formula, missing item, and binding constraint. The maximum is not a suggested
or approved position; S13 leaves System Portfolio Assessment `NOT_EVALUATED`
and Partner Decision `PENDING`.

After S13, run S14 locally:

```bash
python3 partner-demo/investment_decision_v2/scripts/run_gate4_assessment.py \
  path/to/step3/underwriting_output_contract.json \
  --manifest ~/investment_private/gate4_private_workspace_manifest.json
```

S14 re-runs S13 from the current local files, confirms the input bundle and
Gate 3 identity did not change during the run, and returns `ELIGIBLE`,
`ELIGIBLE_WITH_ESCALATION`, `REVIEW_REQUIRED`, `NOT_ELIGIBLE`, or
`NOT_EVALUATED`. The separately owned Partner decision may be `PENDING`,
`APPROVED`, `MODIFIED`, `REJECTED`, or `DEFERRED`. An approval or modification
must bind to the current deterministic assessment hash, stay within the total
issuer constraint ceiling, and acknowledge every active escalation.

The same S14 contract renders four bilingual local Markdown files: One-Page,
Full Report, Evidence Appendix, and Validation Report. The renderer does not
recalculate any ceiling, assessment, or decision. Read
`references/gate4_assessment_and_approval.md` for the complete state machine.

## Privacy Controls

- Real workspaces and private outputs are blocked inside this or any other Git
  worktree, including through a symbolic link.
- Exact local filenames and common private directory names are ignored by Git.
- The pre-commit scanner blocks likely portfolio files without printing their
  contents. Enable it once per clone:

```bash
git config core.hooksPath .githooks
```

- Local Gate 4 modules do not import network, telemetry, crash-reporting, or
  logging clients.
- Spreadsheet formulas are rejected; raw portfolio values remain in memory.
- Temporary writes occur only inside the private output directory and are
  atomically replaced with mode `0600`.
- Direct private PDF writes are blocked. A local PDF may be released only
  through `sanitize_gate4_private_pdf.py`, which rebuilds the pages, replaces
  document metadata with fixed non-identifying values, removes XMP, rejects
  attachments and document-level active actions, reopens the result, and writes
  it with mode `0600`.
- Public tests, demos, and committed files may use synthetic data only.

Sanitize a PDF that already exists inside the private workspace:

```bash
python3 partner-demo/investment_decision_v2/scripts/sanitize_gate4_private_pdf.py \
  ~/investment_private/private_outputs/raw_report.pdf \
  --output ~/investment_private/private_outputs/sanitized_report.pdf \
  --root ~/investment_private
```

The sanitizer's terminal diagnostic omits private paths and values. It does not
make the PDF public or authorize external transmission.

## Synthetic Example

The files under `synthetic_examples/` are fictional and carry
`SYNTHETIC_PUBLIC_EXAMPLE`. Validate each mode with:

```bash
python3 partner-demo/investment_decision_v2/scripts/validate_gate4_private_inputs.py \
  partner-demo/investment_decision_v2/gate4/synthetic_examples/synthetic_gate4_manifest.json

python3 partner-demo/investment_decision_v2/scripts/validate_gate4_private_inputs.py \
  partner-demo/investment_decision_v2/gate4/synthetic_examples/synthetic_aggregated_portfolio_manifest.json

python3 partner-demo/investment_decision_v2/scripts/validate_gate4_private_inputs.py \
  partner-demo/investment_decision_v2/gate4/synthetic_examples/synthetic_exposure_only_manifest.json
```

Install Gate 4 parsing dependencies first:

```bash
python3 -m pip install -r requirements-gate4.txt
```

Build and validate the public synthetic S14 report package:

```bash
python3 partner-demo/investment_decision_v2/scripts/build_gate4_synthetic_demo.py
python3 partner-demo/investment_decision_v2/scripts/validate_gate4_synthetic_delivery.py \
  examples/gate4-synthetic
```

The package contains four bilingual PDFs generated from one shared contract.
The validator requires one A4 page for the One-Page Summary, verifies all file
hashes and rendered decision states, and rejects position-recommendation
wording. Synthetic constraints demonstrate the interface only.
