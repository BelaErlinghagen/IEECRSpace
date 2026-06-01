#!/usr/bin/env bash
#
# RSpace Interface — installer (macOS / Linux)
#
# Works two ways:
#   • From the unzipped project folder:   bash Installation/install.sh
#   • As a one-liner once on GitHub:      curl -LsSf <raw-url>/Installation/install.sh | bash
#
# It needs NO pre-installed Python: it bootstraps `uv` (a single self-contained
# tool that also downloads its own Python), then provisions the dependencies and
# creates a double-click launcher. The API key is entered later in the app's
# Settings tab — this script never asks for it.

set -eu

REPO_URL="https://github.com/CHANGE_ME/rspace-interface"   # TODO: set when the repo exists
UV_BIN_DIR="$HOME/.local/bin"

echo "============================================="
echo "  RSpace Interface — Installer"
echo "============================================="

# ── 1. Find the project folder ──────────────────────────────────────────────────
# install.sh lives in Installation/, so the app root is its parent. When piped
# from curl there is no script file on disk, so we download the project instead.
SCRIPT_DIR=""
if [ -f "$0" ]; then
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
fi

APP_ROOT=""
if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/../rspace_interface.py" ]; then
    APP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
elif [ -f "./rspace_interface.py" ]; then
    APP_ROOT="$(pwd)"
fi

if [ -z "$APP_ROOT" ]; then
    echo "  App files not found locally — downloading from GitHub…"
    if ! command -v git >/dev/null 2>&1; then
        echo "  ERROR: git is required to download the project. Install git and retry." >&2
        exit 1
    fi
    APP_ROOT="${RSPACE_INSTALL_DIR:-$HOME/RSpaceInterface}"
    git clone --depth 1 "$REPO_URL" "$APP_ROOT"
fi
echo "  App folder: $APP_ROOT"

# ── 2. Ensure uv is available (per-user, no admin) ───────────────────────────────
ensure_uv() {
    if command -v uv >/dev/null 2>&1; then return; fi
    if [ -x "$UV_BIN_DIR/uv" ]; then
        export PATH="$UV_BIN_DIR:$PATH"
        return
    fi
    echo "  Installing uv (this also provides Python — nothing else to install)…"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$UV_BIN_DIR:$PATH"
}
ensure_uv

if ! command -v uv >/dev/null 2>&1; then
    echo "  ERROR: uv was installed but isn't on PATH yet." >&2
    echo "  Open a new terminal (or add $UV_BIN_DIR to your PATH) and re-run." >&2
    exit 1
fi

# ── 3. Provision Python + dependencies ──────────────────────────────────────────
echo "  Setting up Python and dependencies (the first run can take a minute)…"
( cd "$APP_ROOT" && uv sync )

# ── 4. Create the double-click launcher ──────────────────────────────────────────
echo "  Creating launcher…"
( cd "$APP_ROOT" && uv run python Installation/finish_setup.py )

echo ""
echo "  ✓ Done!  Open the launcher created in:"
echo "      $APP_ROOT"
echo "  Then enter your RSpace API key in the app's Settings tab."
