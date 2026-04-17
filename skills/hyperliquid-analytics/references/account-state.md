# Account State (Schema Reference)

> **Canonical script: `scripts/account_state.py`.** Run that to get a snapshot; don't hand-roll these calls in new scripts. This file documents the underlying Info API endpoints so you can extend `account_state.py` or build a new script if the existing one isn't enough.

---

Current snapshots of an address on Hyperliquid: perpetual positions, spot balances, open orders, sub-accounts, vaults, and staking. Everything in this file is a "what does this account look like *right now*" query. For history, see [history.md](history.md).

All examples assume the following standard prelude (the `load_config()` helper is defined in [getting-started.md](getting-started.md)):

```python
from hyperliquid.info import Info
from hyperliquid.utils import constants
# from _config import load_config  # or paste the helper inline

cfg = load_config()
addr = cfg["hl_user_address"]
info = Info(constants.MAINNET_API_URL, skip_ws=True)
```

`skip_ws=True` is important — without it, the SDK opens a WebSocket on construction, which you don't need for one-shot queries.

Pass `constants.TESTNET_API_URL` instead if `cfg["network"] == "testnet"`; the [getting-started.md](getting-started.md) helpers can be extended to return the right base URL automatically.

## Perpetual Account State

The most important single endpoint. Returns margin summary, every open position, and account-level risk numbers.

```python
state = info.user_state(addr)
```

Return shape (relevant fields):

```python
{
  "marginSummary": {
    "accountValue": "12345.67",         # USDC value of cross margin account
    "totalNtlPos": "8000.0",            # sum of |position notional|
    "totalRawUsd": "9000.0",            # USDC balance, pre-PnL
    "totalMarginUsed": "1200.0",        # initial margin currently locked
  },
  "crossMarginSummary": { ... },        # same shape, only cross positions
  "crossMaintenanceMarginUsed": "600.0",
  "withdrawable": "5000.0",             # how much is freely withdrawable
  "assetPositions": [
    {
      "type": "oneWay",
      "position": {
        "coin": "BTC",
        "szi": "0.5",                   # signed position size; negative = short
        "leverage": {"type": "cross", "value": 10},
        "entryPx": "62000.0",
        "positionValue": "31500.0",     # current notional at mark
        "unrealizedPnl": "500.0",
        "returnOnEquity": "0.0805",
        "liquidationPx": "55800.0",
        "marginUsed": "3150.0",
        "maxLeverage": 40,
        "cumFunding": {                 # lifetime funding for this position
          "allTime": "12.34",
          "sinceOpen": "5.67",
          "sinceChange": "1.23",
        }
      }
    }
  ],
  "time": 1734567890123,                # L1 timestamp (ms)
}
```

**What to compute from this:**

- **Margin utilization** — `float(marginSummary.totalMarginUsed) / float(marginSummary.accountValue)`. Above 0.8 is a warning, above 0.95 is dangerous.
- **Liquidation distance** for each position — `(currentPx - liquidationPx) / currentPx` for longs (flip for shorts). Use `info.all_mids()[coin]` for `currentPx`.
- **Unrealized PnL by position** — already computed in `unrealizedPnl`. But verify against your own calc: `(allMids[coin] - entryPx) * float(szi)` for longs. Mismatches usually mean the SDK was called against a stale state.

**Cost:** weight 2 per call. Cheap enough to poll every few seconds for a small set of addresses.

**HIP-3 DEXes:** if you want a state for a specific HIP-3 DEX (e.g., `xyz`), pass `dex="xyz"`:

```python
xyz_state = info.user_state(addr, dex="xyz")
```

## Spot Balances

```python
spot = info.spot_user_state(addr)
```

Return shape:

```python
{
  "balances": [
    {
      "coin": "USDC",
      "token": 0,           # spot token index
      "hold": "0.0",        # locked in open spot orders
      "total": "1500.0",    # total balance
      "entryNtl": "1500.0", # cost basis for non-USDC tokens
    },
    {"coin": "PURR", "token": 1, "hold": "0.0", "total": "100.5", "entryNtl": "20.1"},
  ]
}
```

**Computing spot PnL:** for non-USDC tokens, current value = `total * spotMid(coin)`, cost basis = `entryNtl`, PnL = current value − cost basis. Spot mids are in `info.all_mids()` keyed by either symbol or `@{tokenIndex}` depending on whether the token has a registered name.

**Cost:** weight 2.

## Open Orders

Two flavors. They differ in detail level — pick `frontend_open_orders` if you want everything the Hyperliquid UI shows, `open_orders` if you just need the bare order list.

```python
basic = info.open_orders(addr)
# [{"coin": "BTC", "side": "B", "limitPx": "60000", "sz": "0.1",
#   "oid": 12345, "timestamp": 1734567890123, "origSz": "0.1"}, ...]

frontend = info.frontend_open_orders(addr)
# Same fields plus: orderType, reduceOnly, isPositionTpsl, triggerPx,
# triggerCondition, isTrigger, tif (time-in-force), cloid (client id)
```

**Cost:** weight 20 (both endpoints).

**Tip:** `frontend_open_orders` is the right default for analytics. The cost is the same and the extra fields (`reduceOnly`, `isTrigger`, etc.) usually matter for understanding what the trader is actually doing.

## Order Status by ID

If you have an `oid`, look it up directly:

```python
result = info.query_order_by_oid(addr, 12345)
# {"status": "order", "order": {"order": {...}, "status": "filled"}}
# or {"status": "unknownOid"}
```

`status` field on the inner `order` dict is one of: `"open"`, `"filled"`, `"canceled"`, `"triggered"`, `"rejected"`, `"marginCanceled"`.

## Sub-Accounts

Some traders use sub-accounts (separate L1 wallets that share the master wallet's identity for fee tier and reporting purposes).

```python
subs = info.query_sub_accounts(addr)
# [{"name": "spot-bot", "subAccountUser": "0x...", "master": "0x..."}, ...]
```

Each sub-account has its own address, so to get the *full* picture for a master wallet, you need to call `user_state` for the master plus each sub-account address. Pattern in [recipes.md](recipes.md), recipe #1 (account health monitor).

## Vaults

If the user has deposited into a Hyperliquid vault, query their equity:

```python
vault_eq = info.user_vault_equities(addr)
# [{"vaultAddress": "0x...", "equity": "1000.0"}, ...]
```

To get vault metadata (strategy, leader, performance), use the SDK's raw POST since the SDK does not wrap `vaultDetails`:

```python
import httpx
resp = httpx.post(
    constants.MAINNET_API_URL + "/info",
    json={"type": "vaultDetails", "vaultAddress": "0x..."},
).json()
```

## Staking (HYPE Delegations)

```python
delegations  = info.user_staking_delegations(addr)
# [{"validator": "0x...", "amount": "100.0", "lockedUntilTimestamp": ...}]

summary      = info.user_staking_summary(addr)
# {"delegated": "100.0", "undelegated": "0.0", "totalPendingWithdrawal": "0.0",
#  "nPendingWithdrawals": 0}

rewards      = info.user_staking_rewards(addr)
# [{"time": ..., "source": "...", "totalAmount": "0.05"}, ...]
```

For delegation history (changes over time, not just current state), see [history.md](history.md).

## Rate Limit Notes

| Query | Weight |
|---|---|
| `user_state`, `spot_user_state`, `query_order_by_oid` | 2 |
| `open_orders`, `frontend_open_orders`, `query_sub_accounts`, `user_vault_equities`, staking endpoints | 20 |

A single comprehensive snapshot of one account (perp state + spot state + open orders + sub-accounts + vaults + staking) costs roughly **2 + 2 + 20 + 20 + 20 + 20 + 20 = 104 weight**. The 1200/min budget means you can take this snapshot for ~11 distinct addresses per minute serially. Use `asyncio` and a semaphore to parallelize without overshooting; see [rate-limits.md](rate-limits.md).

## Endpoints the SDK Does Not Wrap

The Python SDK lags the API by a few endpoint types. As of now, you need raw `httpx` POST for:

- `vaultDetails` (returns vault strategy, leader, share price)
- `predictedFundings` (cross-venue funding rate predictions; see [market-context.md](market-context.md))
- `exchangeStatus` (L1 freshness check)
- `userTwapSliceFillsByTime` (windowed TWAP slice fills; see [history.md](history.md))
- `subAccountSpotState` (combined spot state for a master + all sub-accounts)

Pattern:

```python
import httpx
from hyperliquid.utils import constants

def info_post(payload: dict) -> dict:
    r = httpx.post(constants.MAINNET_API_URL + "/info", json=payload, timeout=10.0)
    r.raise_for_status()
    return r.json()

vault = info_post({"type": "vaultDetails", "vaultAddress": "0x..."})
```

Use this same pattern any time you find an Info type that has no SDK method. Note that some endpoints that *look* unwrapped (e.g., `perpDexs`, `historicalOrders`, `extraAgents`, `portfolio`) are actually wrapped under slightly different snake_case names (`info.perp_dexs()`, `info.historical_orders(addr)`, `info.extra_agents(addr)`, `info.portfolio(addr)`). Check `info.py` in the SDK before reaching for `httpx`.
