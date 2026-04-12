#!/usr/bin/env python3
"""Polymarket wallet trading report generator.

Fetches all trading activity for a wallet from Polymarket's public API
and generates a comprehensive report with P&L, win rate, and position breakdown.

Usage:
    python3 polymarket_report.py <wallet_address> [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--json]

Examples:
    python3 polymarket_report.py 0xabc...def
    python3 polymarket_report.py 0xabc...def --start 2026-03-01 --end 2026-04-01
    python3 polymarket_report.py 0xabc...def --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

API_BASE = "https://data-api.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Accept": "application/json",
}
TODAY = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")


def fetch_activities(wallet: str, start: str | None, end: str | None) -> list[dict]:
    """Fetch all activities for a wallet, with optional time filtering."""
    all_activities: list[dict] = []
    offset = 0
    while True:
        url = f"{API_BASE}/activity?user={wallet}&limit=100&offset={offset}"
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            print(f"Error fetching offset={offset}: {e}", file=sys.stderr)
            break
        if not data:
            break
        all_activities.extend(data)
        offset += 100
        if len(data) < 100:
            break
        time.sleep(0.3)

    # Apply time filters
    if start:
        start_ts = int(datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
        all_activities = [a for a in all_activities if a["timestamp"] >= start_ts]
    if end:
        end_ts = int(
            datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
        ) + 86400  # include the end day
        all_activities = [a for a in all_activities if a["timestamp"] < end_ts]

    return all_activities


def build_positions(activities: list[dict]) -> dict[str, dict]:
    """Group activities into positions by conditionId."""
    trades = [a for a in activities if a["type"] == "TRADE"]
    redeems = [a for a in activities if a["type"] == "REDEEM"]

    positions: dict[str, dict[str, Any]] = {}
    for t in trades:
        cid = t["conditionId"]
        if cid not in positions:
            positions[cid] = {
                "cost": 0, "tokens": 0, "payout": 0, "trade_count": 0,
                "redeemed": False, "title": "", "outcome": "", "side": "",
                "trade_time": 0, "slug": "", "event_slug": "",
            }
        p = positions[cid]
        p["cost"] += t["usdcSize"]
        p["tokens"] += t["size"]
        p["trade_count"] += 1
        p["title"] = t["title"]
        p["outcome"] = t.get("outcome", "")
        p["side"] = t.get("side", "")
        p["trade_time"] = max(p["trade_time"], t["timestamp"])
        p["slug"] = t.get("slug", "")
        p["event_slug"] = t.get("eventSlug", "")

    for cid in positions:
        p = positions[cid]
        if p["tokens"] > 0:
            p["avg_price"] = p["cost"] / p["tokens"]
        else:
            p["avg_price"] = 0

    for r in redeems:
        cid = r["conditionId"]
        if cid in positions:
            positions[cid]["payout"] += r["usdcSize"]
            positions[cid]["redeemed"] = True

    return positions


def infer_end_date(title: str) -> str | None:
    """Try to extract a date from a market title like 'on April 9'."""
    m = re.search(r"on (\w+ \d+)", title)
    if not m:
        return None
    try:
        # Try current year first, fall back if needed
        year = datetime.now(tz=timezone.utc).year
        date_str = f"{m.group(1)}, {year}"
        return datetime.strptime(date_str, "%B %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def check_market_status(slug: str) -> dict | None:
    """Query Gamma API for market status."""
    try:
        url = f"{GAMMA_API}/markets?slug={slug}"
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            markets = json.loads(resp.read())
        if markets:
            m = markets[0]
            return {
                "end_date": (m.get("endDate") or "")[:10],
                "resolved": m.get("resolved", False),
                "closed": m.get("closed", False),
                "outcome": m.get("outcome", ""),
            }
    except Exception:
        pass
    return None


def classify_positions(positions: dict[str, dict]) -> dict[str, list]:
    """Classify positions into won/lost/expired/active/unclear."""
    won, lost, expired, active, unclear = [], [], [], [], []

    for cid, p in positions.items():
        if p["redeemed"]:
            if p["payout"] > 0:
                won.append(p)
            else:
                lost.append(p)
        else:
            # Try Gamma API first
            status = check_market_status(p["slug"]) if p["slug"] else None
            if status:
                p["end_date"] = status["end_date"]
                p["resolved"] = status["resolved"]
                if status["resolved"] or (status["end_date"] and status["end_date"] < TODAY):
                    expired.append(p)
                else:
                    active.append(p)
            else:
                # Fall back to title date parsing
                inferred = infer_end_date(p["title"])
                if inferred:
                    p["end_date"] = inferred
                    if inferred < TODAY:
                        expired.append(p)
                    else:
                        active.append(p)
                else:
                    unclear.append(p)
            time.sleep(0.15)

    return {
        "won": won, "lost": lost, "expired": expired,
        "active": active, "unclear": unclear,
    }


def generate_report(wallet: str, activities: list[dict], positions: dict[str, dict],
                    classified: dict[str, list]) -> str:
    """Generate the text report."""
    trades = [a for a in activities if a["type"] == "TRADE"]
    redeems = [a for a in activities if a["type"] == "REDEEM"]
    merges = [a for a in activities if a["type"] == "MERGE"]
    splits = [a for a in activities if a["type"] == "SPLIT"]

    won = classified["won"]
    lost = classified["lost"]
    expired = classified["expired"]
    active = classified["active"]
    unclear = classified["unclear"]

    all_ts = [a["timestamp"] for a in activities]
    first = datetime.fromtimestamp(min(all_ts), tz=timezone.utc) if all_ts else None
    last = datetime.fromtimestamp(max(all_ts), tz=timezone.utc) if all_ts else None

    buy_trades = [t for t in trades if t["side"] == "BUY"]
    sell_trades = [t for t in trades if t["side"] == "SELL"]

    lines: list[str] = []
    w = lines.append

    sep = "=" * 80
    thin = "\u2500" * 60

    w(sep)
    w(f"    POLYMARKET WALLET TRADING REPORT")
    w(f"    Wallet: {wallet}")
    w(f"    Report Date: {TODAY}")
    w(sep)

    # 1. Overview
    w(f"\n{thin}")
    w(f"  1. PORTFOLIO OVERVIEW")
    w(thin)
    if first and last:
        days = (last - first).days
        w(f"  Period:              {first.strftime('%Y-%m-%d')} ~ {last.strftime('%Y-%m-%d')} ({days} days)")
    w(f"  Total activities:    {len(activities)}")
    w(f"    TRADE: {len(trades)}  (BUY: {len(buy_trades)}, SELL: {len(sell_trades)})")
    w(f"    REDEEM: {len(redeems)}")
    if merges:
        w(f"    MERGE: {len(merges)}")
    if splits:
        w(f"    SPLIT: {len(splits)}")
    w(f"  Total positions:     {len(positions)}")
    total_cost = sum(p["cost"] for p in positions.values())
    w(f"  Total invested:      {total_cost:.2f} USDC")
    if positions:
        w(f"  Avg position size:   {total_cost / len(positions):.2f} USDC")

    # Trade volume
    if sell_trades:
        w(f"  Buy volume:          {sum(t['usdcSize'] for t in buy_trades):.2f} USDC")
        w(f"  Sell volume:         {sum(t['usdcSize'] for t in sell_trades):.2f} USDC")

    # 2. Position Breakdown
    w(f"\n{thin}")
    w(f"  2. POSITION BREAKDOWN")
    w(thin)
    w(f"  Won (redeemed, payout>0):         {len(won):3d}  cost={sum(p['cost'] for p in won):8.2f}  payout={sum(p['payout'] for p in won):8.2f}")
    w(f"  Lost (redeemed, payout=0):        {len(lost):3d}  cost={sum(p['cost'] for p in lost):8.2f}")
    w(f"  Expired (unredeemed, past end):   {len(expired):3d}  cost={sum(p['cost'] for p in expired):8.2f}  (likely losses*)")
    w(f"  Active (market still open):       {len(active):3d}  cost={sum(p['cost'] for p in active):8.2f}")
    if unclear:
        w(f"  Unclear:                          {len(unclear):3d}  cost={sum(p['cost'] for p in unclear):8.2f}")
    w(f"")
    w(f"  * Expired unredeemed positions are likely losses — bots auto-redeem wins.")

    # 3. Financial Summary
    w(f"\n{thin}")
    w(f"  3. FINANCIAL SUMMARY")
    w(thin)
    win_cost = sum(p["cost"] for p in won)
    win_payout = sum(p["payout"] for p in won)
    win_pnl = win_payout - win_cost
    expired_cost = sum(p["cost"] for p in expired)
    lost_cost = sum(p["cost"] for p in lost)
    unclear_cost = sum(p["cost"] for p in unclear)
    active_cost = sum(p["cost"] for p in active)

    w(f"  Gross winning:       +{win_payout:7.2f} USDC  ({len(won)} wins)")
    w(f"  Winning cost:        -{win_cost:7.2f} USDC")
    w(f"  Win P&L:             {win_pnl:+7.2f} USDC")
    if expired:
        w(f"  Expired losses:      -{expired_cost:7.2f} USDC  ({len(expired)} positions)")
    if lost:
        w(f"  Redeemed losses:     -{lost_cost:7.2f} USDC  ({len(lost)} positions)")
    if unclear:
        w(f"  Unclear losses:      -{unclear_cost:7.2f} USDC  ({len(unclear)} positions)")

    realized_pnl = win_pnl - expired_cost - lost_cost - unclear_cost
    settled_cost = total_cost - active_cost
    w(f"  {'\u2500' * 40}")
    w(f"  Net realized P&L:    {realized_pnl:+7.2f} USDC")
    w(f"  Active capital:      {active_cost:7.2f} USDC  ({len(active)} open positions)")
    w(f"  Total invested:      {total_cost:7.2f} USDC")
    if settled_cost > 0:
        w(f"  Realized ROI:        {realized_pnl / settled_cost * 100:+.1f}%")

    # Merge/Split P&L
    if merges:
        merge_usdc = sum(m["usdcSize"] for m in merges)
        w(f"  Merge income:        +{merge_usdc:7.2f} USDC  ({len(merges)} merges)")
    if splits:
        split_usdc = sum(s["usdcSize"] for s in splits)
        w(f"  Split cost:          -{split_usdc:7.2f} USDC  ({len(splits)} splits)")

    # 4. Win Rate
    w(f"\n{thin}")
    w(f"  4. WIN RATE ANALYSIS")
    w(thin)
    total_settled = len(won) + len(lost) + len(expired) + len(unclear)
    full_lost = len(lost) + len(expired) + len(unclear)
    if total_settled > 0:
        w(f"  Settled positions:   {total_settled}")
        w(f"  Won:                 {len(won)}")
        w(f"  Lost:                {full_lost}")
        w(f"  Win Rate:            {len(won)}/{total_settled} = {len(won) / total_settled * 100:.1f}%")
        if won:
            w(f"  Avg win profit:      {win_pnl / len(won):+.4f} USDC/position")
        if full_lost > 0:
            total_lost_cost = expired_cost + lost_cost + unclear_cost
            avg_loss = total_lost_cost / full_lost
            w(f"  Avg loss:            -{avg_loss:.4f} USDC/position")
            if won and avg_loss > 0:
                w(f"  Win/Loss ratio:      {(win_pnl / len(won)) / avg_loss:.2f}x")
    else:
        w(f"  No settled positions yet.")

    # 5. Redemption Stats
    w(f"\n{thin}")
    w(f"  5. REDEMPTION STATS")
    w(thin)
    w(f"  Total redeem txs:    {len(redeems)}")
    winning_redeems = [r for r in redeems if r["usdcSize"] > 0]
    zero_redeems = [r for r in redeems if r["usdcSize"] == 0]
    w(f"  With payout (>0):    {len(winning_redeems)} txs \u2192 {sum(r['usdcSize'] for r in winning_redeems):.2f} USDC")
    w(f"  Zero payout:         {len(zero_redeems)} txs")
    if positions:
        w(f"  Positions redeemed:  {len(won) + len(lost)}/{len(positions)} = {(len(won) + len(lost)) / len(positions) * 100:.1f}%")

    # 6. Expired positions
    if expired:
        w(f"\n{thin}")
        w(f"  6. EXPIRED UNREDEEMED POSITIONS ({len(expired)})")
        w(thin)
        for p in sorted(expired, key=lambda x: x.get("end_date", "")):
            dt = datetime.fromtimestamp(p["trade_time"], tz=timezone.utc).strftime("%m-%d")
            end = p.get("end_date", "?")
            w(f"  [{dt}] end={end} | ${p['cost']:.2f} {p['outcome']} | {p['title'][:50]}")

    # 7. Active positions
    if active:
        w(f"\n{thin}")
        w(f"  7. ACTIVE POSITIONS ({len(active)})")
        w(thin)
        for p in sorted(active, key=lambda x: x.get("end_date", "")):
            dt = datetime.fromtimestamp(p["trade_time"], tz=timezone.utc).strftime("%m-%d")
            end = p.get("end_date", "?")
            w(f"  [{dt}] end={end} | ${p['cost']:.2f} {p['outcome']} | {p['title'][:50]}")

    # 8. Unclear positions
    if unclear:
        w(f"\n{thin}")
        w(f"  8. UNCLEAR POSITIONS ({len(unclear)})")
        w(thin)
        for p in unclear:
            dt = datetime.fromtimestamp(p["trade_time"], tz=timezone.utc).strftime("%m-%d")
            w(f"  [{dt}] ${p['cost']:.2f} {p['outcome']} | {p['title'][:55]}")

    # 9. Won positions (top 20 by profit)
    if won:
        w(f"\n{thin}")
        w(f"  9. TOP WINNING POSITIONS (by profit)")
        w(thin)
        top_wins = sorted(won, key=lambda x: x["payout"] - x["cost"], reverse=True)[:20]
        for p in top_wins:
            dt = datetime.fromtimestamp(p["trade_time"], tz=timezone.utc).strftime("%m-%d")
            pnl = p["payout"] - p["cost"]
            w(f"  [{dt}] P&L={pnl:+.2f} cost={p['cost']:.2f} payout={p['payout']:.2f} | {p['outcome']} | {p['title'][:40]}")

    # 10. Daily activity
    w(f"\n{thin}")
    w(f"  10. DAILY ACTIVITY")
    w(thin)
    w(f"  {'Date':<12} {'Trades':>6} {'USDC':>10} {'Positions':>10}")
    w(f"  {'\u2500' * 12} {'\u2500' * 6} {'\u2500' * 10} {'\u2500' * 10}")
    days: dict[str, dict] = defaultdict(lambda: {"trades": 0, "usdc": 0.0, "cids": set()})
    for t in trades:
        day = datetime.fromtimestamp(t["timestamp"], tz=timezone.utc).strftime("%Y-%m-%d")
        days[day]["trades"] += 1
        days[day]["usdc"] += t["usdcSize"]
        days[day]["cids"].add(t["conditionId"])
    for day in sorted(days.keys()):
        d = days[day]
        w(f"  {day:<12} {d['trades']:>6} {d['usdc']:>10.2f} {len(d['cids']):>10}")

    # 11. Side/Outcome distribution
    outcomes = Counter(p["outcome"] for p in positions.values() if p["outcome"])
    sides = Counter(p["side"] for p in positions.values() if p["side"])
    if outcomes or sides:
        w(f"\n{thin}")
        w(f"  11. TRADING PATTERNS")
        w(thin)
        if sides:
            w(f"  Side distribution: {dict(sides.most_common())}")
        if outcomes:
            w(f"  Outcome distribution: {dict(outcomes.most_common())}")

    w(f"\n{sep}")
    w(f"  REPORT END")
    w(sep)

    return "\n".join(lines)


def generate_json_report(wallet: str, activities: list[dict], positions: dict[str, dict],
                         classified: dict[str, list]) -> dict:
    """Generate a structured JSON report."""
    trades = [a for a in activities if a["type"] == "TRADE"]
    redeems = [a for a in activities if a["type"] == "REDEEM"]
    won = classified["won"]
    lost = classified["lost"]
    expired = classified["expired"]
    active = classified["active"]
    unclear = classified["unclear"]

    total_cost = sum(p["cost"] for p in positions.values())
    win_cost = sum(p["cost"] for p in won)
    win_payout = sum(p["payout"] for p in won)
    win_pnl = win_payout - win_cost
    expired_cost = sum(p["cost"] for p in expired)
    lost_cost = sum(p["cost"] for p in lost)
    unclear_cost = sum(p["cost"] for p in unclear)
    realized_pnl = win_pnl - expired_cost - lost_cost - unclear_cost
    active_cost = sum(p["cost"] for p in active)
    settled_cost = total_cost - active_cost
    total_settled = len(won) + len(lost) + len(expired) + len(unclear)

    all_ts = [a["timestamp"] for a in activities]

    return {
        "wallet": wallet,
        "report_date": TODAY,
        "period": {
            "first": datetime.fromtimestamp(min(all_ts), tz=timezone.utc).isoformat() if all_ts else None,
            "last": datetime.fromtimestamp(max(all_ts), tz=timezone.utc).isoformat() if all_ts else None,
        },
        "overview": {
            "total_activities": len(activities),
            "total_trades": len(trades),
            "total_redeems": len(redeems),
            "total_positions": len(positions),
            "total_invested_usdc": round(total_cost, 4),
        },
        "settlement": {
            "won": len(won),
            "lost": len(lost),
            "expired_unredeemed": len(expired),
            "active": len(active),
            "unclear": len(unclear),
        },
        "financials": {
            "win_payout_usdc": round(win_payout, 4),
            "win_cost_usdc": round(win_cost, 4),
            "win_pnl_usdc": round(win_pnl, 4),
            "expired_loss_usdc": round(expired_cost, 4),
            "redeemed_loss_usdc": round(lost_cost, 4),
            "net_realized_pnl_usdc": round(realized_pnl, 4),
            "active_capital_usdc": round(active_cost, 4),
            "realized_roi_pct": round(realized_pnl / settled_cost * 100, 2) if settled_cost > 0 else 0,
        },
        "win_rate": {
            "settled_positions": total_settled,
            "wins": len(won),
            "losses": len(lost) + len(expired) + len(unclear),
            "win_rate_pct": round(len(won) / total_settled * 100, 1) if total_settled > 0 else 0,
        },
        "positions": {
            "won": [{"title": p["title"], "cost": round(p["cost"], 4), "payout": round(p["payout"], 4),
                      "pnl": round(p["payout"] - p["cost"], 4), "outcome": p["outcome"]} for p in won],
            "expired": [{"title": p["title"], "cost": round(p["cost"], 4), "outcome": p["outcome"],
                         "end_date": p.get("end_date", "")} for p in expired],
            "active": [{"title": p["title"], "cost": round(p["cost"], 4), "outcome": p["outcome"],
                        "end_date": p.get("end_date", "")} for p in active],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Polymarket wallet trading report")
    parser.add_argument("wallet", help="Wallet address (0x...)")
    parser.add_argument("--start", help="Start date filter (YYYY-MM-DD)")
    parser.add_argument("--end", help="End date filter (YYYY-MM-DD)")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of text")
    parser.add_argument("--skip-market-check", action="store_true",
                        help="Skip Gamma API checks (faster, less accurate)")
    args = parser.parse_args()

    print(f"Fetching activities for {args.wallet}...", file=sys.stderr)
    activities = fetch_activities(args.wallet, args.start, args.end)
    if not activities:
        print("No activities found for this wallet.", file=sys.stderr)
        sys.exit(1)
    print(f"Fetched {len(activities)} activities.", file=sys.stderr)

    positions = build_positions(activities)
    print(f"Built {len(positions)} positions.", file=sys.stderr)

    if args.skip_market_check:
        # Fast mode: classify only by title date parsing and redeem status
        classified: dict[str, list] = {"won": [], "lost": [], "expired": [], "active": [], "unclear": []}
        for cid, p in positions.items():
            if p["redeemed"]:
                if p["payout"] > 0:
                    classified["won"].append(p)
                else:
                    classified["lost"].append(p)
            else:
                inferred = infer_end_date(p["title"])
                if inferred:
                    p["end_date"] = inferred
                    if inferred < TODAY:
                        classified["expired"].append(p)
                    else:
                        classified["active"].append(p)
                else:
                    classified["unclear"].append(p)
    else:
        print("Checking market status...", file=sys.stderr)
        classified = classify_positions(positions)

    if args.json:
        report = generate_json_report(args.wallet, activities, positions, classified)
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        report = generate_report(args.wallet, activities, positions, classified)
        print(report)


if __name__ == "__main__":
    main()
