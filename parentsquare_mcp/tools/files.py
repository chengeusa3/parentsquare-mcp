"""Photo galleries, document files, and saving attachments to disk."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from .. import routes
from ..client import client
from ..config import config
from ..hints import READ_ONLY, SAVES_LOCALLY
from ..media import inline_attachment, save_to_downloads
from ..parsers import abs_url, clamp, date_from, dedupe, first, result, rows, txt

PHOTO_ROWS = [".photo", ".gallery-item", ".album", ".photo-item", '[class*="photoCard"]', "li.photo"]
FILE_ROWS = [".file", ".file-item", ".document", "table tbody tr", "li.file", '[class*="fileRow"]']
DATE_SELECTORS = ["time", ".date", ".timestamp", "[datetime]"]


def register(mcp: MCPServer) -> None:
    @mcp.tool(
        annotations=READ_ONLY,
        title="List photos",
        description=(
            "Photos and photo albums shared by the school, with direct image URLs. Pass a URL to get_post's "
            "attachments or download_file to save one."
        ),
    )
    def list_photos(
        school_id: Annotated[str | None, Field(description="Limit to one school (see list_schools).")] = None,
        page: Annotated[int, Field(description="Page number, 1-based.", ge=1)] = 1,
    ) -> dict[str, Any]:
        candidates = routes.school_photos(school_id) if school_id else routes.PHOTOS
        loaded = None
        if page > 1:
            loaded = client.get_page(f"{candidates[0]}?page={page}", optional=True)
        if loaded is None:
            loaded = client.get_first_page(candidates, label="photos")

        items: list[dict[str, Any]] = []
        for el in rows(loaded.soup, PHOTO_ROWS):
            img = el.select_one("img[src], img[data-src]")
            anchor = el.select_one("a[href]")
            image_url = abs_url(img.get("src") or img.get("data-src") if img else None, loaded.url)
            link = abs_url(anchor.get("href") if anchor else None, loaded.url)
            if not image_url and not link:
                continue
            items.append(
                {
                    "title": txt(first(el, [".title", ".caption", ".album-name", "h3", "h4"]))
                    or (img.get("alt") if img else None)
                    or None,
                    "image_url": image_url,
                    "link": link,
                    "date": date_from(el, DATE_SELECTORS),
                }
            )

        # Galleries often render as bare <img> grids with no wrapper class.
        if not items:
            for img in loaded.soup.select("img[src]"):
                src = abs_url(img.get("src"), loaded.url)
                if not src or any(w in src.lower() for w in ("logo", "icon", "avatar", "spacer", "blank")):
                    continue
                items.append({"title": img.get("alt") or None, "image_url": src, "link": None, "date": None})

        return result(
            items=dedupe(items, "image_url"),
            page=loaded,
            source=loaded.url,
            extra={"page_number": page},
            key="photos",
        )

    @mcp.tool(
        annotations=READ_ONLY,
        title="List files",
        description="Documents the school has shared — handbooks, menus, forms, newsletters — with download URLs.",
    )
    def list_files(
        school_id: Annotated[str | None, Field(description="Limit to one school (see list_schools).")] = None,
        query: Annotated[str | None, Field(description="Case-insensitive filter on file name.")] = None,
    ) -> dict[str, Any]:
        candidates = routes.school_files(school_id) if school_id else routes.FILES
        loaded = client.get_first_page(candidates, label="files")

        items: list[dict[str, Any]] = []
        for el in rows(loaded.soup, FILE_ROWS):
            anchor = el.select_one("a[href]")
            if anchor is None:
                continue
            href = abs_url(anchor.get("href"), loaded.url)
            if not href:
                continue
            text = txt(el)
            items.append(
                {
                    "name": txt(anchor) or href.rsplit("/", 1)[-1],
                    "url": href,
                    "date": date_from(el, DATE_SELECTORS),
                    "description": clamp(text, 300) or None,
                }
            )

        items = dedupe(items, "url")
        if query:
            needle = query.lower()
            items = [i for i in items if needle in str(i["name"]).lower()]

        return result(
            items=items,
            page=loaded,
            source=loaded.url,
            extra={"query": query} if query else {},
            key="files",
        )

    @mcp.tool(
        annotations=SAVES_LOCALLY,
        title="Download a file",
        description=(
            f"Download any ParentSquare attachment to disk (default {config.download_dir}) and return the path. "
            "Use this for things too large to inline, or when you want to keep a copy."
        ),
    )
    def download_file(
        url: Annotated[str, Field(description="Attachment URL from get_post, list_files or list_photos.")],
        filename: Annotated[str | None, Field(description="Override the saved file name.")] = None,
        show: Annotated[bool, Field(description="Also inline the contents in the reply, if it is readable.")] = False,
    ):
        file = client.get_binary(url)
        path = save_to_downloads(file["content"], filename or file["filename"])

        summary = {
            "saved_to": str(path),
            "bytes": len(file["content"]),
            "content_type": file["content_type"],
            "source": file["url"],
        }
        blocks: list[Any] = [f"Saved {path.name} ({len(file['content']) / 1024:.0f} KB) to {path}"]
        if show:
            blocks.extend(inline_attachment(url, path.name))
        blocks.append(str(summary))
        return blocks
