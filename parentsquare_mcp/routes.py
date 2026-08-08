"""Every URL the server knows about.

ParentSquare has no public parent-facing API, so these are the paths the parent
web app itself uses. Districts run slightly different app versions, so treat
each entry as a list of *candidates*: the client tries them in order and keeps
the first that returns a real page instead of a 404 or a login redirect.

``python scripts/doctor.py`` reports which candidate won for each route. Promote
that winner to the front of the list.
"""

from __future__ import annotations

SIGNIN = ["/signin", "/users/sign_in", "/sessions/new"]

FEED = ["/feeds", "/"]
CALENDAR = ["/calendar", "/events"]
CONVERSATIONS = ["/conversations", "/messages"]
DIRECTORY = ["/directory", "/staff"]
PHOTOS = ["/photos", "/gallery"]
# "documents" alone often means Secure Documents; plain file attachments live under feeds/files.
FILES = ["/files", "/documents", "/feeds/files", "/secure_documents"]
SIGNUPS = ["/signups", "/sign_ups"]
NOTICES = ["/notices", "/alerts"]
POLLS = ["/polls"]
FORMS = ["/forms", "/permission_slips"]
PAYMENTS = ["/payments", "/store"]
VOLUNTEER_HOURS = ["/volunteer_hours", "/volunteer"]
SCHOOLS = ["/schools", "/account/schools"]
GROUPS = ["/groups"]
LINKS = ["/links", "/quick_links"]
STUDENTS = ["/students", "/dashboard"]


def school_feed(school_id: str) -> list[str]:
    return [f"/schools/{school_id}/feeds", f"/schools/{school_id}"]


def post(post_id: str) -> list[str]:
    return [f"/feeds/{post_id}", f"/posts/{post_id}"]


def group_feed(group_id: str) -> list[str]:
    return [f"/groups/{group_id}/feeds", f"/groups/{group_id}"]


def conversation(conversation_id: str) -> list[str]:
    return [
        f"/conversations/{conversation_id}",
        f"/messages/{conversation_id}",
        f"/chats/{conversation_id}",
    ]


def school_directory(school_id: str) -> list[str]:
    return [f"/schools/{school_id}/directory", f"/schools/{school_id}/staff"]


def staff_member(user_id: str) -> list[str]:
    return [f"/users/{user_id}", f"/directory/{user_id}", f"/staff/{user_id}"]


def school(school_id: str) -> list[str]:
    return [f"/schools/{school_id}"]


def school_photos(school_id: str) -> list[str]:
    return [f"/schools/{school_id}/photos"]


def school_files(school_id: str) -> list[str]:
    return [f"/schools/{school_id}/files"]


def school_groups(school_id: str) -> list[str]:
    return [f"/schools/{school_id}/groups"]


def school_links(school_id: str) -> list[str]:
    return [f"/schools/{school_id}/links", f"/schools/{school_id}/quick_links"]


def student(student_id: str) -> list[str]:
    return [f"/students/{student_id}"]


#: Words that identify a section in the sidebar, when none of its candidate paths
#: work. Districts rename and re-route these freely, so matching the visible
#: label is more reliable than guessing another URL. Keep them lowercase.
SECTION_KEYWORDS: dict[str, list[str]] = {
    "feed": ["posts", "feed", "home"],
    "calendar": ["calendar", "events"],
    "conversations": ["messages", "conversations", "inbox", "direct message"],
    "directory": ["directory", "staff", "contacts"],
    "photos": ["photos", "gallery", "pictures"],
    # Prefer the exact "Files" More-menu label over "Photos, Videos, Files".
    "files": ["files", "documents", "resources", "secure documents"],
    # Bottom nav often says "SignUp" as one word.
    "signups": ["signup", "signups", "sign ups", "sign-ups", "rsvp", "volunteer signup"],
    "notices": ["notices", "alerts", "secure documents"],
    "polls": ["polls", "surveys"],
    "forms": ["forms", "permission slips", "permission", "signatures", "sign forms"],
    "payments": ["payments", "pay", "fees", "store", "invoices", "billing"],
    "volunteer_hours": ["volunteer hours", "volunteer", "hours"],
    "schools": ["schools", "my schools"],
    "groups": ["groups", "classes"],
    "links": ["links", "quick links", "resources"],
    "students": ["students", "my students", "children"],
}

#: When the static HTML sidebar has no match (common for the JS bottom-nav
#: items like SignUp / More → Polls), try these paths under the current school.
SCHOOL_SCOPED_SUFFIXES: dict[str, list[str]] = {
    "feed": ["feeds"],
    "calendar": ["calendars", "calendar", "events"],
    "conversations": ["messages", "conversations"],  # usually /users/<id>/chats
    "directory": ["users", "directory", "staff"],
    "photos": ["feeds/photos", "photos", "gallery"],
    "files": ["feeds/files", "secure_documents", "files", "documents"],
    "signups": ["sign_ups", "signups"],
    "notices": ["notices?html=true", "notices", "alerts"],
    "polls": ["polls", "surveys"],
    "forms": ["forms", "permission_slips"],
    "payments": ["payments", "store", "fees"],
    "groups": ["groups"],
    "links": ["links", "quick_links"],
}

#: Sidebar entries we recognise, used to classify a school's available sections.
KNOWN_SECTIONS = [
    "posts",
    "feed",
    "calendar",
    "directory",
    "photos",
    "files",
    "documents",
    "signups",
    "sign ups",
    "notices",
    "polls",
    "forms",
    "payments",
    "store",
    "volunteer",
    "groups",
    "links",
    "messages",
    "conversations",
    "students",
]
