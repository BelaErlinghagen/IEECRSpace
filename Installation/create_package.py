#!/usr/bin/env python3
"""
Create a distributable zip of the RSpace Interface.
Run this from anywhere; the zip is saved next to this script.

The zip contains only the source files needed by a new user —
it deliberately excludes .venv/, the user config (APIkey.txt / config.json),
__pycache__, and any generated launchers (the installer recreates those).
"""

import zipfile
from pathlib import Path
from datetime import datetime

INSTALL_DIR = Path(__file__).resolve().parent   # Installation/
APP_DIR = INSTALL_DIR.parent                    # project root

# Files and folders to include (relative to APP_DIR)
INCLUDE = [
    "rspace.py",
    "rspace_interface.py",
    "IEECRlogo.png",
    "pyproject.toml",
    "uv.lock",
    "Installation/install.sh",
    "Installation/install.command",
    "Installation/install.bat",
    "Installation/finish_setup.py",
    "Installation/create_package.py",
]

# Output zip name
timestamp = datetime.now().strftime("%Y%m%d")
zip_name = f"RSpace_Interface_{timestamp}.zip"
zip_path = INSTALL_DIR / zip_name


def main():
    print(f"\nBuilding distribution package: {zip_name}")
    print(f"From: {APP_DIR}\n")

    missing = [f for f in INCLUDE if not (APP_DIR / f).exists()]
    if missing:
        print("WARNING — these files were not found and will be skipped:")
        for m in missing:
            print(f"  {m}")
        print()

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in INCLUDE:
            src = APP_DIR / rel
            if src.exists():
                zf.write(src, rel)
                print(f"  + {rel}")

    size_kb = zip_path.stat().st_size // 1024
    print(f"\nDone — {zip_path.name}  ({size_kb} KB)")
    print(f"Saved to: {zip_path}")
    print()
    print("Hand this zip to other users. They should:")
    print("  1. Unzip it anywhere (e.g. their Desktop)")
    print("  2. Open the  Installation/  folder")
    print("  3. Run the installer for their OS (no Python needed):")
    print("       Windows : double-click install.bat")
    print("       macOS   : double-click install.command")
    print("       Linux   : run  bash install.sh")
    print("  4. Open the launcher it creates, then enter the API key")
    print("     in the app's Settings tab.")


if __name__ == "__main__":
    main()
