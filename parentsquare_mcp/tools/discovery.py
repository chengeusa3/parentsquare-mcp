"""Working out what this account actually contains: schools, students, groups, links."""

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
    dedupe,
    first,
    id_from,
    page_text,
    result,
    rows,
    txt,
)

SCHOOL_ROWS = [".school", ".school-item", ".school-card", '[class*="schoolRow"]', "li.school"]
STUDENT_ROWS = [".student", ".student-item", ".child", ".student-card", '[class*="studentRow"]']
GROUP_ROWS = [".group", ".group-item", ".group-card", "table tbody tr", "li.group"]
LINK_ROWS = [".link", ".quick-link", ".link-item", "li", "tr"]
NAV_SELECTORS = ["nav a[href]", ".sidebar a[href]", "#sidebar a[href]", ".nav a[href]", "aside a[href]"]


def register(mcp: MCPServer) -> None:
    @mcp.tool(
        annotations=READ_ONLY,
        title="List schools and students",
        description=(
            "The schools and students attached to your account, with their ids. Most other tools accept a "
            "school_id — start here to get one."
        ),
    )
    def list_schools() -> dict[str, Any]:
        loaded = client.get_first_page(routes.SCHOOLS, label="schools", section="schools")
        soup, url = loaded.soup, loaded.url

        schools: list[dict[str, Any]] = []
        students: list[dict[str, Any]] = []

        # Current ParentSquare: school + students live in the left switcher.
        switcher = soup.select_one("#switch-institutes-menu")
        if switcher is not None:
            school_id = id_from(url, "schools")
            for li in switcher.select("li.school-section"):
                student_anchor = li.select_one('a[href*="/students/"]')
                if student_anchor is not None:
                    href = student_anchor.get("href")
                    meta = txt(li.select_one(".truncate-text")) or ""
                    grade = None
                    school_name = None
                    if "•" in meta:
                        grade, _, school_name = [p.strip() for p in meta.partition("•")]
                    elif meta:
                        school_name = meta
                    students.append(
                        {
                            "id": id_from(href, "students"),
                            "name": txt(li.select_one("h4")) or txt(student_anchor),
                            "school": school_name or None,
                            "grade": grade or None,
                            "url": abs_url(href, url),
                        }
                    )
                else:
                    name = txt(li.select_one("h4")) or txt(li)
                    if not name:
                        continue
                    # Selected school often has no /schools/<id> link — use the page URL.
                    schools.append(
                        {
                            "id": school_id,
                            "name": name,
                            "url": abs_url(f"/schools/{school_id}", url) if school_id else url,
                        }
                    )

        if not schools:
            for el in rows(soup, SCHOOL_ROWS):
                anchor = el.select_one('a[href*="/schools/"]') or el.select_one("a[href]")
                href = anchor.get("href") if anchor else None
                name = txt(first(el, [".school-name", ".name", ".title", "h2", "h3", "a"])) or clamp(
                    txt(el).split("\n")[0], 120
                )
                if not name:
                    continue
                schools.append({"id": id_from(href, "schools"), "name": name, "url": abs_url(href, url)})

        # Fall back only to clean /schools/<id> links — not every href that contains /schools/.
        if not schools:
            for anchor in soup.select('a[href*="/schools/"]'):
                href = anchor.get("href") or ""
                if not re.search(r"/schools/\d+(?:/feeds)?/?$", href.split("?")[0]):
                    continue
                name = txt(anchor)
                if not name or len(name) > 80:
                    continue
                schools.append({"id": id_from(href, "schools"), "name": name, "url": abs_url(href, url)})

        if not students:
            for el in rows(soup, STUDENT_ROWS):
                anchor = el.select_one('a[href*="/students/"]') or el.select_one("a[href]")
                href = anchor.get("href") if anchor else None
                name = txt(first(el, [".student-name", ".name", "a"])) or clamp(txt(el).split("\n")[0], 120)
                if not name:
                    continue
                students.append(
                    {
                        "id": id_from(href, "students"),
                        "name": name,
                        "school": txt(first(el, [".school", ".school-name"])) or None,
                        "grade": txt(first(el, [".grade", ".grade-level"])) or None,
                        "url": abs_url(href, url),
                    }
                )

        body = result(items=dedupe(schools, "id"), page=loaded, source=url, key="schools")
        body["students"] = dedupe(students, "id")
        body["student_count"] = len(body["students"])
        return body

    @mcp.tool(
        annotations=READ_ONLY,
        title="Sections available for a school",
        description=(
            "Which ParentSquare sections a school actually has — parsed from its sidebar — so you know whether "
            "to bother with polls, payments, volunteer hours and so on."
        ),
    )
    def list_school_features(
        school_id: Annotated[str | None, Field(description="School id from list_schools. Omit for the default view.")] = None,
    ) -> dict[str, Any]:
        candidates = routes.school(school_id) if school_id else routes.FEED
        loaded = client.get_first_page(candidates, label="school page")
        soup, url = loaded.soup, loaded.url

        anchors = []
        for selector in NAV_SELECTORS:
            anchors = soup.select(selector)
            if anchors:
                break
        if not anchors:
            anchors = soup.select("a[href]")

        sections: list[dict[str, Any]] = []
        for anchor in anchors:
            label = txt(anchor)
            href = anchor.get("href")
            if not label or not href or len(label) > 40:
                continue
            lowered = label.lower()
            known = next((s for s in routes.KNOWN_SECTIONS if s in lowered), None)
            sections.append(
                {
                    "label": label,
                    "path": href,
                    "url": abs_url(href, url),
                    "recognized_as": known,
                }
            )

        sections = dedupe(sections, "url")
        return result(
            items=sections,
            page=loaded,
            source=url,
            key="sections",
            extra={
                "school_id": school_id,
                "recognized": sorted({s["recognized_as"] for s in sections if s["recognized_as"]}),
            },
        )

    @mcp.tool(
        annotations=READ_ONLY,
        title="List groups",
        description="ParentSquare groups — classes, clubs, committees — with member counts and whether you are a member.",
    )
    def list_groups(
        school_id: Annotated[str | None, Field(description="Limit to one school (see list_schools).")] = None,
        query: Annotated[str | None, Field(description="Case-insensitive filter on group name and description.")] = None,
    ) -> dict[str, Any]:
        candidates = routes.school_groups(school_id) if school_id else routes.GROUPS
        loaded = client.get_first_page(candidates, label="groups", section="groups")
        soup, url = loaded.soup, loaded.url

        items: list[dict[str, Any]] = []
        for el in rows(soup, GROUP_ROWS):
            text = txt(el)
            if not text:
                continue
            anchor = el.select_one('a[href*="/groups/"]') or el.select_one("a[href]")
            href = anchor.get("href") if anchor else None
            name = txt(first(el, [".group-name", ".name", ".title", "a", "h3"])) or clamp(text.split("\n")[0], 120)
            if not name:
                continue
            lowered = text.lower()
            items.append(
                {
                    "id": id_from(href, "groups"),
                    "name": name,
                    "description": clamp(txt(first(el, [".description", ".about", ".summary"])) or "", 400) or None,
                    "member_count": count_from(text, "members?", "people"),
                    "is_member": ("leave" in lowered or "joined" in lowered or "member" in lowered)
                    and "join " not in lowered,
                    "url": abs_url(href, url),
                }
            )

        # Many districts leave /groups nearly empty and only list groups in the feed filter.
        if not items:
            feed_candidates = routes.school_feed(school_id) if school_id else routes.FEED
            feed = client.get_first_page(feed_candidates, label="feed", section="feed")
            soup, url = feed.soup, feed.url
            for anchor in soup.select('a[href*="/groups/"]'):
                href = anchor.get("href") or ""
                name = txt(anchor)
                group_id = id_from(href, "groups")
                if not name or not group_id or len(name) > 120:
                    continue
                items.append(
                    {
                        "id": group_id,
                        "name": name,
                        "description": None,
                        "member_count": None,
                        "is_member": True,
                        "url": abs_url(href, url),
                    }
                )
            loaded = feed

        items = dedupe(items, "id")
        if query:
            needle = query.lower()
            items = [i for i in items if needle in f"{i['name']} {i.get('description') or ''}".lower()]

        return result(items=items, page=loaded, source=url, key="groups", extra={"query": query} if query else {})

    @mcp.tool(
        annotations=READ_ONLY,
        title="List quick links",
        description="Quick-access links the school has pinned — Google Drive folders, lunch menus, external sites.",
    )
    def list_links(
        school_id: Annotated[str | None, Field(description="Limit to one school (see list_schools).")] = None,
    ) -> dict[str, Any]:
        candidates = routes.school_links(school_id) if school_id else routes.LINKS
        loaded = client.get_first_page(candidates, label="links", section="links")
        soup, url = loaded.soup, loaded.url

        items: list[dict[str, Any]] = []
        for el in rows(soup, LINK_ROWS):
            anchor = el.select_one("a[href]")
            if anchor is None:
                continue
            href = abs_url(anchor.get("href"), url)
            label = txt(anchor)
            if not href or not label:
                continue
            external = not href.startswith(client.url("/").rstrip("/"))
            items.append(
                {
                    "label": label,
                    "url": href,
                    "description": clamp(txt(first(el, [".description", ".about"])) or "", 300) or None,
                    "external": external,
                }
            )

        return result(
            items=dedupe(items, "url"),
            page=loaded,
            source=url,
            key="links",
            extra={"school_id": school_id} if school_id else {},
        )

    @mcp.tool(
        annotations=READ_ONLY,
        title="Student dashboard",
        description="A student's school, grade, classes and teachers.",
    )
    def get_student_dashboard(
        student_id: Annotated[str | None, Field(description="Student id from list_schools. Omit for the default student.")] = None,
    ) -> dict[str, Any]:
        candidates = routes.student(student_id) if student_id else routes.STUDENTS
        loaded = client.get_first_page(candidates, label="student dashboard", section="students")
        soup, url = loaded.soup, loaded.url

        container = first(soup, [".student-detail", ".dashboard", "main", "#content"]) or soup.body

        classes: list[dict[str, Any]] = []
        for el in rows(container, [".class", ".course", ".section", ".class-item", "table tbody tr"]):
            text = txt(el)
            if not text:
                continue
            name = txt(first(el, [".class-name", ".course-name", ".name", "a", "td:first-child"])) or clamp(
                text.split("\n")[0], 120
            )
            if not name:
                continue
            teacher = txt(first(el, [".teacher", ".instructor", ".staff"])) or None
            teacher_anchor = el.select_one('a[href*="/users/"]')
            classes.append(
                {
                    "name": name,
                    "teacher": teacher,
                    "teacher_user_id": id_from(teacher_anchor.get("href") if teacher_anchor else None, "users"),
                    "period": txt(first(el, [".period", ".time"])) or None,
                }
            )

        dashboard: dict[str, Any] = {
            "source": url,
            "student_id": student_id,
            "name": txt(first(container, ["h1", ".student-name", ".name"])) or None,
            "school": txt(first(container, [".school", ".school-name"])) or None,
            "grade": txt(first(container, [".grade", ".grade-level"])) or None,
            "classes": dedupe(classes, "name"),
        }
        dashboard["class_count"] = len(dashboard["classes"])
        if not dashboard["classes"] and not dashboard["name"]:
            dashboard["note"] = (
                "Nothing matched the expected layout — raw page text below. Not every district enables the "
                "student dashboard; list_schools will show what this account has."
            )
            dashboard["page_text"] = page_text(soup)
        return dashboard
