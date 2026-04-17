#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "hyperliquid-python-sdk",
# ]
# ///
"""Pull fills for a Hyperliquid address, with time-windowed or full-history modes.

Handles the Info API pagination cap (~2000 rows per call) by walking
backwards in time using the oldest fill's timestamp as the next endTime
cursor. Deduplicates on (oid, tid) to eliminate boundary duplicates.

Modes:
    --hours N        : pull fills from the last N hours (default: 24)
    --days N         : pull fills from the last N days
    --all            : pull everything back to the start of the account
    --start-ms MS    : explicit start timestamp (ms since epoch)
    --end-ms MS      : explicit end timestamp (default: now)

Output:
    Default text: summary (count, volume, realized PnL, fees)
    --json       : list of fill dicts as JSON
    --out FILE   : write all fills to a file (.json or .csv)

Exit codes:
    0  success
    1  bad args / address
    2  API error

Usage:
    python scripts/fills.py 0xabc...def --hours 24
    python scripts/fills.py 0xabc...def --days 30 --out /tmp/fills.csv
    python scripts/fills.py 0xabc...def --all --json > all_fills.json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time

from _config import load_config, get_info, resolve_address
from _format import emit, fnum, fmt_usd, fmt_ts, ms_now, ms_hours_ago, ms_days_ago, short_addr


def fetch_fills_paginated(info, addr: str, start_ms: int, end_ms: int | None) -> list[dict]:
    """Walk backwards through fills by timestamp, deduping on (oid, tid).

    The Info API caps userFillsByTime at ~2000 rows per response. For
    deeper windows we page backward: each iteration sets endTime to
    one-less-than the oldest fill in the previous page.
    """
    all_fills: list[dict] = []
    cursor_end = end_ms
    while True:
        page = info.user_fills_by_time(addr, start_time=start_ms, end_time=cursor_end) or []
        if not page:
            break
        all_fills.extend(page)
        if len(page) < 2000:
            break
        oldest = min(f["time"] for f in page)
        if oldest <= start_ms:
            break
        cursor_end = oldest - 1
        # Gentle pacing — weight is ~20 per call, budget is 1200/min.
        time.sleep(0.05)

    # Dedupe on (oid, tid); pandas-free.
    seen: set[tuple] = set()
    unique: list[dict] = []
    for f in sorted(all_fills, key=lambda x: x["time"]):
        key = (f.get("oid"), f.get("tid"))
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def summarize(fills: list[dict]) -> dict:
    if not fills:
        return {"n_fills": 0}
    vol = 0.0
    realized = 0.0
    fees = 0.0
    coins: set[str] = set()
    for f in fills:
        vol += fnum(f.get("px")) * fnum(f.get("sz"))
        realized += fnum(f.get("closedPnl"))
        fees += fnum(f.get("fee"))
        coins.add(f.get("coin", "?"))
    return {
        "n_fills": len(fills),
        "n_coins": len(coins),
        "volume_usd": vol,
        "realized_pnl_usd": realized,
        "fees_usd": fees,
        "first_ts": fmt_ts(min(f["time"] for f in fills)),
        "last_ts": fmt_ts(max(f["time"] for f in fills)),
    }


def write_csv(fills: list[dict], path: str) -> None:
    if not fills:
        with open(path, "w", newline="") as f:
            f.write("")
        return
    # Flatten: take the common fields, leave any extra fields as JSON column.
    common_fields = [
        "time", "coin", "side", "px", "sz", "startPosition", "dir",
        "closedPnl", "hash", "oid", "tid", "crossed", "fee", "feeToken",
        "builderFee", "liquidation",
    ]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=common_fields, extrasaction="ignore")
        w.writeheader()
        for fl in fills:
            w.writerow({k: fl.get(k) for k in common_fields})


def write_json(fills: list[dict], path: str) -> None:
    with open(path, "w") as f:
        json.dump(fills, f, indent=2, default=str)


def print_text(r: dict) -> None:
    s = r["summary"]
    print(f"=== Fills for {short_addr(r['address'])} ===")
    print(f"Window: {fmt_ts(r['window']['start_ms'])} → {fmt_ts(r['window']['end_ms'])}")
    print()
    if s["n_fills"] == 0:
        print("(no fills in window)")
        return
    print(f"  Fills:       {s['n_fills']}")
    print(f"  Coins:       {s['n_coins']}")
    print(f"  Volume:      {fmt_usd(s['volume_usd'])}")
    print(f"  Realized:    {fmt_usd(s['realized_pnl_usd'], signed=True)}")
    print(f"  Fees:        {fmt_usd(s['fees_usd'])}")
    print(f"  First fill:  {s['first_ts']}")
    print(f"  Last  fill:  {s['last_ts']}")
    if r.get("out_file"):
        print(f"  Written to:  {r['out_file']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    parser.add_argument("address", nargs="?")

    window_group = parser.add_mutually_exclusive_group()
    window_group.add_argument("--hours", type=float, default=24.0, help="Window in hours (default: 24)")
    window_group.add_argument("--days", type=float, help="Window in days")
    window_group.add_argument("--all", action="store_true", help="Pull full history (start_ms=0)")
    window_group.add_argument("--start-ms", type=int, help="Explicit start timestamp in ms")

    parser.add_argument("--end-ms", type=int, help="Explicit end timestamp in ms (default: now)")
    parser.add_argument("--json", action="store_true", help="Emit full fill list as JSON (not summary)")
    parser.add_argument("--out", help="Write fills to a file (.json or .csv)")
    args = parser.parse_args()

    cfg = load_config()
    addr = resolve_address(args.address, cfg)
    info = get_info(cfg)

    if args.all:
        start_ms = 0
    elif args.start_ms is not None:
        start_ms = args.start_ms
    elif args.days is not None:
        start_ms = ms_days_ago(args.days)
    else:
        start_ms = ms_hours_ago(args.hours)
    end_ms = args.end_ms or ms_now()

    try:
        fills = fetch_fills_paginated(info, addr, start_ms, end_ms)
    except Exception as e:
        print(f"[error] API call failed: {e}", file=sys.stderr)
        return 2

    out_file = None
    if args.out:
        if args.out.endswith(".csv"):
            write_csv(fills, args.out)
        else:
            write_json(fills, args.out)
        out_file = args.out

    if args.json:
        print(json.dumps(fills, indent=2, default=str))
        return 0

    result = {
        "address": addr,
        "window": {"start_ms": start_ms, "end_ms": end_ms},
        "summary": summarize(fills),
        "out_file": out_file,
    }
    emit(result, as_json=False, text_printer=print_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
