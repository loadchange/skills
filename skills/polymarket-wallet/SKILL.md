---
name: polymarket-wallet
description: >
  Polymarket wallet trading analysis and report generation. Use this skill whenever the user
  mentions a Polymarket wallet address OR a Polymarket display name (e.g. "ColdMath"), wants
  to check someone's Polymarket trading history, asks about Polymarket positions/P&L/win
  rate, or provides a 0x address in the context of Polymarket or prediction markets. Also
  triggers when the user asks to "check", "analyze", "look up", or "report on" a Polymarket
  trader by name or address. The script auto-detects name vs address, so pass whichever the
  user gave you.
---

# Polymarket Wallet Report

Generate comprehensive trading reports for any Polymarket wallet — given either a 0x address
or a Polymarket display name — using the public Polymarket Data API and Gamma API. No API
keys required.

## Quick Start

```bash
# By 0x address
python3 <skill-path>/scripts/polymarket_report.py 0x594edb9112f526fa6a80b8f858a6379c8a2c1c11

# By Polymarket display name (auto-resolves to wallet via gamma-api)
python3 <skill-path>/scripts/polymarket_report.py ColdMath

# With time range
python3 <skill-path>/scripts/polymarket_report.py ColdMath --start 2026-03-01 --end 2026-04-01

# JSON output (for programmatic use)
python3 <skill-path>/scripts/polymarket_report.py ColdMath --json

# Fast mode (skip Gamma API checks, uses title parsing only)
python3 <skill-path>/scripts/polymarket_report.py ColdMath --skip-market-check
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

### Username Resolution

The script auto-detects whether the first argument is a 0x address or a display name:

- If it starts with `0x`/`0X`, it's validated as an address (must be `0x` + 40 hex chars).
- Otherwise it's treated as a Polymarket display name and resolved via
  `https://gamma-api.polymarket.com/public-search?q=<name>&search_profiles=true`.

The search is fuzzy (e.g. `ColdMath` also matches `coldmath.i`), so the resolver requires a
**case-insensitive exact match on the `name` field** and picks the unique `proxyWallet`.
If there's zero matches, multiple matches, or a network/HTTP error, it exits with a helpful
stderr message — display names aren't guaranteed unique across profiles, and silently running
the report against the wrong wallet would be worse than failing fast. If resolution fails,
fall back to passing the 0x address directly.

## Parameters

| Flag | Description |
|------|-------------|
| `wallet` | Required. 0x wallet address **or** Polymarket display name (case-insensitive). |
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
