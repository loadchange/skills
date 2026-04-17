#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "hyperliquid-python-sdk",
# ]
# ///
"""Current mid-prices for all markets (or one coin).

Cheapest cross-market snapshot (weight 2). Useful for marking positions
or checking whether an address's entry price is far from the current mid.

Usage:
    python scripts/mids.py                         # all markets
    python scripts/mids.py --coin BTC              # just BTC
    python scripts/mids.py --filter ETH,BTC,HYPE   # comma-separated list
    python scripts/mids.py --json
"""
from __future__ import annotations

import argparse
import sys

from _config import load_config, get_info
from _format import emit, fnum, table


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    parser.add_argument("--coin", help="Single coin")
    parser.add_argument("--filter", help="Comma-separated coin list")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    info = get_info(cfg)

    try:
        mids = info.all_mids() or {}
    except Exception as e:
        print(f"[error] all_mids failed: {e}", file=sys.stderr)
        return 2

    if args.coin:
        filtered = {args.coin: mids.get(args.coin)}
    elif args.filter:
        wanted = [c.strip() for c in args.filter.split(",") if c.strip()]
        filtered = {c: mids.get(c) for c in wanted}
    else:
        filtered = mids

    result = {"n_markets": len(filtered), "mids": filtered}

    if args.json:
        import json as _json
        print(_json.dumps(result, indent=2))
        return 0

    print(f"=== Mids ({len(filtered)} markets) ===")
    rows = [[k, v if v is not None else "(missing)"] for k, v in sorted(filtered.items())]
    # Only print first 60 rows in text mode to keep output manageable
    print(table(rows[:60], ["coin", "mid"], aligns=["l", "r"]))
    if len(rows) > 60:
        print(f"... ({len(rows) - 60} more — use --json for full list)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
