#!/usr/bin/env bash
# RSpace Interface launcher (Linux). Run this to start the app.
# Everything lives inside this folder; the first run sets up uv + Python + deps.
cd "$(dirname "$0")"
export UV_PYTHON_INSTALL_DIR="$PWD/.uv/python"
export UV_CACHE_DIR="$PWD/.uv/cache"
UV="$PWD/.uv/bin/uv"

if [ ! -x "$UV" ] || [ ! -d "$PWD/.venv" ]; then
    echo "First-time setup — this can take a minute…"
    bash Installation/install.sh || { echo "Setup failed."; exit 1; }
fi

exec "$UV" run src/rspace_interface.py
