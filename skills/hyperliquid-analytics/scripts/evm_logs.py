#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Scan HyperEVM event logs with automatic chunking.

Thin wrapper over EvmClient.get_logs_chunked that handles:
  - Block range auto-chunking (starts at 2000 blocks, halves on errors)
  - Topic encoding helpers (Transfer event + optional from/to address filter)
  - Output as summary / full JSON / CSV

Usage:
    # All Transfer events on a contract in the last 50k blocks
    python scripts/evm_logs.py --contract 0xCONTRACT --event Transfer --last-blocks 50000

    # Transfers TO a specific address on a contract
    python scripts/evm_logs.py --contract 0xCONTRACT --event Transfer --to 0xabc --last-blocks 100000

    # Arbitrary event with full signature
    python scripts/evm_logs.py --contract 0xCONTRACT --event-sig "Swap(address,uint256,uint256,uint256,uint256,address)" --days 7

    # Output full logs to CSV
    python scripts/evm_logs.py --contract 0xCONTRACT --event Transfer --last-blocks 10000 --out /tmp/logs.csv
"""
from __future__ import annotations

import argparse
import csv
import json as _json
import sys

from _config import load_config, alchemy_http_url
from _evm import EvmClient, EvmRpcError, keccak256, addr_to_topic, topic_to_addr, hex_to_int
from _format import emit, short_addr


# Known event signatures for convenience.
KNOWN_EVENTS = {
    "Transfer": "Transfer(address,address,uint256)",
    "Approval": "Approval(address,address,uint256)",
    "Deposit": "Deposit(address,uint256)",
    "Withdrawal": "Withdrawal(address,uint256)",
    "Swap": "Swap(address,uint256,uint256,uint256,uint256,address)",
}


def resolve_event_topic(event: str | None, event_sig: str | None) -> str | None:
    if event_sig:
        return "0x" + keccak256(event_sig.encode()).hex()
    if event:
        sig = KNOWN_EVENTS.get(event)
        if not sig:
            raise SystemExit(f"Unknown event {event!r}. Pass --event-sig with the full signature.")
        return "0x" + keccak256(sig.encode()).hex()
    return None


def build_result(cfg: dict, args: argparse.Namespace) -> dict:
    evm = EvmClient(alchemy_http_url(cfg))

    try:
        latest = evm.block_number()
    except EvmRpcError as e:
        return {"error": f"block_number failed: {e}"}

    if args.last_blocks:
        from_block = max(0, latest - args.last_blocks)
        to_block = latest
    else:
        if args.from_block is None or args.to_block is None:
            raise SystemExit("Either --last-blocks or both --from-block and --to-block are required")
        from_block = args.from_block
        to_block = args.to_block

    topic0 = resolve_event_topic(args.event, args.event_sig)
    topics: list = []
    if topic0:
        topics.append(topic0)
    if args.from_addr:
        topics.append(addr_to_topic(args.from_addr))
    else:
        topics.append(None)
    if args.to_addr:
        topics.append(addr_to_topic(args.to_addr))
    else:
        topics.append(None)
    # Trim trailing Nones so we don't send unnecessary filters
    while topics and topics[-1] is None:
        topics.pop()
    if not topics:
        topics = None  # type: ignore

    try:
        logs = evm.get_logs_chunked(
            from_block=from_block,
            to_block=to_block,
            address=args.contract,
            topics=topics,
            chunk_size=args.chunk_size,
        )
    except EvmRpcError as e:
        return {"error": f"get_logs failed: {e}"}

    # Surface a small analysis: unique participants & first/last blocks
    unique_addrs: set[str] = set()
    if topic0 and len(topics or []) >= 2:
        # For indexed address topics, extract them
        for log in logs:
            for t in (log.get("topics") or [])[1:3]:
                try:
                    a = topic_to_addr(t)
                    if int(a, 16) != 0:
                        unique_addrs.add(a.lower())
                except Exception:
                    pass

    return {
        "contract": args.contract,
        "event": args.event or args.event_sig,
        "from_block": from_block,
        "to_block": to_block,
        "chunk_size": args.chunk_size,
        "n_logs": len(logs),
        "n_unique_addresses": len(unique_addrs),
        "unique_addresses_sample": sorted(unique_addrs)[:20],
        "logs": logs,
    }


def print_text(r: dict) -> None:
    if r.get("error"):
        print(f"[error] {r['error']}")
        return
    print(f"=== Logs on {short_addr(r['contract'])} ===")
    print(f"Event:             {r['event']}")
    print(f"Block range:       {r['from_block']} → {r['to_block']} ({r['to_block'] - r['from_block'] + 1} blocks)")
    print(f"Logs returned:     {r['n_logs']}")
    if r["n_unique_addresses"]:
        print(f"Unique addresses:  {r['n_unique_addresses']}")
        print(f"Sample:            {', '.join(short_addr(a) for a in r['unique_addresses_sample'][:10])}")


def write_csv(logs: list[dict], path: str) -> None:
    if not logs:
        open(path, "w").close()
        return
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["blockNumber", "txHash", "logIndex", "address", "topics", "data"])
        for log in logs:
            w.writerow([
                hex_to_int(log.get("blockNumber", "0x0")),
                log.get("transactionHash", ""),
                hex_to_int(log.get("logIndex", "0x0")),
                log.get("address", ""),
                ";".join(log.get("topics") or []),
                log.get("data", ""),
            ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    parser.add_argument("--contract", required=True, help="Contract address emitting the logs")

    ev_group = parser.add_mutually_exclusive_group()
    ev_group.add_argument("--event", help=f"Event name (known: {', '.join(KNOWN_EVENTS)})")
    ev_group.add_argument("--event-sig", help="Full event signature, e.g. 'Transfer(address,address,uint256)'")

    parser.add_argument("--from-addr", help="Filter by indexed 'from' address (topic[1])")
    parser.add_argument("--to-addr", help="Filter by indexed 'to' address (topic[2])")

    rng = parser.add_mutually_exclusive_group()
    rng.add_argument("--last-blocks", type=int, help="Scan the last N blocks from latest")
    parser.add_argument("--from-block", type=int)
    parser.add_argument("--to-block", type=int)

    parser.add_argument("--chunk-size", type=int, default=2000,
                        help="Initial block chunk size (halves adaptively on errors)")
    parser.add_argument("--out", help="Write logs to file (.csv or .json)")
    parser.add_argument("--json", action="store_true", help="Emit full JSON to stdout")
    args = parser.parse_args()

    cfg = load_config(require_alchemy=True)

    try:
        result = build_result(cfg, args)
    except Exception as e:
        print(f"[error] {e}", file=sys.stderr)
        return 2

    if args.out:
        if args.out.endswith(".csv"):
            write_csv(result.get("logs", []), args.out)
        else:
            with open(args.out, "w") as f:
                _json.dump(result, f, indent=2, default=str)

    if args.json:
        print(_json.dumps(result, indent=2, default=str))
    else:
        print_text(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
