"""Shared configuration loader for hyperliquid-analytics scripts.

Every script in this directory imports from this module rather than
re-implementing config loading. The single source of truth lives at:

    ~/.config/hyperliquid-analytics/config.json

Dependencies: Python stdlib + hyperliquid-python-sdk (the OFFICIAL SDK).
No third-party packages — this is intentional. The only runtime dep is
the official Hyperliquid SDK, managed by uv via PEP 723 inline metadata
at the top of each runnable script.

This module is imported by other scripts, so it has no inline metadata
or shebang of its own.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

CONFIG_PATH = Path.home() / ".config" / "hyperliquid-analytics" / "config.json"

SKELETON: dict[str, Any] = {
    "alchemy_api_key": "",
    "hl_user_address": "",
    "network": "mainnet",
    "_help": {
        "alchemy_api_key": (
            "Get a key at https://www.alchemy.com/ — create an app on the "
            "Hyperliquid network. Free tier (30M CU/month) is enough. "
            "Required ONLY for HyperEVM scripts (evm_*.py)."
        ),
        "hl_user_address": (
            "Default Hyperliquid address to analyze. Any public 0x address. "
            "Scripts accept an explicit address as the first positional arg "
            "and override this default."
        ),
        "network": "mainnet or testnet — affects both Info API base URL and Alchemy subdomain.",
    },
}


def load_config(
    require_alchemy: bool = False,
    require_address: bool = False,
) -> dict[str, Any]:
    """Load config from the canonical path.

    Raises SystemExit with a helpful message if the file is missing or
    if a required field is empty. Use require_alchemy/require_address to
    enforce script-specific requirements at the entrypoint.
    """
    if not CONFIG_PATH.exists():
        sys.exit(
            f"Config not found at {CONFIG_PATH}\n"
            f"Run: uv run scripts/bootstrap_config.py"
        )
    try:
        cfg = json.loads(CONFIG_PATH.read_text())
    except json.JSONDecodeError as e:
        sys.exit(f"Config at {CONFIG_PATH} is not valid JSON: {e}")

    if "network" not in cfg or cfg["network"] not in ("mainnet", "testnet"):
        sys.exit(f"network must be 'mainnet' or 'testnet' in {CONFIG_PATH}")

    if require_alchemy and not cfg.get("alchemy_api_key"):
        sys.exit(
            f"alchemy_api_key is empty in {CONFIG_PATH}\n"
            f"This script needs an Alchemy key. Get one at https://www.alchemy.com/"
        )
    if require_address and not cfg.get("hl_user_address"):
        sys.exit(
            f"hl_user_address is empty in {CONFIG_PATH}\n"
            f"Either fill it in or pass an address as the first positional argument."
        )
    return cfg


def get_info(cfg: dict[str, Any]):
    """Return an Info client from the official SDK, configured for the network."""
    # Imported lazily so scripts that don't need HyperCore (e.g., evm_block.py)
    # don't trigger the SDK import path.
    try:
        from hyperliquid.info import Info
        from hyperliquid.utils import constants
    except ImportError:
        sys.exit(
            "hyperliquid-python-sdk is not installed.\n"
            "Run scripts via uv so the official SDK is auto-installed per PEP 723:\n"
            "    uv run scripts/<name>.py [args]\n"
            "(Install uv once: curl -LsSf https://astral.sh/uv/install.sh | sh)"
        )
    base = constants.MAINNET_API_URL if cfg["network"] == "mainnet" else constants.TESTNET_API_URL
    return Info(base, skip_ws=True)


def info_base_url(cfg: dict[str, Any]) -> str:
    """Return the /info base URL string (for raw HTTP calls when SDK lacks a wrap)."""
    if cfg["network"] == "mainnet":
        return "https://api.hyperliquid.xyz"
    return "https://api.hyperliquid-testnet.xyz"


def alchemy_http_url(cfg: dict[str, Any]) -> str:
    """Return the Alchemy HyperEVM HTTP RPC URL for the configured network."""
    return f"https://hyperliquid-{cfg['network']}.g.alchemy.com/v2/{cfg['alchemy_api_key']}"


def alchemy_ws_url(cfg: dict[str, Any]) -> str:
    """Return the Alchemy HyperEVM WebSocket RPC URL for the configured network."""
    return f"wss://hyperliquid-{cfg['network']}.g.alchemy.com/v2/{cfg['alchemy_api_key']}"


def resolve_address(cli_addr: str | None, cfg: dict[str, Any]) -> str:
    """Pick the address to query: CLI arg overrides config default."""
    addr = cli_addr or cfg.get("hl_user_address")
    if not addr:
        sys.exit(
            "No address provided.\n"
            f"Either pass an address as the first positional argument, "
            f"or fill in hl_user_address in {CONFIG_PATH}"
        )
    if not addr.startswith("0x") or len(addr) != 42:
        sys.exit(f"Address {addr!r} doesn't look like a valid 0x... address (42 chars).")
    return addr
