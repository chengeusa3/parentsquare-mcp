"""MCP server exposing a ParentSquare parent account."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from .tools import MODULES

INSTRUCTIONS = """\
Read-only access to a ParentSquare parent account: school posts, calendars, messages, staff directory,
signups, forms, payments and files.

Getting oriented: `list_schools` gives school and student ids that most other tools accept, and
`list_school_features` shows which sections a school actually uses.

Finding something: `get_feeds` browses the feed (it takes a `query` filter and a `page`), then `get_post`
returns the full text plus the contents of attached images and PDFs — school calendars and flyers are very
often posted as attachments rather than as calendar entries, and `get_post` can read them.

If a tool answers with `page_text` and a note about nothing matching the expected layout, the district's
HTML differs from what the parser expects. `debug_fetch` will show what the page really contains.
"""


def build_server() -> MCPServer:
    mcp = MCPServer("parentsquare", instructions=INSTRUCTIONS)
    for module in MODULES:
        module.register(mcp)
    return mcp


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
