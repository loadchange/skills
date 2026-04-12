---
name: polymarket-wallet
description: >
  Polymarket wallet trading analysis and report generation. Use this skill whenever the user
  mentions a Polymarket wallet address, wants to check someone's Polymarket trading history,
  asks about Polymarket positions/P&L/win rate, or provides a 0x address in the context of
  Polymarket or prediction markets. Also triggers when the user asks to "check", "analyze",
  "look up", or "report on" a Polymarket trader or address.
---

# Polymarket Wallet Report

Generate comprehensive trading reports for any Polymarket wallet address using the public
Polymarket Data API and Gamma API. No API keys required.

## Quick Start

```bash
# Full report (all time)
python3 <skill-path>/scripts/polymarket_report.py <wallet_address>

# With time range
python3 <skill-path>/scripts/polymarket_report.py <wallet_address> --start 2026-03-01 --end 2026-04-01

# JSON output (for programmatic use)
python3 <skill-path>/scripts/polymarket_report.py <wallet_address> --json

# Fast mode (skip Gamma API checks, uses title parsing only)
python3 <skill-path>/scripts/polymarket_report.py <wallet_address> --skip-market-check
```

## What the Report Covers

1. **Portfolio Overview** — period, trade count, total invested, avg position size
2. **Position Breakdown** — won / lost / expired / active / unclear
3. **Financial P&L** — gross winning, costs, net realized P&L, ROI
4. **Win Rate Analysis** — settled win rate, avg win/loss, win/loss ratio
5. **Redemption Stats** — redeem count, payout vs zero-payout breakdown
6. **Position Details** — expired unredeemed, active, unclear positions listed
7. **Top Winning Positions** — ranked by profit
8. **Daily Activity** — trades per day with volume
9. **Trading Patterns** — side and outcome distributions

## How It Works

The script fetches activity data from `https://data-api.polymarket.com/activity` in
paginated batches (100 per request). It groups trades by `conditionId` to build positions,
then classifies each position:

- **Won**: redeemed with payout > 0
- **Lost**: redeemed with payout = 0
- **Expired**: not redeemed, market end date has passed (checked via Gamma API or title parsing)
- **Active**: not redeemed, market still open
- **Unclear**: not redeemed, can't determine end date

Expired unredeemed positions are treated as likely losses — bots and active traders
automatically redeem winning positions, so an unredeemed expired position almost certainly
had zero payout.

## Parameters

| Flag | Description |
|------|-------------|
| `wallet` | Required. The 0x wallet address to analyze |
| `--start YYYY-MM-DD` | Optional. Only include activities on or after this date |
| `--end YYYY-MM-DD` | Optional. Only include activities on or before this date |
| `--json` | Output structured JSON instead of text report |
| `--skip-market-check` | Skip Gamma API calls (faster but less accurate classification) |

If no `--start` / `--end` is provided, all available activities are included.

## Usage Notes

- The Polymarket Data API may rate-limit requests. The script includes 300ms delays between
  pagination requests and 150ms delays between Gamma API market checks.
- For wallets with very large trading history, use `--skip-market-check` for faster results.
- The `--json` output is useful for piping into other analysis tools or saving to files.
- Zero-payout redeems in the stats are typically the "losing side" of multi-outcome markets
  where the wallet's other outcome won — they don't represent separate losses.

## When to Use

Run the script whenever the user provides a wallet address and wants Polymarket trading
analysis. Present the text report directly — it's designed to be readable. If the user
asks follow-up questions, re-run with `--json` and parse specific fields.

If the user doesn't specify a time range, run without `--start`/`--end` to get the full
history. If they say something like "last 30 days" or "this month", calculate the
appropriate dates and pass them as `--start`/`--end`.
