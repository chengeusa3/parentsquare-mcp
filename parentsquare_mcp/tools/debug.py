"""A window into the raw pages, for when a selector needs fixing."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from ..client import client
from ..hints import READ_ONLY
from ..parsers import clamp, page_text


def register(mcp: MCPServer) -> None:
    @mcp.tool(
        annotations=READ_ONLY,
        title="Fetch a raw ParentSquare page",
        description=(
            "Escape hatch: fetch any ParentSquare path with your session and return its text, or its raw HTML. "
            "Use this when another tool reports that nothing matched the expected layout, to work out what the "
            "page really looks like — or to reach a section this server has no dedicated tool for."
        ),
    )
    def debug_fetch(
        path: Annotated[str, Field(description='Path or full URL, e.g. "/feeds" or "/schools/123/directory".')],
        raw_html: Annotated[bool, Field(description="Return raw HTML instead of readable text.")] = False,
        limit: Annotated[int, Field(description="Maximum characters to return.", ge=500, le=100_000)] = 8000,
    ) -> dict[str, Any]:
        page = client.get_page(path)
        assert page is not None
        return {
            "url": page.url,
            "bytes": len(page.html),
            "content": clamp(page.html if raw_html else page_text(page.soup, limit), limit),
        }
