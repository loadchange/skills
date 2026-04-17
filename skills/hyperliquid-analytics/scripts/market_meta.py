#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "hyperliquid-python-sdk",
# ]
# ///
"""Perp universe metadata and live asset contexts.

Shows the list of all perpetual markets with their static properties
(leverage cap, decimals) and optionally live state (funding, open
interest, premium, 24h volume) from metaAndAssetCtxs.

Usage:
    python scripts/market_meta.py                # all perps (name + lev)
    python scripts/market_meta.py --live         # include live ctx (OI, funding, volume)
    python scripts/market_meta.py --coin BTC     # filter to one market
    python scripts/market_meta.py --spot         # spot universe instead
    python scripts/market_meta.py --dex xyz      # HIP-3 DEX perp universe
"""
from __future__ import annotations

import argparse
import sys

from _config import load_config, get_info
from _format import emit, fnum, fmt_usd, fmt_pct, table


def build_perp_result(info, dex: str, live: bool, coin_filter: str | None) -> dict:
    if live:
        pair = info.meta_and_asset_ctxs()
        meta = pair[0]
        ctxs = pair[1]
    else:
        meta = info.meta(dex=dex)
        ctxs = None

    universe = meta.get("universe", []) or []
    markets = []
    for i, m in enumerate(universe):
        name = m.get("name")
        if coin_filter and name != coin_filter:
            continue
        row = {
            "name": name,
            "sz_decimals": m.get("szDecimals"),
            "max_leverage": m.get("maxLeverage"),
            "only_isolated": m.get("onlyIsolated"),
        }
        if ctxs and i < len(ctxs):
            c = ctxs[i] or {}
            row.update({
                "funding": fnum(c.get("funding")),
                "open_interest": fnum(c.get("openInterest")),
                "premium": fnum(c.get("premium")),
                "oracle_px": fnum(c.get("oraclePx")),
                "mark_px": fnum(c.get("markPx")),
                "mid_px": fnum(c.get("midPx")),
                "prev_day_px": fnum(c.get("prevDayPx")),
                "day_notional_vlm": fnum(c.get("dayNtlVlm")),
            })
        markets.append(row)
    return {"kind": "perp", "dex": dex or "default", "live": live, "n_markets": len(markets), "markets": markets}


def build_spot_result(info, live: bool, coin_filter: str | None) -> dict:
    if live:
        pair = info.spot_meta_and_asset_ctxs()
        meta = pair[0]
        ctxs = pair[1]
    else:
        meta = info.spot_meta()
        ctxs = None

    universe = meta.get("universe", []) or []
    tokens = meta.get("tokens", []) or []
    markets = []
    for i, m in enumerate(universe):
        name = m.get("name")
        if coin_filter and name != coin_filter and m.get("index") and f"@{m.get('index')}" != coin_filter:
            continue
        row = {
            "name": name,
            "index": m.get("index"),
            "tokens": m.get("tokens"),
        }
        if ctxs and i < len(ctxs):
            c = ctxs[i] or {}
            row.update({
                "mark_px": fnum(c.get("markPx")),
                "mid_px": fnum(c.get("midPx")),
                "prev_day_px": fnum(c.get("prevDayPx")),
                "day_notional_vlm": fnum(c.get("dayNtlVlm")),
                "circulating_supply": fnum(c.get("circulatingSupply")),
                "coin_key": c.get("coin"),
            })
        markets.append(row)
    return {"kind": "spot", "live": live, "n_markets": len(markets), "tokens": tokens, "markets": markets}


def print_perp(r: dict) -> None:
    print(f"=== Perp universe ({r['dex']}) — {r['n_markets']} markets ===")
    if not r["markets"]:
        return
    if r["live"]:
        rows = [[
            m["name"] or "-",
            str(m.get("max_leverage") or "-"),
            f"{m.get('mark_px', 0):.4f}",
            fmt_usd(m.get("open_interest", 0) * m.get("mark_px", 0)),
            fmt_usd(m.get("day_notional_vlm", 0)),
            f"{m.get('funding', 0):.6f}",
        ] for m in r["markets"]]
        print(table(
            rows,
            ["coin", "lev", "markPx", "OI(usd)", "24h vol", "funding"],
            aligns=["l", "r", "r", "r", "r", "r"],
        ))
    else:
        rows = [[m["name"] or "-", str(m.get("max_leverage") or "-"),
                 str(m.get("sz_decimals") or "-"),
                 "Y" if m.get("only_isolated") else ""] for m in r["markets"]]
        print(table(rows, ["coin", "maxLev", "szDec", "isoOnly"], aligns=["l", "r", "r", "c"]))


def print_spot(r: dict) -> None:
    print(f"=== Spot universe — {r['n_markets']} markets ===")
    if not r["markets"]:
        return
    if r["live"]:
        rows = [[
            m["name"] or "-", str(m.get("index") or "-"),
            f"{m.get('mid_px', 0):.6f}",
            fmt_usd(m.get("day_notional_vlm", 0)),
        ] for m in r["markets"]]
        print(table(rows, ["name", "idx", "mid", "24h vol"], aligns=["l", "r", "r", "r"]))
    else:
        rows = [[m["name"] or "-", str(m.get("index") or "-"),
                 str(m.get("tokens") or "-")] for m in r["markets"]]
        print(table(rows, ["name", "idx", "tokens[base,quote]"], aligns=["l", "r", "l"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    parser.add_argument("--spot", action="store_true", help="Query spot universe instead of perp")
    parser.add_argument("--live", action="store_true", help="Include live asset contexts (OI, funding, volume)")
    parser.add_argument("--coin", help="Filter to a single coin name")
    parser.add_argument("--dex", default="", help="HIP-3 DEX name (perp only)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    info = get_info(cfg)

    try:
        if args.spot:
            result = build_spot_result(info, args.live, args.coin)
            emit(result, as_json=args.json, text_printer=print_spot)
        else:
            result = build_perp_result(info, args.dex, args.live, args.coin)
            emit(result, as_json=args.json, text_printer=print_perp)
    except Exception as e:
        print(f"[error] API call failed: {e}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
