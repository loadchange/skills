"""Formatting helpers shared by all scripts.

Keeps output consistent across the skill: same time format, same money
format, same table headers. Scripts also use emit() which chooses between
JSON and text based on a single --json flag.

Dependencies: stdlib only.
"""
from __future__ import annotations

import json
import sys
import time
from typing import Any


def fnum(x: Any, default: float = 0.0) -> float:
    """Convert a Hyperliquid string number to float safely.

    Hyperliquid returns prices, sizes, and USD amounts as strings (to avoid
    JS number precision issues). Most math wants floats. This wrapper never
    raises — missing/None/"nan" become `default`.
    """
    if x is None:
        return default
    try:
        v = float(x)
        if v != v:  # NaN check
            return default
        return v
    except (TypeError, ValueError):
        return default


def fmt_usd(x: Any, precision: int = 2, signed: bool = False) -> str:
    """Format a USD amount: $1,234.56 or -$1,234.56."""
    v = fnum(x)
    sign = "+" if signed and v >= 0 else ""
    if v < 0:
        return f"-${-v:,.{precision}f}"
    return f"{sign}${v:,.{precision}f}"


def fmt_pct(x: Any, precision: int = 2, signed: bool = False) -> str:
    """Format as a percentage: 12.34% or +12.34%."""
    v = fnum(x)
    sign = "+" if signed and v >= 0 else ""
    return f"{sign}{v:.{precision}f}%"


def fmt_ts(ms: int, utc: bool = True) -> str:
    """Format a millisecond epoch as YYYY-MM-DD HH:MM:SS[Z]."""
    if not ms:
        return "-"
    t = time.gmtime(ms / 1000) if utc else time.localtime(ms / 1000)
    suffix = "Z" if utc else ""
    return time.strftime(f"%Y-%m-%d %H:%M:%S{suffix}", t)


def ms_now() -> int:
    """Current wall-clock in milliseconds since epoch."""
    return int(time.time() * 1000)


def ms_hours_ago(hours: float) -> int:
    """Millisecond timestamp of `hours` ago."""
    return int((time.time() - hours * 3600) * 1000)


def ms_days_ago(days: float) -> int:
    """Millisecond timestamp of `days` ago."""
    return int((time.time() - days * 86400) * 1000)


def emit(result: dict, as_json: bool, text_printer=None) -> None:
    """Emit either JSON (for Claude/machine) or text (for humans).

    If as_json is True, dumps result as indented JSON to stdout.
    Otherwise calls text_printer(result) if provided, else falls back
    to a simple pretty-print.
    """
    if as_json:
        print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
        return
    if text_printer is not None:
        text_printer(result)
        return
    # Fallback: indented JSON even when text was requested but no printer given.
    print(json.dumps(result, indent=2, default=str, ensure_ascii=False))


def table(rows: list[list[str]], headers: list[str], aligns: list[str] | None = None) -> str:
    """Render a simple aligned text table. No external deps.

    rows: list of row values (each row is a list of strings with len == len(headers))
    aligns: list of "l" / "r" per column; defaults to all "l"
    """
    if not rows:
        return "(no rows)"
    aligns = aligns or ["l"] * len(headers)
    widths = [len(h) for h in headers]
    for r in rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(str(cell)))

    def fmt_cell(val: str, width: int, align: str) -> str:
        return str(val).rjust(width) if align == "r" else str(val).ljust(width)

    lines = []
    lines.append("  ".join(fmt_cell(h, widths[i], aligns[i]) for i, h in enumerate(headers)))
    lines.append("  ".join("-" * widths[i] for i in range(len(headers))))
    for r in rows:
        lines.append("  ".join(fmt_cell(r[i], widths[i], aligns[i]) for i in range(len(headers))))
    return "\n".join(lines)


def short_addr(addr: str) -> str:
    """Shorten 0xabc...def for display."""
    if not addr or len(addr) < 10:
        return str(addr)
    return f"{addr[:6]}...{addr[-4:]}"


def err(msg: str) -> None:
    """Print to stderr in a consistent format."""
    print(f"[error] {msg}", file=sys.stderr)
