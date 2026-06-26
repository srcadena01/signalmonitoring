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

## How this repo runs itself (read this first if you forgot)

The whole point: get fresh signal data somewhere Claude on the web can read it,
without needing the script to run inside Claude's no-internet sandbox.

- A GitHub Action (`.github/workflows/fetch-signals.yml`) runs hourly on
  GitHub's servers, which DO have internet. It runs the fetcher and commits the
  result to `data/signals-latest.json`.
- Claude (web) reads that file over the internet as a plain URL — no sandbox
  network needed. Use the cache-buster so it never reads a stale copy:
  `https://raw.githubusercontent.com/srcadena01/signalmonitoring/main/data/signals-latest.json?nocache=<anything>`
- So day to day, you do nothing. The data keeps updating on its own.

## Git, in plain terms

Three separate actions — people mix these up:

- **commit** = save a labeled snapshot of your changes, on your computer only.
- **push**   = upload your commits to GitHub.
- **pull**   = download GitHub's commits into your computer.

You only touch git when YOU change a file. The catch: the hourly Action commits
to GitHub on its own, so GitHub is often ahead of your laptop. If you edit
something and try to push, GitHub may reject it ("you're missing some history").
The fix is always the same — grab GitHub's commits first, then push yours:

```bash
git pull --rebase   # get the Action's hourly commits
git push            # upload yours on top
```

To check you're in sync at any time: `git status`. "up to date with
'origin/main'" and "nothing to commit" = you're clean, close the laptop.

API keys for the optional paid sources (Coinglass, Glassnode) are read from
the environment (`COINGLASS_API_KEY`, `GLASSNODE_API_KEY`); without them those
signals return `"Unavailable"` rather than fabricated values.
