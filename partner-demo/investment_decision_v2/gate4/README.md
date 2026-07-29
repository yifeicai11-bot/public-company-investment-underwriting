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

The same policy, opportunity-set, approval, and Gate 3 freshness documents are
required in all three modes.

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
- In full-holdings mode, an exposure summary is optional and can be used as an
  independent reconciliation input.

No default policy values are supplied. Empty templates are intentionally
invalid until the Partner completes them locally.

## Workflow Status

- `GATE_4_FRAMEWORK_READY`: public schemas, templates, and validation logic exist.
- `GATE_4_PRIVATE_INPUTS_REQUIRED`: one or more required private fields or files are missing or invalid.
- `GATE_4_INPUTS_VALIDATED`: the local input set is structurally complete and reconciled.
- `GATE_4_SYSTEM_ASSESSMENT_READY`: reserved for the later constraint engine.
- `PARTNER_APPROVAL_PENDING`: no Partner decision may be treated as approved before the system assessment.
- `GATE_4_APPROVED`: reserved for a named Partner decision after system assessment.

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
approval rationales. S04 validates inputs and the Gate 3 entry boundary only;
the later constraint engine is still `NOT_EVALUATED`.

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
