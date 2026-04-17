"""Minimal HyperEVM JSON-RPC client using only the Python stdlib.

Why not web3.py? The user explicitly requires NO third-party dependencies
beyond the official Hyperliquid SDK, to minimize supply-chain exposure.
web3.py is a well-audited library but is not an official Hyperliquid SDK.
There is no official Hyperliquid-provided HyperEVM client, so we fall back
to raw JSON-RPC over urllib — bog-standard, zero deps, fully inspectable.

Supported: eth_blockNumber, eth_chainId, eth_getBalance, eth_call,
eth_getLogs, eth_getBlockByNumber, eth_getTransactionReceipt.

All values returned from the RPC are hex strings; use the helpers below
(hex_to_int, hex_to_addr) to decode them.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any


class EvmRpcError(RuntimeError):
    pass


class EvmClient:
    def __init__(self, rpc_url: str, timeout: float = 15.0, max_retries: int = 3):
        self.url = rpc_url
        self.timeout = timeout
        self.max_retries = max_retries
        self._id = 0

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def call(self, method: str, params: list | None = None) -> Any:
        """Make a JSON-RPC 2.0 call and return the `result` field.

        Raises EvmRpcError on transport failures, RPC error responses, or
        if the response shape is unexpected. Retries on HTTP 429/5xx up
        to max_retries times with exponential backoff.
        """
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params or [],
        }
        data = json.dumps(payload).encode()
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                req = urllib.request.Request(
                    self.url,
                    data=data,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = json.loads(resp.read())
                if "error" in body:
                    raise EvmRpcError(
                        f"RPC error on {method}: {body['error'].get('message', body['error'])}"
                    )
                if "result" not in body:
                    raise EvmRpcError(f"RPC response missing 'result': {body}")
                return body["result"]
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code == 429 or 500 <= e.code < 600:
                    time.sleep(2 ** attempt)
                    continue
                raise EvmRpcError(f"HTTP {e.code} on {method}: {e.read()[:200].decode('replace')}")
            except (urllib.error.URLError, TimeoutError) as e:
                last_err = e
                time.sleep(2 ** attempt)
        raise EvmRpcError(f"Exhausted retries calling {method}: {last_err}")

    # --- High-level convenience methods ---

    def chain_id(self) -> int:
        return hex_to_int(self.call("eth_chainId"))

    def block_number(self) -> int:
        return hex_to_int(self.call("eth_blockNumber"))

    def get_balance(self, address: str, block: str | int = "latest") -> int:
        block_tag = block if isinstance(block, str) else hex(block)
        return hex_to_int(self.call("eth_getBalance", [address, block_tag]))

    def call_contract(
        self,
        to: str,
        data: str,
        block: str | int = "latest",
    ) -> str:
        """Raw eth_call. Returns the hex result string."""
        block_tag = block if isinstance(block, str) else hex(block)
        return self.call("eth_call", [{"to": to, "data": data}, block_tag])

    def get_logs(
        self,
        from_block: int | str,
        to_block: int | str,
        address: str | list[str] | None = None,
        topics: list | None = None,
    ) -> list[dict]:
        """eth_getLogs with auto-formatting of block args.

        Use get_logs_chunked() for wide ranges — this raw method does NOT
        chunk and can fail with 'query returned too many results' errors.
        """
        f = from_block if isinstance(from_block, str) else hex(from_block)
        t = to_block if isinstance(to_block, str) else hex(to_block)
        params: dict[str, Any] = {"fromBlock": f, "toBlock": t}
        if address is not None:
            params["address"] = address
        if topics is not None:
            params["topics"] = topics
        return self.call("eth_getLogs", [params])

    def get_logs_chunked(
        self,
        from_block: int,
        to_block: int,
        address: str | list[str] | None = None,
        topics: list | None = None,
        chunk_size: int = 2000,
    ) -> list[dict]:
        """Scan eth_getLogs across a wide block range in safe chunks.

        Halves the chunk size adaptively on errors until it succeeds or
        hits the floor (50 blocks). Returns the concatenated log list.
        """
        all_logs: list[dict] = []
        cursor = from_block
        current_chunk = chunk_size
        while cursor <= to_block:
            chunk_end = min(cursor + current_chunk - 1, to_block)
            try:
                logs = self.get_logs(cursor, chunk_end, address=address, topics=topics)
                all_logs.extend(logs)
                cursor = chunk_end + 1
                # Ramp chunk size back up after a successful small chunk
                if current_chunk < chunk_size:
                    current_chunk = min(chunk_size, current_chunk * 2)
            except EvmRpcError:
                if current_chunk <= 50:
                    raise
                current_chunk //= 2
        return all_logs


# --- Encoding / decoding helpers ---

def hex_to_int(h: str) -> int:
    if h is None or h == "0x":
        return 0
    return int(h, 16)


def int_to_hex(i: int) -> str:
    return hex(i)


def addr_to_topic(addr: str) -> str:
    """Left-pad a 20-byte address to a 32-byte topic string."""
    if not addr.startswith("0x"):
        raise ValueError(f"Not a hex address: {addr!r}")
    return "0x" + addr[2:].lower().zfill(64)


def topic_to_addr(topic: str) -> str:
    """Extract a 20-byte address from a 32-byte topic (the last 40 hex chars)."""
    if not topic.startswith("0x") or len(topic) != 66:
        raise ValueError(f"Not a 32-byte topic: {topic!r}")
    return "0x" + topic[-40:]


def encode_call(signature: str, args_hex: list[str] | None = None) -> str:
    """Encode a Solidity function call: 4-byte selector + padded args.

    Only handles:
      - address args (must be passed as 0x..., 42 chars)
      - uint256 args (must be passed as pre-encoded 32-byte hex strings)

    For ERC20 balanceOf(address), pass args_hex=[addr_to_topic(owner)].
    """
    from hashlib import sha3_256  # noqa: F401  — sha3_256 is Keccak-only; we need real Keccak

    # Python stdlib only has sha3_256 (FIPS-202); we need Keccak-256.
    # hashlib in Python 3.6+ ships with `_sha3` which provides Keccak via
    # the undocumented `sha3_*` names — but those are FIPS-202 not Keccak.
    # We compute Keccak-256 using a tiny pure-Python implementation below
    # so we stay stdlib-only.
    selector = keccak256(signature.encode())[:4].hex()
    data = "0x" + selector
    for arg in args_hex or []:
        arg_clean = arg[2:] if arg.startswith("0x") else arg
        data += arg_clean.zfill(64)
    return data


# --- Tiny pure-Python Keccak-256 implementation (stdlib-only) ---
# Needed because hashlib.sha3_256 is FIPS-202 SHA-3, which differs from
# Ethereum's Keccak-256 in the padding byte. Ethereum uses the pre-
# standard Keccak variant (padding 0x01, not 0x06). This implementation
# is adapted from the compact reference in the Keccak team's codebase
# and kept small for auditability. ~40 lines, constant-time-ish.

def _keccak_f(state: list[int]) -> None:
    RC = [
        0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
        0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
        0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
        0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
        0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
        0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
    ]
    R = [
        [0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61],
        [28, 55, 25, 21, 56], [27, 20, 39, 8, 14],
    ]
    MASK = (1 << 64) - 1
    for rnd in range(24):
        # θ
        C = [state[x] ^ state[x + 5] ^ state[x + 10] ^ state[x + 15] ^ state[x + 20] for x in range(5)]
        D = [C[(x - 1) % 5] ^ (((C[(x + 1) % 5] << 1) | (C[(x + 1) % 5] >> 63)) & MASK) for x in range(5)]
        for x in range(5):
            for y in range(5):
                state[x + 5 * y] ^= D[x]
        # ρ & π
        B = [0] * 25
        for x in range(5):
            for y in range(5):
                r = R[x][y]
                v = state[x + 5 * y]
                B[y + 5 * ((2 * x + 3 * y) % 5)] = ((v << r) | (v >> (64 - r))) & MASK
        # χ
        for y in range(5):
            for x in range(5):
                state[x + 5 * y] = B[x + 5 * y] ^ ((~B[((x + 1) % 5) + 5 * y]) & B[((x + 2) % 5) + 5 * y]) & MASK
        # ι
        state[0] ^= RC[rnd]


def keccak256(data: bytes) -> bytes:
    """Keccak-256 (the one Ethereum uses, NOT FIPS SHA-3)."""
    rate = 136  # 1088 bits / 8
    state = [0] * 25
    # Absorb
    padded = bytearray(data)
    padded.append(0x01)  # Keccak pad (Ethereum), NOT 0x06 (FIPS SHA-3)
    while len(padded) % rate != 0:
        padded.append(0x00)
    padded[-1] |= 0x80
    for block_start in range(0, len(padded), rate):
        block = padded[block_start:block_start + rate]
        for i in range(rate // 8):
            lane = int.from_bytes(block[i * 8:(i + 1) * 8], "little")
            state[i] ^= lane
        _keccak_f(state)
    # Squeeze
    out = bytearray()
    for i in range(4):  # 32 bytes / 8 bytes per lane
        out.extend(state[i].to_bytes(8, "little"))
    return bytes(out[:32])


def decode_uint256(hex_result: str) -> int:
    """Decode a single uint256 return value from an eth_call result."""
    if not hex_result or hex_result == "0x":
        return 0
    return int(hex_result[2:], 16) if hex_result.startswith("0x") else int(hex_result, 16)


def decode_string(hex_result: str) -> str:
    """Decode an ABI-encoded string return value from eth_call.

    ABI layout: offset (32 bytes) | length (32 bytes) | bytes... (padded to 32).
    Used for ERC20.symbol() etc. Falls back to trying a bytes32 (right-padded
    ascii) if the shape doesn't match the dynamic-string layout.
    """
    if not hex_result or hex_result == "0x":
        return ""
    raw = bytes.fromhex(hex_result[2:])
    # Try dynamic-string layout
    if len(raw) >= 64:
        try:
            length = int.from_bytes(raw[32:64], "big")
            if 0 < length <= len(raw) - 64:
                return raw[64:64 + length].decode("utf-8", errors="replace")
        except Exception:
            pass
    # Fallback: bytes32 right-padded ASCII
    return raw.rstrip(b"\x00").decode("utf-8", errors="replace")
