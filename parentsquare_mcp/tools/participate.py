"""The things a parent is asked to act on: signups, notices, polls, forms, payments, volunteer hours."""

from __future__ import annotations

import re
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from .. import routes
from ..client import client
from ..hints import READ_ONLY
from ..parsers import (
    abs_url,
    clamp,
    count_from,
    date_from,
    dedupe,
    first,
    id_from,
    money_from,
    progress,
    result,
    rows,
    txt,
)

GENERIC_ROWS = [
    ".list-item",
    ".item",
    ".feed-item",
    ".post",
    "table tbody tr",
]
DATE_SELECTORS = ["time", ".date", ".due-date", ".deadline", ".timestamp", "[datetime]"]
TITLE_SELECTORS = [".title", ".name", ".subject", "h2", "h3", "h4", "a"]

_DUE_RE = re.compile(r"\b(?:due|closes|deadline|by)\b[:\s]*([^\n]{3,60})", re.I)
_STATUS_RE = re.compile(r"\b(signed|unsigned|completed|incomplete|pending|paid|unpaid|submitted|not submitted)\b", re.I)
_JUNK_TITLE_RE = re.compile(
    r"^(switch account|manage account|sign out|home|cancel|submit|add another account)$",
    re.I,
)
_EMPTY_RE = re.compile(r"\bno (posts|polls|sign.?ups|items|forms|payments|results)\b", re.I)


def _base_row(el: Any, base_url: str) -> dict[str, Any] | None:
    # Account-switcher / nav chrome must never become a list row.
    classes = " ".join(el.get("class") or [])
    if "switch-account" in classes or el.select_one(".switch-accounts-header, #current-user-account-menu"):
        return None
    text = txt(el)
    if not text or len(text) < 3:
        return None
    anchor = el.select_one("a[href]")
    href = anchor.get("href") if anchor else None
    title = txt(first(el, TITLE_SELECTORS)) or clamp(text.split("\n")[0], 200)
    if not title or _JUNK_TITLE_RE.match(title.strip()):
        return None
    return {
        "title": title,
        "url": abs_url(href, base_url),
        "id": id_from(href),
        "date": date_from(el, DATE_SELECTORS),
        "_text": text,
    }


def _content_root(soup: Any) -> Any:
    return first(soup, ["#feeds-list", "main#main-content", "main", "#main-content", "#content"]) or soup


def _empty_message(soup: Any) -> str | None:
    remark = first(soup, [".ps-remark", ".empty", ".no-results", ".blank-slate"])
    text = txt(remark) if remark is not None else ""
    if text and _EMPTY_RE.search(text):
        return text
    return None


def _collect(page: Any, row_selectors: list[str], enrich) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    root = _content_root(page.soup)
    for el in rows(root, row_selectors):
        row = _base_row(el, page.url)
        if row is None:
            continue
        text = row.pop("_text")
        enriched = enrich(row, text, el)
        if enriched is not None:
            items.append(enriched)
    return dedupe(items, "url")


def _due_from(text: str) -> str | None:
    match = _DUE_RE.search(text)
    return match.group(1).strip() if match else None


def _status_from(text: str) -> str | None:
    match = _STATUS_RE.search(text)
    return match.group(1).lower() if match else None


def _wrap(page: Any, items: list[dict[str, Any]], key: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    empty = _empty_message(page.soup) if not items else None
    if empty:
        body = {"source": page.url, "count": 0, key: [], "note": empty, **(extra or {})}
        return body
    return result(items=items, page=page, source=page.url, key=key, extra=extra or {})


def register(mcp: MCPServer) -> None:
    @mcp.tool(
        annotations=READ_ONLY,
        title="List signups and RSVPs",
        description=(
            "Open sign-ups, RSVPs and volunteer slots, with progress like \"53/103 Items\" so you can see what "
            "still needs filling."
        ),
    )
    def list_signups() -> dict[str, Any]:
        loaded = client.get_first_page(routes.SIGNUPS, label="signups", section="signups")

        def enrich(row, text, el):
            row["progress"] = progress(text)
            row["due"] = _due_from(text)
            slots = [
                {"item": clamp(txt(slot), 200), "progress": progress(txt(slot))}
                for slot in rows(el, [".signup-item", ".slot", ".signup-slot"])
            ]
            if slots:
                row["slots"] = slots
            return row

        return _wrap(loaded, _collect(loaded, [".signup", *GENERIC_ROWS], enrich), "signups")

    @mcp.tool(
        annotations=READ_ONLY,
        title="List notices",
        description="Alerts, urgent notices and secure documents sent to your account.",
    )
    def list_notices() -> dict[str, Any]:
        loaded = client.get_first_page(routes.NOTICES, label="notices", section="notices")

        def enrich(row, text, el):
            lowered = text.lower()
            row["kind"] = (
                "secure document"
                if "secure" in lowered or "document" in lowered
                else "alert"
                if "alert" in lowered or "urgent" in lowered
                else None
            )
            row["unread"] = "unread" in " ".join(el.get("class") or []).lower()
            row["preview"] = clamp(text, 400)
            return row

        return _wrap(loaded, _collect(loaded, [".notice", ".alert-item", *GENERIC_ROWS], enrich), "notices")

    @mcp.tool(
        annotations=READ_ONLY,
        title="List polls",
        description="Polls with their options, vote counts and the option currently in the lead.",
    )
    def list_polls() -> dict[str, Any]:
        loaded = client.get_first_page(routes.POLLS, label="polls", section="polls")

        def enrich(row, text, el):
            options = []
            for option in rows(el, [".poll-option", ".option", ".poll-result", "li"]):
                label = txt(option)
                if not label:
                    continue
                options.append({"option": clamp(label, 200), "votes": count_from(label, "votes?", "responses?")})
            row["options"] = options
            voted = [o for o in options if o["votes"] is not None]
            row["winning_option"] = max(voted, key=lambda o: o["votes"])["option"] if voted else None
            row["total_votes"] = sum(o["votes"] for o in voted) if voted else None
            row["closes"] = _due_from(text)
            return row

        return _wrap(loaded, _collect(loaded, [".poll", *GENERIC_ROWS], enrich), "polls")

    @mcp.tool(
        annotations=READ_ONLY,
        title="List forms",
        description="Permission slips and signable forms, with whether each one is still outstanding.",
    )
    def list_forms() -> dict[str, Any]:
        loaded = client.get_first_page(routes.FORMS, label="forms", section="forms")

        def enrich(row, text, el):
            row["status"] = _status_from(text)
            row["due"] = _due_from(text)
            row["needs_action"] = row["status"] in {"unsigned", "incomplete", "pending", "not submitted"}
            row["student"] = txt(first(el, [".student", ".student-name", ".child"])) or None
            return row

        items = _collect(loaded, [".form", ".form-item", ".permission-slip", *GENERIC_ROWS], enrich)
        outstanding = [i for i in items if i.get("needs_action")]
        return _wrap(loaded, items, "forms", extra={"outstanding_count": len(outstanding)})

    @mcp.tool(
        annotations=READ_ONLY,
        title="List payments",
        description="Payment items and fees with prices, plus totals for what is due and what is paid.",
    )
    def list_payments() -> dict[str, Any]:
        loaded = client.get_first_page(routes.PAYMENTS, label="payments", section="payments")

        def enrich(row, text, el):
            row["amount"] = money_from(txt(first(el, [".price", ".amount", ".cost"])) or text)
            row["status"] = _status_from(text)
            row["due"] = _due_from(text)
            row["student"] = txt(first(el, [".student", ".student-name", ".child"])) or None
            return row

        items = _collect(loaded, [".payment", ".payment-item", ".fee", ".product", *GENERIC_ROWS], enrich)
        amounts = [i["amount"] for i in items if i.get("amount") is not None]
        unpaid = [i for i in items if i.get("amount") is not None and i.get("status") != "paid"]

        return _wrap(
            loaded,
            items,
            "payments",
            extra={
                "summary": {
                    "items_with_price": len(amounts),
                    "total_listed": round(sum(amounts), 2) if amounts else None,
                    "total_outstanding": round(sum(i["amount"] for i in unpaid), 2) if unpaid else None,
                }
            },
        )

    @mcp.tool(
        annotations=READ_ONLY,
        title="List volunteer hours",
        description="Volunteer hours logged on your account, with the total.",
    )
    def list_volunteer_hours() -> dict[str, Any]:
        loaded = client.get_first_page(routes.VOLUNTEER_HOURS, label="volunteer hours", section="volunteer_hours")

        def enrich(row, text, el):
            hours_text = txt(first(el, [".hours", ".duration", ".time"])) or text
            match = re.search(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\b", hours_text, re.I)
            row["hours"] = float(match.group(1)) if match else None
            row["activity"] = row["title"]
            row["status"] = _status_from(text)
            return row

        items = _collect(loaded, [".volunteer-hour", ".hour-entry", *GENERIC_ROWS], enrich)
        logged = [i["hours"] for i in items if i.get("hours") is not None]

        return _wrap(loaded, items, "entries", extra={"total_hours": round(sum(logged), 2) if logged else None})


# _wrap is defined above with empty-state handling.
