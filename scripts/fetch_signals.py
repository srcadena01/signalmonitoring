#!/usr/bin/env python3
"""
Fetches Bitcoin and macro market signals from real data sources for the
signal-monitoring-agent-skill.

Design notes:
  - The set of signals, their human labels, source names, key requirements,
    and the plain-language ALIASES that map to them all live in the companion
    file `signals.json` (the "registry"). Adding/renaming a signal is mostly a
    JSON edit — the Python below just fetches and dispatches.
  - You can ask for signals by exact name OR by natural phrasing; the resolver
    matches your words against each signal's aliases.
  - Unsupported requests are reported clearly (with the list of what IS
    supported), never faked.

Sources used:
  - CoinGecko    (free, no key)      -> dominance, price, realized volatility
  - Farside      (free; r.jina.ai)   -> spot Bitcoin ETF flows
  - Yahoo Finance(free, no key)      -> DXY (US Dollar Index)
  - Coinglass    (key required)      -> perpetual funding rates
  - Glassnode    (key required)      -> on-chain extras (optional)

API keys are read from environment variables so nothing secret is hardcoded:
  COINGLASS_API_KEY, GLASSNODE_API_KEY

Every fetcher returns a dict: {"value", "trend", "source", "timestamp"} on
success, or {"value": "Unavailable", "reason", ...} on failure. Guardrail:
if data is unavailable, say "Unavailable" — never fabricate values.
"""

import json
import os
import re
import statistics
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

USER_AGENT = "Mozilla/5.0 (signal-monitoring-agent-skill)"
TIMEOUT = 15  # seconds before giving up on a slow/dead server

# Where the registry lives — next to this script, so it's found no matter the
# working directory the script is launched from.
REGISTRY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "signals.json")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _get(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def _unavailable(source, reason):
    return {"value": "Unavailable", "reason": reason, "source": source, "timestamp": _now()}


# ---------------------------------------------------------------------------
# CoinGecko (free, no key) — dominance, price, realized volatility
# ---------------------------------------------------------------------------

def get_bitcoin_dominance():
    source = "CoinGecko (https://api.coingecko.com/api/v3/global)"
    try:
        data = json.loads(_get("https://api.coingecko.com/api/v3/global"))
        pct = data["data"]["market_cap_percentage"]["btc"]
        return {"value": round(pct, 2), "trend": None, "source": source, "timestamp": _now()}
    except (urllib.error.URLError, KeyError, json.JSONDecodeError) as e:
        return _unavailable(source, str(e))


def get_btc_price_usd():
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
    source = f"CoinGecko (market_chart, {days}d)"
    try:
        data = json.loads(_get(
            f"https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
            f"?vs_currency=usd&days={days + 1}&interval=daily"
        ))
        prices = [p[1] for p in data["prices"]]
        if len(prices) < 3:
            return _unavailable(source, "Insufficient price history returned")
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
# Farside hides its page behind Cloudflare, which often blocks plain scripts.
# We try the site directly, then fall back to the free r.jina.ai reader proxy,
# which loads the page (solving the challenge) and returns clean text.

_FARSIDE_DATE_PAT = re.compile(r"\b(\d{2}\s+[A-Za-z]{3}\s+\d{4})\b")


def _to_number(text):
    cleaned = text.strip().replace(",", "").replace("(", "-").replace(")", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _fetch_farside_text():
    # Attempt 1: direct (fast, but often Cloudflare-blocked).
    try:
        html = _get("https://farside.co.uk/btc/").decode("utf-8", errors="ignore")
        if "Just a moment" not in html and "challenge-platform" not in html:
            return html
    except urllib.error.URLError:
        pass
    # Attempt 2: free reader proxy that bypasses Cloudflare.
    try:
        return _get("https://r.jina.ai/https://farside.co.uk/btc/").decode("utf-8", errors="ignore")
    except urllib.error.URLError:
        return None


def _parse_farside_flows(text):
    # Works on both the site's HTML and the proxy's Markdown: each daily line
    # is a date followed by several numbers, the last being that day's "Total".
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
    source = "Farside Investors (https://farside.co.uk/btc/, via r.jina.ai when blocked)"
    text = _fetch_farside_text()
    if text is None:
        return _unavailable(source, "Could not retrieve Farside data (direct fetch and proxy both failed)")
    flows = _parse_farside_flows(text)
    if not flows:
        return _unavailable(source, "Retrieved the page but could not find a parsable daily flow row")
    latest_date, latest_value = flows[-1]
    return {"value": f"${latest_value:.1f}M", "trend": f"as of {latest_date}",
            "source": source, "timestamp": _now()}


# ---------------------------------------------------------------------------
# Yahoo Finance (free, no key) — DXY US Dollar Index
# ---------------------------------------------------------------------------

def get_dxy():
    source = "Yahoo Finance (https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB)"
    try:
        data = json.loads(_get(
            "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?range=5d&interval=1d"
        ))
        meta = data["chart"]["result"][0]["meta"]
        price = meta["regularMarketPrice"]
        prev_close = meta.get("chartPreviousClose")
        trend = f"{(price / prev_close - 1) * 100:+.2f}% vs prior close" if prev_close else None
        return {"value": price, "trend": trend, "source": source, "timestamp": _now()}
    except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError) as e:
        return _unavailable(source, str(e))


# ---------------------------------------------------------------------------
# Coinglass (key required) — perpetual funding rates
# ---------------------------------------------------------------------------

def get_btc_funding_rates(exchange="Binance"):
    source = "Coinglass (https://open-api-v4.coinglass.com)"
    api_key = os.environ.get("COINGLASS_API_KEY")
    if not api_key:
        return _unavailable(source, "COINGLASS_API_KEY not set")
    try:
        url = "https://open-api-v4.coinglass.com/api/futures/funding-rate?symbol=BTC"
        data = json.loads(_get(url, headers={"CG-API-KEY": api_key}))
        rows = data.get("data", [])
        match = next((r for r in rows if r.get("exchangeName") == exchange), None) or (rows[0] if rows else None)
        if not match:
            return _unavailable(source, "No funding rate rows returned")
        return {
            "value": f"{float(match.get('fundingRate', 0)) * 100:.4f}%",
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
    source = f"Glassnode ({endpoint})"
    api_key = os.environ.get("GLASSNODE_API_KEY")
    if not api_key:
        return _unavailable(source, "GLASSNODE_API_KEY not set")
    try:
        query = f"a={asset}&api_key={api_key}"
        if params:
            query += "&" + "&".join(f"{k}={v}" for k, v in params.items())
        data = json.loads(_get(f"https://api.glassnode.com/v1/metrics/{endpoint}?{query}"))
        if not data:
            return _unavailable(source, "Empty response")
        latest = data[-1]
        return {
            "value": latest.get("v"),
            "trend": datetime.fromtimestamp(latest.get("t", 0), tz=timezone.utc).isoformat(timespec="seconds"),
            "source": source,
            "timestamp": _now(),
        }
    except (urllib.error.URLError, KeyError, ValueError, json.JSONDecodeError) as e:
        return _unavailable(source, str(e))


# ---------------------------------------------------------------------------
# Halving cycle — computed, no internet needed
# ---------------------------------------------------------------------------

HALVING_DATES = [
    datetime(2012, 11, 28, tzinfo=timezone.utc),
    datetime(2016, 7, 9, tzinfo=timezone.utc),
    datetime(2020, 5, 11, tzinfo=timezone.utc),
    datetime(2024, 4, 20, tzinfo=timezone.utc),
]
AVG_CYCLE_DAYS = 1458  # ~4 years between halvings, historical average


def get_halving_cycle_position():
    now = datetime.now(timezone.utc)
    last_halving = max(d for d in HALVING_DATES if d <= now)
    days_elapsed = (now - last_halving).days
    months_elapsed = days_elapsed / 30.4368
    cycle_fraction = min(days_elapsed / AVG_CYCLE_DAYS, 1.0)
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
# The registry (signals.json) refers to each fetcher by a short name; this dict
# maps that name to the actual function. Adding a signal that reuses an
# existing source is a pure JSON edit; a brand-new source means adding one
# function here plus a JSON entry.
FETCHERS = {
    "etf_flows": get_bitcoin_etf_flows,
    "dominance": get_bitcoin_dominance,
    "price": get_btc_price_usd,
    "volatility_30d": lambda: get_btc_realized_volatility(30),
    "dxy": get_dxy,
    "funding_rate": get_btc_funding_rates,
    "halving_cycle": get_halving_cycle_position,
}


def load_registry():
    with open(REGISTRY_PATH, encoding="utf-8") as f:
        return json.load(f)


def resolve_signals(query_text, registry):
    """
    Turn a plain-language request into a list of signal names, by matching the
    user's words against each signal's name and aliases (word-boundary match,
    case-insensitive). Returns (matched_signal_names, matched_anything).
    """
    text_lower = query_text.lower()
    matched = []
    for name, meta in registry["signals"].items():
        # The signal's own name plus all its aliases are candidate phrases.
        candidates = [name.replace("_", " "), name] + meta.get("aliases", [])
        for phrase in candidates:
            if re.search(r"\b" + re.escape(phrase.lower()) + r"\b", text_lower):
                if name not in matched:
                    matched.append(name)
                break
    return matched, bool(matched)


def build_manifest(registry):
    """A capability list — what this skill can fetch — for --list and for the
    'unsupported' response so callers can see the options."""
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
#   python fetch_signals.py "show me dollar strength and btc market share"
#                                                   -> by natural phrasing
#   python fetch_signals.py --list                  -> what this skill supports

def main():
    registry = load_registry()
    args = sys.argv[1:]

    # --list / --help: print the capability manifest and exit.
    if args and args[0] in ("--list", "--help", "-h"):
        print(json.dumps(build_manifest(registry), indent=2))
        return

    # No args -> default core set. Otherwise treat all args as one request
    # phrase and resolve it against the registry's names + aliases.
    if not args:
        requested = registry.get("default_signals", list(registry["signals"].keys()))
    else:
        requested, matched_anything = resolve_signals(" ".join(args), registry)
        if not matched_anything:
            # Nothing recognised -> say so clearly, list what IS supported.
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

    # Fetch each resolved signal via its registered fetcher.
    signals = {}
    for name in requested:
        meta = registry["signals"].get(name)
        func = FETCHERS.get(meta["fetcher"]) if meta else None
        if func is None:
            signals[name] = {"value": "Unavailable", "reason": f"No fetcher registered for '{name}'"}
            continue
        signals[name] = func()

    # Wrap with metadata: schema version + when this was generated. Consumers
    # (e.g. Claude reading committed data) can compare generated_at to "now" to
    # judge staleness.
    print(json.dumps({
        "schema_version": registry.get("schema_version"),
        "generated_at": _now(),
        "signals": signals,
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
