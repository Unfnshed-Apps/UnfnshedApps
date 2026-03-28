#!/usr/bin/env python3
"""
Run all tests across the Unfnshed monorepo.

Each app runs in its own pytest process to avoid sys.path/module conflicts
(all apps use `from src.config import ...` with different `src` packages).
"""

import subprocess
import sys
from pathlib import Path

MONOREPO = Path(__file__).parent

# (name, test_dir, required_package_to_check)
TEST_SUITES = [
    ("shared", MONOREPO / "shared" / "tests", None),
    ("Unfnest", MONOREPO / "Unfnest" / "tests", None),
    ("UnfnCNC", MONOREPO / "UnfnCNC" / "tests", None),
    ("Unfnventory", MONOREPO / "Unfnventory" / "tests", None),
    ("Unfnshed-Admin", MONOREPO / "Unfnshed-Admin" / "tests", None),
    ("Unfnshed-Server", MONOREPO / "Unfnshed-Server" / "tests", "fastapi"),
]


def main():
    failed = []
    total_passed = 0
    verbose = "-v" if "--verbose" in sys.argv or "-v" in sys.argv else "-q"

    skipped = []

    for name, test_dir, required_pkg in TEST_SUITES:
        if not any(test_dir.glob("test_*.py")):
            continue

        if required_pkg:
            try:
                __import__(required_pkg)
            except ImportError:
                skipped.append(f"{name} (needs {required_pkg})")
                continue

        print(f"\n{'='*60}")
        print(f"  {name}")
        print(f"{'='*60}")

        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_dir), verbose, "--tb=short"],
            cwd=str(MONOREPO),
        )

        if result.returncode != 0:
            failed.append(name)
        else:
            total_passed += 1

    print(f"\n{'='*60}")
    if skipped:
        print(f"  Skipped: {', '.join(skipped)}")
    if failed:
        print(f"  FAILED: {', '.join(failed)}")
        sys.exit(1)
    else:
        print(f"  All {total_passed} test suites passed")
        sys.exit(0)


if __name__ == "__main__":
    main()
