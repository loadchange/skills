#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "hyperliquid-python-sdk",
# ]
# ///
"""Current account snapshot for a Hyperliquid address.

Returns perpetual positions, spot balances, margin summary, and fee tier.
This is the "what does this account look like right now" script — the
cheapest comprehensive picture of an account's current state.

Exit codes:
    0  success
    1  bad args / address
    2  API error

Usage:
    python scripts/account_state.py                       # use config default address
    python scripts/account_state.py 0xabc...def           # explicit address
    python scripts/account_state.py 0xabc...def --json    # machine-readable output
    python scripts/account_state.py --dex xyz             # HIP-3 DEX state
"""
from __future__ import annotations

import argparse
import sys

from _config import load_config, get_info, resolve_address
from _format import emit, fnum, fmt_usd, fmt_pct, short_addr, table


def build_result(info, addr: str, dex: str = "") -> dict:
    """Query all state endpoints and build a single dict suitable for JSON."""
    state = info.user_state(addr, dex=dex)
    spot = info.spot_user_state(addr)
    fees = info.user_fees(addr)
    mids = info.all_mids()

    margin = state.get("marginSummary", {}) or {}
    cross_margin = state.get("crossMarginSummary", {}) or {}
    account_value = fnum(margin.get("accountValue"))

    positions: list[dict] = []
    for ap in state.get("assetPositions", []) or []:
        p = ap.get("position", {}) or {}
        szi = fnum(p.get("szi"))
        if szi == 0:
            continue
        coin = p.get("coin", "?")
        entry = fnum(p.get("entryPx"))
        mid = fnum(mids.get(coin), entry)
        liq = p.get("liquidationPx")
        liq_f = fnum(liq) if liq is not None else None
        side = "long" if szi > 0 else "short"

        if liq_f and mid > 0:
            if szi > 0:
                liq_distance_pct = (mid - liq_f) / mid * 100
            else:
                liq_distance_pct = (liq_f - mid) / mid * 100
        else:
            liq_distance_pct = None

        positions.append({
            "coin": coin,
            "side": side,
            "size": szi,
            "entry_price": entry,
            "mark_price": mid,
            "notional_usd": abs(szi) * mid,
            "unrealized_pnl_usd": fnum(p.get("unrealizedPnl")),
            "return_on_equity_pct": fnum(p.get("returnOnEquity")) * 100,
            "leverage_type": (p.get("leverage") or {}).get("type"),
            "leverage_value": (p.get("leverage") or {}).get("value"),
            "liquidation_price": liq_f,
            "liquidation_distance_pct": liq_distance_pct,
            "cum_funding_all_time": fnum((p.get("cumFunding") or {}).get("allTime")),
            "cum_funding_since_open": fnum((p.get("cumFunding") or {}).get("sinceOpen")),
            "max_leverage": p.get("maxLeverage"),
        })

    spot_balances: list[dict] = []
    for b in spot.get("balances", []) or []:
        total = fnum(b.get("total"))
        if total == 0:
            continue
        coin = b.get("coin", "?")
        hold = fnum(b.get("hold"))
        entry_ntl = fnum(b.get("entryNtl"))
        # Look up spot mid if available
        spot_mid = fnum(mids.get(coin)) or fnum(mids.get(f"@{b.get('token')}"))
        cur_value = total * spot_mid if spot_mid else None
        spot_balances.append({
            "coin": coin,
            "token_index": b.get("token"),
            "total": total,
            "hold": hold,
            "free": total - hold,
            "entry_notional_usd": entry_ntl,
            "current_price_usd": spot_mid if spot_mid else None,
            "current_value_usd": cur_value,
            "pnl_usd": (cur_value - entry_ntl) if (cur_value is not None and entry_ntl) else None,
        })

    result = {
        "address": addr,
        "dex": dex or "default",
        "l1_time_ms": state.get("time"),
        "perp": {
            "account_value_usd": account_value,
            "total_notional_pos_usd": fnum(margin.get("totalNtlPos")),
            "total_raw_usd": fnum(margin.get("totalRawUsd")),
            "total_margin_used_usd": fnum(margin.get("totalMarginUsed")),
            "cross_maintenance_margin_used_usd": fnum(state.get("crossMaintenanceMarginUsed")),
            "withdrawable_usd": fnum(state.get("withdrawable")),
            "margin_utilization_pct": (fnum(margin.get("totalMarginUsed")) / account_value * 100) if account_value > 0 else 0,
            "n_open_positions": len(positions),
            "positions": positions,
        },
        "spot": {
            "n_balances": len(spot_balances),
            "balances": spot_balances,
        },
        "fees": {
            "taker_rate": fees.get("userCrossRate"),
            "maker_rate": fees.get("userAddRate"),
            "active_referral_discount": fees.get("activeReferralDiscount"),
        },
    }
    return result


def print_text(r: dict) -> None:
    print(f"=== Account state for {short_addr(r['address'])} ({r['dex']}) ===")
    print()

    perp = r["perp"]
    print("-- Perpetual account --")
    print(f"  Account value:        {fmt_usd(perp['account_value_usd'])}")
    print(f"  Total notional pos:   {fmt_usd(perp['total_notional_pos_usd'])}")
    print(f"  Margin used:          {fmt_usd(perp['total_margin_used_usd'])}  "
          f"({fmt_pct(perp['margin_utilization_pct'])})")
    print(f"  Maint margin used:    {fmt_usd(perp['cross_maintenance_margin_used_usd'])}")
    print(f"  Withdrawable:         {fmt_usd(perp['withdrawable_usd'])}")
    print()

    if perp["positions"]:
        print(f"-- Open positions ({perp['n_open_positions']}) --")
        rows = []
        for p in perp["positions"]:
            lev = f"{p['leverage_type']} {p['leverage_value']}x" if p['leverage_type'] else "-"
            liq = f"{p['liquidation_price']:.4f}" if p['liquidation_price'] else "-"
            liq_dist = fmt_pct(p['liquidation_distance_pct'], signed=True) if p['liquidation_distance_pct'] is not None else "-"
            rows.append([
                p["coin"],
                p["side"].upper(),
                f"{p['size']:+.4f}",
                f"{p['entry_price']:.4f}",
                f"{p['mark_price']:.4f}",
                fmt_usd(p["unrealized_pnl_usd"], signed=True),
                lev,
                liq,
                liq_dist,
            ])
        print(table(
            rows,
            ["coin", "side", "size", "entry", "mark", "uPnL", "lev", "liqPx", "liqDist"],
            aligns=["l", "l", "r", "r", "r", "r", "l", "r", "r"],
        ))
    else:
        print("-- No open perpetual positions --")
    print()

    spot = r["spot"]
    if spot["balances"]:
        print(f"-- Spot balances ({spot['n_balances']}) --")
        rows = []
        for b in spot["balances"]:
            price = f"{b['current_price_usd']:.6f}" if b.get("current_price_usd") else "-"
            val = fmt_usd(b["current_value_usd"]) if b.get("current_value_usd") is not None else "-"
            pnl = fmt_usd(b["pnl_usd"], signed=True) if b.get("pnl_usd") is not None else "-"
            rows.append([
                b["coin"],
                f"{b['total']:.6f}",
                f"{b['hold']:.6f}",
                price,
                val,
                pnl,
            ])
        print(table(
            rows,
            ["coin", "total", "hold", "price", "value", "pnl"],
            aligns=["l", "r", "r", "r", "r", "r"],
        ))
    else:
        print("-- No spot balances --")
    print()

    fees = r["fees"]
    print("-- Fee tier --")
    print(f"  Taker: {fees['taker_rate']}  Maker: {fees['maker_rate']}  "
          f"Referral discount: {fees['active_referral_discount']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    parser.add_argument("address", nargs="?", help="Hyperliquid address (default: from config)")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    parser.add_argument("--dex", default="", help="HIP-3 DEX name (default: main perp universe)")
    args = parser.parse_args()

    cfg = load_config()
    addr = resolve_address(args.address, cfg)
    info = get_info(cfg)

    try:
        result = build_result(info, addr, dex=args.dex)
    except Exception as e:
        print(f"[error] Info API call failed: {e}", file=sys.stderr)
        return 2

    emit(result, as_json=args.json, text_printer=print_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
