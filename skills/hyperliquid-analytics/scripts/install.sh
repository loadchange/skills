#!/usr/bin/env bash
#
# One-time setup for hyperliquid-analytics.
#
# Installs `uv` (Rust-based Python package manager from Astral) if missing,
# then runs the bootstrap_config script to create the config skeleton.
#
# Why uv? Because every runnable script in scripts/ declares its dependencies
# inline using PEP 723, and `uv run` handles the install-and-execute cycle in
# one command. That means:
#   * zero system Python pollution
#   * one command per script: `uv run scripts/<name>.py`
#   * no venv path to remember
#   * no `pip install` step to forget
#
# The only Python dep that ever gets installed is `hyperliquid-python-sdk`
# (the OFFICIAL Hyperliquid SDK). Every script's inline metadata declares
# it explicitly; there are no transitive, hidden, or optional packages.
#
# If you already have `uv` installed you can skip this script entirely and
# just run: `uv run scripts/bootstrap_config.py`

set -euo pipefail

echo "hyperliquid-analytics :: setup"
echo "=============================="

# --- Install uv if missing ---
if command -v uv >/dev/null 2>&1; then
    echo "uv already installed: $(uv --version)"
else
    echo "uv not found. Installing from https://astral.sh/uv/install.sh"
    echo ""
    read -r -p "Proceed with uv install? [y/N] " response
    case "${response}" in
        [yY][eE][sS]|[yY])
            curl -LsSf https://astral.sh/uv/install.sh | sh
            ;;
        *)
            echo "Aborted. Install uv manually from https://docs.astral.sh/uv/ and re-run." >&2
            exit 1
            ;;
    esac
    # Re-export PATH so `uv` is visible in this shell
    export PATH="${HOME}/.local/bin:${PATH}"
fi

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv still not on PATH. Add ~/.local/bin to PATH and re-run." >&2
    exit 2
fi

# --- Bootstrap the config file ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo ""
uv run "${SCRIPT_DIR}/bootstrap_config.py"

echo ""
echo "Setup done."
echo ""
echo "Next: edit ~/.config/hyperliquid-analytics/config.json to fill in"
echo "      hl_user_address (required) and alchemy_api_key (only for evm_*.py)."
echo ""
echo "Then run any script with one of:"
echo "    uv run ${SCRIPT_DIR}/account_state.py 0xabc...def"
echo "    ${SCRIPT_DIR}/account_state.py 0xabc...def          # via shebang"
