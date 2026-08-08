"""Tool annotations, so clients know what is safe to call unattended."""

from __future__ import annotations

from mcp.types import ToolAnnotations

#: Reads from ParentSquare and changes nothing, anywhere.
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=True)

#: Reads from ParentSquare but writes a file to the local disk.
SAVES_LOCALLY = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True)
