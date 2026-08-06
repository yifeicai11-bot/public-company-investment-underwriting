# S15 Monitoring and Update Mode

S15 compares two immutable, validated issuer underwriting contracts for the
same SEC issuer. It does not fetch public data, rebuild either issuer analysis,
or edit the prior conclusion.

The monitoring output records changes in:

- FACT and CALC evidence records;
- analyst judgments and inference records;
- evidence and source mappings;
- Warnings and Hard Stops;
- reviewer-approved KPI conditions;
- scenario sensitivities; and
- probability expiration and review triggers.

The system thesis assessment is provisional. The formal thesis status remains
`PENDING_HUMAN_REVIEW`; automatic status changes, position recommendations,
and trade execution are prohibited.

## Required Inputs

1. Prior `underwriting_output_contract.json`.
2. Current `underwriting_output_contract.json`.
3. A dated, reviewer-approved monitoring policy based on the template under
   `templates/`.
4. An explicit monitoring as-of date.

KPI rules must use exact stable `metric_name` and `evidence_class` values from
the issuer contract. The engine does not parse thresholds from free text and
does not invent missing rules. Percent-change rules are suppressed when the
prior denominator is zero or negative.

## Run

```bash
python3 user-demo/investment_decision_v2/scripts/run_monitoring_update.py \
  --previous /path/to/prior/underwriting_output_contract.json \
  --current /path/to/current/underwriting_output_contract.json \
  --policy /path/to/monitoring_policy.yaml \
  --as-of-date YYYY-MM-DD \
  --output-dir /path/outside/the/repo/monitoring-output
```

The CLI writes a machine-readable monitoring contract and a concise bilingual
Markdown summary with restrictive file permissions.
