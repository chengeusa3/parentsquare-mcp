"""Calendar events, from the ICS subscription feed where one exists."""

from __future__ import annotations

import datetime as dt
import re
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from .. import routes
from ..client import Page, client
from ..config import config
from ..hints import READ_ONLY
from ..parsers import abs_url, clamp, date_from, page_text, txt

ICS_HINT_RE = re.compile(r"\.ics(\?|$)|^webcal:|subscribe|ical|calendar_feed", re.I)


def discover_ics_url() -> str | None:
    """ParentSquare puts a per-user subscription link on the calendar page."""
    if config.ics_url:
        return config.ics_url

    try:
        page = client.get_first_page(routes.CALENDAR, label="calendar", section="calendar")
    except Exception:  # noqa: BLE001 - absence is a normal outcome here
        return None

    for anchor in page.soup.select("a[href]"):
        href = anchor.get("href") or ""
        if ICS_HINT_RE.search(href):
            return abs_url(re.sub(r"^webcal:", "https:", href, flags=re.I), page.url)
    return None


def _iso(value: Any) -> str | None:
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    return None


def _shape(event: Any) -> dict[str, Any]:
    start = event.get("DTSTART")
    end = event.get("DTEND")
    start_value = start.dt if start is not None else None
    end_value = end.dt if end is not None else None
    description = str(event.get("DESCRIPTION") or "").strip()

    return {
        "title": str(event.get("SUMMARY") or "(untitled)"),
        "start": _iso(start_value),
        "end": _iso(end_value),
        "all_day": isinstance(start_value, dt.date) and not isinstance(start_value, dt.datetime),
        "location": str(event.get("LOCATION") or "") or None,
        "description": clamp(description, 1500) or None,
        "url": str(event.get("URL") or "") or None,
        "uid": str(event.get("UID") or "") or None,
    }


def parse_ics(data: bytes, start: dt.date, end: dt.date) -> list[dict[str, Any]]:
    """Parse an ICS feed and expand recurring events across the window."""
    from icalendar import Calendar

    calendar = Calendar.from_ical(data)

    try:
        import recurring_ical_events

        occurrences = recurring_ical_events.of(calendar).between(start, end)
    except Exception:  # noqa: BLE001 - fall back to non-recurring events
        occurrences = []
        for component in calendar.walk("VEVENT"):
            value = component.get("DTSTART")
            if value is None:
                continue
            when = value.dt
            when_date = when.date() if isinstance(when, dt.datetime) else when
            if start <= when_date <= end:
                occurrences.append(component)

    events = [_shape(event) for event in occurrences]
    return sorted(events, key=lambda e: (e["start"] or ""))


def parse_html_calendar(page: Page) -> list[dict[str, Any]]:
    """Secondary source: whatever the HTML calendar view happens to render."""
    events: list[dict[str, Any]] = []
    for el in page.soup.select('.event, .calendar-event, .fc-event, [class*="eventItem"]'):
        text = txt(el)
        if not text:
            continue
        anchor = el.select_one("a[href]")
        location = el.select_one(".location")
        events.append(
            {
                "title": clamp(text.split("\n")[0], 200),
                "start": date_from(el, ["time", "[datetime]"]) or el.get("data-date"),
                "end": None,
                "all_day": None,
                "location": txt(location) or None,
                "description": clamp(text, 500),
                "url": abs_url(anchor.get("href") if anchor else None, page.url),
                "uid": None,
            }
        )
    return events


ATTACHMENT_HINT = (
    "No calendar events found. Many schools post the month calendar as an image or PDF flyer instead of "
    "filling in the ParentSquare calendar. Try get_feeds with query \"calendar\", then get_post with "
    "include_attachments=true on any result — an attached calendar can be read directly. list_files is "
    "also worth checking."
)


def register(mcp: MCPServer) -> None:
    @mcp.tool(
        annotations=READ_ONLY,
        title="School calendar events",
        description=(
            "Structured calendar events (title, start/end, location, description) from the ParentSquare ICS "
            "subscription feed, with recurring events expanded over a date range. Falls back to the HTML "
            "calendar view, and when the calendar is empty explains how to find calendars posted as image "
            "or PDF attachments instead."
        ),
    )
    def get_calendar_events(
        days_ahead: Annotated[int, Field(description="How far forward to look.", ge=1, le=400)] = 60,
        days_back: Annotated[int, Field(description="How far back to look.", ge=0, le=400)] = 0,
        query: Annotated[
            str | None, Field(description="Case-insensitive filter on title, location and description.")
        ] = None,
    ) -> dict[str, Any]:
        today = dt.date.today()
        start = today - dt.timedelta(days=days_back)
        end = today + dt.timedelta(days=days_ahead)

        events: list[dict[str, Any]] = []
        source: str | None = None
        notes: list[str] = []

        ics_url = discover_ics_url()
        if ics_url:
            try:
                data = client.get_binary(ics_url)["content"]
                events = parse_ics(data, start, end)
                source = ics_url
            except Exception as err:  # noqa: BLE001 - report, then fall back
                notes.append(f"Could not read the ICS feed ({err}).")
        else:
            notes.append(
                "No ICS subscription link found on the calendar page. If you have one, set PARENTSQUARE_ICS_URL "
                '— it is under Calendar → Subscribe / "Add to my calendar" in ParentSquare.'
            )

        html_page: Page | None = None
        if not events:
            try:
                html_page = client.get_first_page(routes.CALENDAR, label="calendar", section="calendar")
            except Exception:  # noqa: BLE001
                html_page = None
            if html_page is not None:
                events = parse_html_calendar(html_page)
                if events:
                    source = html_page.url

        if query:
            needle = query.lower()
            events = [
                e
                for e in events
                if needle in " ".join(str(e.get(f) or "") for f in ("title", "location", "description")).lower()
            ]

        body: dict[str, Any] = {
            "source": source,
            "range": {"from": start.isoformat(), "to": end.isoformat()},
            "count": len(events),
            "events": events,
        }
        if not events:
            notes.append(ATTACHMENT_HINT)
            if html_page is not None:
                body["page_text"] = page_text(html_page.soup, 3000)
        if notes:
            body["note"] = " ".join(notes)
        return body
