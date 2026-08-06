# External Tool Policy

Use this reference when a review uses any third-party library, GitHub skill, MCP server, market-data source, hosted API, or downloaded open-source tool.

## Core Rule

External tools can accelerate research, but they do not replace validation or judgment. Treat every external output as an input to the skill, not as the final answer.

## Provider Labels

For every material figure or claim sourced through an external tool, record:

- provider or library name
- retrieval date
- original public source if available
- whether the output is official, unofficial, calculated, vendor-derived, or manual
- whether the field is acceptable for user demo, prototype only, or blocked
- confidence level

## Allowed Uses

External tools may be used for:

- company lookup and filing discovery
- SEC filing download
- XBRL financial statement extraction
- filing section and note extraction
- market price and return history
- peer screening
- ratio calculation references
- scenario-supporting market data
- later-stage portfolio analytics

## Validation Requirements

Map external data into the period-aware data object before use:

- period_start
- period_end
- period_type
- duration_days
- unit
- currency
- source_url
- source_location
- reported_or_calculated
- confidence
- validation_status

If an external tool provides a ratio, prefer to recompute the ratio using validated inputs. If recomputation is not possible, label the ratio as vendor-derived or provisional.

## Tool-Specific Guidance

### SEC / EDGAR Tools

Good candidates include EdgarTools and SEC filing download utilities. They may improve filing discovery, XBRL extraction, note extraction, 8-K review, ownership data, and fund filings.

Do not treat extracted data as analyst-verified until it reconciles against the filing, companyfacts data, or validation gates.

### Market Data Tools

Unofficial or free market-data tools may be useful for prototypes, but user-ready valuation should show the provider and retrieval date. If data terms restrict use, label the output as prototype only.

### Commercial APIs

Commercial APIs may be useful if the user or firm has approved access. Do not assume an API key, subscription, or permission exists.

### Portfolio Analytics Libraries

Portfolio analytics and optimization libraries belong in a later portfolio layer unless the user explicitly asks for position sizing, risk contribution, drawdown analytics, or opportunity cost. Do not force them into a single-company credit memo.

## License and Security Guardrails

- Prefer MIT, BSD, Apache, or similarly permissive licenses for optional demo dependencies.
- Avoid AGPL or unclear/no-license dependencies in the default project unless approved.
- Do not install or run unknown code from random repositories without inspecting scope and relevance.
- Do not send confidential or internal data to hosted services without explicit authorization.
- Keep optional dependencies optional; the core skill should still work with public filings and local scripts.

## Integration Priority

Use external tools in this order:

1. Improve data extraction accuracy or coverage.
2. Improve source traceability.
3. Improve validation and reconciliation.
4. Improve valuation/scenario inputs.
5. Improve portfolio sizing or opportunity-cost analysis.

Do not add a tool simply because it is popular or broad.
