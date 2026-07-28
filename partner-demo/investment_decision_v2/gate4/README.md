# Gate 4 Private Input Contract

This directory contains public schemas, empty templates, and synthetic examples
for the local portfolio overlay. It contains no real fund or Partner data.

## Documents

| Document | Supported format | Purpose |
|---|---|---|
| Workspace manifest | JSON or YAML | Binds one dated local input set and names relative files |
| Portfolio policy | JSON or YAML | Stores explicit return, downside, horizon, concentration, liquidity, risk, opportunity-cost, hedge, escalation, reviewer, and Gate 3 eligibility rules |
| Current holdings | CSV or XLSX | Stores the complete dated portfolio, including cash and hedges where applicable |
| Opportunity set | CSV or XLSX | Stores locally reviewed alternatives for later opportunity-cost comparison |
| Approval config | JSON or YAML | Separates system assessment from the Partner-owned decision and disables automatic trading |
| Gate 3 freshness attestation | JSON or YAML | Binds a dated public-source review to one exact Gate 3 report ID and contract hash |

## Value Conventions

- Ratios and returns use decimals in JSON/YAML: `0.20` means 20%.
- CSV/XLSX ratio cells may use either `0.20` or `20%`.
- Dates use ISO `YYYY-MM-DD`.
- Timestamps use ISO 8601 with timezone, preferably `Z`.
- Holdings market values must already be converted to the manifest base currency.
- Signed position weights must reconcile to 100% of portfolio NAV within the
  explicit manifest tolerance.
- LONG and CASH weights are nonnegative; SHORT weights are nonpositive.
- A nonzero hedge ratio requires an existing hedge identifier or a HEDGE row.
- Active opportunity-set rows need validated return and downside data before
  opportunity cost can be evaluated.
- Existing issuer, sector, country, correlated, gross, and net exposures are
  derived later from the complete holdings table. They are not duplicated as
  manually typed exposure totals that could drift from the underlying rows.

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
Initialize and complete the files locally:

```bash
python3 partner-demo/investment_decision_v2/scripts/initialize_gate4_private_workspace.py
```

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
- Private PDF generation is disabled until a tested metadata-sanitization
  control exists.
- Public tests, demos, and committed files may use synthetic data only.

## Synthetic Example

The files under `synthetic_examples/` are fictional and carry
`SYNTHETIC_PUBLIC_EXAMPLE`. Validate them with:

```bash
python3 partner-demo/investment_decision_v2/scripts/validate_gate4_private_inputs.py \
  partner-demo/investment_decision_v2/gate4/synthetic_examples/synthetic_gate4_manifest.json
```

Install Gate 4 parsing dependencies first:

```bash
python3 -m pip install -r requirements-gate4.txt
```
