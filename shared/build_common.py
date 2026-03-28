#!/usr/bin/env python3
"""
Shared build script for Unfnshed applications.

Usage from each app's build.py:
    from shared.build_common import run_build
    run_build("AppName")
"""

import subprocess
import sys
import shutil
from pathlib import Path


def clean_build(app_dir: Path = None):
    """Remove previous build artifacts."""
    base = app_dir or Path.cwd()
    dirs_to_clean = ['build', 'dist']
    for dir_name in dirs_to_clean:
        dir_path = base / dir_name
        if dir_path.exists():
            print(f"Removing {dir_path}...")
            shutil.rmtree(dir_path)
    print("Clean complete.")


def build(app_name: str, app_dir: Path = None):
    """Run PyInstaller build for the given app."""
    base = app_dir or Path.cwd()
    print(f"Building {app_name} for {sys.platform}...")

    cmd = [sys.executable, '-m', 'PyInstaller', f'{app_name}.spec', '--noconfirm']
    result = subprocess.run(cmd, cwd=base)

    if result.returncode == 0:
        print(f"\nBuild successful!")
        print(f"\nOutput location:")
        if sys.platform == 'darwin':
            print(f"  dist/{app_name}.app (macOS application bundle)")
        elif sys.platform == 'win32':
            print(f"  dist/{app_name}/ (folder with {app_name}.exe)")
        else:
            print(f"  dist/{app_name}/ (folder with {app_name} executable)")
    else:
        print("\nBuild failed!")
        sys.exit(1)


def run_build(app_name: str, app_dir: Path = None):
    """Main entry point: parse --clean flag and run the build."""
    if '--clean' in sys.argv:
        clean_build(app_dir)
    build(app_name, app_dir)
