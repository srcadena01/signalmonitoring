#!/usr/bin/env python3
"""
Fetches Bitcoin and macro market signals from real data sources for the
signal-monitoring-agent-skill.

Sources used:
  - CoinGecko   (free, no API key)        -> dominance, price/volatility
  - Farside Investors (free, scraped)     -> spot Bitcoin ETF flows
  - Coinglass   (API key required)        -> perpetual funding rates
  - Glassnode   (API key required)        -> on-chain metrics (optional extras)
  - stooq.com   (free, no API key)        -> DXY (US Dollar Index)

API keys (only needed for Coinglass / Glassnode) are read from environment
variables so no secrets are hardcoded:
  COINGLASS_API_KEY
  GLASSNODE_API_KEY

Currently, do not have access to these API keys

Every function returns a dict with a consistent shape:
  {
    "value": <number or string>,
    "trend": <string, optional>,
    "source": <string, URL or provider name>,
    "timestamp": <ISO8601 UTC string>,
  }
or, if the data could not be retrieved:
  {
    "value": "Unavailable",
    "reason": <string>,
    "source": <string>,
    "timestamp": <ISO8601 UTC string>,
  }

This mirrors the skill's guardrail: "If data is unavailable, state
'Unavailable'." Never fabricate values.
"""

import json
# Used to make the collected information readable
import os
import re
# 'Regular expressions'; used to scrape raw text
import statistics
import sys
# Gives access to system-specific parameters, functions & environment
import urllib.error
# Distiguishes errors
import urllib.request
# Only works when run in the user's own environment if not given network access
from datetime import datetime, timezone
# Used to check data staleness, calculate halving cycle position, timestamps

USER_AGENT = "Mozilla/5.0 (signal-monitoring-agent-skill)"
# identification when making an HTTP request
TIMEOUT = 15 #seconds


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
#readable timestamps


def _get(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()
#carrying out the actual data request, and returning what's collected


def _unavailable(source, reason):
    return {"value": "Unavailable", "reason": reason, "source": source, "timestamp": _now()}
#Clearly state when unable to find relevant data


# ---------------------------------------------------------------------------
# CoinGecko (free, no key) — used to collect data about dominance, price, realized volatility
# ---------------------------------------------------------------------------

def get_bitcoin_dominance():
    """Current BTC market dominance (%) via CoinGecko /global."""
    source = "CoinGecko (https://api.coingecko.com/api/v3/global)"
    try:
        data = json.loads(_get("https://api.coingecko.com/api/v3/global"))
        pct = data["data"]["market_cap_percentage"]["btc"]
        return {
            "value": round(pct, 2),
            "trend": None,
            "source": source,
            "timestamp": _now(),
        }
    except (urllib.error.URLError, KeyError, json.JSONDecodeError) as e:
        return _unavailable(source, str(e))


def get_btc_price_usd():
    """Current BTC/USD spot price via CoinGecko simple price endpoint."""
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
    """
    Annualized realized volatility of BTC over the trailing `days` window,
    computed from daily log returns via CoinGecko market_chart.
    """
    source = f"CoinGecko (https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?days={days})"
    try:
        data = json.loads(_get(
            f"https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
            f"?vs_currency=usd&days={days + 1}&interval=daily"
        ))
        prices = [p[1] for p in data["prices"]]
        if len(prices) < 3:
            return _unavailable(source, "Insufficient price history returned")
        returns = []
        for i in range(1, len(prices)):
            if prices[i - 1] > 0:
                returns.append((prices[i] / prices[i - 1]) - 1)
        daily_std = statistics.stdev(returns)
        annualized_pct = daily_std * (365 ** 0.5) * 100
        return {
            "value": round(annualized_pct, 2),
            "trend": f"{days}-day window, annualized",
            "source": source,
            "timestamp": _now(),
        }
    except (urllib.error.URLError, KeyError, json.JSONDecodeError, statistics.StatisticsError) as e:
        return _unavailable(source, str(e))


# ---------------------------------------------------------------------------
# Farside Investors (free, scraped HTML) — used to spot Bitcoin ETF flows
# ---------------------------------------------------------------------------

def get_bitcoin_etf_flows():
    """
    Latest daily total net flow (USD millions) across US spot Bitcoin ETFs,
    scraped from the Farside Investors flow table.
    """
    source = "Farside Investors (https://farside.co.uk/btc/)"
    try:
        html = _get("https://farside.co.uk/btc/").decode("utf-8", errors="ignore")
        if "Just a moment" in html or "cf-mitigated" in html or "challenge-platform" in html:
            return _unavailable(source, "Blocked by Cloudflare bot-challenge page (no real data returned)")
        # Real daily rows look like:
        # ['04 Jun 2026', '47.7', '(5.5)', ..., '3.2']  -> date + per-issuer
        # columns + a trailing "Total" column, 14 cells wide on the BTC
        # page. We take the last such row as the most recent date.
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)
        date_pat = re.compile(r"^\d{2}\s+[A-Za-z]{3}\s+\d{4}$")
        num_pat = re.compile(r"^\(?-?[\d,]*\.?\d+\)?$")
        latest_value, latest_date = None, None
        for row in rows:
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
            if len(cells) < 3:
                continue
            texts = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            if not date_pat.match(texts[0]):
                continue
            if not all(num_pat.match(t) for t in texts[1:]):
                continue
            last_cell_text = texts[-1].replace(",", "").replace("(", "-").replace(")", "")
            try:
                value = float(last_cell_text)
            except ValueError:
                continue
            latest_value, latest_date = value, texts[0]
        if latest_value is None:
            return _unavailable(source, "Could not find a parsable daily flow row")
        return {
            "value": f"${latest_value:.1f}M",
            "trend": f"as of {latest_date}",
            "source": source,
            "timestamp": _now(),
        }
    except urllib.error.URLError as e:
        return _unavailable(source, str(e))


# ---------------------------------------------------------------------------
# Yahoo Finance chart API (free, no key) — valid data on DXY US Dollar Index
# ---------------------------------------------------------------------------

def get_dxy():
    """Latest DXY (ICE US Dollar Index, ticker DX-Y.NYB) via Yahoo Finance."""
    source = "Yahoo Finance (https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB)"
    try:
        data = json.loads(_get(
            "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?range=5d&interval=1d"
        ))
        meta = data["chart"]["result"][0]["meta"]
        price = meta["regularMarketPrice"]
        prev_close = meta.get("chartPreviousClose")
        trend = None
        if prev_close:
            trend = f"{(price / prev_close - 1) * 100:+.2f}% vs prior close"
        return {
            "value": price,
            "trend": trend,
            "source": source,
            "timestamp": _now(),
        }
    except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError) as e:
        return _unavailable(source, str(e))


# ---------------------------------------------------------------------------
# Coinglass (API key required) — used to find perpetual funding rates
# ---------------------------------------------------------------------------

def get_btc_funding_rates(exchange="Binance"):
    """
    Current BTC perpetual funding rate from Coinglass. Requires
    COINGLASS_API_KEY env var. See https://www.coinglass.com/pricing for
    API access.
    """
    source = "Coinglass (https://open-api-v4.coinglass.com)"
    api_key = os.environ.get("COINGLASS_API_KEY")
    if not api_key:
        return _unavailable(source, "COINGLASS_API_KEY not set")
    try:
        url = "https://open-api-v4.coinglass.com/api/futures/funding-rate?symbol=BTC"
        data = json.loads(_get(url, headers={"CG-API-KEY": api_key}))
        rows = data.get("data", [])
        match = next((r for r in rows if r.get("exchangeName") == exchange), None)
        if not match and rows:
            match = rows[0]
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
# Glassnode (API key required) — on-chain extras
# ---------------------------------------------------------------------------

def get_glassnode_metric(endpoint, asset="BTC", params=None):
    """
    Generic Glassnode on-chain metric fetcher. Requires GLASSNODE_API_KEY
    env var. `endpoint` is the metric path, e.g.
    "indicators/realized_volatility_30d" or "supply/active_more_1y_percent".
    See https://docs.glassnode.com/ for available endpoints.
    """
    source = f"Glassnode ({endpoint})"
    api_key = os.environ.get("GLASSNODE_API_KEY")
    if not api_key:
        return _unavailable(source, "GLASSNODE_API_KEY not set")
    try:
        query = f"a={asset}&api_key={api_key}"
        if params:
            query += "&" + "&".join(f"{k}={v}" for k, v in params.items())
        url = f"https://api.glassnode.com/v1/metrics/{endpoint}?{query}"
        data = json.loads(_get(url))
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
# Deterministic — Used to gather data on the halving cycle position (no API needed)
# ---------------------------------------------------------------------------

HALVING_DATES = [
    datetime(2012, 11, 28, tzinfo=timezone.utc),
    datetime(2016, 7, 9, tzinfo=timezone.utc),
    datetime(2020, 5, 11, tzinfo=timezone.utc),
    datetime(2024, 4, 20, tzinfo=timezone.utc),
]
AVG_CYCLE_DAYS = 1458  # ~4 years between halvings, historical average


def get_halving_cycle_position():
    """
    Months elapsed since the most recent halving, and estimated position
    (0-1) through the historical ~4-year cycle. Deterministic, computed
    from known halving dates — no external API required.
    """
    now = datetime.now(timezone.utc)
    last_halving = max(d for d in HALVING_DATES if d <= now)
    days_elapsed = (now - last_halving).days
    months_elapsed = days_elapsed / 30.4368
    cycle_fraction = min(days_elapsed / AVG_CYCLE_DAYS, 1.0)
    next_estimated = last_halving.replace(year=last_halving.year + 4)
    return {
        "value": f"{months_elapsed:.1f} months post-halving",
        "trend": f"{cycle_fraction * 100:.0f}% through historical avg cycle length",
        "source": f"Computed from known halving date {last_halving.date()} "
                   f"(next estimated ~{next_estimated.date()})",
        "timestamp": _now(),
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

SIGNAL_FUNCS = {
    "etf_flows": get_bitcoin_etf_flows,
    "dominance": get_bitcoin_dominance,
    "price": get_btc_price_usd,
    "volatility_30d": lambda: get_btc_realized_volatility(30),
    "dxy": get_dxy,
    "funding_rate": get_btc_funding_rates,
    "halving_cycle": get_halving_cycle_position,
}

DEFAULT_SIGNALS = [
    "etf_flows", "halving_cycle", "dxy", "dominance", "funding_rate", "volatility_30d",
]


def main():
    requested = sys.argv[1:] or DEFAULT_SIGNALS
    results = {}
    for name in requested:
        func = SIGNAL_FUNCS.get(name)
        if not func:
            results[name] = {"value": "Unavailable", "reason": f"Unknown signal '{name}'"}
            continue
        results[name] = func()
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
