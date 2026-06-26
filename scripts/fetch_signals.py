#!/usr/bin/env python3
"""
Fetches Bitcoin and macro market signals from real data sources for the
signal-monitoring-agent-skill.

How it's organized:
  - signals.json (the "registry") holds the list of signals, their labels,
    sources, key requirements, and the plain-language aliases people might use
    for them. Adding or renaming a signal is mostly a JSON edit.
  - The Python below just does the fetching and the matching. You can ask for
    signals by exact name or by natural phrasing (the resolver checks aliases).
  - Anything we can't fetch is reported as "Unavailable" — never made up.

Sources:
  - CoinGecko     (free, no key)     -> dominance, price, realized volatility
  - Farside       (free; r.jina.ai)  -> spot Bitcoin ETF flows
  - Yahoo Finance (free, no key)     -> DXY (US Dollar Index)
  - Coinglass     (key required)     -> perpetual funding rates
  - Glassnode     (key required)     -> on-chain extras (optional)

API keys come from environment variables so nothing secret sits in the code:
  COINGLASS_API_KEY, GLASSNODE_API_KEY
"""

import json
# Used to make the collected information readable
import os
# Reads environment variables (the API keys)
import re
# 'Regular expressions'; used to scrape raw text
import statistics
# Math helpers — standard deviation, median
import sys
# Gives access to system-specific parameters, functions & environment
import urllib.error
# Distinguishes errors
import urllib.request
# Only works when run in the user's own environment if given network access
from datetime import datetime, timezone
# Used for timestamps and the halving-cycle calculation

USER_AGENT = "Mozilla/5.0 (signal-monitoring-agent-skill)"
# identification when making an HTTP request
TIMEOUT = 15  # seconds — so a dead server can't hang the script forever

REGISTRY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "signals.json")
# Look for signals.json next to this script, no matter where it's run from


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
# readable UTC timestamp


def _get(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()
# carrying out the actual data request, and returning what's collected


def _unavailable(source, reason):
    return {"value": "Unavailable", "reason": reason, "source": source, "timestamp": _now()}
# Clearly state when unable to find relevant data


# ---------------------------------------------------------------------------
# CoinGecko (free, no key) — used to collect dominance, price, realized volatility
# ---------------------------------------------------------------------------

def get_bitcoin_dominance():
    # 'Dominance' = Bitcoin's share of the whole crypto market's value
    source = "CoinGecko (https://api.coingecko.com/api/v3/global)"
    try:
        data = json.loads(_get("https://api.coingecko.com/api/v3/global"))
        pct = data["data"]["market_cap_percentage"]["btc"]
        return {"value": round(pct, 2), "trend": None, "source": source, "timestamp": _now()}
    except (urllib.error.URLError, KeyError, json.JSONDecodeError) as e:
        return _unavailable(source, str(e))
    # If the download, the expected field, or the JSON parsing fails -> Unavailable


def get_btc_price_usd():
    # Current BTC/USD spot price plus its 24h change
    source = "CoinGecko (https://api.coingecko.com/api/v3/simple/price)"
    try:
        data = json.loads(_get(
            "https://api.coingecko.com/api/v3/simple/price"
            "?ids=bitcoin&vs_currencies=usd&include_24hr_change=true"
        ))
        return {
            "value": data["bitcoin"]["usd"],
            "trend": f"{data['bitcoin'].get('usd_24h_change', 0):.2f}% (24h)",
            "source": source,
            "timestamp": _now(),
        }
    except (urllib.error.URLError, KeyError, json.JSONDecodeError) as e:
        return _unavailable(source, str(e))


def get_btc_realized_volatility(days=30):
    # 'Volatility' = how much the price swings day to day, annualized to a %
    source = f"CoinGecko (market_chart, {days}d)"
    try:
        # Ask for days+1 prices — N daily changes need N+1 points
        data = json.loads(_get(
            f"https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
            f"?vs_currency=usd&days={days + 1}&interval=daily"
        ))
        prices = [p[1] for p in data["prices"]]
        if len(prices) < 3:
            return _unavailable(source, "Insufficient price history returned")
        # Daily % changes, then their spread (stdev), scaled up to a yearly figure
        returns = [(prices[i] / prices[i - 1]) - 1 for i in range(1, len(prices)) if prices[i - 1] > 0]
        annualized_pct = statistics.stdev(returns) * (365 ** 0.5) * 100
        return {
            "value": round(annualized_pct, 2),
            "trend": f"{days}-day window, annualized",
            "source": source,
            "timestamp": _now(),
        }
    except (urllib.error.URLError, KeyError, json.JSONDecodeError, statistics.StatisticsError) as e:
        return _unavailable(source, str(e))


# ---------------------------------------------------------------------------
# Farside Investors — spot Bitcoin ETF flows (free, via r.jina.ai when blocked)
# ---------------------------------------------------------------------------
# 'Net flow' = money into the ETFs minus money out, per day. Farside has no
# clean data feed and hides behind Cloudflare, so we scrape the page — directly
# if we can, otherwise through the free r.jina.ai reader proxy which gets past
# the Cloudflare block for us. If the page layout changes this may need updating.

_FARSIDE_DATE_PAT = re.compile(r"\b(\d{2}\s+[A-Za-z]{3}\s+\d{4})\b")
# matches a date like "04 Jun 2026"


def _to_number(text):
    # Farside writes negatives in parentheses, e.g. "(528.3)" = -528.3
    cleaned = text.strip().replace(",", "").replace("(", "-").replace(")", "")
    try:
        return float(cleaned)
    except ValueError:
        return None
    # not a number (e.g. "-" for a not-yet-reported day)


def _fetch_farside_text():
    # Try the site directly first — quick, but often Cloudflare-blocked
    try:
        html = _get("https://farside.co.uk/btc/").decode("utf-8", errors="ignore")
        if "Just a moment" not in html and "challenge-platform" not in html:
            return html
    except urllib.error.URLError:
        pass
    # Fall back to the free reader proxy, which gets past Cloudflare
    try:
        return _get("https://r.jina.ai/https://farside.co.uk/btc/").decode("utf-8", errors="ignore")
    except urllib.error.URLError:
        return None
    # Both attempts failed


def _parse_farside_flows(text):
    # Works on the site's HTML or the proxy's Markdown: each daily line is a
    # date followed by several numbers, the LAST being that day's "Total".
    results = []
    for line in text.splitlines():
        date_match = _FARSIDE_DATE_PAT.search(line)
        if not date_match:
            continue
        numbers = [n for n in (_to_number(c) for c in re.split(r"[|\s]+", line[date_match.end():])) if n is not None]
        if len(numbers) >= 2:  # real rows have per-issuer columns + a Total
            results.append((date_match.group(1), numbers[-1]))
    return results


def get_bitcoin_etf_flows():
    # Most recent day's total net flow across US spot Bitcoin ETFs
    source = "Farside Investors (https://farside.co.uk/btc/, via r.jina.ai when blocked)"
    text = _fetch_farside_text()
    if text is None:
        return _unavailable(source, "Could not retrieve Farside data (direct fetch and proxy both failed)")
    flows = _parse_farside_flows(text)
    if not flows:
        return _unavailable(source, "Retrieved the page but could not find a parsable daily flow row")
    latest_date, latest_value = flows[-1]  # rows run oldest->newest, so last = most recent
    return {"value": f"${latest_value:.1f}M", "trend": f"as of {latest_date}",
            "source": source, "timestamp": _now()}


# ---------------------------------------------------------------------------
# Yahoo Finance (free, no key) — DXY US Dollar Index
# ---------------------------------------------------------------------------

def get_dxy():
    # DXY = the dollar's strength vs a basket of major currencies (ticker DX-Y.NYB)
    source = "Yahoo Finance (https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB)"
    try:
        data = json.loads(_get(
            "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?range=5d&interval=1d"
        ))
        meta = data["chart"]["result"][0]["meta"]
        price = meta["regularMarketPrice"]
        prev_close = meta.get("chartPreviousClose")
        # Trend = % change vs the prior close, only if we have one to compare to
        trend = f"{(price / prev_close - 1) * 100:+.2f}% vs prior close" if prev_close else None
        return {"value": price, "trend": trend, "source": source, "timestamp": _now()}
    except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError) as e:
        return _unavailable(source, str(e))


# ---------------------------------------------------------------------------
# Coinglass (key required) — perpetual funding rates
# ---------------------------------------------------------------------------

def get_btc_funding_rates(exchange="Binance"):
    # Funding rate = small periodic payment between leveraged longs and shorts;
    # hints at which side is crowded. Needs a Coinglass API key.
    source = "Coinglass (https://open-api-v4.coinglass.com)"
    api_key = os.environ.get("COINGLASS_API_KEY")
    if not api_key:
        return _unavailable(source, "COINGLASS_API_KEY not set")
    try:
        url = "https://open-api-v4.coinglass.com/api/futures/funding-rate?symbol=BTC"
        data = json.loads(_get(url, headers={"CG-API-KEY": api_key}))
        rows = data.get("data", [])
        # Prefer the chosen exchange's row; otherwise fall back to whatever's first
        match = next((r for r in rows if r.get("exchangeName") == exchange), None) or (rows[0] if rows else None)
        if not match:
            return _unavailable(source, "No funding rate rows returned")
        return {
            "value": f"{float(match.get('fundingRate', 0)) * 100:.4f}%",  # decimal -> %
            "trend": match.get("exchangeName", exchange),
            "source": source,
            "timestamp": _now(),
        }
    except (urllib.error.URLError, KeyError, ValueError, json.JSONDecodeError) as e:
        return _unavailable(source, str(e))


# ---------------------------------------------------------------------------
# Glassnode (key required) — generic on-chain metric fetcher (optional extras)
# ---------------------------------------------------------------------------

def get_glassnode_metric(endpoint, asset="BTC", params=None):
    # One flexible fetcher for ANY Glassnode metric (MVRV, SOPR, active supply...).
    # endpoint = the metric path; needs a Glassnode API key.
    source = f"Glassnode ({endpoint})"
    api_key = os.environ.get("GLASSNODE_API_KEY")
    if not api_key:
        return _unavailable(source, "GLASSNODE_API_KEY not set")
    try:
        # Build the query string (the bit after "?"): always asset + key, plus extras
        query = f"a={asset}&api_key={api_key}"
        if params:
            query += "&" + "&".join(f"{k}={v}" for k, v in params.items())
        data = json.loads(_get(f"https://api.glassnode.com/v1/metrics/{endpoint}?{query}"))
        if not data:
            return _unavailable(source, "Empty response")
        latest = data[-1]  # most recent point
        return {
            "value": latest.get("v"),  # "v" = the value
            "trend": datetime.fromtimestamp(latest.get("t", 0), tz=timezone.utc).isoformat(timespec="seconds"),
            "source": source,
            "timestamp": _now(),
        }
    except (urllib.error.URLError, KeyError, ValueError, json.JSONDecodeError) as e:
        return _unavailable(source, str(e))


# ---------------------------------------------------------------------------
# Halving cycle — computed from known dates, no internet needed
# ---------------------------------------------------------------------------

HALVING_DATES = [
    datetime(2012, 11, 28, tzinfo=timezone.utc),
    datetime(2016, 7, 9, tzinfo=timezone.utc),
    datetime(2020, 5, 11, tzinfo=timezone.utc),
    datetime(2024, 4, 20, tzinfo=timezone.utc),
]
# Bitcoin halvings happen ~every 4 years; these are the historical dates
AVG_CYCLE_DAYS = 1458  # ~4 years between halvings, historical average


def get_halving_cycle_position():
    # How far we are past the last halving, and through the typical ~4yr cycle
    now = datetime.now(timezone.utc)
    last_halving = max(d for d in HALVING_DATES if d <= now)  # most recent past halving
    days_elapsed = (now - last_halving).days
    months_elapsed = days_elapsed / 30.4368  # avg days per month
    cycle_fraction = min(days_elapsed / AVG_CYCLE_DAYS, 1.0)  # capped at 100%
    next_estimated = last_halving.replace(year=last_halving.year + 4)
    return {
        "value": f"{months_elapsed:.1f} months post-halving",
        "trend": f"{cycle_fraction * 100:.0f}% through historical avg cycle length",
        "source": f"Computed from known halving date {last_halving.date()} (next estimated ~{next_estimated.date()})",
        "timestamp": _now(),
    }


# ---------------------------------------------------------------------------
# REGISTRY GLUE — connect the JSON registry to the Python fetchers
# ---------------------------------------------------------------------------
# signals.json refers to each fetcher by a short name; this maps that name to
# the real function. Reusing an existing source = JSON-only edit; a brand-new
# source = add a function here plus a JSON entry.
FETCHERS = {
    "etf_flows": get_bitcoin_etf_flows,
    "dominance": get_bitcoin_dominance,
    "price": get_btc_price_usd,
    "volatility_30d": lambda: get_btc_realized_volatility(30),  # lambda pins the 30d window
    "dxy": get_dxy,
    "funding_rate": get_btc_funding_rates,
    "halving_cycle": get_halving_cycle_position,
}


def load_registry():
    with open(REGISTRY_PATH, encoding="utf-8") as f:
        return json.load(f)
# read signals.json into Python


def resolve_signals(query_text, registry):
    # Turn plain-language words into signal names by matching them against each
    # signal's name + aliases (whole-word, case-insensitive).
    # Returns (matched names, did-anything-match).
    text_lower = query_text.lower()
    matched = []
    for name, meta in registry["signals"].items():
        candidates = [name.replace("_", " "), name] + meta.get("aliases", [])
        for phrase in candidates:
            # \b...\b = whole-word match, so "vol" won't hit "evolve"
            if re.search(r"\b" + re.escape(phrase.lower()) + r"\b", text_lower):
                if name not in matched:
                    matched.append(name)
                break
    return matched, bool(matched)


def build_manifest(registry):
    # The "what can this skill fetch?" list — used by --list and by the
    # unsupported-request reply so the caller can see the options.
    return {
        "schema_version": registry.get("schema_version"),
        "available_signals": [
            {
                "name": name,
                "label": meta["label"],
                "requires_key": meta.get("requires_key"),
                "source": meta.get("source"),
                "aliases": meta.get("aliases", []),
            }
            for name, meta in registry["signals"].items()
        ],
        "default_signals": registry.get("default_signals", []),
    }


# ---------------------------------------------------------------------------
# CLI ENTRY POINT
# ---------------------------------------------------------------------------
# Usage:
#   python fetch_signals.py                         -> default signal set
#   python fetch_signals.py dxy dominance           -> by exact name
#   python fetch_signals.py "dollar strength and btc market share"  -> natural phrasing
#   python fetch_signals.py --list                  -> what this skill supports

def main():
    registry = load_registry()
    args = sys.argv[1:]  # everything typed after the script name

    # --list / --help -> just print the capability manifest and stop
    if args and args[0] in ("--list", "--help", "-h"):
        print(json.dumps(build_manifest(registry), indent=2))
        return

    # No args -> default core set. Otherwise resolve the phrase against aliases.
    if not args:
        requested = registry.get("default_signals", list(registry["signals"].keys()))
    else:
        requested, matched_anything = resolve_signals(" ".join(args), registry)
        if not matched_anything:
            # Nothing recognised -> say so plainly and list what IS supported
            print(json.dumps({
                "schema_version": registry.get("schema_version"),
                "generated_at": _now(),
                "status": "unsupported",
                "query": " ".join(args),
                "reason": "No known signal matched this request.",
                "supported": build_manifest(registry)["available_signals"],
                "suggestion": "Ask for one of the supported signals above, or extend signals.json to add a new source.",
            }, indent=2, default=str))
            return

    # Fetch each resolved signal through its registered fetcher
    signals = {}
    for name in requested:
        meta = registry["signals"].get(name)
        func = FETCHERS.get(meta["fetcher"]) if meta else None
        if func is None:
            signals[name] = {"value": "Unavailable", "reason": f"No fetcher registered for '{name}'"}
            continue
        signals[name] = func()

    # generated_at lets a consumer (e.g. Claude reading committed data) tell how
    # fresh this is by comparing it to "now"
    print(json.dumps({
        "schema_version": registry.get("schema_version"),
        "generated_at": _now(),
        "signals": signals,
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
# only runs main() when launched directly, not when imported by another file
