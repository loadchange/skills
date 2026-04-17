# Getting Started (Schema Reference)

> **Scripts are the canonical execution path.** To use this skill, run `bash scripts/install.sh` once, then invoke scripts via `uv run scripts/<name>.py`. This file is kept for extension / debugging reference — it describes the config format and install flow. The live code lives in `scripts/`.

---

Set up the config file, install dependencies, and run a smoke test that exercises both the Info API and Alchemy in 30 seconds.

## Configuration File

This skill reads everything from a single JSON file:

```
~/.config/hyperliquid-analytics/config.json
```

The only true secret is `alchemy_api_key`. The Hyperliquid Info API requires no auth.

### Bootstrap

If the file does not exist, create the directory and write the skeleton:

```bash
mkdir -p ~/.config/hyperliquid-analytics
cat > ~/.config/hyperliquid-analytics/config.json <<'EOF'
{
  "alchemy_api_key": "",
  "hl_user_address": "",
  "network": "mainnet",
  "_help": {
    "alchemy_api_key": "Get a key at https://www.alchemy.com/ — create an app on the Hyperliquid network. Free tier (30M CU/month) is enough for most analytics workloads.",
    "hl_user_address": "The Hyperliquid wallet address you want to analyze. Any public address; not a secret.",
    "network": "mainnet or testnet."
  }
}
EOF
```

Then open the file in your editor and fill in the two empty values.

> When this skill is triggered through Claude Code and the file is missing, Claude is instructed (in [SKILL.md](../SKILL.md)) to bootstrap it for you and either ask interactively for the values or wait for you to edit the file.

### Schema

| Field | Required | Type | Description |
|---|---|---|---|
| `alchemy_api_key` | yes | string | Your Alchemy API key. Sole secret in the file. |
| `hl_user_address` | yes | string | The wallet address being analyzed (`0x...` checksummed or lowercase, both work). |
| `network` | yes | `"mainnet"` or `"testnet"` | Selects both the Info API and the Alchemy subdomain. |
| `_help` | no | object | Free-form documentation. Ignored by code. |

You can extend the file with optional fields your own scripts use (e.g. a `watchlist_addresses` array). The `load_config()` helper returns the full dict, so anything you put in is available.

### Where to Get an Alchemy Key

1. Sign up at [alchemy.com](https://www.alchemy.com/)
2. Dashboard → **Create new app** → Chain: **Hyperliquid**, Network: **Mainnet**
3. App page → **API Key** button → copy the key into `alchemy_api_key`

Free tier gives you 30M compute units per month, which is enough for everything in [evm-onchain.md](evm-onchain.md) and the recipes in [recipes.md](recipes.md) at any reasonable analyst pace. See [rate-limits.md](rate-limits.md) for budgeting.

## Python Dependencies

```bash
pip install hyperliquid-python-sdk web3 httpx
```

| Package | Used for |
|---|---|
| `hyperliquid-python-sdk` | The official Hyperliquid Python SDK. Provides `hyperliquid.info.Info` for typed access to most Info API endpoints. |
| `web3` | EVM client for HyperEVM reads via Alchemy. |
| `httpx` | Used as a fallback when the SDK does not wrap a particular Info API endpoint type, or for async fan-out. |

Optional: `pandas` for tabular analysis in the recipes.

## The `load_config()` Helper

Every example in this skill imports this helper. Define it once and import it from your scripts, or copy-paste it inline at the top of single-file scripts:

```python
import json
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "hyperliquid-analytics" / "config.json"


def load_config() -> dict:
    """Load the user's hyperliquid-analytics config.

    Raises FileNotFoundError if the config file is missing entirely, and
    ValueError if required fields are empty. Both errors are intentional —
    they make 'not configured yet' loud, not silent.
    """
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Config not found at {CONFIG_PATH}.\n"
            f"Create it with:\n"
            f"  mkdir -p {CONFIG_PATH.parent}\n"
            f"  echo '{{}}' > {CONFIG_PATH}\n"
            f"then add keys: alchemy_api_key, hl_user_address, network."
        )
    cfg = json.loads(CONFIG_PATH.read_text())
    for required in ("alchemy_api_key", "hl_user_address", "network"):
        if not cfg.get(required):
            raise ValueError(f"'{required}' is empty in {CONFIG_PATH}")
    return cfg


def alchemy_http_url(cfg: dict) -> str:
    return f"https://hyperliquid-{cfg['network']}.g.alchemy.com/v2/{cfg['alchemy_api_key']}"


def alchemy_ws_url(cfg: dict) -> str:
    return f"wss://hyperliquid-{cfg['network']}.g.alchemy.com/v2/{cfg['alchemy_api_key']}"
```

These three functions are the only ones every other reference assumes are in scope. Keep them in a `_config.py` next to your scripts, or paste them at the top of any standalone snippet.

## Smoke Test

Save as `smoke_test.py`, run with `python smoke_test.py`:

```python
from hyperliquid.info import Info
from hyperliquid.utils import constants
from web3 import Web3

# (paste load_config / alchemy_http_url here, or import them from _config.py)

cfg = load_config()
addr = cfg["hl_user_address"]

# 1. HyperCore (L1 trading) read via the official Python SDK
info = Info(constants.MAINNET_API_URL, skip_ws=True)
state = info.user_state(addr)
print("Account value:", state["marginSummary"]["accountValue"])
print("Open positions:", len(state["assetPositions"]))

# 2. HyperEVM read via Alchemy
w3 = Web3(Web3.HTTPProvider(alchemy_http_url(cfg)))
print("HyperEVM block:", w3.eth.block_number)
print("Chain ID:", w3.eth.chain_id)  # 999 = HyperEVM mainnet
print("Native HYPE balance:", w3.from_wei(w3.eth.get_balance(addr), "ether"))
```

Expected: five lines printed. If the address has no Hyperliquid activity, `Account value` will be `"0.0"` and `Open positions` will be `0` — that's normal.

If `load_config()` raises:

- `FileNotFoundError` → run the bootstrap snippet above
- `ValueError: 'alchemy_api_key' is empty` → open `~/.config/hyperliquid-analytics/config.json` and fill in the empty value(s)

## Decision Flow: Info API vs Alchemy

```
Question: where does the data I want live?

  ├── HyperCore L1 trading layer
  │     (positions, fills, orders, funding, fees, staking, vault equities)
  │     ──► Info API   (info.user_state, info.user_fills, ...)
  │
  ├── HyperEVM smart contract layer
  │     (HYPE balance, ERC20 holdings, contract events, transaction history)
  │     ──► Alchemy    (w3.eth.get_balance, w3.eth.get_logs, ...)
  │
  └── Both (e.g., end-to-end portfolio for a wallet that uses both layers)
        ──► Both — fan out with asyncio.gather; see recipes.md
```

A useful rule of thumb: anything that involves trading (perp positions, margin, fills) is **HyperCore** and uses the Info API. Anything that involves Solidity or token contracts is **HyperEVM** and uses Alchemy. The two layers share the same wallet address, but they are independent state.

## Security Notes

- The config file is **not** committed to your repo. If you initialized one inside a project, add `~/.config/hyperliquid-analytics/config.json` to `.gitignore` — though since it lives in your home directory, this is rarely a problem.
- To rotate a leaked Alchemy key: Alchemy dashboard → app → "Revoke and rotate" → paste the new key into `config.json`
- Alchemy keys can be IP-allowlisted from the app's settings page — turn this on for any key used from a fixed server
- The Hyperliquid Info API is anonymous; no rotation needed
- Never paste your `alchemy_api_key` into a chat, an issue, or a `.md` file in a public repo

## What's Next

- Read [account-state.md](account-state.md) to learn the Info API endpoints for current account snapshots.
- Read [history.md](history.md) for paginated history (fills, funding, ledger).
- Read [evm-onchain.md](evm-onchain.md) for the HyperEVM side via Alchemy.
- Jump to [recipes.md](recipes.md) for end-to-end runnable scripts.
