# Auto-fetching signals via GitHub Actions

This lets **Claude web read always-fresh signal data** without the claude.ai
sandbox needing internet. The fetching happens on GitHub's servers (which have
network access); Claude just reads the committed JSON file.

## How it works

```
GitHub Actions (hourly, has internet)
        │  runs scripts/fetch_signals.py
        ▼
data/signals-latest.json   ← committed back into the repo
        │
        ▼
Claude web (GitHub connector) reads the file — no sandbox network needed
```

## One-time setup

1. **Create a GitHub repo** and push this skill folder to it so the repo
   contains `scripts/fetch_signals.py` and `.github/workflows/fetch-signals.yml`
   at the repo root. (If you nest the skill in a subfolder, move `.github/` to
   the repo root and update the `python scripts/...` path in the workflow.)

2. **Enable Actions write access** (usually on by default):
   Repo **Settings → Actions → General → Workflow permissions** →
   "Read and write permissions".

3. *(Optional)* **Add API keys** so funding-rate / Glassnode signals populate:
   Repo **Settings → Secrets and variables → Actions → New repository secret**
   → add `COINGLASS_API_KEY` and/or `GLASSNODE_API_KEY`. Without them, those
   signals return `"Unavailable"` (never fabricated).

4. **Run it once by hand** to confirm: repo **Actions** tab →
   "Fetch market signals" → **Run workflow**. After it finishes, you should see
   `data/signals-latest.json` in the repo.

5. **Connect the repo to Claude web**: claude.ai → Settings → Connectors →
   GitHub → authorize this repo. Now ask Claude to read
   `data/signals-latest.json`.

## Adjusting the schedule

Edit the `cron` line in `.github/workflows/fetch-signals.yml`:
- `"0 * * * *"` — every hour (default)
- `"0 */4 * * *"` — every 4 hours
- `"0 13 * * *"` — once daily at 13:00 UTC

GitHub cron is always **UTC**, and scheduled runs can be delayed several
minutes under load — fine for hourly/daily data.

## Notes & honest caveats

- **ETF flows (Farside)** can still be Cloudflare-blocked even on GitHub's
  runners — when that happens the JSON shows `"Unavailable"` for `etf_flows`,
  by design. (The Jina-proxy fallback was rolled out of this version; re-add it
  if you want ETF flows to be more reliable here.)
- The dated snapshots (`data/signals-YYYY-MM-DD.json`) accumulate one file per
  run-day, giving you a growing history Claude can analyze over time.
- This costs GitHub Actions minutes; hourly runs are well within the free tier
  for a public repo (and modest for private).
