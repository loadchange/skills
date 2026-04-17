#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "hyperliquid-python-sdk",
# ]
# ///
"""Trading activity summary over a recent window (default 24h).

Pulls fills, funding payments, and current state for a single address,
then produces an aggregate of volume, realized PnL, fees, funding cost,
and a per-coin breakdown.

This is the right script when someone asks:
    "how did this wallet trade in the last 24 hours?"
    "summarize today's trading for 0x..."
    "24h PnL for this trader"

Notes:
    * userFunding entries in the Info API nest the actual funding data
      under an inner "delta" object (not at the top level). This script
      handles the nesting correctly. If you see funding = $0 when there
      are clearly funding entries, that bug has crept back in.
    * Realized PnL here is the sum of closedPnl across fills — a clean
      close-only measure. It does NOT include mark-to-market of currently
      open positions (see account_state.py for that).

Exit codes:
    0  success
    1  bad args / address
    2  API error

Usage:
    python scripts/daily_summary.py                           # 24h, config address
    python scripts/daily_summary.py 0xabc...def               # 24h, explicit address
    python scripts/daily_summary.py 0xabc...def --hours 48    # 48h window
    python scripts/daily_summary.py 0xabc...def --json        # JSON output
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

from _config import load_config, get_info, resolve_address
from _format import emit, fnum, fmt_usd, fmt_pct, fmt_ts, ms_now, ms_hours_ago, short_addr, table


def build_result(info, addr: str, hours: float) -> dict:
    end_ms = ms_now()
    start_ms = ms_hours_ago(hours)

    # 1. Fills in window
    fills = info.user_fills_by_time(addr, start_time=start_ms, end_time=end_ms) or []

    # 2. Funding payments in window
    # CRITICAL: each entry wraps the funding fields under a "delta" key.
    # Schema: {"time": ms, "hash": "0x..", "delta": {"type": "funding",
    #          "coin": ..., "usdc": signed_str, "szi": ..., "fundingRate": ..., ...}}
    funding_raw = info.user_funding_history(addr, startTime=start_ms, endTime=end_ms) or []

    # 3. Current state (for the post-window position snapshot)
    state = info.user_state(addr)
    mids = info.all_mids()

    # --- Aggregate fills ---
    total_vol = 0.0
    realized = 0.0
    fees_paid = 0.0
    builder_fees = 0.0
    n_crossed = 0
    n_maker = 0
    dir_counts: dict[str, int] = defaultdict(int)
    per_coin: dict[str, dict] = defaultdict(lambda: {
        "trades": 0, "volume_usd": 0.0, "realized_pnl_usd": 0.0,
        "fees_usd": 0.0, "buy_sz": 0.0, "sell_sz": 0.0,
    })

    for f in fills:
        px = fnum(f.get("px"))
        sz = fnum(f.get("sz"))
        fee = fnum(f.get("fee"))
        bfee = fnum(f.get("builderFee"))
        cpnl = fnum(f.get("closedPnl"))
        notional = px * sz

        total_vol += notional
        fees_paid += fee
        builder_fees += bfee
        realized += cpnl
        if f.get("crossed"):
            n_crossed += 1
        else:
            n_maker += 1
        dir_counts[f.get("dir", "")] += 1

        coin = f.get("coin", "?")
        pc = per_coin[coin]
        pc["trades"] += 1
        pc["volume_usd"] += notional
        pc["realized_pnl_usd"] += cpnl
        pc["fees_usd"] += fee
        if f.get("side") == "B":
            pc["buy_sz"] += sz
        else:
            pc["sell_sz"] += sz

    # --- Aggregate funding (unwrapping delta) ---
    funding_received = 0.0  # positive = user received (they were on the receiving side)
    per_coin_funding: dict[str, float] = defaultdict(float)
    for entry in funding_raw:
        delta = entry.get("delta", {}) if isinstance(entry, dict) else {}
        if delta.get("type") != "funding":
            continue
        usdc = fnum(delta.get("usdc"))  # signed from user perspective
        coin = delta.get("coin", "?")
        funding_received += usdc
        per_coin_funding[coin] += usdc
    # We report funding_paid such that positive = cost to user.
    funding_paid = -funding_received

    # Net 24h P&L
    net = realized - fees_paid - builder_fees - funding_paid

    # --- Position trajectory (first vs last fill) ---
    trajectory = None
    if fills:
        sorted_fills = sorted(fills, key=lambda x: x["time"])
        first = sorted_fills[0]
        last = sorted_fills[-1]
        first_start = fnum(first.get("startPosition"))
        last_start = fnum(last.get("startPosition"))
        last_signed_sz = fnum(last.get("sz")) * (1 if last.get("side") == "B" else -1)
        last_end = last_start + last_signed_sz
        trajectory = {
            "position_before_first_fill": first_start,
            "position_after_last_fill": last_end,
            "net_change": last_end - first_start,
            "first_fill_ts": fmt_ts(first["time"]),
            "last_fill_ts": fmt_ts(last["time"]),
        }

    # --- Current state (post-window) ---
    margin = state.get("marginSummary", {}) or {}
    current_positions = []
    for ap in state.get("assetPositions", []) or []:
        p = ap.get("position", {}) or {}
        szi = fnum(p.get("szi"))
        if szi == 0:
            continue
        current_positions.append({
            "coin": p.get("coin"),
            "size": szi,
            "entry_price": fnum(p.get("entryPx")),
            "mark_price": fnum(mids.get(p.get("coin")), fnum(p.get("entryPx"))),
            "unrealized_pnl_usd": fnum(p.get("unrealizedPnl")),
        })

    per_coin_out = []
    for coin, pc in sorted(per_coin.items(), key=lambda x: -x[1]["volume_usd"]):
        per_coin_out.append({
            "coin": coin,
            "trades": pc["trades"],
            "volume_usd": pc["volume_usd"],
            "realized_pnl_usd": pc["realized_pnl_usd"],
            "fees_usd": pc["fees_usd"],
            "funding_paid_usd": -per_coin_funding.get(coin, 0.0),
            "buy_size": pc["buy_sz"],
            "sell_size": pc["sell_sz"],
        })

    return {
        "address": addr,
        "window": {
            "hours": hours,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "start_utc": fmt_ts(start_ms),
            "end_utc": fmt_ts(end_ms),
        },
        "counts": {
            "fills": len(fills),
            "funding_entries": len(funding_raw),
            "taker": n_crossed,
            "maker": n_maker,
            "direction_breakdown": dict(dir_counts),
        },
        "totals": {
            "volume_usd": total_vol,
            "realized_pnl_usd": realized,
            "fees_paid_usd": fees_paid,
            "builder_fees_usd": builder_fees,
            "funding_paid_usd": funding_paid,
            "net_pnl_usd": net,
        },
        "per_coin": per_coin_out,
        "position_trajectory": trajectory,
        "current_state": {
            "account_value_usd": fnum(margin.get("accountValue")),
            "margin_used_usd": fnum(margin.get("totalMarginUsed")),
            "margin_utilization_pct": (
                fnum(margin.get("totalMarginUsed")) / fnum(margin.get("accountValue")) * 100
                if fnum(margin.get("accountValue")) > 0 else 0
            ),
            "open_positions": current_positions,
        },
    }


def print_text(r: dict) -> None:
    w = r["window"]
    c = r["counts"]
    t = r["totals"]
    cs = r["current_state"]

    print(f"=== {w['hours']:.0f}h trading summary for {short_addr(r['address'])} ===")
    print(f"Window: {w['start_utc']} → {w['end_utc']}")
    print()

    print("-- Activity --")
    print(f"  Trades:          {c['fills']}  ({c['maker']} maker / {c['taker']} taker)")
    print(f"  Volume:          {fmt_usd(t['volume_usd'])}")
    print(f"  Realized PnL:    {fmt_usd(t['realized_pnl_usd'], signed=True)}")
    print(f"  Fees:            {fmt_usd(t['fees_paid_usd'])}")
    if t["builder_fees_usd"]:
        print(f"  Builder fees:    {fmt_usd(t['builder_fees_usd'])}")
    print(f"  Funding (paid):  {fmt_usd(t['funding_paid_usd'], signed=True)}   ({c['funding_entries']} entries)")
    print(f"  ================================================")
    print(f"  NET PnL:         {fmt_usd(t['net_pnl_usd'], signed=True)}")
    print()

    if c["direction_breakdown"]:
        print("-- Direction breakdown --")
        for d, n in sorted(c["direction_breakdown"].items(), key=lambda x: -x[1]):
            pct = n / c["fills"] * 100 if c["fills"] else 0
            print(f"  {d or '(unset)':20s}  {n:>4d}  ({pct:.1f}%)")
        print()

    if r["per_coin"]:
        print("-- Per-coin breakdown --")
        rows = [
            [
                pc["coin"],
                str(pc["trades"]),
                fmt_usd(pc["volume_usd"]),
                fmt_usd(pc["realized_pnl_usd"], signed=True),
                fmt_usd(pc["fees_usd"]),
                fmt_usd(pc["funding_paid_usd"], signed=True),
            ]
            for pc in r["per_coin"]
        ]
        print(table(
            rows,
            ["coin", "trades", "volume", "realized", "fees", "funding"],
            aligns=["l", "r", "r", "r", "r", "r"],
        ))
        print()

    if r["position_trajectory"]:
        pt = r["position_trajectory"]
        print("-- Position trajectory --")
        print(f"  Before first fill:  {pt['position_before_first_fill']:+.4f}")
        print(f"  After last fill:    {pt['position_after_last_fill']:+.4f}")
        print(f"  Net change:         {pt['net_change']:+.4f}")
        print(f"  First fill: {pt['first_fill_ts']}")
        print(f"  Last  fill: {pt['last_fill_ts']}")
        print()

    print("-- Current state (post-window) --")
    print(f"  Account value:       {fmt_usd(cs['account_value_usd'])}")
    print(f"  Margin utilization:  {fmt_pct(cs['margin_utilization_pct'])}")
    if cs["open_positions"]:
        print(f"  Open positions:")
        for p in cs["open_positions"]:
            print(f"    {p['coin']:6s}  size={p['size']:+.4f}  entry={p['entry_price']:.2f}  "
                  f"mark={p['mark_price']:.2f}  uPnL={fmt_usd(p['unrealized_pnl_usd'], signed=True)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    parser.add_argument("address", nargs="?")
    parser.add_argument("--hours", type=float, default=24.0, help="Window size in hours (default: 24)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    addr = resolve_address(args.address, cfg)
    info = get_info(cfg)

    try:
        result = build_result(info, addr, args.hours)
    except Exception as e:
        print(f"[error] API call failed: {e}", file=sys.stderr)
        return 2

    emit(result, as_json=args.json, text_printer=print_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
