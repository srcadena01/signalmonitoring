---
name: updated-signal-monitoring-agent-skill
description: Adaptable version — fetches and structures key signals (ETF flows, halving cycle, macro proxies, volatility, etc.) via a config-driven registry with natural-language routing, a capability manifest, and reliable ETF-flow fetching.
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
2a. Always `web_fetch` the pre-fetched signal data as the **primary** source
   (it is committed hourly by a GitHub Action, and works even where the local
   script has no network — e.g. the claude.ai sandbox). Use the
   **`signals-latest.json`** file ONLY — never a dated `signals-YYYY-MM-DD.json`
   snapshot (those are frozen history). Append a **unique cache-buster** query
   string each run so neither claude.ai nor GitHub's CDN serves a stale copy:

   ```
   https://raw.githubusercontent.com/srcadena01/signalmonitoring/main/data/signals-latest.json?nocache=<unique>
   ```

   Replace `<unique>` with the current date-time or a random value every time.
   **Verify freshness before using the data:** read the top-level
   `generated_at` (or, on older files without it, a signal's `timestamp`) and
   confirm it is recent. If it is more than a few hours old — or still shows a
   previous day — state that the data is stale and re-fetch with a new
   cache-buster before relying on it.

   Then **supplement with `web_search`** for the macro narrative, ETF flows,
   and any signals the JSON marks as `"Unavailable"`. Prefer the committed
   JSON's values; only fall back to `scripts/fetch_signals.py` when running
   locally with network access.
3. For each signal, record the current value, recent trend, and a short interpretation.
4. Determine the overall market regime.
5. Generate a one-sentence overall summary of what the signals imply for MintLocke rules.
6. Return results using the minimal output format below — keep text to a minimum.

## Tooling

Use the bundled script to pull real data instead of estimating from memory:

```
python scripts/fetch_signals.py [signal_name ... | natural-language request]
python scripts/fetch_signals.py --list        # what the skill can fetch
```

The set of signals, their sources, key requirements, and the plain-language
**aliases** that map to them all live in `scripts/signals.json` (the
"registry"). To add or rename a signal that reuses an existing source, edit
that JSON — no Python change needed.

You can request signals three ways:
- **No arguments** → the default core set.
- **By exact name** → `python scripts/fetch_signals.py dxy dominance`.
- **By natural phrasing** → `python scripts/fetch_signals.py "dollar strength and btc market share"` resolves to `dxy` + `dominance` via the registry aliases.

If nothing in the request matches a known signal, the script returns a
structured `"status": "unsupported"` result that lists every supported signal
— surface that to the user instead of guessing.

Output is a JSON object: `{ "schema_version", "generated_at", "signals": {…} }`.
`generated_at` lets a consumer (e.g. Claude reading committed data) judge
**staleness** by comparing it to the current time.

| Signal name      | Maps to                                | Source                |
|------------------|-----------------------------------------|------------------------|
| `etf_flows`      | Bitcoin ETF Flows                       | Farside Investors (free; via `r.jina.ai` reader proxy when Cloudflare blocks) |
| `halving_cycle`  | Bitcoin Halving Cycle Position           | Computed from known halving dates |
| `dxy`            | DXY (US Dollar Index)                   | Yahoo Finance (free, no key) |
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

Keep it **minimal** — favor the table over prose. No section is longer than it
has to be.

```
**Summary:** [1 sentence; 2 only if truly needed] · Confidence: High/Medium/Low

| Signal | Value | Trend | Read |
|--------|-------|-------|------|
| ...    | ...   | ↑/↓/→ | 🟢/🟡/🔴 1–3 words |

**For MintLocke:** [1 sentence]

<sub>Sources: … · as of <timestamp></sub>
```

- **Expand every ticker/abbreviation in parentheses the first time it appears**,
  then use the short form after — e.g. `DXY (US Dollar Index)`, `BTC (Bitcoin)`,
  `ETF (Exchange-Traded Fund)`, `RV (Realized Volatility)`.
- "Read" = a 1–3 word takeaway (e.g. "accumulating", "mild headwind", "neutral").
- **Use small, simple graphics** to make the read instant — but only ones that
  render reliably:
  - Trend arrows in the Trend column: `↑` rising · `↓` falling · `→` flat.
  - A status dot in the Read column: 🟢 supportive · 🟡 neutral · 🔴 cautionary.
  - Keep graphics minimal — one glyph, not decoration. Never let a graphic
    replace the actual number.
  - **Do NOT use Unicode block-element or sparkline characters** (the little
    bar-height glyphs or filled/empty progress blocks). They render
    inconsistently — misaligned boxes or "tofu" — across clients. Use ONLY the
    arrows and emoji dots above for inline cues; nothing else drawn from text
    characters.
- When a **visual chart** genuinely helps (e.g. a signal's recent history),
  render an actual small chart (an image/SVG), not text-block art. Keep it
  simple, and don't restate it in prose. If a real chart isn't available, just
  use the number plus an arrow.
- **Put sources at the very end, in a smaller font**, on one line using a
  `<sub>…</sub>` tag — list the data sources and the as-of timestamp, not a
  source per signal.

## Examples

### Example 1

User: "ETF flows, halving cycle, and dominance."

> **Summary:** ETF inflows strong and dominance rising — interest concentrated in BTC (Bitcoin). · Confidence: High
>
> | Signal | Value | Trend | Read |
> |--------|-------|-------|------|
> | BTC ETF (Exchange-Traded Fund) Flows | +$187M | ↑ | 🟢 accumulating |
> | Halving Cycle | 8.5 mo post-halving | → | 🟢 constructive |
> | BTC Dominance | 58.4% | ↑ | 🟢 rotation into BTC |
>
> **For MintLocke:** Supports maintaining or slightly raising BTC-focused risk.
>
> <sub>Sources: Farside Investors, CoinGecko · as of 2026-06-26</sub>

### Example 2

User: "Macro signals — DXY and funding."

> **Summary:** Stable macro, mildly elevated funding. · Confidence: Medium
>
> | Signal | Value | Trend | Read |
> |--------|-------|-------|------|
> | DXY (US Dollar Index) | 98.7 | ↑ | 🟡 mild USD strength |
> | BTC Funding Rate | +0.012% | ↑ | 🟡 longs crowding |
>
> **For MintLocke:** Caution on aggressive leverage rules.
>
> <sub>Sources: Yahoo Finance, Coinglass · as of 2026-06-26</sub>

### Example 3

User: "Pull the main signals for today." → full core set, same minimal format.

## Guardrails

- Only use verifiable data.
- Never fabricate values.
- If data is unavailable, state "Unavailable."
- Keep interpretations neutral and factual.
- Do not provide trading advice. Only describe what the signals show.
- **Be succinct.** Minimal text: Summary 1 sentence (2 max), "For MintLocke" 1
  sentence. Prefer the table; never add prose that just restates it.
- **Expand each ticker/abbreviation in parentheses on first use** (e.g.
  `DXY (US Dollar Index)`), then use the short form thereafter.
- Cite source for every signal.

## Dependencies

- Python 3 (standard library only — `urllib`, `json`, `statistics`)
- `scripts/fetch_signals.py` bundled in this skill directory
- Optional API keys for paid sources: `COINGLASS_API_KEY`, `GLASSNODE_API_KEY`
- Access to reliable data sources for the core signals: CoinGecko, Farside Investors, Coinglass, Glassnode, Stooq
