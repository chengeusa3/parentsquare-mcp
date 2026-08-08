"""Parser tests against synthetic ParentSquare-shaped HTML.

These do not touch the network. They prove the extraction pipeline works, so
that when the selectors are confirmed against a real account the plumbing behind
them is already known-good.

Run: ./.venv/bin/python -m pytest tests/ -q   (or just ./.venv/bin/python tests/test_parsers.py)
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bs4 import BeautifulSoup  # noqa: E402

from parentsquare_mcp.client import Page  # noqa: E402
from parentsquare_mcp.parsers import (  # noqa: E402
    attachments,
    count_from,
    dedupe,
    id_from,
    money_from,
    phone_from,
    progress,
    result,
    rich_text,
    txt,
)
from parentsquare_mcp.tools.calendar import parse_ics  # noqa: E402
from parentsquare_mcp.tools.feed import parse_feed_items  # noqa: E402

BASE = "https://www.parentsquare.com/feeds"

FEED_HTML = """
<html><body><main>
  <div class="feed-item" data-post-id="9001">
    <h3 class="post-title"><a href="/feeds/9001">Field Trip to the Aquarium</a></h3>
    <span class="author">Ms. Rivera</span>
    <time datetime="2026-08-03T15:04:00Z">Aug 3</time>
    <div class="group-name">3rd Grade</div>
    <div class="post-body">Permission slips are due Friday. See the attached flyer.</div>
    <a href="/attachments/551/aquarium-flyer.pdf">Aquarium Flyer</a>
    <img src="https://cdn.parentsquare.com/photos/551/whale.jpg" alt="whale">
    <img src="https://cdn.parentsquare.com/avatar/12.png" alt="avatar">
    <span class="comments">4 comments</span>
  </div>
  <div class="feed-item" data-post-id="9002">
    <h3 class="post-title"><a href="/feeds/9002">Book Fair Volunteers</a></h3>
    <span class="author">PTA</span>
    <div class="post-body">We still need help. 53/103 Items filled.</div>
  </div>
  <div class="feed-item" data-post-id="9002">
    <h3 class="post-title"><a href="/feeds/9002">Book Fair Volunteers</a></h3>
  </div>
</main></body></html>
"""

ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//ParentSquare//EN
BEGIN:VEVENT
UID:evt-1@parentsquare.com
DTSTART:20260810T160000Z
DTEND:20260810T170000Z
SUMMARY:Back to School Night
LOCATION:Cafeteria
DESCRIPTION:Meet the teachers.
END:VEVENT
BEGIN:VEVENT
UID:evt-2@parentsquare.com
DTSTART:20260812T190000Z
DTEND:20260812T200000Z
RRULE:FREQ=WEEKLY;BYDAY=WE;COUNT=4
SUMMARY:Chess Club
END:VEVENT
BEGIN:VEVENT
UID:evt-3@parentsquare.com
DTSTART;VALUE=DATE:20261225
DTEND;VALUE=DATE:20261226
SUMMARY:Winter Break
END:VEVENT
END:VCALENDAR
"""

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        failures.append(f"{label} {detail}".strip())
        print(f"  FAIL {label} {detail}")


def page_from(html: str, url: str = BASE) -> Page:
    return Page(soup=BeautifulSoup(html, "lxml"), html=html, url=url)


def test_feed_parsing() -> None:
    print("\nfeed parsing")
    items = parse_feed_items(page_from(FEED_HTML))

    check("de-duplicates repeated post ids", len(items) == 2, f"got {len(items)}")
    first_item = items[0]
    check("extracts id", first_item["id"] == "9001", repr(first_item["id"]))
    check("extracts title", first_item["title"] == "Field Trip to the Aquarium", repr(first_item["title"]))
    check("extracts author", first_item["author"] == "Ms. Rivera", repr(first_item["author"]))
    check("prefers datetime attribute", first_item["date"] == "2026-08-03T15:04:00Z", repr(first_item["date"]))
    check("extracts group", first_item["group"] == "3rd Grade", repr(first_item["group"]))
    check("resolves relative url", first_item["url"] == "https://www.parentsquare.com/feeds/9001", first_item["url"])
    check("counts comments", first_item["comment_count"] == 4, repr(first_item["comment_count"]))
    check(
        "finds the pdf attachment",
        "Aquarium Flyer" in first_item["attachment_names"],
        repr(first_item["attachment_names"]),
    )
    check(
        "keeps content images but drops avatars",
        "whale" in first_item["attachment_names"] and "avatar" not in first_item["attachment_names"],
        repr(first_item["attachment_names"]),
    )
    check(
        "reads signup progress",
        items[1].get("signup_progress", {}).get("remaining") == 50,
        repr(items[1].get("signup_progress")),
    )


def test_helpers() -> None:
    print("\nhelpers")
    check("progress parses 53/103", progress("53/103 Items")["label"] == "53/103")
    check("progress ignores plain text", progress("no numbers here") is None)
    check("money parses $1,250.50", money_from("Total: $1,250.50 due") == 1250.50)
    check("phone parses (805) 555-1212", phone_from("call (805) 555-1212 today") == "(805) 555-1212")
    check("count_from reads members", count_from("42 members", "members?") == 42)
    check("id_from reads /users/99", id_from("/users/99?tab=x", "users") == "99")
    check("id_from ignores wrong kind", id_from("/groups/7", "users") == "7", "falls through to trailing id")
    check("dedupe keeps first", len(dedupe([{"id": "a"}, {"id": "a"}, {"id": "b"}], "id")) == 2)

    soup = BeautifulSoup('<div>Read the <a href="/policy">policy</a> now</div>', "lxml")
    rendered = rich_text(soup.div, BASE)
    check("rich_text inlines link urls", "policy (https://www.parentsquare.com/policy)" in rendered, rendered)
    check(
        "rich_text keeps a sentence on one line",
        rendered.strip() == "Read the policy (https://www.parentsquare.com/policy) now",
        repr(rendered),
    )

    prose = BeautifulSoup(
        "<div><p>First paragraph.</p><p>Second one with <b>bold</b> inside.</p></div>", "lxml"
    )
    flattened = rich_text(prose.div, BASE)
    check(
        "rich_text breaks on blocks, not inline tags",
        flattened == "First paragraph.\nSecond one with bold inside.",
        repr(flattened),
    )

    raw_link = BeautifulSoup('<div><a href="https://x.test/a">https://x.test/a</a></div>', "lxml")
    check(
        "rich_text does not annotate a bare url",
        rich_text(raw_link.div, BASE) == "https://x.test/a",
        repr(rich_text(raw_link.div, BASE)),
    )

    node = BeautifulSoup('<div><a href="/files/1/menu.pdf">Lunch Menu</a></div>', "lxml").div
    found = attachments(node, BASE)
    check("attachments resolves urls", found[0]["url"].endswith("/files/1/menu.pdf"), repr(found))


def test_result_fallback() -> None:
    print("\nfallback behaviour")
    page = page_from("<html><body><main><p>Nothing structured here at all.</p></main></body></html>")

    empty = result(items=[], page=page, source=BASE, key="items")
    check("empty result carries page_text", "page_text" in empty and "Nothing structured" in empty["page_text"])
    check("empty result explains itself", "selectors" in empty.get("note", "").lower())

    full = result(items=[{"id": "1"}], page=page, source=BASE, key="items")
    check("populated result omits page_text", "page_text" not in full)
    check("populated result counts rows", full["count"] == 1)


def test_ics() -> None:
    print("\nics parsing")
    start = dt.date(2026, 8, 1)
    end = dt.date(2026, 12, 31)
    events = parse_ics(ICS.encode(), start, end)
    titles = [e["title"] for e in events]

    check("finds the one-off event", "Back to School Night" in titles)
    check("expands the weekly recurrence to 4", titles.count("Chess Club") == 4, str(titles.count("Chess Club")))
    check("sorts by start", [e["start"] for e in events] == sorted(e["start"] for e in events))

    night = next(e for e in events if e["title"] == "Back to School Night")
    check("keeps location", night["location"] == "Cafeteria", repr(night["location"]))
    check("keeps description", night["description"] == "Meet the teachers.", repr(night["description"]))
    check("marks timed events as not all-day", night["all_day"] is False)

    holiday = next(e for e in events if e["title"] == "Winter Break")
    check("marks date-only events as all-day", holiday["all_day"] is True)

    narrow = parse_ics(ICS.encode(), dt.date(2026, 8, 1), dt.date(2026, 8, 11))
    check("respects the window", [e["title"] for e in narrow] == ["Back to School Night"], str(narrow))


def main() -> int:
    test_feed_parsing()
    test_helpers()
    test_result_fallback()
    test_ics()

    print()
    if failures:
        print(f"{len(failures)} failing check(s):")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
