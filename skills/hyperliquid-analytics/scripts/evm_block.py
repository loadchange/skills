#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Current HyperEVM block info and RPC health.

Also useful as a cheap connectivity test for the Alchemy endpoint.

Usage:
    python scripts/evm_block.py               # current block
    python scripts/evm_block.py --block 100   # block at height 100
"""
from __future__ import annotations

import argparse
import sys

from _config import load_config, alchemy_http_url
from _evm import EvmClient, EvmRpcError, hex_to_int
from _format import emit, fmt_ts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    parser.add_argument("--block", help="Block number or 'latest' (default: latest)", default="latest")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cfg = load_config(require_alchemy=True)
    evm = EvmClient(alchemy_http_url(cfg))

    try:
        chain_id = evm.chain_id()
        latest = evm.block_number()
        tag = args.block if args.block == "latest" else hex(int(args.block))
        block = evm.call("eth_getBlockByNumber", [tag, False])
    except EvmRpcError as e:
        print(f"[error] RPC failed: {e}", file=sys.stderr)
        return 2

    result = {
        "network": cfg["network"],
        "chain_id": chain_id,
        "latest_block": latest,
        "queried_block": hex_to_int(block.get("number", "0x0")) if block else None,
        "queried_block_ts_utc": fmt_ts(hex_to_int(block.get("timestamp", "0x0")) * 1000) if block else None,
        "block_hash": block.get("hash") if block else None,
        "parent_hash": block.get("parentHash") if block else None,
        "tx_count": len(block.get("transactions") or []) if block else 0,
        "gas_used": hex_to_int(block.get("gasUsed", "0x0")) if block else 0,
        "gas_limit": hex_to_int(block.get("gasLimit", "0x0")) if block else 0,
        "base_fee_per_gas": hex_to_int(block.get("baseFeePerGas", "0x0")) if block else 0,
    }

    if args.json:
        import json
        print(json.dumps(result, indent=2, default=str))
        return 0

    print(f"=== HyperEVM block info ({cfg['network']}) ===")
    print(f"  Chain ID:       {result['chain_id']}")
    print(f"  Latest block:   {result['latest_block']}")
    print(f"  Queried block:  {result['queried_block']}")
    print(f"  Block time:     {result['queried_block_ts_utc']}")
    print(f"  Block hash:     {result['block_hash']}")
    print(f"  Tx count:       {result['tx_count']}")
    print(f"  Gas used:       {result['gas_used']:,}")
    print(f"  Gas limit:      {result['gas_limit']:,}")
    if result["base_fee_per_gas"]:
        print(f"  Base fee:       {result['base_fee_per_gas'] / 1e9:.4f} gwei")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
