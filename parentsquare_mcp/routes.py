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
FILES = ["/files", "/documents"]
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
    return [f"/conversations/{conversation_id}", f"/messages/{conversation_id}"]


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
