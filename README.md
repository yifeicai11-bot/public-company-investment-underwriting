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

## Frozen Friday V1 Baseline / 已冻结的 Friday V1 基线

The Partner-submitted Friday V1 is preserved at Git tag `v1.0.0-friday` and commit
`15b328137d615ca85e84cb997f3acfc2b15ca03b`. The baseline manifest records the
runtime, contract and renderer versions, source dates, frozen-input hashes,
submitted-output hashes, rounding rules, and regeneration command.

已提交给 Partner 的 Friday V1 已冻结在 Git tag `v1.0.0-friday`。后续开发不会静默改变该版本；
基线文件保存了运行环境、contract 和 renderer 版本、来源日期、输入与输出 hash、显示舍入规则和复现命令。

Verify the frozen files without network access:

```bash
python3 release-baselines/friday-v1/verify_baseline.py
```

Regenerate CROX and AZO from the frozen contracts and compare HTML, PDF page
counts, and rendered pixels:

```bash
python3 release-baselines/friday-v1/verify_baseline.py \
  --render --pdf --pixel-compare
```

See [`release-baselines/friday-v1/baseline_manifest.json`](release-baselines/friday-v1/baseline_manifest.json)
for the authoritative baseline record.

## Use with Codex / 在 Codex 中使用

GitHub hosts the files but does not run the analysis by itself. Download the entire repository, open the repository root in Codex, replace `[公司名称或股票代码]` in the prompt below, and submit it in the Codex chat. Do not open or install only the `public-firm-credit-liquidity-skill` subfolder because the full analysis engine is stored under `partner-demo/`.

GitHub 页面本身不会自动运行分析。请下载整个 repository，在 Codex 中打开仓库根目录，将下面 Prompt 中的 `[公司名称或股票代码]` 替换为目标公司后发送。不要只打开或安装 `public-firm-credit-liquidity-skill` 子文件夹，因为完整分析引擎位于 `partner-demo/`。

Download with Git:

```bash
git clone https://github.com/yifeicai11-bot/public-company-investment-underwriting.git
cd public-company-investment-underwriting
```

Alternatively, select **Code > Download ZIP** on GitHub, unzip it, and open the resulting `public-company-investment-underwriting` folder in Codex.

Copy this prompt into Codex:

```text
请先读取 `public-firm-credit-liquidity-skill/SKILL.md`，并遵循其中的数据验证、来源记录、Data Gate、估值情景和输出规则。

请分析 [公司名称或股票代码]。

要求：
1. 只使用公开资料。
2. 先建立 Data and Evidence Layer，再进行 Issuer Underwriting。
3. 检查财务期间、市场价格日期、股数日期和后续事项，不得混用季度、YTD 和 LTM 数据。
4. 完整分析 receivables、bad debt、cash conversion、working capital、liquidity、debt、leases、covenants、refinancing 和 capital allocation。
5. 明确 Investment Question、Key Debates、Decision Confidence、What Is Priced In 和 Thesis Breaks。
6. 只有在估值和情景假设可复算时才展示情景价格。
7. 未提供基金组合资料时，保持 Portfolio Overlay Disabled，不生成 position sizing。
8. 最终生成中英文 One-Page Summary、Full Report、Evidence Appendix 和 Validation Report。
9. 不要只在聊天框中撰写分析。请实际运行仓库中的 shared builder、investment layer、renderer 和 validation scripts，并将最终文件保存到新的公司输出目录。
10. 首先运行 public-only builder。然后读取生成的 `analyst_input_template.json`，继续搜索公司 filings、investor materials、guidance、consensus 和其他公开资料，建立包含完整 source metadata 的 research-input JSON。不得复制 CROX、AutoZone 或其他公司的假设。
11. 使用完成后的 research-input 重新运行 investment layer，并在当前 Data Gate 允许的范围内生成报告。随后运行 renderer 和独立 validation script。
12. 只有在 contract validation 通过、没有 Hard Stop 且当前 Data Gate 允许时，才生成正式 One-Page、Full Report 和 Evidence Appendix；否则生成 Diagnostic Report，并明确列出缺失资料和修复要求。
13. 最终在聊天框中列出所有生成文件的路径、Data Gate、Decision Confidence、Hard Stop 数量、Warning 数量和 validation 结果。
```

The initial public-only run may stop below Gate 3 when analyst-owned research inputs are incomplete. A partner-ready report requires sourced public research and human review of the Investment Question, Key Debates, FCF normalization, market expectations, valuation assumptions, and scenarios. / 当分析师输入尚不完整时，首次 public-only 运行可能停在 Gate 3 以下。Partner-ready 报告仍需要对投资问题、核心争议、FCF 标准化、市场预期、估值假设和情景进行公开资料研究与人工复核。

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
