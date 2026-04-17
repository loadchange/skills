#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "hyperliquid-python-sdk",
# ]
# ///
"""Current fee tier and rolling volume breakdown for an address.

The Info API's `userFees` type (`info.user_fees`) returns:
  - current taker/maker rates (after referral discounts)
  - 14-day daily volume broken down by maker vs taker
  - fee schedule (tier breakpoints)
  - referral discount and any trial reward state

Usage:
    python scripts/fee_tier.py
    python scripts/fee_tier.py 0xabc...def
    python scripts/fee_tier.py 0xabc...def --json
"""
from __future__ import annotations

import argparse
import sys

from _config import load_config, get_info, resolve_address
from _format import emit, fnum, fmt_usd, short_addr, table


def build_result(info, addr: str) -> dict:
    fees = info.user_fees(addr) or {}
    daily = fees.get("dailyUserVlm") or []

    # Sum 14d volumes
    total_cross = sum(fnum(d.get("userCross")) for d in daily)
    total_add = sum(fnum(d.get("userAdd")) for d in daily)

    return {
        "address": addr,
        "taker_rate": fees.get("userCrossRate"),
        "maker_rate": fees.get("userAddRate"),
        "active_referral_discount": fees.get("activeReferralDiscount"),
        "trial": fees.get("trial"),
        "fee_trial_reward": fees.get("feeTrialReward"),
        "next_trial_available_ts": fees.get("nextTrialAvailableTimestamp"),
        "rolling_14d": {
            "taker_volume_usd": total_cross,
            "maker_volume_usd": total_add,
            "total_volume_usd": total_cross + total_add,
        },
        "daily_breakdown": daily,
        "fee_schedule": fees.get("feeSchedule"),
    }


def print_text(r: dict) -> None:
    print(f"=== Fee tier for {short_addr(r['address'])} ===")
    print()
    print(f"  Taker rate:          {r['taker_rate']}  (after discounts)")
    print(f"  Maker rate:          {r['maker_rate']}")
    print(f"  Referral discount:   {r['active_referral_discount']}")
    print()
    r14 = r["rolling_14d"]
    print("-- Rolling 14-day volume --")
    print(f"  Taker volume:        {fmt_usd(r14['taker_volume_usd'])}")
    print(f"  Maker volume:        {fmt_usd(r14['maker_volume_usd'])}")
    print(f"  Total:               {fmt_usd(r14['total_volume_usd'])}")
    print()
    if r["daily_breakdown"]:
        print("-- Daily breakdown --")
        rows = [
            [
                d.get("date") or "-",
                fmt_usd(fnum(d.get("userCross"))),
                fmt_usd(fnum(d.get("userAdd"))),
                fmt_usd(fnum(d.get("userCross")) + fnum(d.get("userAdd"))),
            ]
            for d in r["daily_breakdown"]
        ]
        print(table(rows, ["date", "taker", "maker", "total"], aligns=["l", "r", "r", "r"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    parser.add_argument("address", nargs="?")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    addr = resolve_address(args.address, cfg)
    info = get_info(cfg)

    try:
        result = build_result(info, addr)
    except Exception as e:
        print(f"[error] API call failed: {e}", file=sys.stderr)
        return 2

    emit(result, as_json=args.json, text_printer=print_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
