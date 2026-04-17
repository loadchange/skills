# HyperCore ↔ HyperEVM (Schema Reference)

> **No dedicated script yet** — cross-layer reconciliation is a less common need. Use `scripts/ledger.py` (L1 side) + `scripts/evm_logs.py` (EVM side) and join by timestamp. This file documents the bridge addresses and precompile layout so you can build a dedicated script if the use case becomes frequent.

---

Hyperliquid runs two execution layers that share a single set of wallet addresses but maintain independent state:

- **HyperCore** — the L1 trading layer. Source of perpetual positions, fills, spot balances, funding, and the Info API endpoints.
- **HyperEVM** — the EVM smart-contract layer. Solidity contracts, ERC20 tokens, Alchemy queries.

The two layers interact through a small set of well-known precompiles and system addresses. This file documents the patterns for reading cross-layer flows — bridge transfers, HIP-3 DEX listings, and reconciling the two sides of a single user action.

> Verify the addresses and patterns below against the current Hyperliquid GitBook before relying on them in production. The Hyperliquid team has revised the precompile layout once already; expect drift.
> Primary source: [hyperliquid.gitbook.io/hyperliquid-docs/for-developers/hyperevm/interacting-with-hypercore](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/hyperevm/interacting-with-hypercore) and [/hypercore-less-than-greater-than-hyperevm-transfers](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/hyperevm/hypercore-less-than-greater-than-hyperevm-transfers)

## Address Map

| Component | Address (HyperEVM) | Purpose |
|---|---|---|
| **L1Read precompile range** | `0x000…0800` and following (`0x0801`, `0x0802`, …) | Read HyperCore state from inside a Solidity contract: positions, oracle prices, spot prices, etc. Each precompile in the range serves a different read. |
| **Oracle price precompile** | `0x000…0807` | Returns the HyperCore oracle price for a given asset index |
| **Spot price precompile** | `0x000…0808` | Returns the current spot mid for a given token index |
| **CoreWriter (L1Write)** | `0x3333333333333333333333333333333333333333` | Send transactions from a HyperEVM contract to HyperCore (e.g., place an order on behalf of an EOA) |
| **HyperCore↔HyperEVM transfer system address** | `0x2000000000000000000000000000000000000XXX` where XXX = HIP-1 token index in hex | Each spot token has a deterministic system address. ETH-side transfers to/from this address bridge the asset between HyperCore and HyperEVM. |

For example, a token with HIP-1 index `1385` (`0x569`) lives at `0x2000000000000000000000000000000000000569` on the HyperEVM bridge.

## Tracking Bridge Transfers (HyperCore → HyperEVM)

When a user moves a spot asset from HyperCore (L1) to HyperEVM, two things happen:

1. **HyperCore side**: a `userNonFundingLedgerUpdates` entry appears with `delta.type` indicating a withdrawal/transfer. Available via `info.user_non_funding_ledger_updates(addr, ...)` ([history.md](history.md)).
2. **HyperEVM side**: a transfer event (or native transfer in the case of HYPE) is emitted from the system bridge address to the user's HyperEVM wallet.

To stitch the two sides together for a single user, query both and join on (user, approximate timestamp):

```python
import time, asyncio
from hyperliquid.info import Info
from hyperliquid.utils import constants
from web3 import Web3
# from _config import load_config, alchemy_http_url  # see getting-started.md

cfg = load_config()
addr = cfg["hl_user_address"]
info = Info(constants.MAINNET_API_URL, skip_ws=True)
w3 = Web3(Web3.HTTPProvider(alchemy_http_url(cfg)))

# 1. HyperCore-side: every non-funding ledger update in the last 30 days
start_ms = int((time.time() - 30 * 86400) * 1000)
ledger = info.user_non_funding_ledger_updates(addr, startTime=start_ms)
bridge_l1 = [
    e for e in ledger
    if e["delta"]["type"] in ("deposit", "withdraw")
]

# 2. HyperEVM-side: incoming transfers to the user from any 0x20...XXX system address
TRANSFER_TOPIC = w3.keccak(text="Transfer(address,address,uint256)").hex()
addr_topic = "0x" + addr[2:].lower().zfill(64)

# Find the block at start_ms (use the helper from evm-onchain.md)
# bridge_block_start = closest_block_at_time(w3, start_ms)
bridge_block_start = w3.eth.block_number - 100_000  # placeholder for the example

# This catches all incoming transfers from any system address.
# In production, you'd narrow by `address` (the specific token contract) for cost.
incoming = w3.eth.get_logs({
    "fromBlock": bridge_block_start,
    "toBlock": "latest",
    "topics": [TRANSFER_TOPIC, None, addr_topic],
})

# 3. Join: for each L1 ledger entry, find the closest HyperEVM transfer in time
def join_bridges(l1_entries, evm_logs, tol_seconds=30):
    pairs = []
    for entry in l1_entries:
        l1_time = entry["time"]
        for log in evm_logs:
            block = w3.eth.get_block(log["blockNumber"])
            evm_time = block["timestamp"] * 1000
            if abs(evm_time - l1_time) < tol_seconds * 1000:
                pairs.append((entry, log))
                break
    return pairs

# pairs = join_bridges(bridge_l1, incoming)
```

**Caveats:**

- **Timestamp alignment is fuzzy.** L1 timestamps and HyperEVM block timestamps are within seconds of each other but not identical. A 30-second tolerance window is usually enough.
- **Chunk wide log scans.** `eth_getLogs` over months of HyperEVM blocks can return huge result sets. Use the `get_logs_chunked` helper from [evm-onchain.md](evm-onchain.md).
- **HYPE (native) bridges differently.** Native HYPE doesn't go through an ERC20 Transfer event — track it via `eth_getBlockByNumber` with `full=True` and inspect each transaction's `to` field, or use Alchemy's debug/trace APIs (Growth tier).

## Tracking Bridge Transfers (HyperEVM → HyperCore)

The reverse direction follows the same pattern, just with the addresses swapped:

- **HyperEVM side**: a Transfer event from the user *to* the system bridge address `0x20...XXX`.
- **HyperCore side**: a `userNonFundingLedgerUpdates` entry with `delta.type == "deposit"` (from the user's perspective, the asset arrives on L1).

Note that the L1 ledger's `"deposit"` and `"withdraw"` types refer to the *L1 account's* perspective: a "deposit" means the L1 balance went up.

## Identifying HIP-3 DEXes

Hyperliquid HIP-3 lets third parties launch their own perpetual DEXes that share the same underlying matching engine. Each DEX has its own universe of markets and its own state.

```python
dexes = info.perp_dexs()
# [{"name": "xyz", "full_name": "XYZ Markets", "deployer": "0x..."}, ...]
```

For each DEX, query the universe and the user's state by passing `dex=` to the relevant Info API method:

```python
xyz_meta  = info.meta(dex="xyz")
xyz_state = info.user_state(addr, dex="xyz")
```

Markets in HIP-3 DEXes use the naming convention `dexname:SYMBOL` (e.g., `"xyz:XYZ100"`). Make sure your normalization layer in market-context handling treats these correctly so HIP-3 markets don't collide with the main perpetual universe.

## Reconciling Cost Basis Across Layers

A trader who holds a spot asset on HyperCore, bridges it to HyperEVM, swaps it on a HyperEVM DEX, then bridges the proceeds back, has cost-basis information scattered across both layers:

| Step | State source |
|---|---|
| Bought spot on HyperCore | `info.user_fills_by_time(addr)` (filter `coin == "PURR/USDC"`) |
| Bridged to HyperEVM | `info.user_non_funding_ledger_updates` + corresponding Transfer log |
| Swapped on HyperEVM DEX | `eth_getLogs` against the DEX router contract's events |
| Bridged proceeds back | Mirror of step 2 |
| Sold proceeds on HyperCore | `info.user_fills_by_time(addr)` again |

Reconciliation requires reading from both Info API and Alchemy and joining by timestamp. The exact join keys depend on which DEX router you're tracking. There is no single Hyperliquid-provided endpoint that gives a unified cross-layer cost basis — you must construct it yourself.

A reasonable simplification when accuracy isn't critical: treat each layer's state as independent. Compute "Hyperliquid PnL" purely from `info.user_fills_by_time` and "HyperEVM PnL" from on-chain swap events, and present them side by side. Most analytics use cases don't actually need the unified view, only the per-layer view.

## When Not to Use This File

If your analysis lives entirely on one layer — e.g., a perpetual trader who never touches HyperEVM, or a HyperEVM DeFi user who never trades perps — skip cross-layer entirely. The Info API alone or Alchemy alone is enough. Cross-layer stitching is an analyst-persona need, not a trader-persona need.

## See Also

- [evm-onchain.md](evm-onchain.md) — base patterns for HyperEVM reads
- [history.md](history.md) — `userNonFundingLedgerUpdates` structure
- [Hyperliquid GitBook: Interacting with HyperCore](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/hyperevm/interacting-with-hypercore)
- [Hyperliquid GitBook: HyperCore ↔ HyperEVM transfers](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/hyperevm/hypercore-less-than-greater-than-hyperevm-transfers)
- [HIP-1: Native Token Standard](https://hyperliquid.gitbook.io/hyperliquid-docs/hyperliquid-improvement-proposals-hips/hip-1-native-token-standard)
