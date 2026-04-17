# HyperEVM On-Chain (Schema Reference)

> **Canonical scripts: `scripts/evm_balance.py`, `scripts/evm_logs.py`, `scripts/evm_block.py`.** These use a stdlib-only JSON-RPC client (`scripts/_evm.py`) to avoid web3.py. This file describes the Alchemy RPC surface and HyperEVM conventions — read it when you need to extend a script or add a new one.

---

The HyperEVM side of Hyperliquid: native HYPE balances, ERC20 token holdings, contract event history, and historical state queries. All read-only, all via the standard Ethereum JSON-RPC interface served by Alchemy.

The reason to use Alchemy here rather than the public `rpc.hyperliquid.xyz/evm`:

- **Archival is enabled on every Alchemy plan, including free.** This is what makes `eth_getLogs` over wide block ranges and `eth_call` at historical block heights actually work. The public HL RPC does not advertise archival.
- **The public HL RPC is rate-limited to ~100 req/min per IP.** Alchemy gives you 30M compute units per month on the free tier, which is much more headroom for analytics workloads.
- **Alchemy supports WebSocket subscriptions** (`eth_subscribe`). The public HL RPC does not.

Setup:

```python
from web3 import Web3
# from _config import load_config, alchemy_http_url, alchemy_ws_url  # see getting-started.md

cfg = load_config()
ALCHEMY_HTTP = alchemy_http_url(cfg)
ALCHEMY_WS   = alchemy_ws_url(cfg)

w3 = Web3(Web3.HTTPProvider(ALCHEMY_HTTP))
assert w3.is_connected()
assert w3.eth.chain_id == 999  # HyperEVM mainnet (998 for testnet)
```

## Native HYPE Balance

```python
addr = cfg["hl_user_address"]
wei = w3.eth.get_balance(addr)
hype = w3.from_wei(wei, "ether")
print(f"{hype} HYPE")
```

For a balance at a historical block (archival query):

```python
balance_at_block = w3.eth.get_balance(addr, block_identifier=12345678)
```

This single capability — historical state at any past block — is the main reason to use Alchemy for analytics. The public RPC does not advertise archival support.

## ERC20 Token Balance

Alchemy's `alchemy_getTokenBalances` Enhanced API is **not** confirmed to be supported on HyperEVM (Alchemy's Enhanced API suite is primarily designed for Ethereum mainnet, Base, Polygon, etc.). Use the standard `balanceOf` ABI call instead:

```python
ERC20_ABI = [
    {"name": "balanceOf", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "account", "type": "address"}],
     "outputs": [{"type": "uint256"}]},
    {"name": "decimals", "type": "function", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "uint8"}]},
    {"name": "symbol", "type": "function", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "string"}]},
]

def erc20_balance(w3, token_addr: str, holder: str):
    contract = w3.eth.contract(address=Web3.to_checksum_address(token_addr), abi=ERC20_ABI)
    raw = contract.functions.balanceOf(Web3.to_checksum_address(holder)).call()
    decimals = contract.functions.decimals().call()
    symbol = contract.functions.symbol().call()
    return symbol, raw / (10 ** decimals)

sym, bal = erc20_balance(w3, "0x...", addr)
print(f"{bal} {sym}")
```

**Pattern for many tokens:** if you need balances for a watchlist of N tokens, use `asyncio` to fan out the calls and a semaphore to bound concurrency. Each `balanceOf` call is one `eth_call` (cheap on Alchemy's CU budget). See [recipes.md](recipes.md) recipe #7 for a full portfolio-assembler example.

**Where do I get the token addresses?** For HIP-1 spot tokens, see the `tokens` field in `info.spot_meta()` — each token's address pattern is deterministic (see [cross-layer.md](cross-layer.md) for the system address scheme). For arbitrary HyperEVM project tokens, you'll need to know the contract addresses out of band (project docs, explorer, or a token list).

## Contract Event History (`eth_getLogs`)

This is where Alchemy's archival shines. Pulling historical events over wide block ranges is exactly the kind of workload the public RPC chokes on.

```python
# All ERC20 Transfer events involving `addr` on a specific token, last 100k blocks
TRANSFER_TOPIC = w3.keccak(text="Transfer(address,address,uint256)").hex()
addr_topic = "0x" + addr[2:].lower().zfill(64)  # pad to 32 bytes

current = w3.eth.block_number
logs_in = w3.eth.get_logs({
    "fromBlock": current - 100_000,
    "toBlock": current,
    "address": "0x...",  # the token contract
    "topics": [TRANSFER_TOPIC, None, addr_topic],   # to == addr
})
logs_out = w3.eth.get_logs({
    "fromBlock": current - 100_000,
    "toBlock": current,
    "address": "0x...",
    "topics": [TRANSFER_TOPIC, addr_topic, None],   # from == addr
})
```

Notes:

- `topics[0]` is the event signature. `topics[1]` and `topics[2]` are the indexed parameters (`from` and `to` for ERC20 Transfer). Use `None` to wildcard.
- Pass the holder address as a 32-byte left-padded hex string in the topic filter, not as a regular address.
- For very wide ranges, **chunk by block range** to avoid timeouts. A safe ceiling is around 2000 blocks per call for a high-traffic contract; for low-traffic contracts you can go much wider. If a request times out, halve the range and retry.

### Chunked Log Scan Helper

```python
from web3.exceptions import Web3RPCError

def get_logs_chunked(w3, filter_params: dict, chunk_size: int = 2000):
    """Scan eth_getLogs across a wide block range in safe chunks."""
    start = filter_params["fromBlock"]
    end = filter_params["toBlock"]
    all_logs = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + chunk_size - 1, end)
        try:
            logs = w3.eth.get_logs({**filter_params, "fromBlock": cursor, "toBlock": chunk_end})
            all_logs.extend(logs)
            cursor = chunk_end + 1
        except Web3RPCError as e:
            # Likely "query returned more than X results" — halve the chunk and retry
            if chunk_size <= 100:
                raise
            chunk_size //= 2
    return all_logs
```

## Historical State Queries

Pass `block_identifier` to any read call to get state at that block. The block can be a number, a hash, or a tag (`"latest"`, `"earliest"`).

```python
# Token total supply at a specific block
contract = w3.eth.contract(address="0x...", abi=ERC20_ABI)
supply_then = contract.functions.totalSupply().call(block_identifier=12345678)
supply_now  = contract.functions.totalSupply().call()
print(f"Supply changed: {supply_now - supply_then}")

# Native balance over time — daily snapshots
import datetime
def closest_block_at_time(w3, target_ts_ms: int):
    """Binary search for the block whose timestamp is closest to target."""
    lo, hi = 1, w3.eth.block_number
    while lo < hi:
        mid = (lo + hi) // 2
        if w3.eth.get_block(mid)["timestamp"] * 1000 < target_ts_ms:
            lo = mid + 1
        else:
            hi = mid
    return lo
```

`closest_block_at_time` is a workhorse — many analytics tasks need to ask "what was the state at noon on day X" rather than "what was the state at block N." Cache the results to amortize the binary search cost.

## WebSocket Subscriptions (`eth_subscribe`)

The standard Ethereum subscription API works through Alchemy's WebSocket endpoint. Use this when you want to react to new blocks or new logs in real time.

```python
import asyncio
from web3 import AsyncWeb3, WebSocketProvider

async def watch_new_blocks():
    async with AsyncWeb3(WebSocketProvider(ALCHEMY_WS)) as w3:
        sub_id = await w3.eth.subscribe("newHeads")
        async for msg in w3.socket.process_subscriptions():
            block = msg["result"]
            print("New block:", block["number"], "tx count:", len(block.get("transactions", [])))

# asyncio.run(watch_new_blocks())
```

For filtered logs (e.g., react to every Transfer involving a specific address):

```python
async def watch_transfers(token_addr: str):
    async with AsyncWeb3(WebSocketProvider(ALCHEMY_WS)) as w3:
        TRANSFER_TOPIC = w3.keccak(text="Transfer(address,address,uint256)").hex()
        await w3.eth.subscribe("logs", {"address": token_addr, "topics": [TRANSFER_TOPIC]})
        async for msg in w3.socket.process_subscriptions():
            log = msg["result"]
            print("Transfer log at block", log["blockNumber"], "tx", log["transactionHash"])
```

## Debug & Trace APIs

Available on Alchemy **Growth tier and above** — not on the free tier. Useful for transaction-level analysis (call traces, internal transfers).

```python
trace = w3.provider.make_request(
    "debug_traceTransaction",
    ["0x<txhash>", {"tracer": "callTracer"}]
)
```

Out of scope for most user-data analytics, but worth knowing about when you need to reverse-engineer a specific transaction.

## What Alchemy Does NOT Cover

- **HyperCore (L1 trading) data** — Alchemy is HyperEVM-only. For positions, fills, funding, etc., use the Info API ([account-state.md](account-state.md), [history.md](history.md)).
- **Hyperliquid-specific gRPC streams** (`StreamBlocks`, `StreamFills`, `StreamL2Book`, `StreamL4Book`) — these come from running your own non-validator node or from a third-party (Dwellir, QuickNode).
- **`alchemy_getTokenBalances` and other Enhanced APIs** — not confirmed for HyperEVM as of the audit. Use plain `eth_call` to `balanceOf`.

## Compute Unit Budgeting

| Method | Approx CU cost |
|---|---|
| `eth_blockNumber`, `eth_chainId` | ~10 |
| `eth_getBalance`, `eth_call` | ~26 |
| `eth_getTransactionByHash`, `eth_getTransactionReceipt` | ~15–30 |
| `eth_getLogs` | ~75 base + per-result |
| `eth_getBlockByNumber` (full txs) | ~20 |
| Archival queries (any with `block_identifier`) | 2× the standard cost |
| `debug_traceTransaction` | 309 |

Free tier: **30M compute units / month** (~1M / day). Growth tier: 2x that plus higher rate limit ceilings. For most user-data analytics workloads, free tier is plenty unless you're scanning hundreds of millions of blocks of logs.

## See Also

- [cross-layer.md](cross-layer.md) — how to correlate HyperEVM activity with HyperCore-side ledger events (deposits, withdrawals, bridge flows)
- [rate-limits.md](rate-limits.md) — pacing patterns that work for both Info API and Alchemy
- [Alchemy HyperEVM RPC Quickstart](https://www.alchemy.com/rpc/hyperliquid)
