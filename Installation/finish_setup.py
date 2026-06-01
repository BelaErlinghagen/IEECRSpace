#!/usr/bin/env python3
"""Create a double-click launcher for the RSpace Interface.

Run via `uv run python Installation/finish_setup.py` from the installer once uv
and the dependencies are in place. The generated launcher simply calls
`uv run rspace_interface.py`, so each start re-checks the environment and stays
self-healing. No API key is collected here — that happens in the app's Settings
tab.
"""

import platform
import stat
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
UV_PATH_LINE_UNIX = 'export PATH="$HOME/.local/bin:$PATH"\n'
UV_PATH_LINE_WIN = (
    'if exist "%USERPROFILE%\\.local\\bin\\uv.exe" '
    'set "PATH=%USERPROFILE%\\.local\\bin;%PATH%"\r\n'
)


def _make_executable(path):
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _write_windows():
    path = APP_ROOT / "Launch RSpace.bat"
    path.write_text(
        "@echo off\r\n"
        'cd /d "%~dp0"\r\n'
        f"{UV_PATH_LINE_WIN}"
        "uv run rspace_interface.py\r\n"
        "if errorlevel 1 pause\r\n",
        encoding="utf-8",
    )
    return [path]


def _write_mac():
    path = APP_ROOT / "Launch RSpace.command"
    path.write_text(
        "#!/bin/bash\n"
        'cd "$(dirname "$0")"\n'
        f"{UV_PATH_LINE_UNIX}"
        "uv run rspace_interface.py\n",
        encoding="utf-8",
    )
    _make_executable(path)
    return [path]


def _write_linux():
    sh = APP_ROOT / "launch_rspace.sh"
    sh.write_text(
        "#!/bin/bash\n"
        'cd "$(dirname "$0")"\n'
        f"{UV_PATH_LINE_UNIX}"
        "uv run rspace_interface.py\n",
        encoding="utf-8",
    )
    _make_executable(sh)

    desktop = APP_ROOT / "RSpace Interface.desktop"
    desktop.write_text(
        "[Desktop Entry]\n"
        "Version=1.0\n"
        "Type=Application\n"
        "Name=RSpace Interface\n"
        "Comment=Lab notebook interface for RSpace\n"
        f'Exec=bash "{sh}"\n'
        "Terminal=false\n"
        "Categories=Science;Education;\n",
        encoding="utf-8",
    )
    _make_executable(desktop)
    return [sh, desktop]


def main():
    system = platform.system()
    if system == "Windows":
        created = _write_windows()
    elif system == "Darwin":
        created = _write_mac()
    else:
        created = _write_linux()

    for path in created:
        print(f"  Created: {path.name}")


if __name__ == "__main__":
    main()
