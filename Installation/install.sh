#!/usr/bin/env bash
#
# RSpace Interface — portable setup (macOS / Linux).
#
# Sets up everything INSIDE the application folder, so nothing is written to
# per-user/system locations (which on managed/domain machines get redirected to
# network shares and cause trouble). It installs `uv` into ./.uv/bin, a managed
# Python into ./.uv/python, and the dependencies into ./.venv. Run it directly, or
# just let the "IEECRSpace_Launcher" launcher run it on first start.

set -eu

# Locate the application root (the parent of this Installation/ folder).
if [ -f "$0" ]; then
    APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
elif [ -f "./src/rspace_interface.py" ]; then
    APP_ROOT="$(pwd)"
else
    echo "ERROR: run this from inside the unzipped RSpace Interface folder." >&2
    exit 1
fi

echo "============================================="
echo "  RSpace Interface — setup (self-contained)"
echo "============================================="
echo "  App folder: $APP_ROOT"

# Keep uv, its managed Python, its cache and the venv all inside the app folder.
export UV_INSTALL_DIR="$APP_ROOT/.uv/bin"
export UV_PYTHON_INSTALL_DIR="$APP_ROOT/.uv/python"
export UV_CACHE_DIR="$APP_ROOT/.uv/cache"
export UV_NO_MODIFY_PATH=1          # do not touch the user's shell profile/PATH
UV="$UV_INSTALL_DIR/uv"
mkdir -p "$UV_INSTALL_DIR" "$UV_PYTHON_INSTALL_DIR" "$UV_CACHE_DIR" "$APP_ROOT/config"

# 1. Install uv into the app folder if it isn't there yet.
if [ ! -x "$UV" ]; then
    echo "  Installing uv into the app folder (no system changes)…"
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi
if [ ! -x "$UV" ]; then
    echo "  ERROR: uv was not installed at $UV" >&2
    exit 1
fi

# 2. Provision the pinned Python + dependencies into ./.venv.
echo "  Downloading Python and dependencies into the folder (first time only)…"
( cd "$APP_ROOT" && "$UV" sync )

echo ""
echo "  ✓ Setup complete. Start the app with the 'IEECRSpace_Launcher' file in:"
echo "      $APP_ROOT"
echo "  Then enter your RSpace API key in the Settings tab."
