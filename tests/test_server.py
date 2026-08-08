"""End-to-end test against a fake ParentSquare served on localhost.

Exercises the whole stack — HTTP client, cookie auth, route fallback, tool
registration, attachment inlining — without touching the real site.

Run: ./.venv/bin/python tests/test_server.py
"""

from __future__ import annotations

import asyncio
import base64
import http.server
import json
import os
import socket
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# A 1x1 PNG, so the image path is exercised with real bytes.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)

SIGNIN = """<html><body><h1>Sign in to ParentSquare</h1>
<form action="/sessions" method="post">
  <input type="hidden" name="authenticity_token" value="tok123">
  <input type="email" name="user[email]">
  <input type="password" name="user[password]">
</form></body></html>"""

# The sidebar is what route discovery mines when candidate paths all 404.
FEED = """<html><body>
<nav class="sidebar">
  <a href="/feeds">Posts</a>
  <a href="/my_forms">Forms</a>
  <a href="/school_pay">Payments</a>
  <a href="/dm">Messages</a>
</nav>
<main>
<div class="feed-item" data-post-id="9001">
  <h3 class="post-title"><a href="/feeds/9001">Field Trip to the Aquarium</a></h3>
  <span class="author">Ms. Rivera</span>
  <time datetime="2026-08-03T15:04:00Z">Aug 3</time>
  <div class="post-body">Permission slips due Friday.</div>
  <a href="/attachments/551/flyer.pdf">Aquarium Flyer</a>
</div>
<div class="feed-item" data-post-id="9002">
  <h3 class="post-title"><a href="/feeds/9002">Book Fair Volunteers</a></h3>
  <div class="post-body">We need help. 53/103 Items filled.</div>
</div>
</main></body></html>"""

POST = """<html><body><main class="post-detail">
<h1 class="post-title">Field Trip to the Aquarium</h1>
<span class="author">Ms. Rivera</span>
<div class="post-body"><p>Permission slips are due <b>Friday</b>.</p>
<p>Details in the <a href="/policy">policy</a>.</p></div>
<a href="/attachments/551/flyer.pdf">Aquarium Flyer</a>
<img src="/photos/whale.png" alt="whale photo">
<div class="comment"><span class="author">Dad</span><div>Can I chaperone?</div></div>
</main></body></html>"""

SCHOOLS = """<html><body><main>
<div class="school"><a href="/schools/77">Oak Elementary</a></div>
<div class="school"><a href="/schools/88">Pine Middle</a></div>
<div class="student"><a href="/students/5">Haoyu</a><span class="grade">Grade 3</span></div>
</main></body></html>"""

DIRECTORY = """<html><body><main><table class="directory"><tbody>
<tr><td>Name</td><td>Role</td></tr>
<tr class="directory-entry"><td><a href="/users/301">Ms. Rivera</a></td><td>3rd Grade Teacher</td>
    <td>(805) 555-1212</td></tr>
</tbody></table></main></body></html>"""

CALENDAR = """<html><body><main>
<a href="/calendar/feed.ics?token=abc">Subscribe to this calendar</a>
</main></body></html>"""

ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:e1
DTSTART:20260810T160000Z
DTEND:20260810T170000Z
SUMMARY:Back to School Night
LOCATION:Cafeteria
END:VEVENT
END:VCALENDAR
"""

EMPTY_PAGE = "<html><body><main><p>Nothing here yet.</p></main></body></html>"

# Deliberately served at /documents, not /files, so route fallback is exercised.
DOCUMENTS = """<html><body><main><ul>
<li class="file"><a href="/files/1/menu.pdf">Lunch Menu</a></li>
</ul></main></body></html>"""

# These three sit at paths no candidate list knows about — reachable only by
# matching their sidebar labels. This is the case a real district hits.
MY_FORMS = """<html><body><main><ul>
<li class="form"><a href="/forms/1">Field Trip Permission Slip</a> unsigned, due Sep 5</li>
<li class="form"><a href="/forms/2">Media Release</a> signed</li>
</ul></main></body></html>"""

SCHOOL_PAY = """<html><body><main><ul>
<li class="payment"><a href="/payments/1">Yearbook</a> <span class="price">$25.00</span> unpaid</li>
<li class="payment"><a href="/payments/2">Field Trip Fee</a> <span class="price">$12.50</span> paid</li>
</ul></main></body></html>"""

DM = """<html><body><main><ul>
<li class="conversation"><a href="/conversations/12">Ms. Rivera</a>
    <span class="preview">About Friday's trip</span></li>
</ul></main></body></html>"""

ROUTES: dict[str, tuple[str, bytes]] = {
    "/signin": ("text/html", SIGNIN.encode()),
    "/feeds": ("text/html", FEED.encode()),
    "/feeds/9001": ("text/html", POST.encode()),
    "/schools": ("text/html", SCHOOLS.encode()),
    "/directory": ("text/html", DIRECTORY.encode()),
    "/calendar": ("text/html", CALENDAR.encode()),
    "/calendar/feed.ics": ("text/calendar", ICS),
    "/attachments/551/flyer.pdf": ("application/pdf", PDF),
    "/photos/whale.png": ("image/png", PNG),
    "/polls": ("text/html", EMPTY_PAGE.encode()),
    "/documents": ("text/html", DOCUMENTS.encode()),
    "/my_forms": ("text/html", MY_FORMS.encode()),
    "/school_pay": ("text/html", SCHOOL_PAY.encode()),
    "/dm": ("text/html", DM.encode()),
}

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        failures.append(f"{label} {detail}".strip())
        print(f"  FAIL {label} {detail}")


#: The only credentials the fake site accepts.
GOOD_EMAIL = "parent@example.com"
GOOD_PASSWORD = "correct-horse"

#: Session values the fake site treats as signed in. Anything else is stale.
VALID_SESSIONS = {"fake-session-value", "issued-by-login"}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):  # noqa: A002 - silence the default access log
        pass

    def do_POST(self):  # noqa: N802
        """The sign-in form target, so the password flow can be exercised."""
        if self.path != "/sessions":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        import urllib.parse as _parse

        form = _parse.parse_qs(self.rfile.read(length).decode())
        email = form.get("user[email]", [""])[0]
        password = form.get("user[password]", [""])[0]
        token = form.get("authenticity_token", [""])[0]

        if email == GOOD_EMAIL and password == GOOD_PASSWORD and token == "tok123":
            self.send_response(302)
            self.send_header("Set-Cookie", "psq_session=issued-by-login; Path=/; HttpOnly")
            self.send_header("Location", "/feeds")
            self.end_headers()
            return

        body = SIGNIN.replace("<h1>", '<div class="alert">Invalid email or password</div><h1>').encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]

        # No valid session → bounce to the sign-in page, like the real app.
        cookies = dict(
            part.strip().split("=", 1)
            for part in self.headers.get("Cookie", "").split(";")
            if "=" in part
        )
        if cookies.get("psq_session") not in VALID_SESSIONS and path != "/signin":
            self.send_response(302)
            self.send_header("Location", "/signin")
            self.end_headers()
            return

        if path in ROUTES:
            content_type, body = ROUTES[path]
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<html><body>404 error</body></html>")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def payload(result) -> dict | None:
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            try:
                return json.loads(text)
            except ValueError:
                continue
    return None


async def run_checks(mcp) -> None:
    print("\ntools over http")

    feeds = payload(await mcp.call_tool("get_feeds", {}))
    check("get_feeds returns rows", feeds["count"] == 2, str(feeds.get("count")))
    check("get_feeds resolves urls", feeds["items"][0]["url"].endswith("/feeds/9001"))
    check("get_feeds reads signup progress", feeds["items"][1]["signup_progress"]["remaining"] == 50)

    filtered = payload(await mcp.call_tool("get_feeds", {"query": "aquarium"}))
    check("get_feeds query filters", filtered["count"] == 1, str(filtered.get("count")))

    miss = payload(await mcp.call_tool("get_feeds", {"query": "zzzz"}))
    check("get_feeds explains an empty filter", "matched" in miss and miss["count"] == 0)

    post_result = await mcp.call_tool("get_post", {"post_id": "9001"})
    blocks = post_result.content
    post = payload(post_result)
    check("get_post extracts body prose", "Permission slips are due Friday." in post["body"], repr(post["body"])[:120])
    check("get_post inlines link urls", "policy (http" in post["body"], repr(post["body"])[:200])
    check("get_post reads comments", post["comments"][0]["author"] == "Dad", str(post.get("comments")))
    check("get_post lists attachments", len(post["attachments"]) == 2, str(len(post["attachments"])))
    kinds = [type(b).__name__ for b in blocks]
    check("get_post returns an image block", any("Image" in k for k in kinds), str(kinds))

    schools = payload(await mcp.call_tool("list_schools", {}))
    check("list_schools finds both schools", schools["count"] == 2, str(schools.get("count")))
    check("list_schools extracts ids", schools["schools"][0]["id"] == "77", str(schools["schools"][0]))
    check("list_schools finds the student", schools["student_count"] == 1, str(schools.get("student_count")))

    directory = payload(await mcp.call_tool("get_directory", {}))
    check("get_directory skips the header row", directory["count"] == 1, str(directory.get("count")))
    entry = directory["staff"][0]
    check("get_directory reads the name", entry["name"] == "Ms. Rivera", repr(entry["name"]))
    check("get_directory reads the role", entry["role"] == "3rd Grade Teacher", repr(entry["role"]))
    check("get_directory reads the phone", entry["phone"] == "(805) 555-1212", repr(entry["phone"]))
    check("get_directory reads the user id", entry["user_id"] == "301", repr(entry["user_id"]))

    events = payload(await mcp.call_tool("get_calendar_events", {"days_ahead": 400}))
    check("calendar discovers the ics link", events["count"] == 1, str(events.get("count")))
    check("calendar reads the event", events["events"][0]["title"] == "Back to School Night", str(events["events"]))

    files = payload(await mcp.call_tool("list_files", {}))
    check("list_files falls back to /documents", files["count"] == 1, str(files.get("count")))
    check("list_files reads the name", files["files"][0]["name"] == "Lunch Menu", str(files.get("files")))

    print("\nsidebar route discovery (no candidate path works)")
    forms = payload(await mcp.call_tool("list_forms", {}))
    check("list_forms discovers /my_forms", forms["source"].endswith("/my_forms"), str(forms.get("source")))
    check("list_forms reads both rows", forms["count"] == 2, str(forms.get("count")))
    check(
        "list_forms flags the outstanding one",
        forms["outstanding_count"] == 1,
        str(forms.get("outstanding_count")),
    )
    check(
        "list_forms reads the status",
        forms["forms"][0]["status"] == "unsigned",
        str(forms["forms"][0]),
    )

    payments = payload(await mcp.call_tool("list_payments", {}))
    check("list_payments discovers /school_pay", payments["source"].endswith("/school_pay"), str(payments.get("source")))
    check("list_payments reads prices", payments["summary"]["total_listed"] == 37.5, str(payments.get("summary")))
    check(
        "list_payments totals only what is unpaid",
        payments["summary"]["total_outstanding"] == 25.0,
        str(payments.get("summary")),
    )

    dms = payload(await mcp.call_tool("list_conversations", {}))
    check("list_conversations discovers /dm", dms["source"].endswith("/dm"), str(dms.get("source")))
    check("list_conversations reads the thread", dms["count"] == 1, str(dms.get("count")))
    check("list_conversations reads the id", dms["conversations"][0]["id"] == "12", str(dms["conversations"][0]))

    polls = payload(await mcp.call_tool("list_polls", {}))
    check("an empty section degrades to page_text", "page_text" in polls, str(list(polls)))
    check("an empty section explains itself", "selectors" in polls.get("note", "").lower())

    # A section that exists at none of the candidate paths must fail loudly, with
    # an error that says how to fix it. In-process this surfaces as an exception;
    # over the wire the protocol layer turns it into isError (see test_stdio.py).
    try:
        await mcp.call_tool("list_notices", {})
        check("a missing section reports an error", False, "no error raised")
    except Exception as err:  # noqa: BLE001
        message = str(err)
        check("a missing section reports an error", True)
        check("the error lists the paths tried", "/notices, /alerts" in message, message[:160])
        check("the error names routes.py", "routes.py" in message, message[:160])


def main() -> int:
    port = free_port()
    base = f"http://127.0.0.1:{port}"

    os.environ["PARENTSQUARE_BASE_URL"] = base
    os.environ["PARENTSQUARE_COOKIE"] = "psq_session=fake-session-value"
    os.environ["PARENTSQUARE_DOWNLOAD_DIR"] = str(ROOT / ".test-downloads")

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    try:
        from parentsquare_mcp.server import build_server

        print(f"fake ParentSquare on {base}")
        asyncio.run(run_checks(build_server()))
    finally:
        server.shutdown()

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
