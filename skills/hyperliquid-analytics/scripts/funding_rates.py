#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "hyperliquid-python-sdk",
# ]
# ///
"""Per-market (asset-level) funding rate history.

Different from funding.py, which shows user-level funding payments. This
script shows market-wide funding rates for a given coin over a time window,
useful for "what's the historical funding been on ETH perp?".

Usage:
    python scripts/funding_rates.py BTC                       # last 24h
    python scripts/funding_rates.py ETH --days 7
    python scripts/funding_rates.py HYPE --days 30 --json
"""
from __future__ import annotations

import argparse
import sys

from _config import load_config, get_info
from _format import emit, fnum, fmt_ts, ms_now, ms_hours_ago, ms_days_ago, table


def build_result(info, coin: str, start_ms: int, end_ms: int) -> dict:
    rows = info.funding_history(name=coin, startTime=start_ms, endTime=end_ms) or []

    entries = []
    rates = []
    for r in rows:
        rate = fnum(r.get("fundingRate"))
        entries.append({
            "time_ms": r.get("time"),
            "time_utc": fmt_ts(r.get("time", 0)),
            "funding_rate": rate,
            "premium": fnum(r.get("premium")),
        })
        rates.append(rate)

    avg = sum(rates) / len(rates) if rates else 0.0
    annualized_pct = avg * 24 * 365 * 100  # hourly funding → annualized

    return {
        "coin": coin,
        "window": {"start_ms": start_ms, "end_ms": end_ms,
                   "start_utc": fmt_ts(start_ms), "end_utc": fmt_ts(end_ms)},
        "counts": {"intervals": len(entries)},
        "summary": {
            "mean_rate": avg,
            "min_rate": min(rates) if rates else 0,
            "max_rate": max(rates) if rates else 0,
            "annualized_pct": annualized_pct,
        },
        "entries": entries,
    }


def print_text(r: dict) -> None:
    print(f"=== Funding rates for {r['coin']} ===")
    print(f"Window: {r['window']['start_utc']} → {r['window']['end_utc']}")
    print(f"Intervals: {r['counts']['intervals']}")
    print()
    s = r["summary"]
    print(f"  Mean rate:        {s['mean_rate']:.8f}")
    print(f"  Min rate:         {s['min_rate']:.8f}")
    print(f"  Max rate:         {s['max_rate']:.8f}")
    print(f"  Annualized (est): {s['annualized_pct']:+.2f}%")
    if r["entries"]:
        print()
        print("-- Recent (up to 20) --")
        rows = [[e["time_utc"], f"{e['funding_rate']:.8f}", f"{e['premium']:.6f}"]
                for e in r["entries"][-20:]]
        print(table(rows, ["time", "rate", "premium"], aligns=["l", "r", "r"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    parser.add_argument("coin", help="Market symbol, e.g., BTC")
    window = parser.add_mutually_exclusive_group()
    window.add_argument("--hours", type=float, default=24.0)
    window.add_argument("--days", type=float)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    info = get_info(cfg)

    start_ms = ms_days_ago(args.days) if args.days is not None else ms_hours_ago(args.hours)
    end_ms = ms_now()

    try:
        result = build_result(info, args.coin, start_ms, end_ms)
    except Exception as e:
        print(f"[error] funding_history failed: {e}", file=sys.stderr)
        return 2

    emit(result, as_json=args.json, text_printer=print_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
