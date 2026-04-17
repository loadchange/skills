# Market Context (Schema Reference)

> **Canonical scripts: `scripts/market_meta.py`, `scripts/mids.py`, `scripts/funding_rates.py`.** These fetch and print the same data this file documents. Use this reference to understand the schemas and field meanings.

---

Market metadata, mids, candles, and funding rates. These endpoints are not user-data per se — they're the **enrichment layer** that lets you turn raw user data into something interpretable. Knowing a fill happened at $62000 means little until you join it against the mid at the same timestamp, the funding rate paid that hour, and the asset's max leverage.

All examples assume the standard imports from [account-state.md](account-state.md).

## Universe Metadata

The list of perpetual markets and their static properties.

```python
meta = info.meta()
# {
#   "universe": [
#     {"name": "BTC", "szDecimals": 5, "maxLeverage": 40, "onlyIsolated": false},
#     {"name": "ETH", "szDecimals": 4, "maxLeverage": 25, "onlyIsolated": false},
#     ...
#   ]
# }
```

| Field | Meaning |
|---|---|
| `name` | Coin symbol used in all other queries (`"BTC"`, `"HYPE"`, etc.) |
| `szDecimals` | Decimal precision for size (used to format limit orders correctly) |
| `maxLeverage` | Maximum leverage allowed for this market |
| `onlyIsolated` | If true, cross-margin is disabled for this market |

**Cache for 1–5 minutes.** This list changes only when Hyperliquid lists a new market or adjusts leverage, which happens infrequently.

**Cost:** weight 20.

## Live Asset Contexts

Universe metadata combined with live state (funding, OI, premium, volume). This is what you need for "what's happening *right now* in the market."

```python
ctxs = info.meta_and_asset_ctxs()
# Returns a 2-tuple [meta, asset_ctxs]
universe_meta, asset_ctxs = ctxs[0], ctxs[1]
# asset_ctxs[i] corresponds to universe_meta["universe"][i]:
# {"funding": "0.0000125",       # current 1h funding rate
#  "openInterest": "12345.67",    # OI in coin units
#  "prevDayPx": "61500.0",
#  "dayNtlVlm": "1234567890.0",   # 24h notional volume
#  "premium": "0.0001",           # mark-index premium
#  "oraclePx": "62100.0",
#  "markPx": "62110.0",
#  "midPx": "62105.0",
#  "impactPxs": ["62050.0", "62160.0"]}
```

To zip them together for analysis:

```python
universe_meta, asset_ctxs = info.meta_and_asset_ctxs()
markets = [
    {"name": u["name"], **c}
    for u, c in zip(universe_meta["universe"], asset_ctxs)
]
```

**Cost:** weight 20. Don't poll this too aggressively — it's expensive relative to `all_mids`.

## Spot Metadata and Contexts

```python
spot_meta = info.spot_meta()
# {"universe": [{"name": "PURR/USDC", "tokens": [1, 0], "index": 0, ...}, ...],
#  "tokens":   [{"name": "USDC", "szDecimals": ..., "weiDecimals": 8, "index": 0, ...},
#               {"name": "PURR", "szDecimals": ..., "weiDecimals": 5, "index": 1, ...}, ...]}

spot_ctxs = info.spot_meta_and_asset_ctxs()
spot_universe_meta, spot_asset_ctxs = spot_ctxs[0], spot_ctxs[1]
# spot_asset_ctxs[i] = {"dayNtlVlm": ..., "markPx": ..., "midPx": ..., "prevDayPx": ...,
#                       "circulatingSupply": ..., "coin": "@1", ...}
```

**Cost:** weight 20.

## All Mids

A flat dictionary of all mid prices, keyed by coin name (perp) or `@{tokenIndex}` (spot). The cheapest way to get a current price for many markets at once.

```python
mids = info.all_mids()
# {"BTC": "62105.0", "ETH": "2345.0", "HYPE": "28.5",
#  "@1": "0.20", "@107": "...", "PURR/USDC": "0.20", ...}
```

**Important:** spot markets appear under both their `@{idx}` form and their human-readable form (e.g., `"PURR/USDC"`) when one exists. Perp markets only use the symbol form.

**Cost:** weight 2. Cheap enough to call frequently.

**Use this for marking positions:** when computing unrealized PnL on a position, fetch one `all_mids()` and look up by the coin name from `assetPositions[].position.coin`. This is much cheaper than calling `meta_and_asset_ctxs` just to get prices.

## Candles

OHLCV bars for charting and execution-quality analysis.

```python
import time
candles = info.candles_snapshot(
    name="BTC",
    interval="1h",  # 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 8h, 12h, 1d, 3d, 1w, 1M
    startTime=int((time.time() - 7 * 86400) * 1000),
    endTime=int(time.time() * 1000),
)
# [{"t": openMs, "T": closeMs, "s": "BTC", "i": "1h",
#   "o": "61000.0", "h": "62500.0", "l": "60800.0", "c": "62100.0",
#   "v": "1234.5", "n": 8765}, ...]
```

| Field | Meaning |
|---|---|
| `t` / `T` | Bar open / close timestamps in ms |
| `s` | Symbol |
| `i` | Interval |
| `o` / `h` / `l` / `c` | Open / high / low / close |
| `v` | Volume in coin units |
| `n` | Number of trades in bar |

**Spot candles:** pass the spot market name in the form `"@1"` or `"PURR/USDC"`.

**Cost:** weight 20. There's an effective cap on how many bars come back per call (in the hundreds), so for very long ranges you may need to chunk.

**Use this for execution-quality analysis:** for each fill, fetch the corresponding 1-minute candle and compute slippage as `(fill_px − minute_vwap) / minute_vwap`. See recipe #4 in [recipes.md](recipes.md).

## Funding Rate History

```python
import time
funding_hist = info.funding_history(
    name="BTC",
    startTime=int((time.time() - 30 * 86400) * 1000),
    endTime=None,
)
# [{"coin": "BTC", "fundingRate": "0.0000125", "premium": "0.0001",
#   "time": 1734567890123}, ...]
```

This is the **market-wide** funding rate history (i.e., what every long paid to every short at each interval), as opposed to `user_funding_history` which is the per-user payments.

**Cost:** weight 20.

**Use this for cost attribution:** if you want to know "if I had held a 1 BTC long for the last 30 days, what would my funding cost have been?", sum `fundingRate * mark_price * 1.0` across the period. The user-side `user_funding_history` already gives you the actual paid values, but market-side data is needed for backtesting "what if" scenarios.

## Predicted Funding (Cross-Venue)

A snapshot of the next funding interval's predicted rate at Hyperliquid and several centralized exchanges. Useful for funding arbitrage screening.

```python
import httpx
from hyperliquid.utils import constants

predictions = httpx.post(
    constants.MAINNET_API_URL + "/info",
    json={"type": "predictedFundings"},
    timeout=10.0,
).json()
# Format: array of [coin, [[venue, info], ...]] pairs
# [["BTC",
#   [["HlPerp",  {"fundingRate": "0.0000125", "nextFundingTime": ..., "fundingIntervalHours": 1}],
#    ["BinPerp", {"fundingRate": "0.000010",  "nextFundingTime": ..., "fundingIntervalHours": 8}]]],
#  ["ETH", ...], ...]
```

The Python SDK does not wrap this; use raw `httpx`. **Cost:** weight 20.

**Beware the interval mismatch:** Hyperliquid funds hourly (1h interval), Binance funds 8-hourly. To compare apples to apples, normalize both to a common interval first (e.g., annualized: `funding * (24 * 365 / interval_hours)`).

## Exchange Status (Freshness Check)

```python
import httpx
from hyperliquid.utils import constants

status = httpx.post(
    constants.MAINNET_API_URL + "/info",
    json={"type": "exchangeStatus"},
    timeout=10.0,
).json()
# {"time": 1734567890123, "blockNumber": 123456789, ...}
```

`time` is the latest L1 timestamp Hyperliquid has processed. If this lags wall-clock by more than a few seconds, treat downstream queries as stale. The Python SDK does not wrap this. Cost is small.

## Coin Naming Conventions

This trips people up constantly. Same asset, different name in different contexts:

| Context | Format | Example |
|---|---|---|
| Perpetual | Coin symbol | `"BTC"`, `"ETH"`, `"HYPE"` |
| Spot (canonical) | `@{tokenIndex}` | `"@1"` (PURR), `"@107"` |
| Spot (display, when registered) | `SYMBOL/USDC` | `"PURR/USDC"` |
| HIP-3 DEX market | `dexname:SYMBOL` | `"xyz:XYZ100"` |

When you query `all_mids()`, spot markets often appear under **both** the `@{idx}` and `SYMBOL/USDC` forms. Always have a normalization step in your code so you don't double-count.

## Caching Strategy

| Endpoint | Recommended TTL |
|---|---|
| `meta`, `spot_meta`, `perpDexs` | 5 minutes |
| `meta_and_asset_ctxs`, `spot_meta_and_asset_ctxs` | 5–15 seconds |
| `all_mids` | 1–5 seconds |
| `funding_history` | 60 seconds |
| `candles_snapshot` | indefinite for closed bars; 1 second for the current bar |
| `exchangeStatus` | never cache; the whole point is freshness |

These TTLs are starting points. Tighten them if your use case is HFT-adjacent; loosen them if you're running a daily report. The 1200 weight/min budget is the hard ceiling that determines what you can actually afford.
