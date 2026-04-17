#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "hyperliquid-python-sdk",
# ]
# ///
"""Non-funding ledger updates for an address.

Covers deposits, withdrawals, perp↔spot transfers, sub-account transfers,
vault deposits/withdrawals, internal transfers, and staking rewards claims.
Each entry wraps its details under a `delta` object — the `delta.type`
field tells you which kind of balance change it is.

Common delta.type values:
    deposit, withdraw, accountClassTransfer, subAccountTransfer,
    vaultCreate, vaultDeposit, vaultWithdraw, rewardsClaim, internalTransfer

Usage:
    python scripts/ledger.py                          # 24h, config address
    python scripts/ledger.py 0xabc...def --days 30
    python scripts/ledger.py 0xabc...def --type deposit
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

from _config import load_config, get_info, resolve_address
from _format import emit, fnum, fmt_usd, fmt_ts, ms_now, ms_hours_ago, ms_days_ago, short_addr, table


def build_result(info, addr: str, start_ms: int, end_ms: int, filter_type: str | None) -> dict:
    raw = info.user_non_funding_ledger_updates(addr, startTime=start_ms, endTime=end_ms) or []

    entries = []
    by_type: dict[str, int] = defaultdict(int)
    net_by_type: dict[str, float] = defaultdict(float)

    for e in raw:
        if not isinstance(e, dict):
            continue
        delta = e.get("delta") or {}
        dtype = delta.get("type", "?")
        if filter_type and dtype != filter_type:
            continue
        usdc = fnum(delta.get("usdc"))
        by_type[dtype] += 1
        net_by_type[dtype] += usdc
        entries.append({
            "time_ms": e.get("time"),
            "time_utc": fmt_ts(e.get("time", 0)),
            "hash": e.get("hash"),
            "type": dtype,
            "usdc": usdc,
            "raw_delta": delta,
        })

    return {
        "address": addr,
        "window": {"start_ms": start_ms, "end_ms": end_ms,
                   "start_utc": fmt_ts(start_ms), "end_utc": fmt_ts(end_ms)},
        "filter_type": filter_type,
        "counts_by_type": dict(by_type),
        "net_by_type_usd": {k: v for k, v in net_by_type.items()},
        "entries": entries,
    }


def print_text(r: dict) -> None:
    print(f"=== Ledger updates for {short_addr(r['address'])} ===")
    print(f"Window: {r['window']['start_utc']} → {r['window']['end_utc']}")
    if r.get("filter_type"):
        print(f"Filter: type == {r['filter_type']}")
    print(f"Total entries: {len(r['entries'])}")
    print()
    if r["counts_by_type"]:
        print("-- By type --")
        rows = []
        for t in sorted(r["counts_by_type"]):
            rows.append([t, str(r["counts_by_type"][t]),
                         fmt_usd(r["net_by_type_usd"].get(t, 0), signed=True)])
        print(table(rows, ["type", "count", "net USDC"], aligns=["l", "r", "r"]))
        print()
    if r["entries"][:20]:
        print("-- Recent entries (up to 20) --")
        rows = []
        for e in r["entries"][-20:]:
            rows.append([e["time_utc"], e["type"], fmt_usd(e["usdc"], signed=True)])
        print(table(rows, ["time", "type", "usdc"], aligns=["l", "l", "r"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    parser.add_argument("address", nargs="?")
    window = parser.add_mutually_exclusive_group()
    window.add_argument("--hours", type=float, default=24.0)
    window.add_argument("--days", type=float)
    parser.add_argument("--type", help="Filter by delta.type (e.g., deposit, withdraw, accountClassTransfer)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    addr = resolve_address(args.address, cfg)
    info = get_info(cfg)

    start_ms = ms_days_ago(args.days) if args.days is not None else ms_hours_ago(args.hours)
    end_ms = ms_now()

    try:
        result = build_result(info, addr, start_ms, end_ms, args.type)
    except Exception as e:
        print(f"[error] API call failed: {e}", file=sys.stderr)
        return 2

    emit(result, as_json=args.json, text_printer=print_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
