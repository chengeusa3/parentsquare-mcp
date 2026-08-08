"""Configuration, all of it from the environment."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


@dataclass
class Config:
    #: Districts sometimes sit on a vanity host; override if yours does.
    base_url: str = field(default_factory=lambda: _env("PARENTSQUARE_BASE_URL", "https://www.parentsquare.com").rstrip("/"))

    #: Raw ``Cookie:`` header copied from a logged-in browser tab. Preferred auth.
    cookie: str = field(default_factory=lambda: _env("PARENTSQUARE_COOKIE"))

    #: Fallback auth. Works for password logins only — not district SSO.
    email: str = field(default_factory=lambda: _env("PARENTSQUARE_EMAIL"))
    password: str = field(default_factory=lambda: _env("PARENTSQUARE_PASSWORD"))

    #: Personal ICS subscription URL from ParentSquare's calendar page.
    ics_url: str = field(default_factory=lambda: _env("PARENTSQUARE_ICS_URL"))

    state_dir: Path = field(
        default_factory=lambda: Path(_env("PARENTSQUARE_STATE_DIR", str(Path.home() / ".parentsquare-mcp")))
    )
    download_dir: Path = field(
        default_factory=lambda: Path(
            _env("PARENTSQUARE_DOWNLOAD_DIR", str(Path.home() / "Downloads" / "ParentSquare"))
        )
    )

    #: Attachments larger than this are linked rather than inlined into the reply.
    max_inline_bytes: int = field(default_factory=lambda: _env_int("PARENTSQUARE_MAX_INLINE_BYTES", 4_000_000))
    timeout_s: int = field(default_factory=lambda: _env_int("PARENTSQUARE_TIMEOUT_S", 30))
    user_agent: str = field(default_factory=lambda: _env("PARENTSQUARE_USER_AGENT", DEFAULT_USER_AGENT))
    debug: bool = field(default_factory=lambda: _env("PARENTSQUARE_DEBUG") == "1")

    @property
    def session_file(self) -> Path:
        return self.state_dir / "session.json"

    def ensure_state_dir(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.chmod(0o700)


config = Config()


def debug_log(*args: object) -> None:
    """stdout is the MCP transport — diagnostics must go to stderr."""
    if config.debug:
        print("[parentsquare]", *args, file=sys.stderr, flush=True)
