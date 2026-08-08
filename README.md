# ParentSquare MCP

An MCP server that gives Claude read access to your own ParentSquare parent account —
school posts, calendars, messages, the staff directory, signups, forms, payments and files.

School calendars and flyers are very often posted as **image or PDF attachments** rather than as
calendar entries. This server downloads them and hands them to Claude as real image/text content,
so "what's on the school calendar next week?" works even when the calendar itself is empty.

---

## Before you start: how this connects

ParentSquare has no public parent-facing API. Their documented API is district-side, for pushing
student data in from an SIS — it is issued to district IT, not to parents, and it is not what you
want here. So this server signs in as you and reads the same parent web app you use in a browser.

Two consequences worth knowing up front:

- **You need to supply your own session.** See [Authentication](#authentication).
- **The page layouts are not a contract.** Districts run slightly different versions of the app, so
  the URLs and HTML selectors are best-effort. Every route is a list of candidates that gets tried in
  order, every parser degrades to returning the readable page text instead of failing, and
  `scripts/doctor.py` tells you exactly which ones need adjusting for your district.
  **Expect to run the doctor once and tweak a few things.** See [Fitting it to your district](#fitting-it-to-your-district).

---

## Install

```bash
cd "~/Desktop/ParentSquare MCP"
python3 -m venv .venv
./.venv/bin/python -m pip install -e .
```

## Authentication

### Method 1 — browser cookie (recommended)

Works with every district, including ones that sign in through Google, Clever or ClassLink, and with
two-factor accounts.

1. Sign in to ParentSquare in your browser.
2. Open DevTools → **Network**, click any request to `parentsquare.com`.
3. Under **Request Headers**, copy the entire value of `Cookie:`.
4. Put it in `PARENTSQUARE_COOKIE` (see [Connect it to Claude](#connect-it-to-claude)).

The cookie expires eventually — when tools start reporting that the session expired, repeat this.

### Method 2 — email and password

Only works if your district uses a plain ParentSquare password, with no two-factor.

```bash
PARENTSQUARE_EMAIL=you@example.com ./.venv/bin/python scripts/login.py
```

This caches the session in `~/.parentsquare-mcp/session.json` (mode 600). If your district uses SSO
or 2FA, the script says so and points you back to Method 1.

## Connect it to Claude

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "parentsquare": {
      "command": "/Users/chen/Desktop/ParentSquare MCP/.venv/bin/python",
      "args": ["-m", "parentsquare_mcp"],
      "cwd": "/Users/chen/Desktop/ParentSquare MCP",
      "env": {
        "PARENTSQUARE_COOKIE": "_parentsquare_session=…; remember_user_token=…"
      }
    }
  }
}
```

Restart Claude Desktop.

### Claude Code

```bash
claude mcp add parentsquare \
  --env PARENTSQUARE_COOKIE="_parentsquare_session=…" \
  -- "/Users/chen/Desktop/ParentSquare MCP/.venv/bin/python" -m parentsquare_mcp
```

If you used `scripts/login.py`, the cached session is picked up automatically and you can drop the
`env` block entirely.

See `.env.example` for every setting.

---

## Fitting it to your district

Run this once after connecting:

```bash
./.venv/bin/python scripts/doctor.py
```

It reports, for every section, which URL works and how many rows the parser got:

```
— routes —
  ok  feed               /feeds
  ok  directory          /directory
  MISS payments          (none of the candidates worked)

— tools (23 registered) —
  ok   get_feeds              12 rows
  THIN list_signups           0 rows — selectors need work. Source: https://…/signups
```

- **MISS** — your district uses a different URL. Find it in your browser and add it to the front of
  the matching list in `parentsquare_mcp/routes.py`.
- **THIN** — the page loaded but nothing matched. Ask Claude to call `debug_fetch` on that URL to see
  the real markup, then adjust the selector list at the top of the relevant file in
  `parentsquare_mcp/tools/`. The selectors are plain CSS lists, deliberately easy to edit.
- **empty** — the page loaded and genuinely has nothing in it. Nothing to fix.

Nothing in the doctor writes to ParentSquare.

---

## Tools

**Feed and posts**
| Tool | What it does |
| --- | --- |
| `get_feeds` | Paginated feed: titles, authors, dates, summaries, attachment names. Takes a `query` filter. |
| `get_post` | Full post — body, comments, poll results, signup items, and the **contents** of attached images and PDFs. |
| `get_group_feed` | Posts from one group. |

**Calendar**
| Tool | What it does |
| --- | --- |
| `get_calendar_events` | Structured events from the ICS feed, recurring events expanded. When empty, explains how to find calendars posted as attachments. |

**Communication**
| Tool | What it does |
| --- | --- |
| `list_conversations` / `get_conversation` | Read message threads. |
| `get_directory` | Staff directory: name, role, phone, email, user id. |
| `get_staff_member` | Full profile including office hours and profile photo. |

**Media and files**
| Tool | What it does |
| --- | --- |
| `list_photos` | Photo gallery with image URLs. |
| `list_files` | Shared documents with download URLs. |
| `download_file` | Save any attachment to disk. |

**Things to act on**
| Tool | What it does |
| --- | --- |
| `list_signups` | Sign-ups and RSVPs with progress (e.g. `53/103 Items`). |
| `list_notices` | Alerts and secure documents. |
| `list_polls` | Polls with vote counts and the leading option. |
| `list_forms` | Permission slips, with an outstanding count. |
| `list_payments` | Payment items with prices and totals. |
| `list_volunteer_hours` | Logged hours with the total. |

**Discovery**
| Tool | What it does |
| --- | --- |
| `list_schools` | Schools and students, with the ids other tools take. |
| `list_school_features` | Which sections a school actually has, from its sidebar. |
| `list_groups` | Groups with member counts and membership status. |
| `list_links` | Pinned quick links. |
| `get_student_dashboard` | A student's school, grade, classes and teachers. |
| `debug_fetch` | Escape hatch: fetch any ParentSquare path and see what is really there. |

Nothing here writes to ParentSquare — every tool is read-only against your account. On your own disk,
`download_file` saves where you ask it to, and `get_post` saves image-only PDFs (scans, which have no
extractable text) to `~/Downloads/ParentSquare` so they are still reachable.

## Things to try

> What did the school send home this week?

> Is there anything I still need to sign or pay for?

> The October calendar was posted as a PDF — what days is my kid off?

> Who is my son's teacher and what's their email?

## Tests

```bash
./.venv/bin/python tests/run_all.py
```

Four suites — parsers, tools over HTTP, a real MCP handshake over stdio, and the authentication
paths — all against a fake ParentSquare served on localhost. They never touch the real site, so they
are safe to run at any time.

## Layout

```
parentsquare_mcp/
  config.py      environment settings
  client.py      auth, HTTP, route fallback, login-bounce detection
  routes.py      every URL, as ordered candidate lists   ← edit when doctor says MISS
  parsers.py     shared HTML helpers and the fallback result shape
  media.py       attachments → images / PDF text
  tools/         one module per group of tools           ← edit when doctor says THIN
scripts/
  login.py       cache a session with email + password
  doctor.py      check routes and tools against your account
tests/
```

## Notes

- Read-only by design. Nothing posts, replies, signs, pays or RSVPs on your behalf.
- Your credentials stay on your machine: in the client config env block, or in
  `~/.parentsquare-mcp/session.json` at mode 600.
- Because it depends on the parent web app's HTML, a ParentSquare redesign can break parsing. That is
  what `doctor.py` and `debug_fetch` are for, and why nothing hard-fails when a selector misses.
