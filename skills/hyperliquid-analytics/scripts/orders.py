#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "hyperliquid-python-sdk",
# ]
# ///
"""Open and historical orders for a Hyperliquid address.

Three modes:
    --open        : currently open orders (frontend_open_orders — rich schema)
    --history     : historical orders with final status (historical_orders)
    --oid N       : look up a specific order by id
    (default: --open)

Usage:
    python scripts/orders.py 0xabc...def --open
    python scripts/orders.py 0xabc...def --history
    python scripts/orders.py 0xabc...def --oid 12345
"""
from __future__ import annotations

import argparse
import sys

from _config import load_config, get_info, resolve_address
from _format import emit, fnum, fmt_ts, short_addr, table


def build_result(info, addr: str, mode: str, oid: int | None) -> dict:
    if mode == "oid":
        r = info.query_order_by_oid(addr, oid)
        return {"address": addr, "mode": "oid", "oid": oid, "result": r}
    if mode == "history":
        rows = info.historical_orders(addr) or []
        out = []
        for r in rows:
            o = r.get("order", {}) if isinstance(r, dict) else {}
            inner = o.get("order", o)  # historicalOrders returns nested {order: {order: {...}, status}}
            out.append({
                "coin": inner.get("coin"),
                "side": inner.get("side"),
                "limit_px": fnum(inner.get("limitPx")),
                "sz": fnum(inner.get("sz")),
                "oid": inner.get("oid"),
                "status": r.get("status") if "status" in r else o.get("status"),
                "status_ts": r.get("statusTimestamp") or o.get("statusTimestamp"),
                "order_type": inner.get("orderType"),
                "reduce_only": inner.get("reduceOnly"),
            })
        return {"address": addr, "mode": "history", "count": len(out), "orders": out}
    # default: open
    rows = info.frontend_open_orders(addr) or []
    out = []
    for o in rows:
        out.append({
            "coin": o.get("coin"),
            "side": o.get("side"),
            "limit_px": fnum(o.get("limitPx")),
            "sz": fnum(o.get("sz")),
            "orig_sz": fnum(o.get("origSz")),
            "oid": o.get("oid"),
            "timestamp_ms": o.get("timestamp"),
            "time_utc": fmt_ts(o.get("timestamp", 0)),
            "order_type": o.get("orderType"),
            "reduce_only": o.get("reduceOnly"),
            "is_trigger": o.get("isTrigger"),
            "trigger_px": o.get("triggerPx"),
            "trigger_condition": o.get("triggerCondition"),
            "tif": o.get("tif"),
            "cloid": o.get("cloid"),
        })
    return {"address": addr, "mode": "open", "count": len(out), "orders": out}


def print_text(r: dict) -> None:
    print(f"=== Orders for {short_addr(r['address'])} (mode={r['mode']}) ===")
    if r["mode"] == "oid":
        print(r["result"])
        return
    print(f"Count: {r.get('count', 0)}")
    print()
    if not r.get("orders"):
        print("(none)")
        return
    rows = []
    if r["mode"] == "open":
        for o in r["orders"]:
            rows.append([
                o["coin"] or "-", o["side"] or "-",
                f"{o['limit_px']}", f"{o['sz']}", f"{o['oid']}",
                o.get("order_type") or "-", o.get("tif") or "-",
                "Y" if o.get("reduce_only") else "",
                "Y" if o.get("is_trigger") else "",
                o["time_utc"],
            ])
        print(table(
            rows,
            ["coin", "side", "limit_px", "sz", "oid", "type", "tif", "reduce", "trig", "time"],
            aligns=["l", "l", "r", "r", "r", "l", "l", "c", "c", "l"],
        ))
    else:  # history
        for o in r["orders"][:50]:  # cap text display
            rows.append([
                o.get("coin") or "-", o.get("side") or "-",
                f"{o['limit_px']}", f"{o['sz']}", f"{o['oid']}",
                o.get("status") or "-",
            ])
        print(table(
            rows,
            ["coin", "side", "limit_px", "sz", "oid", "status"],
            aligns=["l", "l", "r", "r", "r", "l"],
        ))
        if len(r["orders"]) > 50:
            print(f"... ({len(r['orders']) - 50} more)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    parser.add_argument("address", nargs="?")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--open", action="store_true", help="Currently open orders (default)")
    mode.add_argument("--history", action="store_true", help="Historical orders with status")
    mode.add_argument("--oid", type=int, help="Lookup a single order by id")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    addr = resolve_address(args.address, cfg)
    info = get_info(cfg)

    if args.oid is not None:
        mode_str = "oid"
    elif args.history:
        mode_str = "history"
    else:
        mode_str = "open"

    try:
        result = build_result(info, addr, mode_str, args.oid)
    except Exception as e:
        print(f"[error] API call failed: {e}", file=sys.stderr)
        return 2

    emit(result, as_json=args.json, text_printer=print_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
