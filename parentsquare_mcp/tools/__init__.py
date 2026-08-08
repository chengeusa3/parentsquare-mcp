"""Tool modules. Each exposes ``register(mcp)``."""

from . import calendar, comms, debug, discovery, feed, files, participate

MODULES = [feed, calendar, comms, files, participate, discovery, debug]

__all__ = ["MODULES", "calendar", "comms", "debug", "discovery", "feed", "files", "participate"]
