---
name: signal-monitoring-agent-skill
description: Fetches and structures key signals (ETF flows, halving cycle, macro proxies, volatility, etc.)
---

# Signal Monitoring Agent Skill

## When to apply this skill

- Before evaluating or proposing rules
- During daily market reviews
- When another skill requests market context
- Before adjusting risk parameters

## Inputs

Describe which signals to retrieve in plain language. The more specific the message the better.

### Default Signal Set

- Bitcoin ETF Flows
- Bitcoin Halving Cycle Position
- DXY (US Dollar Index)
- Bitcoin Dominance
- Bitcoin Perpetual Funding Rates
- Bitcoin 30-Day Realized Volatility

### Example Inputs

- "Check the latest Bitcoin ETF flows, Bitcoin halving cycle position, and Bitcoin dominance."
- "Give me Bitcoin macro signals (DXY, 10-year Treasury yield, Bitcoin funding rates)."
- "Pull the main signals we care about for today."

## Steps

1. Determine the requested signals (or default to the core set).
2. Retrieve the latest verifiable data for each signal by running
   `scripts/fetch_signals.py` (see Tooling below) rather than guessing or
   relying on web search alone.
3. For each signal, record the current value, recent trend, and a short interpretation.
4. Determine the overall market regime.
5. Generate a short overall summary of what the signals imply for MintLocke rules.
6. Return results using the exact output format below.

## Tooling

Use the bundled script to pull real data instead of estimating from memory:

```
python scripts/fetch_signals.py [signal_name ...]
```

With no arguments it returns the default signal set as JSON. Available
signal names:

| Signal name      | Maps to                                | Source                |
|------------------|-----------------------------------------|------------------------|
| `etf_flows`      | Bitcoin ETF Flows                       | Farside Investors (scraped) |
| `halving_cycle`  | Bitcoin Halving Cycle Position           | Computed from known halving dates |
| `dxy`            | DXY (US Dollar Index)                   | Stooq (free, no key) |
| `dominance`      | Bitcoin Dominance                       | CoinGecko (free, no key) |
| `funding_rate`   | Bitcoin Perpetual Funding Rates          | Coinglass (requires `COINGLASS_API_KEY`) |
| `volatility_30d` | Bitcoin 30-Day Realized Volatility       | CoinGecko (computed from daily price history) |
| `price`          | BTC/USD spot price (extra, not core set) | CoinGecko (free, no key) |

`scripts/fetch_signals.py` also exposes `get_glassnode_metric(endpoint, asset, params)`
for any additional on-chain metric from Glassnode's API (requires
`GLASSNODE_API_KEY`), e.g. active supply, MVRV, SOPR — call it directly in a
short Python snippet if the user asks for a Glassnode metric not in the
table above.

Requires `pip install requests`-free standard library only (uses
`urllib`), so no extra dependencies beyond Python 3. Coinglass and
Glassnode functions return `"Unavailable"` if their respective API key
env vars (`COINGLASS_API_KEY`, `GLASSNODE_API_KEY`) are not set — surface
that to the user rather than fabricating a value, per the Guardrails below.

## Output Format

```
Signal Summary
[2–4 sentence summary of the overall market picture based on the signals]

Data Confidence
[High / Medium / Low]

Key Signals

Signal Name
Current Value:
Trend:
Interpretation:
Source:
Timestamp:

(repeat for each signal)

Implication for MintLocke
[One or two sentences describing what the signals imply for evaluating rules or adjusting risk settings.]
```

## Examples

### Example 1

User input: "Check the latest Bitcoin ETF flows, Bitcoin halving cycle position, and Bitcoin dominance."

Output:

Signal Summary: Bitcoin ETF flows remain strongly positive while dominance is rising, indicating continued institutional interest concentrated in Bitcoin.

Key Signals:
- Bitcoin ETF Flows: +$187M (increasing) — strong institutional accumulation
- Bitcoin Halving Cycle Position: 8.5 months post-halving — historically constructive period
- Bitcoin Dominance: 58.4% (rising) — capital rotating into Bitcoin

Implication for MintLocke: Current conditions support maintaining or slightly increasing risk exposure in Bitcoin-focused rules.

### Example 2

User input: "Give me Bitcoin macro signals (DXY, 10-year Treasury yield, Bitcoin funding rates)."

Output:

Signal Summary: Macro conditions are stable with mildly elevated funding rates.

Key Signals:
- DXY: 98.7 (slightly up) — mild USD strength
- 10-year Treasury Yield: 4.32% (flat) — neutral rates environment
- Bitcoin Funding Rates: +0.012% (elevated) — leveraged long interest increasing

Implication for MintLocke: No major macro headwinds, but elevated funding suggests caution on overly aggressive leverage rules.

### Example 3

User input: "Pull the main signals we care about for today."

Output: Full core set with summary and implication.

## Guardrails

- Only use verifiable data.
- Never fabricate values.
- If data is unavailable, state "Unavailable."
- Keep interpretations neutral and factual.
- Do not provide trading advice. Only describe what the signals show.
- Cite source for every signal.

## Dependencies

- Python 3 (standard library only — `urllib`, `json`, `statistics`)
- `scripts/fetch_signals.py` bundled in this skill directory
- Optional API keys for paid sources: `COINGLASS_API_KEY`, `GLASSNODE_API_KEY`
- Access to reliable data sources for the core signals: CoinGecko, Farside Investors, Coinglass, Glassnode, Stooq
