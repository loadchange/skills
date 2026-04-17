#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "hyperliquid-python-sdk",
# ]
# ///
"""User funding payment history over a time window.

Pulls the userFunding endpoint (wrapped as info.user_funding_history in
the SDK) and handles the delta-nesting of the response. Each entry comes
back as:

    {"time": ms, "hash": "0x...",
     "delta": {"type": "funding", "coin": ..., "usdc": signed_str,
               "szi": ..., "fundingRate": ..., ...}}

The sign convention for `usdc` is from the USER's perspective: negative
means the user paid, positive means they received. This script reports
"funding_paid" as positive = cost to user (i.e., flipped sign), since
that's what people mean when they ask "how much funding did I pay".

Usage:
    python scripts/funding.py                                  # 24h, config address
    python scripts/funding.py 0xabc...def --hours 168          # last 7 days
    python scripts/funding.py 0xabc...def --days 30 --json
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

from _config import load_config, get_info, resolve_address
from _format import emit, fnum, fmt_usd, fmt_ts, ms_now, ms_hours_ago, ms_days_ago, short_addr, table


def build_result(info, addr: str, start_ms: int, end_ms: int) -> dict:
    raw = info.user_funding_history(addr, startTime=start_ms, endTime=end_ms) or []

    entries = []
    total_received = 0.0  # signed: +received, -paid
    per_coin_received: dict[str, float] = defaultdict(float)
    per_coin_count: dict[str, int] = defaultdict(int)

    for e in raw:
        if not isinstance(e, dict):
            continue
        delta = e.get("delta") or {}
        if delta.get("type") != "funding":
            continue
        usdc = fnum(delta.get("usdc"))
        coin = delta.get("coin", "?")
        total_received += usdc
        per_coin_received[coin] += usdc
        per_coin_count[coin] += 1
        entries.append({
            "time_ms": e.get("time"),
            "time_utc": fmt_ts(e.get("time", 0)),
            "coin": coin,
            "usdc_signed": usdc,           # + = received, − = paid
            "paid_usd": -usdc,              # + = cost to user
            "szi": fnum(delta.get("szi")),
            "funding_rate": delta.get("fundingRate"),
            "hash": e.get("hash"),
        })

    per_coin = []
    for coin, received in sorted(per_coin_received.items(), key=lambda x: x[1]):
        per_coin.append({
            "coin": coin,
            "count": per_coin_count[coin],
            "received_usd": received,      # signed: + = net received
            "paid_usd": -received,          # signed: + = net cost
        })

    return {
        "address": addr,
        "window": {"start_ms": start_ms, "end_ms": end_ms,
                   "start_utc": fmt_ts(start_ms), "end_utc": fmt_ts(end_ms)},
        "counts": {"entries": len(entries)},
        "totals": {
            "received_usd": total_received,    # signed: + = net received
            "paid_usd": -total_received,        # signed: + = net cost
        },
        "per_coin": per_coin,
        "entries": entries,
    }


def print_text(r: dict) -> None:
    print(f"=== Funding history for {short_addr(r['address'])} ===")
    print(f"Window: {r['window']['start_utc']} → {r['window']['end_utc']}")
    print(f"Entries: {r['counts']['entries']}")
    print()
    print(f"  Total paid (signed, + = cost):     {fmt_usd(r['totals']['paid_usd'], signed=True)}")
    print(f"  Total received (signed, + = gain): {fmt_usd(r['totals']['received_usd'], signed=True)}")
    print()
    if r["per_coin"]:
        print("-- Per-coin --")
        rows = [
            [pc["coin"], str(pc["count"]),
             fmt_usd(pc["paid_usd"], signed=True),
             fmt_usd(pc["received_usd"], signed=True)]
            for pc in r["per_coin"]
        ]
        print(table(rows, ["coin", "count", "paid", "received"], aligns=["l", "r", "r", "r"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    parser.add_argument("address", nargs="?")
    window = parser.add_mutually_exclusive_group()
    window.add_argument("--hours", type=float, default=24.0)
    window.add_argument("--days", type=float)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    addr = resolve_address(args.address, cfg)
    info = get_info(cfg)

    start_ms = ms_days_ago(args.days) if args.days is not None else ms_hours_ago(args.hours)
    end_ms = ms_now()

    try:
        result = build_result(info, addr, start_ms, end_ms)
    except Exception as e:
        print(f"[error] API call failed: {e}", file=sys.stderr)
        return 2

    emit(result, as_json=args.json, text_printer=print_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
