#!/usr/bin/env python3
"""Sign in once and cache the session cookies.

Only works for districts that use a ParentSquare email + password. If yours signs
in through Google, Clever or ClassLink, use the PARENTSQUARE_COOKIE method
described in the README instead.
"""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parentsquare_mcp.client import AuthError, client  # noqa: E402
from parentsquare_mcp.config import config  # noqa: E402


def main() -> int:
    email = os.environ.get("PARENTSQUARE_EMAIL") or input("ParentSquare email: ").strip()
    password = os.environ.get("PARENTSQUARE_PASSWORD") or getpass.getpass("Password: ")

    if not email or not password:
        print("Email and password are both required.", file=sys.stderr)
        return 2

    print(f"Signing in to {config.base_url} …")
    try:
        client.login(email, password)
    except AuthError as err:
        print(f"\nLogin failed: {err}", file=sys.stderr)
        return 1

    print(f"Signed in. Session saved to {config.session_file}")
    print("Now run: python scripts/doctor.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
