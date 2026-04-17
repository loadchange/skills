#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Create the hyperliquid-analytics config skeleton.

Writes an empty config file at ~/.config/hyperliquid-analytics/config.json
with placeholder fields and inline help. The user (or Claude) can then edit
the file to fill in alchemy_api_key and hl_user_address.

Re-running this script is safe: if the file already exists it prints the
current path and exits 0 without touching the file.

Usage:
    python scripts/bootstrap_config.py           # create skeleton
    python scripts/bootstrap_config.py --force   # overwrite existing file
    python scripts/bootstrap_config.py --show    # print current contents
"""
from __future__ import annotations

import argparse
import json
import sys

from _config import CONFIG_PATH, SKELETON


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    parser.add_argument("--force", action="store_true", help="Overwrite existing config")
    parser.add_argument("--show", action="store_true", help="Print current config instead of writing")
    args = parser.parse_args()

    if args.show:
        if not CONFIG_PATH.exists():
            print(f"(no config at {CONFIG_PATH})")
            return 1
        print(f"# {CONFIG_PATH}")
        print(CONFIG_PATH.read_text())
        return 0

    if CONFIG_PATH.exists() and not args.force:
        print(f"Config already exists at {CONFIG_PATH}")
        print("Use --force to overwrite, or --show to inspect.")
        print("Fill in alchemy_api_key and hl_user_address if they are empty.")
        return 0

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(SKELETON, indent=2, ensure_ascii=False))
    try:
        CONFIG_PATH.chmod(0o600)
    except OSError:
        pass  # not fatal on platforms that don't support chmod

    print(f"Created config skeleton at {CONFIG_PATH}")
    print()
    print("Next steps:")
    print(f"  1. Open {CONFIG_PATH} in your editor")
    print(f"  2. Fill in 'hl_user_address' (default Hyperliquid address to analyze)")
    print(f"  3. Fill in 'alchemy_api_key' if you want to run evm_*.py scripts")
    print(f"     (get one free at https://www.alchemy.com/ — Hyperliquid network)")
    print(f"  4. Set 'network' to 'mainnet' or 'testnet'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
