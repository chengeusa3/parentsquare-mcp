#!/usr/bin/env python3
"""Check this server against your real ParentSquare account.

Two passes:

1. **Routes** — for every path in ``routes.py``, report whether it loads, 404s,
   or bounces to the sign-in page. Promote whichever candidate wins to the front
   of its list in ``routes.py``.
2. **Tools** — run each read-only tool with default arguments and report how many
   rows it parsed. A tool that returns 0 rows *and* a ``page_text`` fallback has
   selectors that need adjusting for your district; use ``debug_fetch`` on the
   reported URL to see the real markup.

Nothing here writes to ParentSquare.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parentsquare_mcp import routes  # noqa: E402
from parentsquare_mcp.client import AuthError, client  # noqa: E402
from parentsquare_mcp.config import config  # noqa: E402
from parentsquare_mcp.server import build_server  # noqa: E402

GREEN, YELLOW, RED, DIM, RESET = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[0m"

ROUTE_GROUPS: dict[str, list[str]] = {
    "feed": routes.FEED,
    "calendar": routes.CALENDAR,
    "conversations": routes.CONVERSATIONS,
    "directory": routes.DIRECTORY,
    "photos": routes.PHOTOS,
    "files": routes.FILES,
    "signups": routes.SIGNUPS,
    "notices": routes.NOTICES,
    "polls": routes.POLLS,
    "forms": routes.FORMS,
    "payments": routes.PAYMENTS,
    "volunteer_hours": routes.VOLUNTEER_HOURS,
    "schools": routes.SCHOOLS,
    "groups": routes.GROUPS,
    "links": routes.LINKS,
    "students": routes.STUDENTS,
}

#: Tools that are safe to call with no arguments.
DEFAULT_TOOLS = [
    "list_schools",
    "get_feeds",
    "get_calendar_events",
    "list_conversations",
    "get_directory",
    "list_photos",
    "list_files",
    "list_signups",
    "list_notices",
    "list_polls",
    "list_forms",
    "list_payments",
    "list_volunteer_hours",
    "list_groups",
    "list_links",
    "list_school_features",
    "get_student_dashboard",
]


def check_routes() -> dict[str, str | None]:
    winners: dict[str, str | None] = {}
    print(f"\n{DIM}— routes —{RESET}")

    for name, candidates in ROUTE_GROUPS.items():
        winner = None
        details = []
        for candidate in candidates:
            try:
                page = client.get_page(candidate, optional=True)
            except AuthError:
                raise
            except Exception as err:  # noqa: BLE001
                details.append(f"{candidate} → error ({type(err).__name__})")
                continue
            if page is None:
                details.append(f"{candidate} → not found")
                continue
            if winner is None:
                winner = candidate
            details.append(f"{candidate} → ok ({len(page.html) // 1024} KB)")

        if winner:
            winners[name] = winner
            print(f"  {GREEN}ok  {RESET} {name:<18} {winner}")
            if len(candidates) > 1:
                for line in details:
                    print(f"       {DIM}{line}{RESET}")
            continue

        # No candidate worked — see whether the sidebar knows where it lives.
        discovered = client.discover_section(name)
        if discovered:
            winners[name] = discovered
            print(f"  {YELLOW}NAV {RESET} {name:<18} {discovered}  {DIM}(found via the sidebar){RESET}")
            print(f"       {DIM}add '{discovered}' to routes.py to skip the lookup{RESET}")
        else:
            winners[name] = None
            print(f"  {RED}MISS{RESET} {name:<18} (no candidate worked, and no sidebar link matched)")
        for line in details:
            print(f"       {DIM}{line}{RESET}")

    return winners


def _payload(result: object) -> dict | None:
    """Pull the JSON body out of whatever shape call_tool returned.

    SDK 2.0 hands back a CallToolResult; older builds returned a tuple or a bare
    list of content blocks. Accept all three so this script survives an upgrade.
    """
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    content = getattr(result, "content", None)
    if content is None:
        if isinstance(result, tuple):
            content = result[0]
        elif isinstance(result, dict):
            return result
        else:
            content = result

    if isinstance(content, list):
        for block in content:
            text = getattr(block, "text", None)
            if text:
                try:
                    return json.loads(text)
                except ValueError:
                    continue
    return None


async def check_tools() -> None:
    mcp = build_server()
    registered = {tool.name for tool in await mcp.list_tools()}
    print(f"\n{DIM}— tools ({len(registered)} registered) —{RESET}")

    for name in DEFAULT_TOOLS:
        if name not in registered:
            print(f"  {RED}GONE{RESET} {name}")
            continue
        try:
            body = _payload(await mcp.call_tool(name, {}))
        except Exception as err:  # noqa: BLE001
            print(f"  {RED}FAIL{RESET} {name:<22} {type(err).__name__}: {err}")
            continue

        if body is None:
            print(f"  {YELLOW}????{RESET} {name:<22} returned content this script could not read")
            continue

        count = body.get("count")
        if count is None:
            count = len(body.get("events") or body.get("classes") or [])
        fell_back = "page_text" in body

        if count and not fell_back:
            print(f"  {GREEN}ok  {RESET} {name:<22} {count} rows")
        elif fell_back:
            print(f"  {YELLOW}THIN{RESET} {name:<22} 0 rows — selectors need work. Source: {body.get('source')}")
        else:
            print(f"  {DIM}empty{RESET} {name:<21} 0 rows, no fallback (section may just be unused)")

        if body.get("note"):
            print(f"       {DIM}{str(body['note'])[:160]}{RESET}")


def main() -> int:
    print(f"ParentSquare doctor — {config.base_url}")
    print(f"session file: {config.session_file} ({'present' if config.session_file.exists() else 'absent'})")

    try:
        client.ensure_auth()
    except AuthError as err:
        print(f"\n{RED}Not signed in.{RESET} {err}", file=sys.stderr)
        return 1
    print(f"{GREEN}Signed in.{RESET}")

    check_routes()
    asyncio.run(check_tools())

    print(
        f"\n{DIM}Next: promote each winning route to the front of its list in parentsquare_mcp/routes.py "
        f"(NAV routes work already — adding them just saves a lookup). For any MISS, find the URL in your "
        f"browser. For any THIN tool, run debug_fetch on its source URL to see the real markup.{RESET}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
