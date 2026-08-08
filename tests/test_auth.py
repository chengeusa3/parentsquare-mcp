"""Authentication tests — the part most likely to bite on first run.

Each case needs its own process, because the client is a module-level singleton
that reads the environment at import time. This script re-executes itself with
`--case <name>` to get a clean interpreter per scenario.

Run: ./.venv/bin/python tests/test_auth.py
"""

from __future__ import annotations

import http.server
import os
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_server import GOOD_EMAIL, GOOD_PASSWORD, Handler, free_port  # noqa: E402

STATE_DIR = ROOT / ".test-state"


# --------------------------------------------------------------------- cases
# Each returns a list of "label|passed|detail" lines on stdout.


def case_no_credentials() -> list[str]:
    from parentsquare_mcp.client import AuthError, client

    try:
        client.ensure_auth()
    except AuthError as err:
        message = str(err)
        return [
            f"raises AuthError with no credentials|1|",
            f"names PARENTSQUARE_COOKIE|{int('PARENTSQUARE_COOKIE' in message)}|{message[:80]}",
            f"names the login script|{int('scripts/login.py' in message)}|{message[:80]}",
            f"mentions SSO|{int('SSO' in message)}|{message[:80]}",
        ]
    return ["raises AuthError with no credentials|0|no error raised"]


def case_bad_cookie() -> list[str]:
    from parentsquare_mcp.client import AuthError, client

    try:
        client.ensure_auth()
    except AuthError as err:
        return [f"a stale cookie is rejected|1|", f"explains how to refresh|{int('cookie' in str(err).lower())}|"]
    return ["a stale cookie is rejected|0|accepted a bogus session"]


def case_password_login() -> list[str]:
    from parentsquare_mcp.client import client
    from parentsquare_mcp.config import config

    lines = []
    client.ensure_auth()
    lines.append("password login succeeds|1|")
    lines.append(f"session file is written|{int(config.session_file.exists())}|{config.session_file}")

    mode = oct(config.session_file.stat().st_mode)[-3:]
    lines.append(f"session file is owner-only|{int(mode == '600')}|mode {mode}")

    page = client.get_page("/feeds")
    lines.append(f"the session works afterwards|{int(page is not None)}|")
    return lines


def case_wrong_password() -> list[str]:
    from parentsquare_mcp.client import AuthError, client

    try:
        client.ensure_auth()
    except AuthError as err:
        message = str(err)
        return [
            "a wrong password is reported|1|",
            f"surfaces the site's own message|{int('Invalid email or password' in message)}|{message[:90]}",
        ]
    return ["a wrong password is reported|0|login unexpectedly succeeded"]


CASES = {
    "no_credentials": case_no_credentials,
    "bad_cookie": case_bad_cookie,
    "password_login": case_password_login,
    "wrong_password": case_wrong_password,
}


# ------------------------------------------------------------------- harness

ENVIRONMENTS = {
    "no_credentials": {},
    "bad_cookie": {"PARENTSQUARE_COOKIE": "psq_session=expired-and-invalid"},
    "password_login": {"PARENTSQUARE_EMAIL": GOOD_EMAIL, "PARENTSQUARE_PASSWORD": GOOD_PASSWORD},
    "wrong_password": {"PARENTSQUARE_EMAIL": GOOD_EMAIL, "PARENTSQUARE_PASSWORD": "wrong"},
}


def main() -> int:
    if "--case" in sys.argv:
        name = sys.argv[sys.argv.index("--case") + 1]
        for line in CASES[name]():
            print(line)
        return 0

    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"fake ParentSquare on {base_url}")

    failures: list[str] = []
    try:
        for name, extra_env in ENVIRONMENTS.items():
            print(f"\n{name}")
            if STATE_DIR.exists():
                for stale in STATE_DIR.iterdir():
                    stale.unlink()

            env = {
                k: v
                for k, v in os.environ.items()
                if not k.startswith("PARENTSQUARE_")
            }
            env |= {
                "PARENTSQUARE_BASE_URL": base_url,
                "PARENTSQUARE_STATE_DIR": str(STATE_DIR),
                **extra_env,
            }

            proc = subprocess.run(
                [sys.executable, __file__, "--case", name],
                capture_output=True,
                text=True,
                env=env,
                cwd=str(ROOT),
            )
            if proc.returncode != 0:
                failures.append(f"{name} crashed: {proc.stderr.strip()[-300:]}")
                print(f"  FAIL case crashed\n{proc.stderr.strip()[-500:]}")
                continue

            for line in proc.stdout.strip().splitlines():
                label, passed, detail = (line.split("|", 2) + ["", ""])[:3]
                if passed == "1":
                    print(f"  ok   {label}")
                else:
                    failures.append(f"{label} {detail}".strip())
                    print(f"  FAIL {label} {detail}")
    finally:
        server.shutdown()

    print()
    if failures:
        print(f"{len(failures)} failing check(s):")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
