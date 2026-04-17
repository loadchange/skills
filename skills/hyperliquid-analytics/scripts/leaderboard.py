#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "hyperliquid-python-sdk",
# ]
# ///
"""Rank multiple addresses by account value, notional exposure, or margin utilization.

Feed the script a list of addresses (from file or stdin or CLI) and it
pulls clearinghouseState for each, then sorts. This is the canonical
pattern for whale tracking / leaderboard generation.

Usage:
    python scripts/leaderboard.py 0xa 0xb 0xc              # inline list
    python scripts/leaderboard.py --file addrs.txt         # one address per line
    cat addrs.txt | python scripts/leaderboard.py -        # from stdin
    python scripts/leaderboard.py --file addrs.txt --sort notional --top 10
"""
from __future__ import annotations

import argparse
import sys
import time

from _config import load_config, get_info
from _format import emit, fnum, fmt_usd, fmt_pct, short_addr, table


def load_addresses(args: argparse.Namespace) -> list[str]:
    addrs: list[str] = []
    if args.addresses:
        if args.addresses == ["-"]:
            addrs = [line.strip() for line in sys.stdin if line.strip()]
        else:
            addrs = list(args.addresses)
    if args.file:
        with open(args.file) as f:
            addrs.extend(line.strip() for line in f if line.strip() and not line.startswith("#"))
    # Dedupe preserving order
    seen = set()
    out = []
    for a in addrs:
        if a and a not in seen:
            seen.add(a)
            out.append(a)
    return out


def build_result(info, addresses: list[str]) -> dict:
    rows = []
    for i, addr in enumerate(addresses):
        try:
            state = info.user_state(addr)
        except Exception as e:
            rows.append({"address": addr, "error": str(e)})
            continue
        margin = state.get("marginSummary", {}) or {}
        av = fnum(margin.get("accountValue"))
        ntl = fnum(margin.get("totalNtlPos"))
        mu = fnum(margin.get("totalMarginUsed"))
        positions = state.get("assetPositions", []) or []
        n_open = sum(1 for p in positions if fnum((p.get("position") or {}).get("szi")) != 0)
        rows.append({
            "address": addr,
            "account_value_usd": av,
            "total_notional_usd": ntl,
            "margin_used_usd": mu,
            "margin_utilization_pct": (mu / av * 100) if av > 0 else 0,
            "n_open_positions": n_open,
        })
        # Gentle pacing: weight 2 per call, but avoid 10-20 concurrent hammering
        if (i + 1) % 10 == 0:
            time.sleep(0.1)
    return {"count": len(rows), "rows": rows}


def print_text(r: dict) -> None:
    good = [row for row in r["rows"] if "error" not in row]
    errors = [row for row in r["rows"] if "error" in row]
    print(f"=== Leaderboard ({len(good)} ok / {len(errors)} errors) ===")
    print()
    if good:
        table_rows = [[
            short_addr(row["address"]),
            fmt_usd(row["account_value_usd"]),
            fmt_usd(row["total_notional_usd"]),
            fmt_pct(row["margin_utilization_pct"]),
            str(row["n_open_positions"]),
        ] for row in good]
        print(table(
            table_rows,
            ["address", "account_value", "notional", "margin_util", "open"],
            aligns=["l", "r", "r", "r", "r"],
        ))
    if errors:
        print()
        print("-- Errors --")
        for e in errors:
            print(f"  {e['address']}: {e['error']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    parser.add_argument("addresses", nargs="*", help="Addresses to query (use '-' for stdin)")
    parser.add_argument("--file", help="File with one address per line")
    parser.add_argument("--sort", choices=["account_value", "notional", "margin_util"],
                        default="account_value")
    parser.add_argument("--top", type=int, help="Show only top N after sorting")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    info = get_info(cfg)

    addresses = load_addresses(args)
    if not addresses:
        print("[error] No addresses provided. Pass them inline, with --file, or via stdin ('-').",
              file=sys.stderr)
        return 1

    try:
        result = build_result(info, addresses)
    except Exception as e:
        print(f"[error] API call failed: {e}", file=sys.stderr)
        return 2

    # Sort
    good_rows = [r for r in result["rows"] if "error" not in r]
    sort_key = {
        "account_value": "account_value_usd",
        "notional": "total_notional_usd",
        "margin_util": "margin_utilization_pct",
    }[args.sort]
    good_rows.sort(key=lambda x: -x[sort_key])
    if args.top:
        good_rows = good_rows[:args.top]
    result["rows"] = good_rows + [r for r in result["rows"] if "error" in r]

    emit(result, as_json=args.json, text_printer=print_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
