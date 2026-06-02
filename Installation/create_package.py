#!/usr/bin/env python3
"""
Create a distributable zip of the RSpace Interface.
Run this from anywhere; the zip is saved next to this script.

The zip is a self-contained app folder (ImageJ-style): the launchers, the source
in src/, and the installer. It deliberately excludes the in-folder runtime that the
installer builds (.uv/, .venv/) and the user's config/ (which holds the API key),
plus caches/__pycache__.
"""

import zipfile
from pathlib import Path
from datetime import datetime

INSTALL_DIR = Path(__file__).resolve().parent   # Installation/
APP_DIR = INSTALL_DIR.parent                    # project root

# Files to include (relative to APP_DIR). The app folder the user receives.
INCLUDE = [
    "src/rspace.py",
    "src/rspace_interface.py",
    "src/IEECRlogo.png",
    "pyproject.toml",
    "uv.lock",
    ".python-version",
    "IEECRSpace_Launcher.command",
    "IEECRSpace_Launcher.bat",
    "IEECRSpace_Launcher.sh",
    "Installation/install.sh",
    "Installation/install.bat",
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
    print("  1. Unzip it anywhere (keep the whole folder together)")
    print("  2. Double-click the launcher for their OS — it self-installs on first run:")
    print("       Windows : 'IEECRSpace_Launcher.bat'")
    print("       macOS   : 'IEECRSpace_Launcher.command'")
    print("       Linux   : run  bash IEECRSpace_Launcher.sh")
    print("  3. Enter the RSpace API key in the app's Settings tab.")
    print()
    print("Everything (Python, dependencies, config) stays inside that one folder.")


if __name__ == "__main__":
    main()
