"""Turning downloaded attachments into something Claude can actually read."""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import Image

from .client import client
from .config import config, debug_log
from .parsers import clamp

IMAGE_FORMATS = {
    "image/png": "png",
    "image/jpeg": "jpeg",
    "image/gif": "gif",
    "image/webp": "webp",
}

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._ -]+")


def safe_filename(name: str, fallback: str = "download") -> str:
    cleaned = _SAFE_NAME_RE.sub("_", (name or "").strip()).strip("._ ")
    return cleaned or fallback


def extract_pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - optional dependency
        debug_log("pypdf not installed; PDFs will not be read as text")
        return ""

    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages[:40]]
    except Exception as err:  # noqa: BLE001 - malformed PDFs are common
        debug_log("pdf text extraction failed:", err)
        return ""

    text = "\n".join(pages)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def save_to_downloads(data: bytes, filename: str) -> Path:
    config.download_dir.mkdir(parents=True, exist_ok=True)
    target = config.download_dir / safe_filename(filename)
    stem, suffix = target.stem, target.suffix
    counter = 1
    while target.exists():
        target = config.download_dir / f"{stem} ({counter}){suffix}"
        counter += 1
    target.write_bytes(data)
    return target


def to_content(file: dict[str, Any], label: str | None = None) -> list[Any]:
    """Render a downloaded file as MCP content blocks.

    Images become real image blocks so a flyer or a photographed calendar can be
    read directly. PDFs are converted to text where possible; scanned PDFs are
    saved to disk and reported, since there is nothing useful to inline.
    """
    data: bytes = file["content"]
    content_type: str = file["content_type"]
    filename = label or file["filename"]
    url = file["url"]
    size = len(data)

    if size > config.max_inline_bytes:
        return [
            f"[{filename} — {content_type}, {size / 1e6:.1f} MB — too large to inline. "
            f"Use download_file to save it: {url}]"
        ]

    if content_type in IMAGE_FORMATS:
        return [f"[image: {filename}]", Image(data=data, format=IMAGE_FORMATS[content_type])]

    if content_type in {"image/heic", "image/heif"}:
        return [f"[{filename} is a HEIC image and cannot be displayed inline. Save it with download_file: {url}]"]

    if content_type == "application/pdf":
        text = extract_pdf_text(data)
        if len(text) > 200:
            return [f"[pdf: {filename}]\n\n{clamp(text, 12000)}"]
        saved = save_to_downloads(data, filename if filename.lower().endswith(".pdf") else f"{filename}.pdf")
        return [
            f"[pdf: {filename} — no extractable text, so it is almost certainly a scan or an image-only "
            f"flyer. Saved to {saved} — open it directly, or ask to have it converted to an image.]"
        ]

    if content_type.startswith("text/") or content_type == "application/json":
        return [f"[{filename}]\n\n{clamp(data.decode('utf-8', errors='replace'), 8000)}"]

    return [f"[{filename} — {content_type}, {size / 1024:.0f} KB. Not inlineable; use download_file: {url}]"]


def inline_attachment(url: str, label: str | None = None) -> list[Any]:
    """Fetch and render an attachment, tolerating individual failures."""
    try:
        file = client.get_binary(url)
    except Exception as err:  # noqa: BLE001 - one bad attachment must not fail the tool
        return [f"[could not load attachment {label or url}: {err}]"]
    return to_content(file, label)
