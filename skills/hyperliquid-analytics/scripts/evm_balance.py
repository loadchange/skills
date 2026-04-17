#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Native HYPE balance + ERC20 token balances for a HyperEVM address.

Uses _evm.EvmClient (stdlib JSON-RPC only, no web3.py) to call:
  - eth_getBalance      : native HYPE
  - eth_call balanceOf  : ERC20 tokens (for each token in the watchlist)
  - eth_call decimals   : decoded per token once
  - eth_call symbol     : decoded per token once

Token watchlist sources (in priority):
  1. --token <addr>          : single token from CLI
  2. --tokens a,b,c          : comma-separated list from CLI
  3. --tokens-file path      : one per line
  4. config["evm_tokens"]    : list in config.json (add manually)

If no watchlist is provided, only the native HYPE balance is reported.

Usage:
    python scripts/evm_balance.py                              # native only
    python scripts/evm_balance.py 0xabc --token 0xERC20_ADDR
    python scripts/evm_balance.py 0xabc --tokens-file /tmp/tokens.txt
    python scripts/evm_balance.py 0xabc --block 12345678       # historical (archival)
"""
from __future__ import annotations

import argparse
import sys

from _config import load_config, resolve_address, alchemy_http_url
from _evm import EvmClient, EvmRpcError, encode_call, addr_to_topic, decode_uint256, decode_string
from _format import emit, fmt_usd, short_addr, table


def load_token_list(args: argparse.Namespace, cfg: dict) -> list[str]:
    tokens: list[str] = []
    if args.token:
        tokens.append(args.token)
    if args.tokens:
        tokens.extend(t.strip() for t in args.tokens.split(",") if t.strip())
    if args.tokens_file:
        with open(args.tokens_file) as f:
            tokens.extend(line.strip() for line in f if line.strip() and not line.startswith("#"))
    if not tokens and cfg.get("evm_tokens"):
        tokens = list(cfg["evm_tokens"])
    # Dedupe
    seen = set()
    unique = []
    for t in tokens:
        t = t.lower()
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def erc20_balance(evm: EvmClient, token_addr: str, holder: str, block: int | str) -> dict:
    """Fetch balance, decimals, symbol for one token. Returns empty dict on error."""
    try:
        bal_hex = evm.call_contract(
            token_addr, encode_call("balanceOf(address)", [addr_to_topic(holder)]), block
        )
        dec_hex = evm.call_contract(token_addr, encode_call("decimals()"), block)
        sym_hex = evm.call_contract(token_addr, encode_call("symbol()"), block)
    except EvmRpcError as e:
        return {"token": token_addr, "error": str(e)}
    raw = decode_uint256(bal_hex)
    decimals = decode_uint256(dec_hex)
    symbol = decode_string(sym_hex)
    balance = raw / (10 ** decimals) if decimals else raw
    return {
        "token": token_addr,
        "symbol": symbol,
        "decimals": decimals,
        "balance_raw": raw,
        "balance": balance,
    }


def build_result(cfg: dict, addr: str, tokens: list[str], block: int | str) -> dict:
    evm = EvmClient(alchemy_http_url(cfg))
    try:
        chain_id = evm.chain_id()
    except EvmRpcError as e:
        return {"address": addr, "error": f"RPC unreachable: {e}"}

    try:
        block_num = evm.block_number() if block == "latest" else (block if isinstance(block, int) else None)
    except EvmRpcError as e:
        return {"address": addr, "error": f"block_number failed: {e}"}

    try:
        native_wei = evm.get_balance(addr, block)
    except EvmRpcError as e:
        return {"address": addr, "error": f"get_balance failed: {e}"}
    native_hype = native_wei / 1e18

    erc20_balances = []
    for token in tokens:
        r = erc20_balance(evm, token, addr, block)
        if "error" not in r and r["balance"] == 0:
            # Skip zero balances for brevity in the text view, keep in JSON
            r["zero"] = True
        erc20_balances.append(r)

    return {
        "address": addr,
        "network": cfg["network"],
        "chain_id": chain_id,
        "block": block_num,
        "native": {
            "symbol": "HYPE",
            "balance_wei": native_wei,
            "balance": native_hype,
        },
        "erc20": erc20_balances,
    }


def print_text(r: dict) -> None:
    if r.get("error"):
        print(f"[error] {r['error']}")
        return
    print(f"=== HyperEVM balances for {short_addr(r['address'])} ===")
    print(f"Network: {r['network']}  chain_id: {r['chain_id']}  block: {r['block']}")
    print()
    n = r["native"]
    print(f"-- Native --")
    print(f"  HYPE: {n['balance']:.6f}")
    print()
    erc20 = r["erc20"]
    if not erc20:
        print("-- No ERC20 tokens queried --")
        print("  Pass --token <addr> or --tokens-file to check token balances.")
        return
    nonzero = [t for t in erc20 if "error" not in t and not t.get("zero")]
    zero = [t for t in erc20 if "error" not in t and t.get("zero")]
    errors = [t for t in erc20 if "error" in t]
    if nonzero:
        print(f"-- ERC20 balances ({len(nonzero)} nonzero) --")
        rows = [[t["symbol"] or "?",
                 f"{t['balance']:.6f}",
                 str(t["decimals"]),
                 short_addr(t["token"])] for t in nonzero]
        print(table(rows, ["symbol", "balance", "dec", "contract"], aligns=["l", "r", "r", "l"]))
    if zero:
        print(f"-- Zero balances ({len(zero)}) --")
        print("  " + ", ".join(t["symbol"] or short_addr(t["token"]) for t in zero))
    if errors:
        print(f"-- Errors ({len(errors)}) --")
        for e in errors:
            print(f"  {short_addr(e['token'])}: {e['error']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    parser.add_argument("address", nargs="?")
    parser.add_argument("--token", help="Single ERC20 contract address to query")
    parser.add_argument("--tokens", help="Comma-separated list of ERC20 contract addresses")
    parser.add_argument("--tokens-file", help="File with one token address per line")
    parser.add_argument("--block", default="latest",
                        help="Block number for historical query (default: latest)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cfg = load_config(require_alchemy=True)
    addr = resolve_address(args.address, cfg)
    tokens = load_token_list(args, cfg)
    block: int | str = args.block if args.block == "latest" else int(args.block)

    try:
        result = build_result(cfg, addr, tokens, block)
    except Exception as e:
        print(f"[error] RPC failed: {e}", file=sys.stderr)
        return 2

    emit(result, as_json=args.json, text_printer=print_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
