# Public-Company Investment Underwriting

An auditable, bilingual public-company issuer-underwriting skill and research-support engine. / 一套可审计、可复用、支持中英文输出的上市公司基本面与投资研究框架。

- **Release:** V1
- **Current scope:** SEC-reporting, US GAAP, non-financial public companies
- **Positioning:** issuer-level research and IC pre-read support, not an automated trading system

> This repository contains public-data research demonstrations only. It contains no fund holdings, client information, live position sizes, or partner-specific portfolio constraints. Portfolio Overlay is disabled in the included examples. / 本仓库只包含公开资料研究示例，不包含基金持仓、客户信息、真实仓位或组合约束；示例中的组合叠加层均未启用。

## Partner Demo / 演示文件

| Company | One-Page Summary | Full Report | Evidence Appendix | QA Summary | Validation |
|---|---|---|---|---|---|
| Crocs (CROX) | [PDF](examples/crox/CROX_One_Page_Summary_Bilingual.pdf) | [PDF](examples/crox/CROX_Full_Report_Bilingual.pdf) | [PDF](examples/crox/CROX_Evidence_Audit_Appendix_Bilingual.pdf) | [PDF](examples/crox/CROX_Friday_V1_QA_Summary_Bilingual.pdf) | [JSON](examples/crox/validation_report.json) |
| AutoZone (AZO) | [PDF](examples/autozone/AZO_One_Page_Summary_Bilingual.pdf) | [PDF](examples/autozone/AZO_Full_Report_Bilingual.pdf) | [PDF](examples/autozone/AZO_Evidence_Audit_Appendix_Bilingual.pdf) | [PDF](examples/autozone/AZO_Friday_V1_QA_Summary_Bilingual.pdf) | [JSON](examples/autozone/validation_report.json) |

The One-Page Summary presents the investment question, public-data view, what is priced in, scenario price sensitivity, key debates, decision boundaries, and the next evidence required. The Full Report expands the same validated contract into issuer underwriting, earnings quality, working capital, cash conversion, liquidity, debt and refinancing, valuation, scenarios, decision rules, and source records.

一页摘要用于快速判断是否值得继续研究；完整报告则展开业务、盈利质量、营运资金、现金转化、流动性、债务与再融资、估值、情景、决策规则和来源记录。两者来自同一个 validated contract，不独立重算数字或结论。

## What the System Does / 系统能力

- Starts with a mandatory Investment Question rather than a generic company description.
- Separates `FACT`, `CALC`, `INFERENCE`, `JUDGMENT`, and `MISSING` evidence.
- Enforces period, as-of-date, unit, share-count, market-price, and source-lineage controls.
- Prevents quarter/YTD mixing and CFO/FCF or liquidity double counting.
- Underwrites receivables, bad-debt evidence, working capital, cash conversion, liquidity, debt, leases, covenants, refinancing, capital allocation, and subsequent events.
- Connects issuer fundamentals to reverse valuation and Bear/Base/Bull price sensitivities.
- Suppresses target return, probability-weighted return, and position sizing when the required method, horizon, evidence, approval, or portfolio context is missing.
- Produces a bilingual One-Page, Full Report, Evidence Appendix, and QA Summary from one shared output contract.

## Architecture / 架构

| Layer | Main component | Responsibility |
|---|---|---|
| Skill | [`public-firm-credit-liquidity-skill/`](public-firm-credit-liquidity-skill/) | Reusable Codex/Claude-style workflow, source policy, risk framework, sector overlays, and output standards |
| Data and Evidence | [`build_public_company_decision_pack.py`](partner-demo/investment_decision_v2/scripts/build_public_company_decision_pack.py) | SEC ingestion, period normalization, evidence IDs, source registry, market-date controls, and validation |
| Issuer and Investment Analysis | [`build_public_company_investment_layer.py`](partner-demo/investment_decision_v2/scripts/build_public_company_investment_layer.py) | Investment Question, Key Debates, FCF, liquidity, credit, reverse valuation, scenarios, and decision rules |
| Shared Contract | [`underwriting_contract.py`](partner-demo/investment_decision_v2/scripts/underwriting_contract.py) | Data Gates, output suppression, confidence, evidence lineage, and hard-stop rules |
| Rendering | [`render_public_company_artifacts.py`](partner-demo/investment_decision_v2/scripts/render_public_company_artifacts.py) | Formatting-only bilingual HTML/PDF rendering |
| Independent QA | [`validate_friday_v1_delivery.py`](partner-demo/investment_decision_v2/scripts/validate_friday_v1_delivery.py) | Reproduces market cap, FCF bridge, reverse valuation, scenarios, dates, contract identity, and output boundaries |

## Data Gates / 数据门槛

| Gate | Meaning | Maximum permitted output |
|---|---|---|
| 0 | Data not validated | Diagnostic only |
| 1 | Core financial and market data validated | Preliminary screen |
| 2 | Issuer underwriting complete | Qualified issuer and credit view |
| 2.5 | Valuation or scenario work incomplete | Continue Research / Need More Work |
| 3 | Valuation and scenario prices reproducible | Public-data investment review and valuation range |
| 4 | Fund inputs validated and human-approved | Approved portfolio overlay and position range |

The system never places a trade. Gate 4 requires real fund constraints and explicit human approval.

## Run Locally / 本地运行

Requirements:

- Python 3.11+
- Internet access for SEC and public market-data retrieval
- Google Chrome or Chromium only when PDF output is requested

The SEC asks automated clients to identify themselves. Set your own contact before live retrieval:

```bash
export SEC_USER_AGENT="Your Name your.email@example.com"
```

Build a public-only underwriting contract for a supported company:

```bash
python3 partner-demo/investment_decision_v2/scripts/build_public_company_investment_layer.py AAPL
```

Build a reviewed research fixture:

```bash
python3 partner-demo/investment_decision_v2/scripts/build_public_company_investment_layer.py CROX \
  --research-input partner-demo/investment_decision_v2/research_inputs/crox_gate3_public_input.json
```

Render bilingual artifacts:

```bash
python3 partner-demo/investment_decision_v2/scripts/render_public_company_artifacts.py \
  partner-demo/investment_decision_v2/friday_v1_outputs/crox_crocs_inc/step3/underwriting_output_contract.json \
  --out-dir examples/crox \
  --pdf
```

Validate the contract and rendered files:

```bash
python3 partner-demo/investment_decision_v2/scripts/validate_friday_v1_delivery.py \
  partner-demo/investment_decision_v2/friday_v1_outputs/crox_crocs_inc/step3/underwriting_output_contract.json \
  --html-dir examples/crox
```

Run the shared test suite:

```bash
python3 -m unittest discover \
  -s partner-demo/investment_decision_v2/tests \
  -p 'test_*.py' \
  -v
```

## Current Validation / 当前验证

- 38 shared accounting, evidence, market-data, gate, scenario, and rendering tests passed locally.
- CROX: 36 independent delivery checks passed; 0 failures; 0 hard stops.
- AutoZone: 36 independent delivery checks passed; 0 failures; 0 hard stops.
- Both One-Page PDFs are one A4 page; both Full Reports are 11 A4 pages and were visually reviewed after page rendering.

## Boundaries / 使用边界

- Current shared core is for SEC-reporting, US GAAP, non-financial issuers. Banks, insurers, foreign private issuers, and non-US-GAAP companies require specialized overlays.
- Scenario values and selected multiples are analyst-owned sensitivities unless stronger evidence is supplied; they are not automatically treated as fair values.
- Probability-weighted return is not a formal conclusion without a documented method, freshness review, sensitivity analysis, and human approval.
- The included public-data reports do not determine whether a fund should buy, sell, or size a position.
- Market, filing, and consensus observations are dated. Refresh all sources and subsequent events before live use.

## Public-Data and Use Notice

The examples use cited public filings, official company materials, public market-data endpoints, and public webpages. References to third-party providers identify the source displayed by the cited webpage; this repository does not include a raw licensed database. Users remain responsible for complying with each source's terms and for independently verifying data before investment use.

This project is research software and an analytical demonstration. It is not investment advice, a credit rating, an offer, or authorization to trade.
