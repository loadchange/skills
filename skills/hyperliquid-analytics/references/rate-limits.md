# Rate Limits (Reference)

> **Scripts already pace themselves** — `fills.py` sleeps 50 ms between pagination calls, `leaderboard.py` sleeps every 10 addresses. If you add a new script that does bulk queries, copy these patterns. This file documents the weight costs per endpoint and the shared `HyperliquidAnalyticsClient` async wrapper for production workloads.

---

The two backends this skill uses have very different rate-limit models. Production analytics workloads need to respect both at once.

## Hyperliquid Info API

| Limit | Value |
|---|---|
| **REST budget per IP** | 1200 weight / minute |
| **WebSocket subscriptions per IP** | 1000 |
| **Auth** | None (public) |
| **Throttle response** | HTTP 429 |

The budget is a **token bucket**, not a per-call limit. You can spend all 1200 weight in five seconds and then sit idle for 55, or spread it evenly. Either way, the bucket refills at 20/sec.

### Per-Query Weight Reference

| Endpoint type | Weight |
|---|---|
| `clearinghouseState`, `spotClearinghouseState`, `allMids`, `l2Book`, single order lookups | **2** |
| `openOrders`, `frontendOpenOrders`, `meta`, `metaAndAssetCtxs`, `spotMeta`, `spotMetaAndAssetCtxs`, `userFees`, `historicalOrders`, `candleSnapshot`, `fundingHistory`, `predictedFundings`, `subAccounts`, `vaultDetails`, `userVaultEquities`, staking endpoints | **20** |
| `userFills`, `userFillsByTime`, `userFunding`, `userNonFundingLedgerUpdates`, `userTwapSliceFillsByTime` | **20 + per-row overhead** (the response-size component varies; budget conservatively at ~30 per call) |

Numbers verified against [hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits) at write time. The Hyperliquid team has changed these before; re-check if your code starts hitting unexpected 429s.

### What Fits in 1200/min

- **60 full account snapshots** (perp + spot + open orders + sub-accounts + vaults + staking ≈ 100 weight each) per minute
- **600 cheap polls** (just `clearinghouseState` or `allMids`, weight 2) per minute
- **40 history-page calls** (weight ~30 each) per minute — meaning a 50-page backfill for one address takes ~75 seconds

If your workload exceeds these envelopes, either run from multiple IPs or accept the wall-clock cost.

### Backoff Pattern

```python
import time
import httpx
from httpx import HTTPStatusError

def post_with_backoff(url: str, payload: dict, max_retries: int = 5) -> dict:
    delay = 1.0
    for attempt in range(max_retries):
        try:
            r = httpx.post(url, json=payload, timeout=10.0)
            r.raise_for_status()
            return r.json()
        except HTTPStatusError as e:
            if e.response.status_code != 429 or attempt == max_retries - 1:
                raise
            # Read Retry-After if present, else exponential + jitter
            ra = e.response.headers.get("Retry-After")
            sleep = float(ra) if ra else delay + (delay * 0.1)  # jitter
            time.sleep(sleep)
            delay = min(delay * 2, 30.0)
    raise RuntimeError("unreachable")
```

The exponential factor (2x) is aggressive but appropriate for a public no-auth API where you have no way to negotiate a quota bump.

## Alchemy HyperEVM

| Limit | Free | Growth |
|---|---|---|
| **Compute units / month** | 30M | 60M+ |
| **Throughput** | ~330 CU/sec | ~660 CU/sec |
| **Throttle response** | HTTP 429 |

### CU Cost Reference (HyperEVM)

| Method | Approx CU |
|---|---|
| `eth_blockNumber`, `eth_chainId` | ~10 |
| `eth_getBalance`, `eth_call` | ~26 |
| `eth_getTransactionByHash` / `Receipt` | ~15–30 |
| `eth_getBlockByNumber` (full txs) | ~20 |
| `eth_getLogs` | ~75 base + per-result fee |
| Archival query (any with `block_identifier=N` other than latest) | 2× the standard cost |
| `debug_traceTransaction` (Growth+ only) | ~309 |

These numbers come from Alchemy's published CU table. Re-check at [alchemy.com/pricing](https://www.alchemy.com/pricing) if budgeting for production.

### Block-Range Chunking

`eth_getLogs` over very wide ranges can either time out or get throttled. The fix is **chunking**: scan, say, 2000 blocks at a time, with adaptive halving on errors. Pattern in [evm-onchain.md](evm-onchain.md), `get_logs_chunked`.

For a typical "last N days of contract events" scan:

| Days | Approx blocks (HyperEVM) | Recommended chunk size |
|---|---|---|
| 1 | ~17k | 2000 |
| 7 | ~120k | 2000 |
| 30 | ~520k | 1000 |
| 90 | ~1.5M | 500 |

These numbers assume HyperEVM's ~5-second target block time. Adjust if it changes.

## A Shared Rate-Limit-Aware Client

Production analytics jobs usually need to coordinate calls across both backends. Here's a single-class wrapper that paces both, sharing concurrency limits across them so neither monopolizes the workload's CPU and event-loop time.

```python
import asyncio
import time
from collections import deque
from typing import Any
import httpx
from web3 import AsyncWeb3, AsyncHTTPProvider
from hyperliquid.utils import constants
# from _config import load_config, alchemy_http_url  # see getting-started.md

class HyperliquidAnalyticsClient:
    """
    Async client that paces both the Hyperliquid Info API and Alchemy HyperEVM RPC.
    Use one instance per process. Safe for concurrent use.

    Reads alchemy_api_key and network from ~/.config/hyperliquid-analytics/config.json
    via the load_config() helper from getting-started.md.
    """

    def __init__(self, cfg: dict | None = None, info_weight_budget: int = 1000):
        if cfg is None:
            cfg = load_config()
        self.cfg = cfg
        # Leave 200 weight/minute headroom on the 1200 cap
        base = constants.MAINNET_API_URL if cfg["network"] == "mainnet" else constants.TESTNET_API_URL
        self.info_url = base + "/info"
        self.alchemy_url = alchemy_http_url(cfg)
        self._http = httpx.AsyncClient(timeout=10.0)
        self._w3 = AsyncWeb3(AsyncHTTPProvider(self.alchemy_url))

        # Sliding-window weight tracker for Info API
        self._info_window: deque[tuple[float, int]] = deque()
        self._info_budget = info_weight_budget
        self._info_lock = asyncio.Lock()

        # Concurrency caps — picked so we don't overload either backend
        self._info_sem = asyncio.Semaphore(8)
        self._alchemy_sem = asyncio.Semaphore(16)

    async def info_post(self, payload: dict, weight: int = 20) -> Any:
        """POST to /info with weight-aware pacing."""
        await self._reserve_weight(weight)
        async with self._info_sem:
            for attempt in range(5):
                try:
                    r = await self._http.post(self.info_url, json=payload)
                    r.raise_for_status()
                    return r.json()
                except httpx.HTTPStatusError as e:
                    if e.response.status_code != 429:
                        raise
                    await asyncio.sleep(2 ** attempt)
            raise RuntimeError("info_post exhausted retries")

    async def _reserve_weight(self, weight: int):
        """Block until adding `weight` to the rolling 60s window stays under budget."""
        async with self._info_lock:
            now = time.monotonic()
            cutoff = now - 60.0
            while self._info_window and self._info_window[0][0] < cutoff:
                self._info_window.popleft()
            spent = sum(w for _, w in self._info_window)
            if spent + weight > self._info_budget:
                # Wait until enough weight has aged out of the window
                oldest_ts, _ = self._info_window[0]
                wait = max(0.0, (oldest_ts + 60.0) - now)
                await asyncio.sleep(wait)
            self._info_window.append((time.monotonic(), weight))

    async def get_balance(self, address: str, block: int | str = "latest"):
        async with self._alchemy_sem:
            return await self._w3.eth.get_balance(address, block_identifier=block)

    async def get_logs(self, filter_params: dict):
        async with self._alchemy_sem:
            return await self._w3.eth.get_logs(filter_params)

    async def close(self):
        await self._http.aclose()
```

**Why it's structured this way:**

- **Sliding-window weight tracking** rather than a fixed-rate token bucket: matches Hyperliquid's actual budget model and lets you spend the budget unevenly when bursts are useful.
- **Separate semaphores** for Info and Alchemy so a slow Alchemy call doesn't starve Info workers (and vice versa).
- **Single shared `httpx.AsyncClient`** to reuse connections — important on Info API where every call is a new TCP handshake otherwise.
- **`info_weight_budget=1000`** leaves headroom under the 1200 cap. Don't run right at the ceiling — burst clearing on the L1 side can cause unexpected 429s.

### Usage Example

```python
import asyncio

async def main():
    client = HyperliquidAnalyticsClient()  # reads ~/.config/hyperliquid-analytics/config.json
    try:
        # Fan out: query 50 addresses' perp state in parallel
        addrs = ["0x...", "0x...", ...]
        tasks = [
            client.info_post({"type": "clearinghouseState", "user": a}, weight=2)
            for a in addrs
        ]
        states = await asyncio.gather(*tasks)
        print(f"Pulled {len(states)} states")
    finally:
        await client.close()

asyncio.run(main())
```

50 weight-2 calls = 100 weight, well within budget. The semaphore caps real concurrency so you don't open 50 simultaneous connections.

## Caching Layer

For analytics workloads, an in-process cache for static-ish data pays for itself in seconds:

```python
import time
from functools import wraps

def ttl_cache(ttl_seconds: float):
    def decorator(fn):
        cache = {}
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.monotonic()
            if key in cache:
                cached_at, value = cache[key]
                if now - cached_at < ttl_seconds:
                    return value
            value = await fn(*args, **kwargs)
            cache[key] = (now, value)
            return value
        return wrapper
    return decorator

@ttl_cache(ttl_seconds=300)
async def get_meta(client):
    return await client.info_post({"type": "meta"}, weight=20)
```

Suggested TTLs (also in [market-context.md](market-context.md)):

| Endpoint | TTL |
|---|---|
| `meta`, `spotMeta`, `perpDexs` | 300 s |
| `metaAndAssetCtxs`, `spotMetaAndAssetCtxs` | 10 s |
| `allMids` | 2 s |
| `userFees` (per address) | 60 s |
| Anything else position/state-related | don't cache |

## Operational Tips

1. **Profile before optimizing.** Run a small workload, log each call's weight, sum it. If your weight budget is mostly going to one endpoint, you've found the optimization target.
2. **Cache `meta` aggressively.** It's cheap to fetch but expensive to fetch *repeatedly*. The TTL cache above pays for itself.
3. **Don't poll faster than data changes.** `clearinghouseState` updates every block (~sub-second), but most analytics needs are per-minute or per-hour. Match your poll cadence to your real consumer.
4. **Run from one IP per workload.** The 1200/min limit is per-IP. Splitting one workload across multiple IPs is "supported" in the sense that it works, but each IP is a separate budget — don't accidentally synchronize them and burn 6000/min on the same logical job.
5. **WebSocket subscriptions are free per-message.** If you need very high update rates for a small number of markets, subscribing via the native HL WebSocket (`wss://api.hyperliquid.xyz/ws`) bypasses the REST budget entirely. That's beyond the scope of this skill (this skill is read-pull, not subscribe-push), but it's the right answer when polling becomes painful.
