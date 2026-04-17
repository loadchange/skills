---
name: hyperliquid-analytics
description: >
  Query and analyze Hyperliquid account/address data by running pre-built
  Python scripts that use the official hyperliquid-python-sdk (HyperCore
  data) and stdlib-only JSON-RPC against Alchemy (HyperEVM data). Covers
  perpetual positions, margin, spot balances, open and historical orders,
  fill history with PnL attribution, funding payments, fees, sub-accounts,
  vault and staking positions, rolling volume, per-coin and per-day PnL
  breakdowns, multi-address leaderboards, market metadata, funding rate
  history, and HyperEVM on-chain reads (native HYPE balance, ERC20 holdings,
  contract event scanning, archival block queries). Use this skill whenever
  the user asks about analyzing a Hyperliquid wallet, trader, or address —
  pulling positions, computing PnL over any window, paginating deep fill
  history, building a portfolio view, screening cost components (funding,
  fees), running on-chain analytics on HyperEVM contracts, or backfilling
  user trade history for backtesting. Triggers on phrases like "hyperliquid
  positions", "hyperliquid PnL", "hyperliquid fills", "funding paid on
  hyperliquid", "analyze hyperliquid wallet", "hyperliquid portfolio",
  "hyperliquid trader leaderboard", "HyperEVM token holdings", "HyperEVM
  transaction history", "hyperliquid backtest data", "hyperliquid account
  health", "hyperliquid fee tier", "24h summary for this address", and
  similar. Distinct from the sibling `hyperliquid` skill (which covers
  Dwellir-specific infrastructure such as L4 order book, gRPC streaming,
  and 100-level orderbook depth).
---

# Hyperliquid User Data & Analytics

This skill ships **pre-built, tested Python scripts** that answer the common questions about a Hyperliquid address. Do not write new scripts on the fly when one of the bundled scripts already answers the question — invoke the existing script, parse its JSON output, and report the finding. Only modify a script when you hit an error that a code change would fix.

Why scripts instead of inline code:
1. **Deterministic** — same args produce the same API calls and the same output shape every time
2. **Auditable** — the security stance (official SDK + stdlib only, no third-party Python packages) is enforced at the script level, not re-invented per conversation
3. **Fast and cheap** — no re-deriving the pagination loop, the funding `delta`-nesting quirk, or the per-call weight budget on every request

## Runtime Stack

| Layer | What it is | Why this and not alternatives |
|---|---|---|
| **Python runtime & deps** | [`uv`](https://docs.astral.sh/uv/) + PEP 723 inline script metadata | Every script declares its deps inline; `uv run` auto-installs into an isolated, cached per-script env. Zero system Python pollution. |
| **HyperCore reads** | [`hyperliquid-python-sdk`](https://github.com/hyperliquid-dex/hyperliquid-python-sdk) (official) via `Info` class | Only runtime dep. The API type strings, wrapping, and response shapes are all handled by the official SDK. |
| **HyperEVM reads** | Python stdlib (`urllib`, `json`, `hashlib`) against Alchemy's HyperEVM RPC | No web3.py, no httpx, no requests — all supply-chain risk mitigation. A pure-Python Keccak-256 lives in `scripts/_evm.py` so function selectors can be computed without pulling in a crypto dep. |
| **No networking sinks** | — | Scripts only read from `api.hyperliquid.xyz` and Alchemy. They never write, sign, or upload. |

## Security Stance

The user explicitly requires that scripts **only import from the Python standard library and the official `hyperliquid-python-sdk`**. Do not add `web3`, `httpx`, `requests`, `pandas`, or any other third-party package to any script's PEP 723 `dependencies` list without first asking. The rationale is supply-chain minimization: every extra package is a potential backdoor vector, and the skill can do its job without them. If you genuinely need something stdlib can't provide, surface it and ask before adding.

## First-Run Setup (three steps, idempotent)

When this skill is invoked in a fresh environment:

1. **Ensure `uv` is installed.** Check with `command -v uv`. If missing:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
   This installs `uv` to `~/.local/bin/uv`. After install, `export PATH="$HOME/.local/bin:$PATH"` for the current session.

2. **Ensure the config file exists** at `~/.config/hyperliquid-analytics/config.json`. If missing, run:
   ```bash
   uv run scripts/bootstrap_config.py
   ```
   This writes a skeleton with empty `alchemy_api_key`, `hl_user_address`, and `network: "mainnet"`. Tell the user where the file is and what fields it needs, then offer to (a) collect values interactively and write them back, or (b) let them edit the file manually.

3. **Skip the Alchemy key check for HyperCore-only tasks.** The Info API (used by all non-`evm_*` scripts) requires no auth. If the user's task is purely about positions/fills/funding/PnL, an empty `alchemy_api_key` is fine — the relevant scripts only validate it when needed (via `load_config(require_alchemy=True)`).

You can shortcut all three with the one-liner:
```bash
bash scripts/install.sh
```

## Canonical Invocation Pattern

Every script uses the same CLI shape: optional address as the first positional arg (falls back to `hl_user_address` from config), plus flags. Output defaults to human-readable text; pass `--json` for machine-readable output (useful when the caller is Claude parsing the result).

```bash
uv run scripts/<name>.py [address] [flags]

# or via shebang if chmod +x was run:
./scripts/<name>.py [address] [flags]
```

The shebang (`#!/usr/bin/env -S uv run --script`) handles everything: uv reads the PEP 723 block from the file, creates or reuses a cached venv with just the declared deps, and runs the script.

First run per-script: ~10-20 s (cold install of the SDK into uv's cache).
Every subsequent run of that script, or any other script that declares the same deps: ~1-2 s.

## Script Catalog

Pick the right script for the question. When in doubt, lean toward the more specific match — don't use `daily_summary.py` when the user asked for positions only (that's `account_state.py`, faster and cheaper).

### HyperCore account state

| If the user asks about... | Run this |
|---|---|
| Current positions, margin, liq distance, fee tier, open orders in one shot | `scripts/account_state.py <addr>` |
| Spot balances only | `scripts/account_state.py <addr>` (included in the output) |
| Open orders (rich schema) / order lookup by oid / historical orders | `scripts/orders.py <addr> --open` / `--oid N` / `--history` |
| Current fee tier and 14-day volume breakdown | `scripts/fee_tier.py <addr>` |

### HyperCore history (pagination-aware)

| If the user asks about... | Run this |
|---|---|
| "Summarize the last N hours / day of trading for this address" | `scripts/daily_summary.py <addr> --hours 24` |
| Raw fills over a time window or full account history | `scripts/fills.py <addr> --hours 24` / `--days 30` / `--all` |
| Write fills to CSV or JSON for external analysis | `scripts/fills.py <addr> --all --out fills.csv` |
| User funding payments (with correct `delta.usdc` sign handling) | `scripts/funding.py <addr> --days 7` |
| Deposits, withdrawals, perp↔spot transfers, vault ops, internal transfers | `scripts/ledger.py <addr> --days 30 [--type deposit]` |
| Multi-day PnL broken down by coin and by day (for a PnL curve) | `scripts/pnl_report.py <addr> --days 7` |

### Market context (for enrichment)

| If the user asks about... | Run this |
|---|---|
| All perp universe metadata, maybe with live contexts (OI, funding, volume) | `scripts/market_meta.py [--live] [--coin BTC] [--dex xyz]` |
| Spot universe instead | `scripts/market_meta.py --spot [--live]` |
| Current mid prices across all markets (cheap weight=2 snapshot) | `scripts/mids.py [--filter BTC,ETH,HYPE]` |
| Market-wide funding rate history for a specific coin | `scripts/funding_rates.py BTC --days 7` |

### Multi-address analysis

| If the user asks about... | Run this |
|---|---|
| Rank a list of addresses by account value / notional / margin util | `scripts/leaderboard.py 0xa 0xb 0xc --sort notional --top 10` |
| Leaderboard from a file of addresses | `scripts/leaderboard.py --file addrs.txt` |

### HyperEVM (requires `alchemy_api_key` in config)

| If the user asks about... | Run this |
|---|---|
| Native HYPE balance and optional ERC20 token balances | `scripts/evm_balance.py <addr> [--token 0x... | --tokens-file tokens.txt]` |
| Historical balance at a specific block (archival query) | `scripts/evm_balance.py <addr> --block 12345678` |
| Scan Transfer/Swap/etc events on a contract over a block range | `scripts/evm_logs.py --contract 0x... --event Transfer --last-blocks 50000` |
| HyperEVM connectivity check / latest block info | `scripts/evm_block.py` |

### Config & setup

| Purpose | Script |
|---|---|
| Create or inspect the config file | `scripts/bootstrap_config.py` (pass `--show` to cat it, `--force` to overwrite) |
| One-shot setup (install uv if missing, bootstrap config) | `bash scripts/install.sh` |

### Shared helper modules (do not run directly)

These are imported by the scripts above; you don't run them.

- `scripts/_config.py` — `load_config()`, `get_info()`, `alchemy_http_url()`, `resolve_address()`
- `scripts/_format.py` — number formatters, tables, timestamp helpers, `emit()`
- `scripts/_evm.py` — stdlib-only JSON-RPC client for HyperEVM, including a pure-Python Keccak-256 so we don't need `pycryptodome` or `web3.py`

## Workflow When a Request Arrives

1. **Identify which script answers the user's question** using the catalog above. If two scripts could answer it, prefer the more specific one.

2. **Check config file exists.** If `~/.config/hyperliquid-analytics/config.json` is missing, run `uv run scripts/bootstrap_config.py` first and tell the user.

3. **Run the script via `uv run` or the direct shebang.** Pass the address either inline (positional) or rely on the config default. Use `--json` when the raw data is what you need for further computation; use the default text output when you're going to paraphrase it for a human.

4. **Parse the output and present it** in the user's requested format (usually Chinese markdown summary for this user's preference, English otherwise).

5. **If the script errors:**
   - Read the traceback. If it's a real bug (wrong field name, bad pagination, SDK method drift), **modify the script** to fix it rather than writing a new one inline. The fix then benefits every future invocation.
   - If it's an API limitation (rate limit, 422 unsupported type), retry with backoff or fall back to a narrower window.
   - If it's a config problem (missing key, bad address), tell the user exactly which field to fill in.

6. **If the user's question isn't covered by any script**, consider whether you should add one to `scripts/` rather than writing inline code. The bar: if the same analysis will plausibly be requested again, it's worth a script.

## Known Schema Gotchas (learned the hard way)

These are the bits of the Hyperliquid API that are easy to get wrong. All bundled scripts already handle them:

- **`userFunding` nests data under `delta`.** Each entry looks like `{"time": ms, "hash": "0x...", "delta": {"type": "funding", "coin": ..., "usdc": signed_str, ...}}`. Reading `entry["usdc"]` directly gives `None` / zero — you must go through `entry["delta"]["usdc"]`. `funding.py` and `daily_summary.py` handle this correctly.
- **`usdc` on funding entries is signed from the user's perspective.** Negative = user paid, positive = user received. Scripts that talk about "funding paid" flip the sign so positive means "cost to user".
- **`userFills` and `userFillsByTime` are capped at ~2000 rows per call.** For deeper windows, paginate backwards via `end_time = oldest_fill_time - 1`. `fills.py` and `pnl_report.py` implement this correctly and dedupe on `(oid, tid)` to remove boundary duplicates.
- **`dir` values include flip directions.** Beyond `"Open Long"`, `"Close Long"`, `"Open Short"`, `"Close Short"`, the API also emits `"Long > Short"` and `"Short > Long"` when a single fill flips the position side. `daily_summary.py` counts these explicitly.
- **Alchemy Enhanced APIs (`alchemy_getTokenBalances`, `alchemy_getAssetTransfers`) are NOT confirmed on HyperEVM.** `evm_balance.py` uses plain `eth_call` against each token's `balanceOf` — slower but verified to work.
- **Some SDK methods use camelCase kwargs** (e.g., `user_funding_history(user, startTime, endTime)`) while others use snake_case (`user_fills_by_time(user, start_time, end_time)`). The bundled scripts have the right argument names; if you add a new script, double-check against `info.py` in the SDK source rather than guessing.

## Documentation Links

- Hyperliquid API: [hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api)
- Info endpoint: [hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint)
- Rate limits: [hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits)
- Python SDK: [github.com/hyperliquid-dex/hyperliquid-python-sdk](https://github.com/hyperliquid-dex/hyperliquid-python-sdk)
- uv docs: [docs.astral.sh/uv/](https://docs.astral.sh/uv/)
- PEP 723 inline script metadata: [peps.python.org/pep-0723/](https://peps.python.org/pep-0723/)
- Alchemy HyperEVM: [alchemy.com/rpc/hyperliquid](https://www.alchemy.com/rpc/hyperliquid)
- HyperEVM precompiles: [hyperliquid.gitbook.io/hyperliquid-docs/for-developers/hyperevm/interacting-with-hypercore](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/hyperevm/interacting-with-hypercore)

For schema details on individual Info endpoints and the HyperEVM precompile addresses, see the files under `references/`. Those files are docs, not code — they describe what the API returns, which is useful when you're extending a script or writing a new one.
