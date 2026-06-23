# Signal Monitoring

Fetches key Bitcoin & macro market signals (ETF flows, halving cycle, DXY,
dominance, funding rates, realized volatility) from free public data sources.

- `scripts/fetch_signals.py` — the fetcher (Python standard library only)
- `scripts/signals.json` — the **signal registry**: names, sources, key
  requirements, and plain-language aliases. Add/rename signals by editing this.
- `.github/workflows/fetch-signals.yml` — GitHub Action that runs the fetcher
  hourly and commits results to `data/`
- `data/signals-latest.json` — most recent fetch (auto-updated by the Action)
- `GITHUB_ACTION_SETUP.md` — how the auto-fetch + Claude-web reading works
- `SKILL.md` — the agent-skill definition

## Run locally

```bash
python scripts/fetch_signals.py                 # default signal set, prints JSON
python scripts/fetch_signals.py dxy dominance   # specific signals by name
python scripts/fetch_signals.py "dollar strength and btc market share"  # natural phrasing
python scripts/fetch_signals.py --list          # list everything the skill can fetch
```

Requests that match no known signal return a structured `"unsupported"`
response listing what *is* supported — never a fabricated value.

## Adding a new signal

1. If it reuses an existing source, just add an entry to
   `scripts/signals.json` (label, fetcher, aliases, source, requires_key).
2. If it needs a brand-new source, add a `get_*()` function in
   `fetch_signals.py`, register it in the `FETCHERS` dict, then add the JSON
   entry. That's it — the resolver, `--list`, and CLI pick it up automatically.

API keys for the optional paid sources (Coinglass, Glassnode) are read from
the environment (`COINGLASS_API_KEY`, `GLASSNODE_API_KEY`); without them those
signals return `"Unavailable"` rather than fabricated values.
