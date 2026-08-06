# Migration to v1.1.0

This release adds a supported delivery interface around the existing shared engines. It does not alter the frozen v1.0.0 tag. The final version also includes S17 true held-out acceptance and the shared facility-parser correction identified during that process.

## Recommended command change

Previous multi-command workflows remain available, but new users should move to:

```bash
python underwrite.py analyze AAPL --output-root outputs
```

For a reviewed public research input:

```bash
python underwrite.py analyze AAPL \
  --output-root outputs \
  --research-input /path/to/aapl_public_research_input.json \
  --pdf
```

The entry point calls the shared builder, checks the shared contract, independently reproduces validated calculations, and only then renders formal outputs. It does not recalculate investment analysis itself.

## Delivery behavior change

The recommended entry point intentionally withholds user-ready One-Page and Full Report files below Gate 3. Lower-gate contracts and their evidence remain available, together with a pipeline diagnostic and analyst-input template. Existing direct renderer commands retain their historical behavior for controlled regression use.

## Dependency change

Create a clean Python 3.11/3.12 environment and install:

```bash
python -m pip install -r requirements.lock
```

`requirements-gate4.txt` is retained as a compatibility pointer. `requirements.lock` is authoritative for the full repository.

## Output-path change

The default unified output root is `outputs/`, which is ignored by Git. The layout is:

```text
outputs/
└── <company>/
    ├── step3/
    │   ├── underwriting_output_contract.json
    │   └── analyst_input_template.json
    └── delivery/
        ├── pipeline_manifest.json
        ├── validation_report.json
        └── gated report files or pipeline_diagnostic.json
```

The exact company directory remains builder-owned; integrations should read the returned `pipeline_manifest.json`, not infer a folder name.

## Gate 4 and monitoring

Do not pass portfolio data through `underwrite.py analyze`. Gate 4 continues to consume an immutable Gate 3 contract through the repo-external private workspace. S15 monitoring continues to compare two exact validated issuer contracts. Neither path is migrated into the public ticker command.

## Compatibility and rollback

- Contract schema `5.0.0` and `5.1.0` remain recognized by current Gate 4 eligibility rules.
- Frozen v1.0.0 artifacts remain reproducible from the recorded baseline commit.
- To inspect the old baseline without changing the current branch, run `python release-baselines/v1.0.0/verify_baseline.py`.
- Do not overwrite v1.0.0 examples with release-candidate output.
