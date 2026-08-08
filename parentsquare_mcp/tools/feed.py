"""Feed browsing and post reading."""

from __future__ import annotations

import json
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from .. import routes
from ..client import Page, client
from ..hints import READ_ONLY
from ..media import inline_attachment
from ..parsers import (
    abs_url,
    attachments,
    clamp,
    count_from,
    date_from,
    dedupe,
    first,
    id_from,
    matches,
    progress,
    result,
    rich_text,
    rows,
    txt,
)

ITEM_SELECTORS = [
    ".feed-item",
    ".post-wrapper",
    ".post-container",
    "article.post",
    ".post",
    "[data-post-id]",
    '[id^="post_"]',
    '[id^="feed_"]',
    "li.feed",
    ".card",
]
TITLE_SELECTORS = [".post-title", ".feed-title", ".title", "h2 a", "h2", "h3 a", "h3", "h4", "a.subject"]
AUTHOR_SELECTORS = [".author", ".post-author", ".by-line", ".byline", ".sender", ".user-name"]
DATE_SELECTORS = ["time", ".date", ".post-date", ".timestamp", ".created-at", "[datetime]"]
BODY_SELECTORS = [".post-body", ".post-content", ".feed-body", ".body", ".content", ".description", ".message"]
GROUP_SELECTORS = [".group-name", ".post-group", ".audience", ".recipients"]


def parse_feed_items(page: Page) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    for el in rows(page.soup, ITEM_SELECTORS):
        text = txt(el)
        if not text:
            continue

        anchor = (
            el.select_one('a[href*="/feeds/"]') or el.select_one('a[href*="/posts/"]') or el.select_one("a[href]")
        )
        href = anchor.get("href") if anchor else None
        post_id = el.get("data-post-id") or id_from(href, "feeds", "posts")

        body = txt(first(el, BODY_SELECTORS))
        item: dict[str, Any] = {
            "id": post_id,
            "title": txt(first(el, TITLE_SELECTORS)) or clamp(text.split("\n")[0], 160),
            "author": txt(first(el, AUTHOR_SELECTORS)) or None,
            "date": date_from(el, DATE_SELECTORS),
            "group": txt(first(el, GROUP_SELECTORS)) or None,
            "summary": clamp(body or text, 600),
            "url": abs_url(href, page.url),
            "attachment_names": [a["name"] for a in attachments(el, page.url)],
            "comment_count": count_from(text, "comments?", "replies"),
        }

        signup = progress(text)
        if signup and any(word in text.lower() for word in ("item", "slot", "spot", "volunteer", "sign up")):
            item["signup_progress"] = signup

        items.append(item)

    return dedupe(items, "id")


def _load_feed(candidates: list[str], label: str, page_number: int) -> Page:
    if page_number > 1:
        direct = client.get_page(f"{candidates[0]}?page={page_number}", optional=True)
        if direct is not None:
            return direct
    return client.get_first_page(candidates, label=label)


def register(mcp: MCPServer) -> None:
    @mcp.tool(
        annotations=READ_ONLY,
        title="Browse the school feed",
        description=(
            "Browse the paginated ParentSquare feed: post titles, authors, dates, summaries, attachment names "
            "and links. Use this to find something, then get_post for the full text and attachments."
        ),
    )
    def get_feeds(
        page: Annotated[int, Field(description="Page number, 1-based.", ge=1)] = 1,
        school_id: Annotated[str | None, Field(description="Limit to one school (see list_schools).")] = None,
        query: Annotated[
            str | None,
            Field(description="Case-insensitive filter on title, author, group and summary, applied after fetching."),
        ] = None,
    ) -> dict[str, Any]:
        candidates = routes.school_feed(school_id) if school_id else routes.FEED
        loaded = _load_feed(candidates, "feed", page)

        items = parse_feed_items(loaded)
        scanned = len(items)
        if query:
            items = [i for i in items if matches(i, query, "title", "author", "summary", "group")]

        note = None
        if query and not items and scanned:
            note = f'No posts on page {page} matched "{query}" — try another page.'

        extra: dict[str, Any] = {"page_number": page}
        if query:
            extra |= {"query": query, "matched": len(items), "scanned_on_page": scanned}

        return result(items=items, page=loaded, source=loaded.url, extra=extra, note=note)

    @mcp.tool(
        annotations=READ_ONLY,
        title="Read a full post",
        description=(
            "Full details for one post: body text, comments, poll results, signup items, and — when "
            "include_attachments is on — the contents of attached images and PDFs, so calendars and flyers "
            "can be read directly."
        ),
    )
    def get_post(
        post_id: Annotated[str, Field(description="Post id from get_feeds.")],
        include_attachments: Annotated[
            bool, Field(description="Download and inline images/PDFs attached to the post.")
        ] = True,
    ):
        loaded = client.get_first_page(routes.post(post_id), label=f"post {post_id}")
        soup, url = loaded.soup, loaded.url

        container = first(soup, [".post-detail", ".post-show", ".feed-item", ".post", "main", "#content"]) or soup.body
        heading = soup.select_one("h1")

        post: dict[str, Any] = {
            "id": post_id,
            "title": txt(first(container, TITLE_SELECTORS)) or txt(heading) or None,
            "author": txt(first(container, AUTHOR_SELECTORS)) or None,
            "date": date_from(container, DATE_SELECTORS),
            "group": txt(first(container, GROUP_SELECTORS)) or None,
            "body": rich_text(first(container, BODY_SELECTORS) or container, url),
            "url": url,
        }

        comments = [
            {
                "author": txt(first(el, AUTHOR_SELECTORS)) or None,
                "date": date_from(el, DATE_SELECTORS),
                "text": clamp(txt(el), 1500),
            }
            for el in rows(container, [".comment", ".comments li", ".comment-item", '[id^="comment_"]'])
        ]
        if comments:
            post["comments"] = comments

        poll_options = [
            {"option": txt(el), "votes": count_from(txt(el), "votes?", "responses?")}
            for el in rows(container, [".poll-option", ".poll .option", ".poll-result", '[class*="pollOption"]'])
        ]
        if poll_options:
            post["poll"] = {"options": poll_options}

        signup_items = [
            {"item": clamp(txt(el), 300), "progress": progress(txt(el))}
            for el in rows(container, [".signup-item", ".signup-slot", ".slot", ".signup li"])
        ]
        if signup_items:
            post["signup_items"] = signup_items

        found = attachments(container, url)
        post["attachments"] = found

        blocks: list[Any] = [json.dumps(post, indent=2)]
        if include_attachments and found:
            for attachment in found[:10]:
                blocks.extend(inline_attachment(attachment["url"], attachment["name"]))
            if len(found) > 10:
                blocks.append(f"[{len(found) - 10} further attachments not inlined]")
        return blocks

    @mcp.tool(
        annotations=READ_ONLY,
        title="Posts from one group",
        description="Posts belonging to a specific ParentSquare group (see list_groups for ids).",
    )
    def get_group_feed(
        group_id: Annotated[str, Field(description="Group id from list_groups.")],
        page: Annotated[int, Field(description="Page number, 1-based.", ge=1)] = 1,
    ) -> dict[str, Any]:
        loaded = _load_feed(routes.group_feed(group_id), f"group {group_id} feed", page)
        items = parse_feed_items(loaded)
        heading = loaded.soup.select_one("h1")
        return result(
            items=items,
            page=loaded,
            source=loaded.url,
            extra={"group_id": group_id, "page_number": page, "group_name": txt(heading) or None},
        )
