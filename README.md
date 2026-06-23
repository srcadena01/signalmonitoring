# Signal Monitoring

Fetches key Bitcoin & macro market signals (ETF flows, halving cycle, DXY,
dominance, funding rates, realized volatility) from free public data sources.

- `scripts/fetch_signals.py` — the fetcher (Python standard library only)
- `.github/workflows/fetch-signals.yml` — GitHub Action that runs the fetcher
  hourly and commits results to `data/`
- `data/signals-latest.json` — most recent fetch (auto-updated by the Action)
- `GITHUB_ACTION_SETUP.md` — how the auto-fetch + Claude-web reading works
- `SKILL.md` — the agent-skill definition

## Run locally

```bash
python scripts/fetch_signals.py            # default signal set, prints JSON
python scripts/fetch_signals.py dxy dominance   # specific signals
```

API keys for the optional paid sources (Coinglass, Glassnode) are read from
the environment (`COINGLASS_API_KEY`, `GLASSNODE_API_KEY`); without them those
signals return `"Unavailable"` rather than fabricated values.
