"""Full protocol test: a real MCP client talking to the server over stdio.

Starts the fake ParentSquare from test_server.py, launches the real server as a
subprocess exactly the way Claude Desktop will, and drives it through a genuine
MCP handshake. This is what proves the thing actually works as an MCP server —
not just that the functions return the right dicts.

Run: ./.venv/bin/python tests/test_stdio.py
"""

from __future__ import annotations

import asyncio
import http.server
import json
import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from mcp import ClientSession, StdioServerParameters, stdio_client  # noqa: E402

from test_server import Handler, free_port  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        failures.append(f"{label} {detail}".strip())
        print(f"  FAIL {label} {detail}")


def text_of(result) -> str:
    return " ".join(getattr(block, "text", "") for block in result.content)


async def run(base_url: str) -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "parentsquare_mcp"],
        cwd=str(ROOT),
        env={
            **os.environ,
            "PARENTSQUARE_BASE_URL": base_url,
            "PARENTSQUARE_COOKIE": "psq_session=fake-session-value",
            "PARENTSQUARE_STATE_DIR": str(ROOT / ".test-state"),
            "PARENTSQUARE_DOWNLOAD_DIR": str(ROOT / ".test-downloads"),
        },
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print("\nhandshake")
            check("server initializes", init.server_info.name == "parentsquare", init.server_info.name)
            check("server ships instructions", bool(init.instructions), repr(init.instructions)[:60])

            print("\ntool discovery")
            tools = (await session.list_tools()).tools
            names = {t.name for t in tools}
            check("all 23 tools are advertised", len(tools) == 23, str(len(tools)))
            check("get_post is advertised", "get_post" in names)
            check(
                "read-only tools are marked",
                next(t for t in tools if t.name == "get_feeds").annotations.read_only_hint is True,
            )
            check(
                "download_file is not marked read-only",
                next(t for t in tools if t.name == "download_file").annotations.read_only_hint is False,
            )

            print("\ncalls over the wire")
            feeds = await session.call_tool("get_feeds", {})
            check("get_feeds succeeds", feeds.is_error is not True, text_of(feeds)[:200])
            body = json.loads(text_of(feeds))
            check("get_feeds returns both posts", body["count"] == 2, str(body.get("count")))

            post = await session.call_tool("get_post", {"post_id": "9001"})
            types = [block.type for block in post.content]
            check("get_post returns an image content block", "image" in types, str(types))
            check("get_post returns text alongside it", "text" in types, str(types))

            failing = await session.call_tool("list_notices", {})
            check("a broken route comes back as isError", failing.is_error is True, str(failing.is_error))
            check("the error survives the wire", "routes.py" in text_of(failing), text_of(failing)[:200])

            no_auth = await session.call_tool("debug_fetch", {"path": "/feeds"})
            check("debug_fetch works", no_auth.is_error is not True, text_of(no_auth)[:120])


def main() -> int:
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"fake ParentSquare on {base_url}")

    try:
        asyncio.run(run(base_url))
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
