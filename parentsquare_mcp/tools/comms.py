"""Message threads and the staff directory."""

from __future__ import annotations

import json
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from .. import routes
from ..client import client
from ..hints import READ_ONLY
from ..media import inline_attachment
from ..parsers import (
    abs_url,
    attachments,
    clamp,
    date_from,
    dedupe,
    email_from,
    first,
    id_from,
    page_text,
    phone_from,
    result,
    rich_text,
    rows,
    txt,
)

CONVERSATION_ROWS = [
    ".conversation",
    ".conversation-item",
    ".message-thread",
    "tr.conversation",
    '[id^="conversation_"]',
    ".thread",
]
MESSAGE_ROWS = [".message", ".message-item", ".conversation-message", '[id^="message_"]', ".chat-message"]
DIRECTORY_ROWS = [
    ".directory-entry",
    ".staff-member",
    ".directory tr",
    "table.directory tbody tr",
    ".member",
    "tbody tr",
]
DATE_SELECTORS = ["time", ".date", ".timestamp", "[datetime]"]
NAME_SELECTORS = [".sender", ".author", ".from", ".name", "strong"]


def register(mcp: MCPServer) -> None:
    @mcp.tool(
        annotations=READ_ONLY,
        title="List message threads",
        description="Direct-message threads: who they are with, subject, last-message preview and unread state.",
    )
    def list_conversations(
        page: Annotated[int, Field(description="Page number, 1-based.", ge=1)] = 1,
    ) -> dict[str, Any]:
        loaded = None
        if page > 1:
            loaded = client.get_page(f"{routes.CONVERSATIONS[0]}?page={page}", optional=True)
        if loaded is None:
            loaded = client.get_first_page(routes.CONVERSATIONS, label="conversations")

        items: list[dict[str, Any]] = []
        for el in rows(loaded.soup, CONVERSATION_ROWS):
            text = txt(el)
            if not text:
                continue
            anchor = el.select_one("a[href]")
            href = (anchor.get("href") if anchor else None) or el.get("data-href")
            first_cell = el.select_one("td:first-child")

            items.append(
                {
                    "id": el.get("data-conversation-id") or id_from(href, "conversations", "messages"),
                    "with": txt(first(el, [".participants", ".with", ".name", ".sender"]) or first_cell) or None,
                    "subject": txt(first(el, [".subject", ".title", ".conversation-subject"])) or None,
                    "preview": clamp(txt(first(el, [".preview", ".snippet", ".last-message", ".body"])) or text, 300),
                    "date": date_from(el, DATE_SELECTORS),
                    "unread": "unread" in " ".join(el.get("class") or []).lower()
                    or el.select_one(".unread, .badge") is not None,
                    "url": abs_url(href, loaded.url),
                }
            )

        return result(
            items=dedupe(items, "id"),
            page=loaded,
            source=loaded.url,
            extra={"page_number": page},
            key="conversations",
        )

    @mcp.tool(
        annotations=READ_ONLY,
        title="Read a message thread",
        description="Every message in one thread, in order, with senders, timestamps and any attachments.",
    )
    def get_conversation(
        conversation_id: Annotated[str, Field(description="Thread id from list_conversations.")],
        include_attachments: Annotated[
            bool, Field(description="Download and inline images/PDFs sent in the thread.")
        ] = False,
    ):
        loaded = client.get_first_page(
            routes.conversation(conversation_id), label=f"conversation {conversation_id}"
        )
        soup, url = loaded.soup, loaded.url

        messages: list[dict[str, Any]] = []
        files: list[dict[str, str]] = []

        for el in rows(soup, MESSAGE_ROWS):
            text = txt(el)
            if not text:
                continue
            found = attachments(el, url)
            files.extend(found)
            messages.append(
                {
                    "from": txt(first(el, NAME_SELECTORS)) or None,
                    "date": date_from(el, DATE_SELECTORS),
                    "text": rich_text(first(el, [".body", ".content", ".text", ".message-body"]) or el, url, 4000),
                    "attachment_names": [f["name"] for f in found],
                }
            )

        subject = first(soup, ["h1", ".subject", ".conversation-subject"])
        body = result(
            items=messages,
            page=loaded,
            source=url,
            extra={"conversation_id": conversation_id, "subject": txt(subject) or None},
            key="messages",
        )

        blocks: list[Any] = [json.dumps(body, indent=2)]
        if include_attachments:
            for file in files[:10]:
                blocks.extend(inline_attachment(file["url"], file["name"]))
        return blocks

    @mcp.tool(
        annotations=READ_ONLY,
        title="Staff directory",
        description="School staff directory as structured rows: name, role/title, phone, email and user id.",
    )
    def get_directory(
        school_id: Annotated[str | None, Field(description="Limit to one school (see list_schools).")] = None,
        query: Annotated[str | None, Field(description="Case-insensitive filter on name and role.")] = None,
    ) -> dict[str, Any]:
        candidates = routes.school_directory(school_id) if school_id else routes.DIRECTORY
        loaded = client.get_first_page(candidates, label="directory")
        soup, url = loaded.soup, loaded.url

        items: list[dict[str, Any]] = []
        for el in rows(soup, DIRECTORY_ROWS):
            text = txt(el)
            if not text or text.lower().startswith(("name", "staff", "title", "role")):
                continue  # header row

            anchor = (
                el.select_one('a[href*="/users/"]') or el.select_one('a[href*="/directory/"]') or el.select_one("a[href]")
            )
            href = anchor.get("href") if anchor else None
            cells = el.select("td")

            name = txt(first(el, [".name", ".staff-name", ".member-name", "a"]))
            if not name and cells:
                name = txt(cells[0])
            if not name:
                name = clamp(text.split("\n")[0], 120)
            if not name:
                continue

            role = txt(first(el, [".role", ".title", ".position", ".job-title"]))
            if not role and len(cells) > 1:
                role = txt(cells[1])

            items.append(
                {
                    "name": name,
                    "role": role or None,
                    "phone": phone_from(text),
                    "email": email_from(text),
                    "user_id": id_from(href, "users", "directory"),
                    "url": abs_url(href, url),
                }
            )

        items = dedupe(items, "user_id")
        if query:
            needle = query.lower()
            items = [i for i in items if needle in f"{i['name']} {i.get('role') or ''}".lower()]

        return result(
            items=items,
            page=loaded,
            source=url,
            extra={"query": query} if query else {},
            key="staff",
        )

    @mcp.tool(
        annotations=READ_ONLY,
        title="Staff member details",
        description=(
            "Full profile for one staff member — email, phone, role, office hours — including their profile "
            "photo inline."
        ),
    )
    def get_staff_member(
        user_id: Annotated[str, Field(description="User id from get_directory.")],
        include_photo: Annotated[bool, Field(description="Inline the profile photo.")] = True,
    ):
        loaded = client.get_first_page(routes.staff_member(user_id), label=f"staff member {user_id}")
        soup, url = loaded.soup, loaded.url

        container = first(soup, [".profile", ".user-profile", ".staff-detail", "main", "#content"]) or soup.body
        text = txt(container)

        mailto = container.select_one('a[href^="mailto:"]') if container else None
        tel = container.select_one('a[href^="tel:"]') if container else None

        person: dict[str, Any] = {
            "user_id": user_id,
            "name": txt(first(container, ["h1", ".profile-name", ".name"])) or None,
            "role": txt(first(container, [".role", ".title", ".position"])) or None,
            "email": (mailto.get("href", "")[7:] if mailto else None) or email_from(text),
            "phone": (tel.get("href", "")[4:] if tel else None) or phone_from(text),
            "office_hours": txt(first(container, [".office-hours", ".hours", '[class*="officeHours"]'])) or None,
            "bio": clamp(txt(first(container, [".bio", ".about", ".description"])), 2000) or None,
            "url": url,
        }

        photo = None
        for img in container.select("img[src]") if container else []:
            candidate = abs_url(img.get("src"), url)
            if candidate and not any(word in candidate.lower() for word in ("logo", "spacer", "blank", "icon")):
                photo = candidate
                break
        person["photo_url"] = photo

        if not person["name"] and not person["email"]:
            person["page_text"] = page_text(soup, 3000)

        blocks: list[Any] = [json.dumps(person, indent=2)]
        if include_photo and photo:
            blocks.extend(inline_attachment(photo, f"{person['name'] or 'staff'} photo"))
        return blocks
