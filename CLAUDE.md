# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo does

Fetches Bitcoin and macro market signals (ETF flows, halving cycle, DXY, dominance, funding rates, realized volatility) from free public APIs. A GitHub Action runs the fetcher hourly and commits results to `data/signals-latest.json`, so Claude on the web can read fresh data without needing sandbox network access.

## Run locally

```bash
python scripts/fetch_signals.py                             # default core signal set
python scripts/fetch_signals.py dxy dominance               # by exact signal name
python scripts/fetch_signals.py "dollar strength and btc market share"  # natural phrasing
python scripts/fetch_signals.py --list                      # list all supported signals
python scripts/fetch_signals.py --history 14                # dated series for trend charts
```

No dependencies beyond Python 3 standard library (`urllib`, `json`, `statistics`). Optional API keys enable paid signals:
- `COINGLASS_API_KEY` — funding rates (Coinglass)
- `GLASSNODE_API_KEY` — on-chain extras (Glassnode)

Without keys, those signals return `"Unavailable"` rather than fabricated values.

## Sync with GitHub

The hourly Action commits to GitHub independently, so the remote is often ahead. Before pushing local edits:

```bash
git pull --rebase   # get the Action's commits first
git push            # upload yours on top
```

## Architecture

**Registry-driven design** — the signal set and routing live in `scripts/signals.json`, not in Python. To add a signal that reuses an existing source, edit the JSON only. To add a brand-new source, add a `get_*()` function in `fetch_signals.py`, register it in `FETCHERS`, then add the JSON entry.

Key files:
- `scripts/signals.json` — signal registry: names, sources, key requirements, plain-language aliases
- `scripts/fetch_signals.py` — all fetchers plus CLI entry point; reads the registry at runtime
- `.github/workflows/fetch-signals.yml` — hourly GitHub Action that commits results to `data/`
- `data/signals-latest.json` — always-current snapshot (never use dated snapshots for live data)
- `data/signals-history.json` — ~14-day series per chartable signal (`price`, `dxy`, `volatility_30d`, `etf_flows`, `halving_cycle`); `dominance` and `funding_rate` have no series

**Output schema** (both local and committed):
```json
{ "schema_version": "1.1", "generated_at": "<ISO UTC>", "signals": { "<name>": { "value", "trend", "source", "timestamp" } } }
```

**Signal resolution** — `resolve_signals()` matches CLI args against signal names and their `aliases` list (whole-word, case-insensitive). Unrecognized requests return a structured `"status": "unsupported"` response listing all supported signals.

**Farside ETF flows** — scraped (no JSON API). Tries the site directly first; falls back to the `r.jina.ai` reader proxy when Cloudflare blocks. Parse logic in `_parse_farside_flows()` works on both raw HTML and the proxy's Markdown.

**Reading committed data from the web** — always append a unique cache-buster to avoid stale CDN copies:
```
https://raw.githubusercontent.com/srcadena01/signalmonitoring/main/data/signals-latest.json?nocache=<unique>
```
Check `generated_at` before using the data; if it's more than a few hours old, re-fetch with a new cache-buster.

## Agent skill

`SKILL.md` defines this repo as a Claude agent skill (`signal-monitoring-agent-skill`). The skill instructs Claude to prefer the committed `signals-latest.json` (via `web_fetch`) over running the script locally, since the claude.ai sandbox has no network. `GITHUB_ACTION_SETUP.md` covers the one-time GitHub setup.
