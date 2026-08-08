"""Authenticated HTTP access to the ParentSquare parent web app."""

from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass
from typing import Any, Iterable

import httpx
from bs4 import BeautifulSoup

from .config import config, debug_log
from . import routes

LOGIN_PATH_RE = re.compile(r"/(signin|sign_in|sessions/new|login|saml|sso|oauth)", re.I)
PASSWORD_FORM_RE = re.compile(r"""<input[^>]+type=["']password["']|name=["']user\[password\]["']""", re.I)
NOT_FOUND_RE = re.compile(r"page (you were looking for )?does(n't| not) exist|404 error", re.I)
TWO_FACTOR_RE = re.compile(r"two[- ]?factor|verification code|one[- ]?time (code|passcode)|authenticator", re.I)


class AuthError(RuntimeError):
    """The session is missing, expired, or the login could not be completed."""


class RouteError(RuntimeError):
    """The page we asked for does not exist at any known URL."""


@dataclass
class Page:
    soup: BeautifulSoup
    html: str
    url: str


def _looks_like_login(url: str, html: str) -> bool:
    path = urllib.parse.urlparse(url).path
    return bool(LOGIN_PATH_RE.search(path)) and bool(PASSWORD_FORM_RE.search(html))


def _looks_like_not_found(status: int, html: str) -> bool:
    if status == 404:
        return True
    return status == 200 and bool(NOT_FOUND_RE.search(html))


class ParentSquareClient:
    def __init__(self) -> None:
        self._http = httpx.Client(
            base_url=config.base_url,
            follow_redirects=True,
            timeout=config.timeout_s,
            headers={
                "User-Agent": config.user_agent,
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        self._auth_checked = False
        #: Route candidates that already proved themselves, keyed by candidate tuple.
        self._route_cache: dict[tuple[str, ...], str] = {}
        #: Sections resolved from the sidebar; None means "looked, found nothing".
        self._discovered: dict[str, str | None] = {}
        #: The page we mine for sidebar links. False means "tried, unavailable".
        self._nav_cache: Page | bool | None = None

        self._load_session()
        if config.cookie:
            self._seed_cookie_header(config.cookie)

    # ------------------------------------------------------------- session

    def _seed_cookie_header(self, header: str) -> None:
        for part in header.split(";"):
            name, sep, value = part.strip().partition("=")
            if sep and name:
                self._http.cookies.set(name.strip(), value.strip())

    def _load_session(self) -> None:
        try:
            saved = json.loads(config.session_file.read_text())
        except (OSError, ValueError):
            return
        cookies = saved.get("cookies")
        if isinstance(cookies, dict):
            for name, value in cookies.items():
                self._http.cookies.set(name, value)
            debug_log(f"loaded {len(cookies)} cookies from {config.session_file}")

    def save_session(self) -> None:
        try:
            config.ensure_state_dir()
            payload = {"cookies": dict(self._http.cookies)}
            config.session_file.write_text(json.dumps(payload, indent=2))
            config.session_file.chmod(0o600)
        except OSError as err:  # pragma: no cover - best effort
            debug_log("could not save session:", err)

    # ---------------------------------------------------------------- http

    def url(self, path_or_url: str) -> str:
        return urllib.parse.urljoin(config.base_url + "/", path_or_url)

    def get_page(self, path_or_url: str, *, optional: bool = False) -> Page | None:
        """Fetch a page and assert it is the page we asked for.

        Raises :class:`AuthError` for a login bounce and :class:`RouteError` for
        a 404, so callers can react to the two very differently.
        """
        self.ensure_auth()
        response = self._http.get(self.url(path_or_url), headers={"Accept": "text/html"})
        html = response.text
        final_url = str(response.url)

        if _looks_like_login(final_url, html):
            self._auth_checked = False
            raise AuthError(
                "ParentSquare bounced this request to the sign-in page — the session is missing or expired. "
                "Refresh it with `python scripts/login.py`, or paste a fresh browser cookie into "
                "PARENTSQUARE_COOKIE."
            )

        if _looks_like_not_found(response.status_code, html) or response.status_code >= 400:
            if optional:
                return None
            raise RouteError(f"No usable page at {final_url} (HTTP {response.status_code}).")

        return Page(soup=BeautifulSoup(html, "lxml"), html=html, url=final_url)

    def get_first_page(
        self, candidates: Iterable[str], *, label: str = "page", section: str | None = None
    ) -> Page:
        """Try each candidate path in order; remember the one that worked.

        If every candidate fails and ``section`` names an entry in
        ``routes.SECTION_KEYWORDS``, fall back to finding the section by its
        sidebar label. Districts re-route these pages freely, so what the link
        *says* is a better bet than guessing another URL.
        """
        candidates = list(candidates)
        key = tuple(candidates)
        cached = self._route_cache.get(key)
        ordered = [cached, *[c for c in candidates if c != cached]] if cached else candidates

        last_error: Exception | None = None
        for candidate in ordered:
            try:
                page = self.get_page(candidate)
            except AuthError:
                raise
            except (RouteError, httpx.HTTPError) as err:
                last_error = err
                continue
            if page is not None:
                self._route_cache[key] = candidate
                debug_log(f"{label}: using {candidate}")
                return page

        if section:
            discovered = self.discover_section(section)
            if discovered and discovered not in candidates:
                try:
                    page = self.get_page(discovered)
                except (AuthError, RouteError, httpx.HTTPError) as err:
                    last_error = err
                else:
                    if page is not None:
                        self._route_cache[key] = discovered
                        debug_log(f"{label}: discovered {discovered} from the sidebar")
                        return page

        hint = ""
        if section:
            hint = (
                f" Also looked for a sidebar link labelled like "
                f"{'/'.join(routes.SECTION_KEYWORDS.get(section, [])[:3])} and found "
                f"{'nothing' if not self.discover_section(section) else 'a link that did not load'}."
            )
        raise RouteError(
            f"Could not load the {label} page. Tried: {', '.join(candidates)}.{hint} "
            f"Last error: {last_error or 'unknown'}. Fix the URL in parentsquare_mcp/routes.py — "
            "`python scripts/doctor.py` reports the right one, and `debug_fetch` can show you the sidebar."
        )

    # --------------------------------------------------------- nav discovery

    def _nav_page(self) -> Page | None:
        """The page whose sidebar we mine for section links. Fetched at most once."""
        if self._nav_cache is not None:
            return self._nav_cache or None
        for candidate in routes.FEED:
            try:
                page = self.get_page(candidate, optional=True)
            except (AuthError, httpx.HTTPError):
                continue
            if page is not None:
                self._nav_cache = page
                return page
        self._nav_cache = False  # remember the miss, don't retry every call
        return None

    def _nav_anchors(self, page: Page) -> list[Any]:
        """Collect sidebar / bottom-nav links; fall back to every anchor on the page."""
        anchors: list[Any] = []
        seen: set[int] = set()
        for selector in ("nav a[href]", ".sidebar a[href]", "#sidebar a[href]", "aside a[href]"):
            for anchor in page.soup.select(selector):
                ident = id(anchor)
                if ident in seen:
                    continue
                seen.add(ident)
                anchors.append(anchor)
        if not anchors:
            anchors = list(page.soup.select("a[href]"))
        return anchors

    def _match_section_href(self, section: str, anchors: list[Any]) -> str | None:
        """Pick the best href for ``section`` from a list of anchors."""
        keywords = routes.SECTION_KEYWORDS.get(section, [])

        # Student / school switchers are labelled with names, not "Students".
        if section == "students":
            for anchor in anchors:
                href = anchor.get("href") or ""
                if re.search(r"/students/\d+", href):
                    return href
        if section == "schools":
            for anchor in anchors:
                href = anchor.get("href") or ""
                if re.search(r"/schools/\d+(/feeds)?/?$", href):
                    return href

        best: tuple[int, str] | None = None
        for anchor in anchors:
            text = anchor.get_text(" ", strip=True).lower()
            href = anchor.get("href")
            if not text or not href or len(text) > 48:
                continue
            for keyword in keywords:
                if keyword not in text:
                    continue
                # Exact label beats a longer compound like "Photos, Videos, Files".
                score = 0 if text == keyword else 1 if text.startswith(keyword) else 2 + len(text)
                if best is None or score < best[0]:
                    best = (score, href)
        return best[1] if best else None

    def discover_section(self, section: str) -> str | None:
        """Find a section's real path by matching its sidebar (or More-menu) label."""
        if section in self._discovered:
            return self._discovered[section]

        keywords = routes.SECTION_KEYWORDS.get(section, [])
        found: str | None = None
        page = self._nav_page() if (keywords or section in {"students", "schools"}) else None

        if page is not None:
            anchors = self._nav_anchors(page)
            found = self._match_section_href(section, anchors)

            # Polls / Files often live only under the bottom-nav "More" screen.
            if found is None:
                more_href = None
                for anchor in anchors:
                    text = anchor.get_text(" ", strip=True).lower()
                    href = anchor.get("href")
                    if href and text in {"more", "more features"}:
                        more_href = href
                        break
                # Bottom-nav "More" is often JS-only; the school-scoped path still works.
                if more_href is None:
                    school_id = self._school_id_from_page(page)
                    if school_id:
                        more_href = f"/schools/{school_id}/more_features"
                if more_href:
                    try:
                        more_page = self.get_page(more_href, optional=True)
                    except (AuthError, httpx.HTTPError):
                        more_page = None
                    if more_page is not None:
                        found = self._match_section_href(section, self._nav_anchors(more_page))
                        if found is None:
                            found = self._match_section_href(section, list(more_page.soup.select("a[href]")))

            # Last resort: try well-known /schools/<id>/… paths (JS bottom-nav items).
            if found is None:
                school_id = self._school_id_from_page(page)
                suffixes = routes.SCHOOL_SCOPED_SUFFIXES.get(section, [])
                if school_id and suffixes:
                    for suffix in suffixes:
                        candidate = f"/schools/{school_id}/{suffix.lstrip('/')}"
                        try:
                            hit = self.get_page(candidate, optional=True)
                        except (AuthError, httpx.HTTPError):
                            continue
                        if hit is None:
                            continue
                        # Reject soft redirects (e.g. /payments → /feeds).
                        if not self._same_section_path(candidate, hit.url):
                            continue
                        found = candidate
                        break

            if found:
                debug_log(f"discovered {section!r} at {found}")

        self._discovered[section] = found
        return found

    def _same_section_path(self, requested: str, final_url: str) -> bool:
        """True when ``final_url`` is still the page we asked for (query ignored)."""
        req = urllib.parse.urlparse(self.url(requested)).path.rstrip("/")
        got = urllib.parse.urlparse(final_url).path.rstrip("/")
        return got == req or got.startswith(req + "/")

    def _school_id_from_page(self, page: Page) -> str | None:
        match = re.search(r"/schools/(\d+)", page.url or "")
        if match:
            return match.group(1)
        for anchor in page.soup.select('a[href*="/schools/"]'):
            href = anchor.get("href") or ""
            m = re.search(r"/schools/(\d+)", href)
            if m:
                return m.group(1)
        return None

    def try_json(self, path_or_url: str) -> Any | None:
        """Some ParentSquare views answer with JSON when asked politely."""
        self.ensure_auth()
        try:
            response = self._http.get(
                self.url(path_or_url),
                headers={"Accept": "application/json, text/javascript;q=0.9", "X-Requested-With": "XMLHttpRequest"},
            )
            if response.status_code >= 400:
                return None
            if "json" not in response.headers.get("content-type", ""):
                return None
            return response.json()
        except (httpx.HTTPError, ValueError):
            return None

    def get_binary(self, path_or_url: str) -> dict[str, Any]:
        self.ensure_auth()
        response = self._http.get(self.url(path_or_url), headers={"Accept": "*/*"})
        if response.status_code >= 400:
            raise RouteError(f"HTTP {response.status_code} downloading {response.url}")

        disposition = response.headers.get("content-disposition", "")
        match = re.search(r"""filename\*?=(?:UTF-8'')?"?([^";]+)"?""", disposition, re.I)
        fallback = urllib.parse.unquote(urllib.parse.urlparse(str(response.url)).path.rsplit("/", 1)[-1]) or "download"

        return {
            "content": response.content,
            "content_type": response.headers.get("content-type", "application/octet-stream").split(";")[0].strip(),
            "filename": urllib.parse.unquote(match.group(1)) if match else fallback,
            "url": str(response.url),
        }

    # ---------------------------------------------------------------- auth

    def ensure_auth(self) -> None:
        if self._auth_checked:
            return

        if len(self._http.cookies) and self._probe_session():
            self._auth_checked = True
            return

        if config.email and config.password:
            self.login(config.email, config.password)
            self._auth_checked = True
            return

        raise AuthError(
            "Not signed in to ParentSquare. Either set PARENTSQUARE_COOKIE to the Cookie header from a "
            "logged-in browser tab, or set PARENTSQUARE_EMAIL / PARENTSQUARE_PASSWORD and run "
            "`python scripts/login.py`. If your district signs in through Google/Clever/ClassLink SSO, "
            "the cookie method is the only one that works."
        )

    def _probe_session(self) -> bool:
        for candidate in routes.FEED:
            try:
                response = self._http.get(self.url(candidate), headers={"Accept": "text/html"})
            except httpx.HTTPError as err:
                debug_log("session probe failed:", err)
                continue
            if response.status_code >= 400:
                continue
            if not _looks_like_login(str(response.url), response.text):
                return True
        return False

    def login(self, email: str, password: str) -> bool:
        """Password login.

        Rather than hard-coding field names, this reads the real sign-in form and
        reproduces it — which survives the app renaming things and carries
        whatever CSRF token the form ships with.
        """
        page = self._find_signin_page()
        soup = page.soup

        form = next((f for f in soup.select("form") if f.select_one('input[type="password"]')), None)
        if form is None:
            raise AuthError(
                f"No password form found at {page.url}. Your district almost certainly uses SSO "
                "(Google, Clever, ClassLink…). Use the PARENTSQUARE_COOKIE method instead."
            )

        password_input = form.select_one('input[type="password"]')
        password_field = password_input.get("name") or "user[password]"

        email_input = form.select_one('input[type="email"]') or next(
            (
                el
                for el in form.select('input[type="text"], input:not([type])')
                if re.search(r"email|login|user|username", el.get("name") or "", re.I)
            ),
            None,
        )
        email_field = (email_input.get("name") if email_input else None) or "user[email]"

        data: dict[str, str] = {}
        for el in form.select("input"):
            name = el.get("name")
            kind = (el.get("type") or "text").lower()
            if not name or kind in {"submit", "button"}:
                continue
            if kind == "checkbox" and not el.has_attr("checked"):
                continue
            data[name] = el.get("value") or ""
        data[email_field] = email
        data[password_field] = password

        csrf_meta = soup.select_one('meta[name="csrf-token"]')
        action = self.url(form.get("action") or urllib.parse.urlparse(page.url).path)

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": page.url,
            "Origin": config.base_url,
            "Accept": "text/html",
        }
        if csrf_meta and csrf_meta.get("content"):
            headers["X-CSRF-Token"] = csrf_meta["content"]

        response = self._http.post(action, data=data, headers=headers)
        body = response.text

        if TWO_FACTOR_RE.search(body):
            raise AuthError(
                "Login hit a two-factor prompt, which this server cannot complete. Sign in with your browser "
                "and use the PARENTSQUARE_COOKIE method instead."
            )

        # A rejected login re-renders the form. Test the body, not the URL: the
        # form posts to /sessions, which is not itself a sign-in path.
        if PASSWORD_FORM_RE.search(body) or _looks_like_login(str(response.url), body):
            notice = BeautifulSoup(body, "lxml").select_one('.alert, .flash, .error, [role="alert"]')
            detail = f": {notice.get_text(strip=True)}" if notice else "."
            raise AuthError(f"ParentSquare rejected the login{detail}")

        # Confirm positively rather than trusting the absence of a failure signal.
        if not self._probe_session():
            raise AuthError(
                "The login POST appeared to succeed but the session does not work. This usually means the "
                "district uses SSO — use the PARENTSQUARE_COOKIE method instead."
            )

        self.save_session()
        debug_log("login succeeded")
        return True

    def _find_signin_page(self) -> Page:
        last_error: Exception | None = None
        for candidate in routes.SIGNIN:
            try:
                response = self._http.get(self.url(candidate), headers={"Accept": "text/html"})
            except httpx.HTTPError as err:
                last_error = err
                continue
            if response.status_code < 400 and PASSWORD_FORM_RE.search(response.text):
                return Page(soup=BeautifulSoup(response.text, "lxml"), html=response.text, url=str(response.url))
        raise AuthError(f"Could not find the ParentSquare sign-in page. {last_error or ''}".strip())


client = ParentSquareClient()
