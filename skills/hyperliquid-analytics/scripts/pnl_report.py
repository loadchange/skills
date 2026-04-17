#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "hyperliquid-python-sdk",
# ]
# ///
"""Multi-day PnL report grouped by coin and by day.

Pulls all fills in the window (paginated), then groups them two ways:
1. By coin: volume, realized PnL, fees
2. By day (UTC): realized PnL, volume, n_trades — gives a daily series
   suitable for drawing a PnL curve.

Also pulls funding history and attributes funding cost to each day's line.

Usage:
    python scripts/pnl_report.py                        # last 7 days, config addr
    python scripts/pnl_report.py 0xabc --days 30
    python scripts/pnl_report.py 0xabc --days 7 --json
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict

from _config import load_config, get_info, resolve_address
from _format import emit, fnum, fmt_usd, fmt_ts, ms_now, ms_days_ago, short_addr, table


def day_key(ms: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))


def fetch_all_fills(info, addr, start_ms, end_ms):
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
        time.sleep(0.05)
    seen = set()
    unique = []
    for f in sorted(all_fills, key=lambda x: x["time"]):
        k = (f.get("oid"), f.get("tid"))
        if k not in seen:
            seen.add(k)
            unique.append(f)
    return unique


def build_result(info, addr: str, days: int) -> dict:
    end_ms = ms_now()
    start_ms = ms_days_ago(days)

    fills = fetch_all_fills(info, addr, start_ms, end_ms)
    funding_raw = info.user_funding_history(addr, startTime=start_ms, endTime=end_ms) or []

    # By coin
    per_coin: dict[str, dict] = defaultdict(lambda: {
        "trades": 0, "volume_usd": 0.0, "realized_pnl_usd": 0.0, "fees_usd": 0.0,
    })
    # By day (UTC)
    per_day: dict[str, dict] = defaultdict(lambda: {
        "trades": 0, "volume_usd": 0.0, "realized_pnl_usd": 0.0,
        "fees_usd": 0.0, "funding_paid_usd": 0.0, "net_usd": 0.0,
    })

    for f in fills:
        px = fnum(f.get("px"))
        sz = fnum(f.get("sz"))
        fee = fnum(f.get("fee"))
        cpnl = fnum(f.get("closedPnl"))
        notional = px * sz
        coin = f.get("coin", "?")
        pc = per_coin[coin]
        pc["trades"] += 1
        pc["volume_usd"] += notional
        pc["realized_pnl_usd"] += cpnl
        pc["fees_usd"] += fee

        dk = day_key(f["time"])
        pd = per_day[dk]
        pd["trades"] += 1
        pd["volume_usd"] += notional
        pd["realized_pnl_usd"] += cpnl
        pd["fees_usd"] += fee

    for entry in funding_raw:
        delta = entry.get("delta", {}) if isinstance(entry, dict) else {}
        if delta.get("type") != "funding":
            continue
        usdc = fnum(delta.get("usdc"))
        dk = day_key(entry.get("time", 0))
        per_day[dk]["funding_paid_usd"] += -usdc  # + = cost

    # Net per day
    for pd in per_day.values():
        pd["net_usd"] = pd["realized_pnl_usd"] - pd["fees_usd"] - pd["funding_paid_usd"]

    # Totals
    total = {
        "trades": sum(pc["trades"] for pc in per_coin.values()),
        "volume_usd": sum(pc["volume_usd"] for pc in per_coin.values()),
        "realized_pnl_usd": sum(pc["realized_pnl_usd"] for pc in per_coin.values()),
        "fees_usd": sum(pc["fees_usd"] for pc in per_coin.values()),
        "funding_paid_usd": sum(pd["funding_paid_usd"] for pd in per_day.values()),
    }
    total["net_usd"] = total["realized_pnl_usd"] - total["fees_usd"] - total["funding_paid_usd"]

    return {
        "address": addr,
        "window": {"days": days, "start_ms": start_ms, "end_ms": end_ms,
                   "start_utc": fmt_ts(start_ms), "end_utc": fmt_ts(end_ms)},
        "totals": total,
        "per_coin": [
            {"coin": c, **v} for c, v in sorted(per_coin.items(), key=lambda x: -x[1]["volume_usd"])
        ],
        "per_day": [
            {"day": d, **v} for d, v in sorted(per_day.items())
        ],
    }


def print_text(r: dict) -> None:
    print(f"=== {r['window']['days']}-day PnL report for {short_addr(r['address'])} ===")
    print(f"Window: {r['window']['start_utc']} → {r['window']['end_utc']}")
    print()

    t = r["totals"]
    print(f"  Trades:             {t['trades']}")
    print(f"  Volume:             {fmt_usd(t['volume_usd'])}")
    print(f"  Realized PnL:       {fmt_usd(t['realized_pnl_usd'], signed=True)}")
    print(f"  Fees:               {fmt_usd(t['fees_usd'])}")
    print(f"  Funding paid:       {fmt_usd(t['funding_paid_usd'], signed=True)}")
    print(f"  ================================================")
    print(f"  NET PnL:            {fmt_usd(t['net_usd'], signed=True)}")
    print()

    if r["per_coin"]:
        print("-- Per coin --")
        rows = [[
            pc["coin"], str(pc["trades"]),
            fmt_usd(pc["volume_usd"]),
            fmt_usd(pc["realized_pnl_usd"], signed=True),
            fmt_usd(pc["fees_usd"]),
        ] for pc in r["per_coin"]]
        print(table(rows, ["coin", "trades", "volume", "realized", "fees"],
                    aligns=["l", "r", "r", "r", "r"]))
        print()

    if r["per_day"]:
        print("-- Per day --")
        rows = [[
            pd["day"], str(pd["trades"]),
            fmt_usd(pd["volume_usd"]),
            fmt_usd(pd["realized_pnl_usd"], signed=True),
            fmt_usd(pd["fees_usd"]),
            fmt_usd(pd["funding_paid_usd"], signed=True),
            fmt_usd(pd["net_usd"], signed=True),
        ] for pd in r["per_day"]]
        print(table(
            rows,
            ["day", "trades", "volume", "realized", "fees", "funding", "net"],
            aligns=["l", "r", "r", "r", "r", "r", "r"],
        ))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    parser.add_argument("address", nargs="?")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    addr = resolve_address(args.address, cfg)
    info = get_info(cfg)

    try:
        result = build_result(info, addr, args.days)
    except Exception as e:
        print(f"[error] API call failed: {e}", file=sys.stderr)
        return 2

    emit(result, as_json=args.json, text_printer=print_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
