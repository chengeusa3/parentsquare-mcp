"""HTML parsing helpers shared by every tool.

The guiding rule: never fail a tool call because a selector missed. Structured
parsing is attempted first; when it finds nothing, the caller falls back to the
readable text of the page so Claude still gets the information.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Iterable, Sequence

from bs4 import BeautifulSoup, Tag

BOILERPLATE = "script, style, noscript, svg, iframe, nav, header, footer, .navbar, .sidebar, #sidebar"

_PHONE_RE = re.compile(r"(\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}(?:\s*(?:x|ext\.?)\s*\d+)?)", re.I)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PROGRESS_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
_MONEY_RE = re.compile(r"\$\s?([\d,]+(?:\.\d{2})?)")
_FILE_RE = re.compile(r"\.(pdf|docx?|xlsx?|pptx?|csv|txt|rtf|jpe?g|png|gif|heic|webp|ics)(\?|$)", re.I)
_FILE_PATH_RE = re.compile(r"/(attachments|files|documents|uploads|rails/active_storage)/", re.I)
_CHROME_IMG_RE = re.compile(r"avatar|icon|logo|spacer|blank|emoji", re.I)


def txt(node: Tag | None) -> str:
    if node is None:
        return ""
    text = node.get_text("\n")
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()


def clamp(text: str | None, limit: int = 4000) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n… [truncated, {len(text) - limit} more characters]"


def abs_url(href: str | None, base: str) -> str | None:
    if not href:
        return None
    try:
        return urllib.parse.urljoin(base, href)
    except ValueError:
        return None


def id_from(href: str | None, *kinds: str) -> str | None:
    """Pull a numeric id out of a href like /feeds/12345 or /users/99?x=1."""
    s = str(href or "")
    for kind in kinds:
        match = re.search(rf"/{kind}/(\d+)", s)
        if match:
            return match.group(1)
    tail = re.search(r"/(\d+)(?:[/?#]|$)", s)
    return tail.group(1) if tail else None


def first(node: Tag | BeautifulSoup | None, selectors: Sequence[str]) -> Tag | None:
    """First selector that matches anything, so parsers tolerate app variants."""
    if node is None:
        return None
    for selector in selectors:
        found = node.select_one(selector)
        if found is not None:
            return found
    return None


def rows(node: Tag | BeautifulSoup | None, selectors: Sequence[str]) -> list[Tag]:
    """Rows of a list view — empty list rather than an exception when nothing matches."""
    if node is None:
        return []
    for selector in selectors:
        found = node.select(selector)
        if found:
            return found
    return []


def page_text(page_soup: BeautifulSoup, limit: int = 6000) -> str:
    """Readable text of the main content area, for when structured parsing misses."""
    main = first(page_soup, ["main", "#main", "#content", ".main-content", ".content"]) or page_soup.body
    if main is None:
        return ""
    clone = BeautifulSoup(str(main), "lxml")
    for junk in clone.select(BOILERPLATE):
        junk.decompose()
    return clamp(txt(clone), limit)


#: Tags that should end a line when flattening prose.
_BLOCK_TAGS = (
    "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "blockquote", "table", "ul", "ol", "pre",
)


def rich_text(node: Tag | None, base: str, limit: int = 8000) -> str:
    """Body text that keeps links as ``label (url)`` so they can be followed.

    Unlike :func:`txt`, this preserves sentences: inline elements stay on their
    line and only block elements break, so a paragraph with a link in the middle
    reads as prose rather than as one word per line.
    """
    if node is None:
        return ""

    clone = BeautifulSoup(str(node), "lxml")
    for junk in clone.select("script, style"):
        junk.decompose()

    for anchor in clone.select("a[href]"):
        href = abs_url(anchor.get("href"), base)
        label = anchor.get_text(" ", strip=True)
        if not href or not label:
            continue
        # A label that is already a URL needs no annotating.
        if "://" in label or label.rstrip("/") == href.rstrip("/"):
            anchor.replace_with(label)
        else:
            anchor.replace_with(f"{label} ({href})")

    for br in clone.find_all("br"):
        br.replace_with("\n")
    for tag in clone.find_all(_BLOCK_TAGS):
        tag.insert_after("\n")

    text = clone.get_text("").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return clamp(text.strip(), limit)


def attachments(node: Tag | None, base: str) -> list[dict[str, str]]:
    """Attachment links and content images found inside a block."""
    if node is None:
        return []
    found: dict[str, dict[str, str]] = {}

    for anchor in node.select("a[href]"):
        href = abs_url(anchor.get("href"), base)
        if not href:
            continue
        if not (_FILE_RE.search(href) or _FILE_PATH_RE.search(href)):
            continue
        name = anchor.get_text(" ", strip=True) or urllib.parse.unquote(href.rsplit("/", 1)[-1].split("?")[0])
        found.setdefault(href, {"name": name, "url": href, "kind": "attachment"})

    for img in node.select("img[src], img[data-src]"):
        src = abs_url(img.get("src") or img.get("data-src"), base)
        if not src or _CHROME_IMG_RE.search(src):  # skip UI chrome
            continue
        found.setdefault(src, {"name": img.get("alt") or "image", "url": src, "kind": "image"})

    return list(found.values())


def progress(text: str | None) -> dict[str, Any] | None:
    """``53/103 Items`` style progress that ParentSquare uses on signups."""
    match = _PROGRESS_RE.search(text or "")
    if not match:
        return None
    filled, total = int(match.group(1)), int(match.group(2))
    return {"filled": filled, "total": total, "remaining": max(0, total - filled), "label": f"{filled}/{total}"}


def count_from(text: str | None, *words: str) -> int | None:
    match = re.search(rf"(\d[\d,]*)\s*(?:{'|'.join(words)})", text or "", re.I)
    return int(match.group(1).replace(",", "")) if match else None


def money_from(text: str | None) -> float | None:
    match = _MONEY_RE.search(text or "")
    return float(match.group(1).replace(",", "")) if match else None


def phone_from(text: str | None) -> str | None:
    match = _PHONE_RE.search(text or "")
    return match.group(1) if match else None


def email_from(text: str | None) -> str | None:
    match = _EMAIL_RE.search(text or "")
    return match.group(0) if match else None


def date_from(node: Tag | None, selectors: Sequence[str]) -> str | None:
    el = first(node, selectors)
    if el is None:
        return None
    return el.get("datetime") or txt(el) or None


def result(
    *,
    items: list[dict[str, Any]],
    page: Any,
    source: str,
    note: str | None = None,
    extra: dict[str, Any] | None = None,
    key: str = "items",
) -> dict[str, Any]:
    """The shape every list tool answers in.

    A selector drift degrades to "here is the page" rather than an error.
    """
    body: dict[str, Any] = {"source": source, **(extra or {})}
    body["count"] = len(items)
    body[key] = items
    if note:
        body["note"] = note
    if not items and page is not None:
        prefix = f"{note} " if note else ""
        body["note"] = (
            prefix + "No rows matched the expected layout — falling back to the raw page text below. "
            "If this keeps happening, the selectors for this tool need updating for your district."
        )
        body["page_text"] = page_text(page.soup)
    return body


def dedupe(items: Iterable[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for item in items:
        value = item.get(key)
        if value and value in seen:
            continue
        if value:
            seen.add(value)
        output.append(item)
    return output


def matches(item: dict[str, Any], query: str | None, *fields: str) -> bool:
    if not query:
        return True
    haystack = " ".join(str(item.get(f) or "") for f in fields).lower()
    return query.lower() in haystack
