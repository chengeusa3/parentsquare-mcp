#!/usr/bin/env python3
"""Run every test suite. None of them touch the real ParentSquare."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUITES = ["test_parsers.py", "test_server.py", "test_stdio.py", "test_auth.py"]


def main() -> int:
    failed: list[str] = []

    for suite in SUITES:
        print(f"\n{'=' * 60}\n{suite}\n{'=' * 60}")
        proc = subprocess.run([sys.executable, str(HERE / suite)], capture_output=True, text=True)
        for line in proc.stdout.splitlines():
            if "HTTP Request" not in line:
                print(line)
        if proc.returncode != 0:
            failed.append(suite)
            print(proc.stderr.strip()[-1500:], file=sys.stderr)

    print(f"\n{'=' * 60}")
    if failed:
        print(f"FAILED: {', '.join(failed)}")
        return 1
    print(f"All {len(SUITES)} suites passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
