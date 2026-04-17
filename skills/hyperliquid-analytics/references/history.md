# History (Schema Reference)

> **Canonical scripts: `scripts/fills.py`, `scripts/funding.py`, `scripts/ledger.py`, `scripts/pnl_report.py`, `scripts/orders.py --history`.** These handle pagination, the `delta` nesting quirk on `userFunding`, and `(oid, tid)` deduplication. This file documents the underlying endpoints and their schemas — read it when you need to extend a script or understand what a field means.

---

Pulling fills, funding payments, ledger updates, and historical orders from the Info API. The hard part is **pagination** — Hyperliquid history endpoints return at most ~2000 rows per call, and the only reliable cursor is timestamp.

All examples assume the standard imports from [account-state.md](account-state.md).

## Fills

Two endpoints, both return user fill records but with different time semantics.

### `user_fills` — most recent 2000

```python
fills = info.user_fills(addr)
# [{"coin": "BTC", "px": "62000.0", "sz": "0.1", "side": "B", "time": ...,
#   "startPosition": "0.0", "dir": "Open Long", "closedPnl": "0.0",
#   "hash": "0x...", "oid": 12345, "crossed": True, "fee": "0.62",
#   "tid": 999, "feeToken": "USDC", "builderFee": "0.0"}, ...]
```

Returns the last 2000 fills, latest first. Useful for "what just happened" — for backfilling history, use the windowed variant below.

### `user_fills_by_time` — windowed pull

```python
fills = info.user_fills_by_time(addr, start_time=ms_since_epoch, end_time=None)
```

Returns fills in the time window, capped at ~2000 per call. To pull more than 2000, walk backwards by setting `end_time` to one less than the oldest fill's timestamp:

```python
import time

def fetch_all_fills(info, addr, start_ms: int):
    """Pull every fill from start_ms to now. Returns a list (possibly empty)."""
    all_fills = []
    end_ms = None  # None means "up to now"
    while True:
        page = info.user_fills_by_time(addr, start_time=start_ms, end_time=end_ms)
        if not page:
            break
        all_fills.extend(page)
        if len(page) < 2000:
            break  # last page
        # Walk the cursor: the oldest fill in this page becomes the new ceiling
        oldest = min(f["time"] for f in page)
        if oldest <= start_ms:
            break
        end_ms = oldest - 1
        time.sleep(0.05)  # be polite; weight is 20+ per call
    # Latest first → oldest first, deduplicate on (oid, tid)
    seen = set()
    deduped = []
    for f in sorted(all_fills, key=lambda x: x["time"]):
        key = (f["oid"], f["tid"])
        if key not in seen:
            seen.add(key)
            deduped.append(f)
    return deduped
```

Why deduplicate: when paginating, the boundary fill (whose timestamp equals the cursor) can show up in two consecutive pages. The `(oid, tid)` pair is unique across all fills.

**Cost:** weight 20 per call plus per-row overhead. A 6-month backfill for an active trader can easily be 50+ calls. Budget your weight before kicking it off.

**Important fields:**

| Field | Meaning |
|---|---|
| `dir` | Human-readable direction: `"Open Long"`, `"Close Long"`, `"Open Short"`, `"Close Short"`. Convenient for filtering opens vs closes. |
| `closedPnl` | Realized PnL **only on close fills**. Sum this across closes to get realized PnL. |
| `startPosition` | Position size before the fill. Useful for reconstructing the position trajectory. |
| `crossed` | True if the fill was crossing (took liquidity). False = made liquidity. |
| `fee` / `feeToken` | Fee paid in the listed token. Watch for `feeToken="USDC"` vs token-denominated. |
| `builderFee` | Extra fee paid to a builder code (Hyperliquid's affiliate scheme). |
| `tid` | Trade ID, unique within Hyperliquid. Use as a deduplication key. |

## Funding Payments

```python
funding = info.user_funding_history(addr, startTime=ms_since_epoch, endTime=None)
# [{"time": ..., "coin": "BTC", "usdc": "-1.23", "szi": "0.5", "fundingRate": "0.000005"}, ...]
```

`usdc` is signed: negative means the user *paid* funding, positive means they received. Sum these to get total funding cost.

**Pagination:** same pattern as fills — walk backwards by setting `endTime` to the oldest row's `time - 1`.

**Cost:** weight 20 per call.

## Non-Funding Ledger Updates

Deposits, withdrawals, transfers, vault deposits/withdrawals, sub-account transfers, rebates, and any other balance change that is not a fill or a funding payment.

```python
ledger = info.user_non_funding_ledger_updates(addr, startTime=ms_since_epoch, endTime=None)
# [{"time": ..., "hash": "0x...", "delta": {"type": "deposit", "usdc": "1000.0"}}, ...]
```

`delta.type` values you'll see in practice:

- `deposit` — bridge deposit (HyperEVM → HyperCore or external)
- `withdraw` — bridge withdrawal
- `accountClassTransfer` — transfer between perp and spot account classes
- `subAccountTransfer` — transfer between master and sub-account
- `vaultCreate`, `vaultDeposit`, `vaultWithdraw` — vault activity
- `rewardsClaim` — staking or other rewards claim
- `internalTransfer` — direct USDC transfer between Hyperliquid users

For bridge tracking and reconciling against HyperEVM-side activity, see [cross-layer.md](cross-layer.md).

## Historical Orders

Order lifecycle records — every order ever placed by an address, with their final status. Useful for reconstructing strategy behavior (cancel rates, fill rates).

```python
orders = info.historical_orders(addr)
# [{"order": {"coin": ..., "side": ..., "limitPx": ..., "sz": ..., "oid": ..., ...},
#   "status": "filled" | "canceled" | "triggered" | ...,
#   "statusTimestamp": ...}, ...]
```

Cost: weight 20.

This endpoint returns at most 2000 historical orders. There is no time-windowed variant, so for accounts with very long histories you may not see the full record. Cross-check by counting `dir == "Open *"` fills from `user_fills_by_time` against the order count.

## Fee Tier and Volume

```python
fees = info.user_fees(addr)
# {"dailyUserVlm": [{"date": "2025-12-30", "userCross": ..., "userAdd": ..., ...}, ...],
#  "feeSchedule": {...},
#  "userCrossRate": "0.00045",
#  "userAddRate": "0.00015",
#  "activeReferralDiscount": "0.04",
#  "trial": null,
#  "feeTrialReward": "0.0",
#  "nextTrialAvailableTimestamp": null}
```

`userCrossRate` and `userAddRate` are the **current** taker and maker fee rates respectively, with referral discounts already applied. `dailyUserVlm` is the rolling 14-day volume breakdown that determines fee tier.

**Cost:** weight 20.

## TWAP Slice Fills

If a trader uses TWAP orders, each TWAP execution generates "slice fills" — synthetic fills that aggregate the slices of a parent TWAP. These are tracked separately from regular fills.

```python
twap_fills = info.user_twap_slice_fills(addr)
# Same shape as fills, but each entry has an extra "twapId" field
```

For windowed pulls (the SDK does not wrap `userTwapSliceFillsByTime` directly), use raw `httpx`:

```python
import httpx
from hyperliquid.utils import constants

twap_fills_windowed = httpx.post(
    constants.MAINNET_API_URL + "/info",
    json={
        "type": "userTwapSliceFillsByTime",
        "user": addr,
        "startTime": ms_since_epoch,
        # "endTime": ...,  # optional
    },
    timeout=10.0,
).json()
```

Pagination follows the same backward-walk pattern as `user_fills_by_time`. Cost: weight 20.

## Worked Example: 6-Month Fill History to DataFrame

```python
import time
import pandas as pd
from hyperliquid.info import Info
from hyperliquid.utils import constants
# from _config import load_config  # see getting-started.md

cfg = load_config()
addr = cfg["hl_user_address"]
info = Info(constants.MAINNET_API_URL, skip_ws=True)

start_ms = int((time.time() - 180 * 86400) * 1000)
fills = fetch_all_fills(info, addr, start_ms)  # function from earlier in this file

df = pd.DataFrame(fills)
df["time"] = pd.to_datetime(df["time"], unit="ms")
df["px"] = df["px"].astype(float)
df["sz"] = df["sz"].astype(float)
df["fee"] = df["fee"].astype(float)
df["closedPnl"] = df["closedPnl"].astype(float)
df["notional"] = df["px"] * df["sz"]

print(f"Pulled {len(df)} fills across {df['coin'].nunique()} coins")
print(f"Realized PnL: ${df['closedPnl'].sum():.2f}")
print(f"Total fees:   ${df['fee'].sum():.2f}")
print(f"Net (realized PnL − fees): ${(df['closedPnl'].sum() - df['fee'].sum()):.2f}")

df.to_parquet(f"fills_{addr[:8]}.parquet")
```

This is the foundation of most user-data analytics. From here you can:

- Group by `coin` for per-market PnL
- Group by day for a daily PnL series
- Filter `crossed == False` for maker-only execution analysis
- Join with funding history (next section) for full cost attribution

## Pagination Caveats

1. **Boundary duplicates** — always dedupe on a stable unique key (`(oid, tid)` for fills, `(time, hash)` for ledger).
2. **Max windows** — Hyperliquid's docs do not document an explicit max time window per call, but in practice the response cap is ~2000 rows. Use the cursor pattern; do not try to pull a year in one call.
3. **Total cap on `user_fills`** — the non-windowed `user_fills` is capped around 10,000 most-recent fills. For deep history, always use `user_fills_by_time`.
4. **Wall-clock vs L1 time** — Hyperliquid timestamps are in L1 milliseconds (which usually track wall-clock closely but not perfectly). Don't compare `time` fields from Hyperliquid against, say, your local Python `time.time()` if precision matters; check `exchangeStatus` for the L1 clock.
5. **Rate limits** — see [rate-limits.md](rate-limits.md). A 6-month backfill for an active trader is easily 50+ calls, which is 1000+ weight, which is most of your minute budget.
