# Agent Instructions / Agent 使用指令

This file contains copy-ready instructions for Codex, Claude Code, or another
local coding agent opened at the repository root.

本文件包含可以直接复制给 Codex、Claude Code 或其他本地 coding agent 的指令。

## Operating Boundary / 运行边界

- Use the public-only path when no portfolio is provided. It produces Gate 3 outputs and keeps the Portfolio Overlay disabled.
- Use the Gate 4 path only when a private portfolio workspace has been completed locally. Gate 4 consumes the exact validated Gate 3 contract; it does not rebuild issuer analysis.
- Never paste real holdings, fund policy, exposures, approval data, or position sizes into GitHub, a hosted chat, an external API, logs, or public output folders.
- Do not use synthetic examples as real portfolio inputs. The committed Gate 4 package is only a public demonstration of the interface and report structure.

- 没有提供 portfolio 时，使用 public-only 路径，生成 Gate 3，并保持 Portfolio Overlay 关闭。
- 只有在本地完成私有 portfolio workspace 后，才使用 Gate 4。Gate 4 消费已经验证过的 Gate 3 contract，不重新构建 issuer analysis。
- 不要把真实持仓、基金政策、敞口、审批资料或仓位上传到 GitHub、托管聊天、外部 API、日志或公开输出目录。
- 不要把仓库中的 synthetic 示例当作真实 portfolio 输入。仓库里的 Gate 4 只是公开演示界面和报告结构。

## Public-Only Gate 3 Prompt / 公开资料 Gate 3 指令

Copy the following prompt after opening the repository root:

```text
请先读取 `public-firm-credit-liquidity-skill/SKILL.md`，并遵循其中的数据验证、来源记录、Data Gate、估值情景和输出规则。

请分析 [公司名称或股票代码]。

本次运行使用 public-only 模式，不提供、不读取任何真实 portfolio 数据。请：
1. 只使用公开资料。
2. 先建立 Data and Evidence Layer，再进行 Issuer Underwriting。
3. 检查财务期间、市场价格日期、股数日期和后续事项，不得混用季度、YTD、FY 和 LTM 数据。
4. 完整分析 receivables、bad debt、cash conversion、working capital、liquidity、debt、leases、covenants、refinancing 和 capital allocation。
5. 明确 Investment Question、Key Debates、Decision Confidence、What Is Priced In 和 Thesis Breaks。
6. 只有在估值和情景假设可复算时才展示情景价格、回报或估值范围。
7. 区分 FACT、CALC、INFERENCE、JUDGMENT 和 MISSING；每个重要数字都必须有来源、日期、locator 和验证状态。
8. 不得复制 CROX、AZO 或其他公司的假设、数字、结论或 portfolio context。
9. 保持 `Portfolio Overlay: Disabled`、`Portfolio Decision: Not Evaluated`，不要生成 position sizing、组合动作或自动交易指令。
10. 实际运行仓库中的 shared builder、investment layer、renderer 和独立 validation script，不要只在聊天框里写报告。
11. 如果当前资料不足以达到 Gate 3，生成 diagnostic 和 analyst-input template；不得用默认值补齐缺失估值、概率或组合约束。
12. 只有在 contract validation 通过、没有 Hard Stop 且 Data Gate 允许时，才生成中英文 One-Page Summary、Full Report、Evidence Appendix 和 Validation Report。
13. 最后列出所有文件路径、Data Gate、Decision Confidence、Hard Stop 数量、Warning 数量、缺失资料和 validation 结果。
```

The public-only path can produce a complete Gate 3 review when the required
public research inputs are validated. It cannot produce a fund-specific
position size or portfolio action.

## Portfolio-Enabled Gate 4 Prompt / 提供组合后的 Gate 4 指令

Use this prompt only after the private workspace has been completed outside the
repository. Replace the paths with local paths; do not paste private file
contents into the chat.

```text
请先读取 `public-firm-credit-liquidity-skill/SKILL.md` 以及
`public-firm-credit-liquidity-skill/references/gate4_private_data_workflow.md`。

请分析 [公司名称或股票代码]，并使用本地私有 workspace：
`[Gate 4 manifest 的本地路径]`

请严格执行以下顺序：
1. 先用公开资料完成或读取该公司的 Gate 3 Data and Evidence Layer、Issuer Underwriting 和估值/情景 contract。
2. 验证 Gate 3 contract 的版本、report ID、contract hash、报告日期、财务日期、市场价格日期、最新财报、后续事项、概率有效期、估值状态、Hard Stop 和 Warning。
3. 如果 Gate 3 过期、不合格或 hash 不一致，返回对应 diagnostic；不得重复或覆盖 issuer analysis。
4. 通过 Gate 3 freshness check 后，只在本地读取私有 workspace，运行 Gate 4 local entry。
5. 运行 S13 Portfolio Constraint Engine，计算 existing issuer、single-name、sector、country、liquidity、holding period、downside、risk budget、correlated exposure、opportunity cost 和适用 hedge constraints。
6. 对每条 constraint 显示 limit、candidate value、formula、source field、missing field、escalation threshold 和 binding status；不得用默认值填补缺失项。
7. 运行 S14 Assessment and Approval，分别输出 System Assessment（Eligible、Eligible with Escalation、Review Required、Not Eligible 或 Not Evaluated）和 User Decision（Pending、Approved、Modified、Rejected 或 Deferred）。
8. 最大允许仓位只能作为 constraint ceiling 展示，不得表述为建议仓位；不得自动执行交易。
9. 生成本地 Gate 4 的中英文 One-Page Summary、Full Report、Evidence Appendix 和 Validation Report。私有文件只能写入本地私有输出目录。
10. 最后只在聊天框报告状态、文件的本地路径、Gate 3 freshness、Gate 4 assessment、missing fields、warnings、hard stops 和 approval status；不要输出真实持仓明细、仓位数值或其他私有字段。
```

Recommended local commands:

```bash
python3 user-demo/investment_decision_v2/scripts/initialize_gate4_private_workspace.py \
  --input-mode EXPOSURE_ONLY

python3 user-demo/investment_decision_v2/scripts/run_gate4_local_entry.py \
  path/to/step3/underwriting_output_contract.json \
  --manifest ~/investment_private/gate4_private_workspace_manifest.json

python3 user-demo/investment_decision_v2/scripts/run_gate4_constraint_engine.py \
  path/to/step3/underwriting_output_contract.json \
  --manifest ~/investment_private/gate4_private_workspace_manifest.json

python3 user-demo/investment_decision_v2/scripts/run_gate4_assessment.py \
  path/to/step3/underwriting_output_contract.json \
  --manifest ~/investment_private/gate4_private_workspace_manifest.json
```

Gate 4 has three input modes: `EXPOSURE_ONLY`, `AGGREGATED_PORTFOLIO`, and
`FULL_HOLDINGS`. The selected mode controls what can be evaluated; it does not
remove the need for current inputs and named human approval.
