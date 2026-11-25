"""The browser is the client. No token ever leaves it.

Why this exists: a `sessionid` copied out of a browser and replayed by an
httpx/instagrapi client is an Android-shaped device holding a token issued to
Chrome — the shape Instagram calls a stolen session. That cost one account
challenge. Here the requests are issued *by* the logged-in browser, same origin,
with its own `sessionid`, `csrftoken`, `mid` and `ig_did`, so there is nothing
to tell apart from a person browsing.

Two ways to reach that browser, same class:

- `BROWSER_CDP=http://127.0.0.1:9222` — drive an already-running Chrome.
- `BROWSER_PROFILE=/data/browser-profile` — launch our own persistent Chromium
  and keep the login in the profile directory. This is the Pi deployment: log in
  once over VNC, and the profile *is* the credential.

Everything above this module is unchanged: it returns the same DTOs as
`instagram.py`, and reuses that module's parsers rather than growing a second
copy of the JSON mapping.
"""
from __future__ import annotations

import json
import os
import queue
import re
import threading
import time
import uuid
from collections.abc import Iterator
from urllib.parse import parse_qs, urlencode, urlparse

from . import direct
from .dtos import AccountDTO, Page, PostDTO, StoryDTO, TrayEntry
from .instagram import (FOLLOWING_URL, WEB, Page, _best, _dict, _epoch,
                        _url, host_allowed, parse_timeline, post_from_media)
from .provider import ProviderError, SessionExpired

PAGE_LIMIT = 50
WA = "https://web.whatsapp.com"
CHALLENGE_MSG = ("Instagram is showing a security check in the browser — open it and finish "
                 "the check, then resume sync")
NOT_LOGGED_IN = ("the browser profile is not logged in to Instagram — log in once in that "
                 "browser (VNC on the Pi), then resume sync")

# One script for every call: same-origin fetch with the page's own session, which
# is the entire point. The csrftoken header is read from the page's own cookie,
# exactly as Instagram's own client does for a write.
def _story_links(media: dict) -> list[dict]:
    """The stickers an author put on a story: profiles, music, links, tags.

    Story items carry them in flat arrays whose names Instagram has changed
    before (`story_mentions` became bloks stickers), so every shape is read
    defensively and anything unrecognised is dropped rather than guessed at.
    """
    out: list[dict] = []

    def add(kind: str, label: str, url: str | None = None,
            detail: str | None = None) -> None:
        label = (label or "").strip()
        if not label or any(l["kind"] == kind and l["label"] == label for l in out):
            return
        out.append({"kind": kind, "label": label, "url": url, "detail": detail})

    def unwrap(url: str | None) -> str | None:
        """Outbound links arrive wrapped in l.instagram.com/?u=<encoded>."""
        if not url:
            return None
        if "l.instagram.com" in url:
            got = parse_qs(urlparse(url).query).get("u")
            if got:
                return got[0]
        return url

    for entry in media.get("story_bloks_stickers") or []:
        data = _dict(_dict(entry).get("bloks_sticker")).get("sticker_data") or {}
        mention = data.get("ig_mention") if isinstance(data, dict) else None
        if mention:
            username = _dict(mention).get("username")
            add("profile", username, f"{WEB}/{username}/",
                _dict(mention).get("full_name"))
    for entry in media.get("story_mentions") or []:
        user = _dict(_dict(entry).get("user"))
        add("profile", user.get("username"), f"{WEB}/{user.get('username')}/",
            user.get("full_name"))
    for entry in media.get("story_link_stickers") or []:
        link = _dict(_dict(entry).get("story_link"))
        url = unwrap(link.get("url"))
        add("url", link.get("title") or (url and hostname_of(url)) or "", url)
    for entry in media.get("story_hashtags") or []:
        name = _dict(_dict(entry).get("hashtag")).get("name")
        add("hashtag", f"#{name}" if name else "", f"{WEB}/explore/tags/{name}/")
    for entry in media.get("story_locations") or []:
        place = _dict(_dict(entry).get("location"))
        if place.get("pk"):
            add("place", place.get("name"), f"{WEB}/explore/locations/{place['pk']}/",
                place.get("address"))
        else:
            add("place", place.get("name"), None, place.get("address"))
    for entry in media.get("story_music_stickers") or []:
        info = _dict(_dict(entry).get("music_asset_info"))
        title, artist = info.get("title"), info.get("display_artist")
        add("music", title, None, artist)
    cta = _dict(media.get("story_cta"))
    if cta.get("url"):
        add("url", cta.get("title") or hostname_of(cta["url"]) or "",
            unwrap(cta["url"]))
    return out


def hostname_of(url: str) -> str | None:
    try:
        host = urlparse(url).netloc.lstrip("www.")
        path = urlparse(url).path.strip("/")
        return f"{host}/{path}" if path else host
    except ValueError:
        return None


_XDT_KEYS = """() => {
  const KEY = 'xdt_api__v1__feed__timeline__connection';
  const scripts = [...document.querySelectorAll('script')].map(s => s.textContent || '');
  const hits = scripts.join(' ').match(/xdt_[a-z0-9_]+/gi) || [];
  const out = {keys: [...new Set(hits)].sort()};
  const find = o => {
    if (!o || typeof o !== 'object') return null;
    if (o[KEY]) return o[KEY];
    for (const k of Object.keys(o)) { const hit = find(o[k]); if (hit) return hit; }
    return null;
  };
  for (const text of scripts) {
    if (!text.includes(KEY)) continue;
    const blobs = [text, ...text.split('\\n')];
    for (const raw of blobs) {
      let blob;
      try { blob = JSON.parse(raw); } catch (e) { continue; }
      const conn = find(blob);
      if (!conn) continue;
      const e0 = (conn.edges || [])[0] || {};
      out.timeline = {keys: Object.keys(conn), n: (conn.edges || []).length,
                      page_info: conn.page_info,
                      edge: Object.keys(e0),
                      node: Object.keys(e0.node || {}),
                      nodeKeys: Object.keys((e0.node || {}).media || (e0.node || {}).item || {}).slice(0, 20)};
      return out;
    }
  }
  out.timeline = 'not parsed';
  return out;
}"""

# The home page ships its own first feed page as a Relay preloader, in exactly
# the media shape the old REST timeline returned. `/api/v1/feed/timeline/` now
# answers with the login HTML, so this is the only feed the browser has.
_FEED_PREFETCH = """() => {
  const KEY = 'xdt_api__v1__feed__timeline__connection';
  const scripts = [...document.querySelectorAll('script')].map(s => s.textContent || '');
  const find = o => {
    if (!o || typeof o !== 'object') return null;
    if (o[KEY]) return o[KEY];
    for (const k of Object.keys(o)) { const hit = find(o[k]); if (hit) return hit; }
    return null;
  };
  for (const text of scripts) {
    if (!text.includes(KEY)) continue;
    for (const raw of [text, ...text.split('\\n')]) {
      let blob;
      try { blob = JSON.parse(raw); } catch (e) { continue; }
      const conn = find(blob);
      if (conn) return (conn.edges || []).map(e => (e.node || {}).media).filter(Boolean);
    }
  }
  return [];
}"""

_FETCH = """async ([url, method, body]) => {
  const csrf = (document.cookie.split('; ').find(c => c.startsWith('csrftoken=')) || '').split('=')[1];
  const headers = {'x-ig-app-id': '936619743392459', 'x-requested-with': 'XMLHttpRequest'};
  if (csrf) headers['x-csrftoken'] = decodeURIComponent(csrf);
  if (method !== 'GET') headers['content-type'] = 'application/x-www-form-urlencoded';
  const r = await fetch(url, {method, credentials: 'include', headers,
                              body: method === 'GET' ? undefined : new URLSearchParams(body).toString()});
  const text = await r.text();
  return [r.status, r.url, text.length > 4000000 ? text.slice(0, 4000000) : text];
}"""

# The story page ships its own data: `script[type="application/json"]` carries a
# Relay preloader for PolarisStoriesV3ReelPage, including each segment's
# video_versions. Walk it and hand back the reels array untouched.
# The profile header's own button. `Requested` is what a private account shows
# after you ask to follow, and it unfollows the same way.
_FOLLOW_BUTTON = """() => {
  const hit = [...document.querySelectorAll('button, div[role="button"]')]
    .find(b => ['Following', 'Requested'].includes((b.innerText || '').trim()));
  if (!hit) return null;
  const r = hit.getBoundingClientRect();
  return [r.x + r.width / 2, r.y + r.height / 2];
}"""

_UNFOLLOW_CONFIRM = """() => {
  const dialog = [...document.querySelectorAll('[role="dialog"]')].pop();
  if (!dialog) return null;
  const hit = [...dialog.querySelectorAll('button, div[role="button"]')]
    .find(b => (b.innerText || '').trim() === 'Unfollow');
  if (!hit) return null;
  const r = hit.getBoundingClientRect();
  return [r.x + r.width / 2, r.y + r.height / 2];
}"""

_FOLLOW_STATE = """() => {
  const hit = [...document.querySelectorAll('button, div[role="button"]')]
    .map(b => (b.innerText || '').trim())
    .find(t => t === 'Follow' || t === 'Following' || t === 'Requested');
  return hit || null;
}"""

_STORY_PREFETCH = """() => {
  const blob = [...document.querySelectorAll('script[type="application/json"]')]
    .map(s => s.textContent || '')
    .find(t => t.includes('xdt_api__v1__feed__reels_media'));
  if (!blob) return [];
  const seen = new Set();
  const walk = o => {
    if (!o || typeof o !== 'object' || seen.has(o)) return null;
    seen.add(o);
    if (o.xdt_api__v1__feed__reels_media) return o.xdt_api__v1__feed__reels_media;
    for (const v of Object.values(o)) {
      const hit = walk(v);
      if (hit) return hit;
    }
    return null;
  };
  const found = walk(JSON.parse(blob));
  const reels = found ? (found.reels_media || found.reels || []) : [];
  return Array.isArray(reels) ? reels : Object.values(reels);
}"""

# A post page ships the same web-API media dict the timeline does, in a Relay
# preloader blob. Same walk as the story page: find the key, hand back the item.
_POST_PREFETCH = """() => {
  const blob = [...document.querySelectorAll('script[type="application/json"]')]
    .map(s => s.textContent || '')
    .find(t => t.includes('xdt_api__v1__media__shortcode__web_info'));
  if (!blob) return null;
  const seen = new Set();
  const walk = o => {
    if (!o || typeof o !== 'object' || seen.has(o)) return null;
    seen.add(o);
    if (o.xdt_api__v1__media__shortcode__web_info) return o.xdt_api__v1__media__shortcode__web_info;
    for (const v of Object.values(o)) {
      const hit = walk(v);
      if (hit) return hit;
    }
    return null;
  };
  const found = walk(JSON.parse(blob));
  if (!found) return null;
  if (Array.isArray(found)) return found[0] || null;
  if (Array.isArray(found.items)) return found.items[0] || null;
  return found.first || found;
}"""


# Chromium writes the locking process's hostname into these. Every container
# restart changes the hostname, so a profile written by yesterday's container
# looks "in use by another computer" and the launch hangs until it times out.
# The app is the profile's only owner by design (the one-time login helper must
# be stopped first), so a lock that is not ours is stale by definition.
_LOCK_FILES = ("SingletonLock", "SingletonCookie", "SingletonSocket")


def clear_stale_lock(profile: str) -> list[str]:
    removed = []
    for name in _LOCK_FILES:
        path = os.path.join(profile, name)
        try:
            os.unlink(path)
            removed.append(name)
        except FileNotFoundError:
            pass
        except OSError:
            pass
    return removed


# Reads the heart's own aria-label, which is the only honest source for "is this
# liked" — and the same element a person clicks.
# A post page carries one heart per comment plus the post's own, all with the
# same aria-label; comment hearts are 16 px and the post's is 24 px. Taking the
# first one liked a comment instead — silently, since the click was accepted.
_LIKE_STATE = """() => {
  const hearts = [...document.querySelectorAll('svg[aria-label="Like"], svg[aria-label="Unlike"]')];
  if (!hearts.length) return null;
  let best = null, bestArea = 0;
  for (const svg of hearts) {
    const box = svg.getBoundingClientRect();
    const area = box.width * box.height;
    if (area > bestArea) { best = {svg, box}; bestArea = area; }
  }
  return {label: best.svg.getAttribute('aria-label'),
          point: [best.box.x + best.box.width / 2, best.box.y + best.box.height / 2]};
}"""


class ThreadProxy:
    """Playwright's sync API belongs to the thread that created it.

    FastAPI runs a route handler in a worker thread, so a like (or a story
    reaction) arrives on a different thread than the one that launched
    Chromium — and greenlet refuses to switch: `Cannot switch to a different
    thread`. Every call therefore goes through one owning thread. That is also
    what a browser wants anyway: one page, serialised, never two threads
    driving it at once.
    """

    def __init__(self, factory) -> None:
        self._factory = factory
        self._jobs: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._error: BaseException | None = None
        threading.Thread(target=self._run, daemon=True,
                         name="browser-provider").start()
        self._ready.wait(120)

    def _run(self) -> None:
        try:
            target = self._factory()
        except BaseException as exc:            # noqa: BLE001 - surfaced to the caller
            self._error = exc
            self._ready.set()
            return
        self._ready.set()
        while True:
            job = self._jobs.get()
            if job is None:
                return
            name, args, kwargs, done, box = job
            try:
                box["value"] = getattr(target, name)(*args, **kwargs)
            except BaseException as exc:        # noqa: BLE001 - re-raised on the caller
                box["error"] = exc
            finally:
                done.set()

    def __getattr__(self, name: str):
        def call(*args, **kwargs):
            if name.startswith("__"):
                raise AttributeError(name)
            if self._error is not None:
                raise self._error
            done, box = threading.Event(), {}
            self._jobs.put((name, args, kwargs, done, box))
            done.wait()
            if "error" in box:
                raise box["error"]
            return box.get("value")

        return call




_HOVER_LAST_BUBBLE = """() => {
  const ys = [innerHeight - 320, innerHeight - 420, innerHeight - 220,
              innerHeight - 520];
  for (const y of ys) {
    const x = innerWidth * 0.62;
    const el = document.elementFromPoint(x, y);
    if (!el) continue;
    const b = el.getBoundingClientRect();
    if (b.width < 40) continue;
    return y;
  }
  return 0;
}"""

_DISMISS = """label => {
  const el = [...document.querySelectorAll('div[role="button"], span, button')]
    .find(x => (x.innerText || '').trim() === label
            || (x.getAttribute('aria-label') || '') === label);
  if (!el) return false;
  el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
  return true;
}"""

# The picker is a horizontal strip of small unlabelled tiles, 24px square,
# drawn just above the bubble's hover bar. Nothing in it has an aria-label, so
# it is found by shape: a row of same-sized boxes sharing one y.
_PICKER = """nearY => {
  const boxes = [...document.querySelectorAll('*')]
    .map(el => ({el, b: el.getBoundingClientRect()}))
    .filter(x => x.b.width > 14 && x.b.width < 64 && x.b.height > 14 && x.b.height < 64
              && x.b.x > 600 && Math.abs(x.b.y - nearY) < 300);
  const rows = {};
  for (const x of boxes) {
    const k = Math.round(x.b.y / 8);
    (rows[k] = rows[k] || []).push(x);
  }
  let best = [];
  for (const k in rows) if (rows[k].length > best.length) best = rows[k];
  best.sort((a, b) => a.b.x - b.b.x);
  return {count: best.length,
          html: best.length ? (best[0].el.parentElement.outerHTML || '').slice(0, 1200) : '',
          spots: best.map(x => ({
            tag: x.el.tagName, role: x.el.getAttribute('role'),
            alt: x.el.getAttribute('alt'),
            x: Math.round(x.b.x), y: Math.round(x.b.y),
            w: Math.round(x.b.width), h: Math.round(x.b.height)}))};
}"""

_CLICK_LABEL = """([prefix, nearY]) => {
  const hits = [...document.querySelectorAll('[aria-label]')]
    .filter(x => (x.getAttribute('aria-label') || '').startsWith(prefix))
    .map(x => ({x, b: x.getBoundingClientRect()}))
    .filter(h => h.b.width > 0 && h.b.y > 0)
    .sort((a, b) => Math.abs(a.b.y - nearY) - Math.abs(b.b.y - nearY));
  if (!hits.length) return false;
  const el = hits[0].x;
  el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
  return {y: Math.round(hits[0].b.y), count: hits.length};
}"""


_REACT_MUTATION = "IGDirectReactionSendMutation"

_REPLAY = """([body, head]) => fetch('/api/graphql', {
    method: 'POST', credentials: 'include',
    headers: {'content-type': 'application/x-www-form-urlencoded'},
    body}).then(r => r.text()).then(t => t.slice(0, head))"""



class BrowserProvider:
    """Implements `provider.Provider` by asking a logged-in browser to fetch."""

    def __init__(self, config, conn=None) -> None:
        self.config = config
        self.conn = conn
        self._pw = None
        self._browser = None
        self._ctx = None
        self._page = None
        self._pages: dict[str, object] = {}

    # ------------------------------------------------------------- lifecycle

    def connect(self) -> None:
        if self._page is not None:
            return
        self._attach()
        self._page = self._find("instagram.com")
        self._page.goto(f"{WEB}/", wait_until="domcontentloaded", timeout=60000)
        if not self._cookie("ds_user_id"):
            raise SessionExpired(NOT_LOGGED_IN)

    def _attach(self) -> None:
        """Get a browser and a context, once. Origin-free on purpose: the
        WhatsApp page must be reachable without touching Instagram's."""
        if self._ctx is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:                     # noqa: BLE001 - a clear message beats a traceback
            raise ProviderError(
                "PROVIDER=browser needs playwright — pip install playwright") from None
        self._pw = sync_playwright().start()
        cdp = getattr(self.config, "browser_cdp", "") or ""
        if cdp:
            self._browser = self._pw.chromium.connect_over_cdp(cdp)
            self._ctx = self._browser.contexts[0]
        else:
            profile = str(getattr(self.config, "browser_profile", "") or "")
            if not profile:
                raise ProviderError("PROVIDER=browser needs BROWSER_PROFILE or BROWSER_CDP")
            headless = bool(getattr(self.config, "browser_headless", False))
            if not headless and not os.environ.get("DISPLAY"):
                raise ProviderError(
                    "PROVIDER=browser is configured headed (BROWSER_HEADLESS=false) but there is "
                    "no DISPLAY — run under xvfb-run, or set BROWSER_HEADLESS=true")
            clear_stale_lock(profile)
            self._ctx = self._pw.chromium.launch_persistent_context(
                profile,
                headless=headless,
                executable_path=os.environ.get("CHROMIUM_PATH") or None,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
                # Playwright adds --enable-automation by default, which sets
                # navigator.webdriver. The whole point of this provider is that
                # there is nothing to tell apart from a person browsing.
                ignore_default_args=["--enable-automation"],
                viewport={"width": 1280, "height": 900},
                locale="en-GB", timezone_id="Europe/Athens")

    def _find(self, needle: str):
        """An existing tab on that origin, or a new one. Never `pages[0]`: with two
        origins in one browser, the first tab is whoever loaded first."""
        page = next((p for p in self._ctx.pages if needle in (p.url or "")), None)
        return page or self._ctx.new_page()

    def page_for(self, origin: str):
        """One page per origin. The Instagram relay holds its own into `_page`;
        the WhatsApp relay asks for its own, and neither navigation moves the
        other."""
        self._attach()
        page = self._pages.get(origin)
        if page is None:
            page = self._find(origin)
            self._pages[origin] = page
        return page

    def close(self) -> None:
        for obj in (self._ctx, self._browser):
            try:
                obj and obj.close()
            except Exception:                   # noqa: BLE001 - closing must never raise
                pass
        try:
            self._pw and self._pw.stop()
        except Exception:                       # noqa: BLE001
            pass
        self._page = self._ctx = self._browser = self._pw = None
        self._pages = {}

    def _cookie(self, name: str) -> str:
        for cookie in self._ctx.cookies():
            if cookie.get("name") == name:
                return cookie.get("value") or ""
        return ""

    @property
    def user_id(self) -> str:
        self.connect()
        return self._cookie("ds_user_id")

    # ------------------------------------------------------------------ calls

    def _call(self, path: str, params: dict | None = None, *, method: str = "GET",
              body: dict | None = None) -> dict:
        self.connect()
        url = path + (f"?{urlencode(params)}" if params else "")
        status, final, text = self._page.evaluate(_FETCH, [url, method, body or {}])
        if "challenge" in (final or ""):
            raise SessionExpired(CHALLENGE_MSG)
        if status in (401, 403):
            raise SessionExpired(f"{NOT_LOGGED_IN} [{path.split('?')[0]} {status}]")
        if status >= 400:
            raise ProviderError(f"Instagram returned {status} for {path}")
        try:
            return json.loads(text)
        except ValueError:
            # A login wall answers 200 with HTML. Saying so beats a JSON traceback.
            raise SessionExpired(f"{NOT_LOGGED_IN} [{path.split('?')[0]} html]") from None

    def _write(self, path: str, body: dict, what: str) -> None:
        """One attempt, no retry — same rule as every other write here."""
        try:
            self._call(path, method="POST", body=body)
        except SessionExpired as exc:
            raise SessionExpired(f"{what} failed: {exc}") from None
        except ProviderError as exc:
            raise type(exc)(f"{what} failed: {exc}") from None

    # ------------------------------------------------------------------ reads


    def following(self) -> tuple[list[AccountDTO], bool]:
        uid = self.user_id
        if not uid:
            raise ProviderError("logged in but Instagram returned no user id")
        accounts: list[AccountDTO] = []
        seen: set[str] = set()
        cursor: str | None = None
        try:
            for _ in range(PAGE_LIMIT):
                batch = self._call(FOLLOWING_URL.format(uid=uid),
                                   {"max_id": cursor} if cursor else None)
                users = batch.get("users") or []
                if not isinstance(users, list):
                    return accounts, False
                for user in users:
                    if not isinstance(user, dict):
                        continue
                    pk = str(user.get("pk") or user.get("id") or "")
                    if not pk or pk in seen:
                        continue
                    seen.add(pk)
                    accounts.append(AccountDTO(
                        pk=pk, username=user.get("username") or pk,
                        full_name=user.get("full_name"),
                        pic_url=user.get("profile_pic_url")))
                cursor = batch.get("next_max_id")
                if not batch.get("more_available") or not cursor:
                    return accounts, True
        except ProviderError:
            # A partial list must never look complete: the caller would unfollow
            # the tail and empty the allowlist.
            return accounts, False
        return accounts, False

    # ------------------------------------------------------------- messages
    #
    # Instagram's DM REST path is retired and its replacement carries a
    # `doc_id` that rotates, so these drive the page a person would open. The
    # list is free to read; opening a thread marks it read on Instagram, which
    # is why it is a separate call and not part of the list.

    def _open(self, path: str, settle: int = 5000) -> None:
        self.connect()
        self._page.goto(f"{WEB}{path}", wait_until="domcontentloaded", timeout=60000)
        self._page.wait_for_timeout(settle)
        url = self._page.url or ""
        if "challenge" in url:
            raise SessionExpired(CHALLENGE_MSG)
        if "/accounts/login" in url:
            raise SessionExpired(NOT_LOGGED_IN)

    def capture(self, path: str, name: str, settle: int = 5000) -> str:
        """Learn one of the page's own GraphQL requests by opening the page.

        `igd` replays these bodies, and a body is only learnable from the page
        that fires it — the `doc_id` rotates and nothing else carries the
        operation name. The match is on the name inside the POST body, which is
        how the reaction capture has always worked.
        """
        self.connect()
        bodies: list[str] = []

        def note(req) -> None:
            body = req.post_data or ""
            if "/api/graphql" in req.url and name in body:
                bodies.append(body)

        self._page.on("request", note)
        try:
            self._open(path, settle=settle)
            if not bodies:
                self._page.wait_for_timeout(3000)
        finally:
            self._page.remove_listener("request", note)
        return bodies[-1] if bodies else ""

    def _capture_reaction(self, path: str, settle: int) -> str:
        """Learn the reaction mutation by reacting once, then taking it back.

        Nothing on a page load fires this mutation, so the only way to learn its
        current `doc_id` is to press the button the way a person would. The
        reaction is removed again before returning: capturing a template must
        not leave a heart on someone's message.
        """
        self.connect()
        bodies: list[str] = []

        def note(req) -> None:
            body = req.post_data or ""
            if "/api/graphql" in req.url and _REACT_MUTATION in body:
                bodies.append(body)

        self._page.on("request", note)
        try:
            self._open(path, settle=settle)
            self._page.evaluate(_DISMISS, "Not Now")
            self._page.wait_for_timeout(600)
            y = self._page.evaluate(_HOVER_LAST_BUBBLE)
            if not y:
                return ""
            self._hover_last(y)
            self._page.evaluate(_CLICK_LABEL, ["React to message", y])
            self._page.wait_for_timeout(1500)
            spot = self._page.evaluate(_PICKER, y)
            spots = (spot or {}).get("spots") or []
            first = [s for s in spots if s.get("role") == "button"]
            if first:
                self._page.mouse.click(first[0]["x"] + first[0]["w"] / 2,
                                       first[0]["y"] + first[0]["h"] / 2)
            self._page.wait_for_timeout(2500)
        finally:
            self._page.remove_listener("request", note)
        if not bodies:
            return ""
        body = bodies[-1]
        # Put it back: same call, opposite status.
        try:
            undo = json.loads(parse_qs(body)["variables"][0])
            undo["input"]["reaction_status"] = "deleted"
            params = parse_qs(body, keep_blank_values=True)
            params["variables"] = [json.dumps(undo, separators=(",", ":"))]
            self.graphql(urlencode(params, doseq=True))
        except Exception:                   # noqa: BLE001 — the template matters, not the undo
            pass
        return body

    def graphql(self, body: str, limit: int = 8_000_000) -> str:
        """One replayed GraphQL POST, in the page's own session. Returns JSON text."""
        self.connect()
        return self._page.evaluate(_REPLAY, [body, limit])

    def inbox_raw(self) -> list[dict]:
        """The list's own lines, uncleaned. Diagnosis only."""
        self._open("/direct/inbox/")
        return list(self._page.evaluate(direct.INBOX_JS))

    def inbox(self) -> list[dict]:
        self._open("/direct/inbox/")
        return direct.clean_inbox(self._page.evaluate(direct.INBOX_JS))

    def thread(self, name: str) -> dict:
        self._open("/direct/inbox/")
        for _ in range(10):
            if self._page.evaluate(direct.OPEN_JS, name):
                break
            # The list renders only what is on screen; walk down it until the
            # conversation exists, then stop — a click on the wrong row would
            # open a stranger's thread.
            if not self._page.evaluate(direct.SCROLL_JS, 700):
                break
            self._page.wait_for_timeout(700)
        else:
            raise ProviderError(f"no conversation named {name!r}")
        self._page.wait_for_timeout(5000)
        if "challenge" in (self._page.url or ""):
            raise SessionExpired(CHALLENGE_MSG)
        return direct.clean_thread(self._page.evaluate(direct.THREAD_JS))

    def inbox_all(self, rounds: int = 40) -> list[dict]:
        """Every conversation the list will hand over, not just what is on screen.

        The list is virtual: it renders the rows in view. Scrolling to the end
        is the only way to see the quiet ones.
        """
        self._open("/direct/inbox/")
        seen: dict[str, dict] = {}
        for _ in range(rounds):
            for row in direct.clean_inbox(self._page.evaluate(direct.INBOX_JS)):
                seen.setdefault(row["name"], row)
            if not self._page.evaluate(direct.SCROLL_JS, 800):
                break
            self._page.wait_for_timeout(600)
        return list(seen.values())

    def fetch_probe(self, url: str) -> dict:
        """What the page's own fetch returns for a URL. Diagnosis only."""
        self.connect()
        status, final, text = self._page.evaluate(_FETCH, [url, "GET", {}])
        return {"status": status, "final": final, "head": text[:300]}

    def probe(self, name: str = "", path: str = "") -> dict:
        """Anchors, or the preloaded keys, of a page. Diagnosis only."""
        if path:
            self._open(path)
            return {"keys": self._page.evaluate(_XDT_KEYS),
                    "url": self._page.url}
        self.thread(name)
        return self._page.evaluate(direct.PROBE_JS)

    def history(self, name: str) -> list[dict]:
        """`[{text, mine}]` — the transcript, with authors, for a backfill."""
        self.thread(name)
        return direct.clean_rows(self._page.evaluate(direct.THREAD_ROWS_JS))

    def send_dm(self, name: str, text: str) -> bool:
        """Write into a conversation as the account.

        This is the one place the app speaks on Instagram, so it is deliberately
        blunt: open the thread, type, Enter, then read the transcript back and
        check the last line is ours. A `False` is a send that cannot be proven,
        which the caller treats as not sent.
        """
        self.thread(name)                  # navigates, opens, and proves the name
        box = self._page.locator('div[role="textbox"][contenteditable="true"]').last
        if box.count() == 0:
            box = self._page.locator("textarea").last
        if box.count() == 0:
            raise ProviderError("no message box on the thread page")
        box.click()
        box.type(text, delay=25)
        box.press("Enter")
        self._page.wait_for_timeout(2500)
        lines = direct.clean_thread(
            self._page.evaluate(direct.THREAD_JS))["lines"]
        return any(text[:40] in line for line in lines[-3:])

    def timeline_page(self, max_id: str | None) -> Page:
        """The newest posts, off the home page's own preload.

        No pagination: the old REST endpoint is gone and the GraphQL one needs a
        `doc_id` that rotates. One page is enough for a cycle — new posts are at
        the top — and the caller stops on the first page of already-stored ones.
        """
        if max_id:
            return Page(items=[], next_max_id=None, more_available=False)
        self._open("/")
        media = self._page.evaluate(_FEED_PREFETCH) or []
        return parse_timeline({"feed_items": [{"media_or_ad": m} for m in media],
                               "more_available": False})

    def post_by_code(self, code: str) -> PostDTO | None:
        """The post page's own preloaded media blob — the story-page trick again.

        Used when a link from a chat has to become a card without a sync.
        """
        self.connect()
        try:
            self._page.goto(f"{WEB}/p/{code}/", wait_until="domcontentloaded",
                            timeout=45000)
            url = self._page.url or ""
            if "challenge" in url:
                raise SessionExpired(CHALLENGE_MSG)
            if "/accounts/login" in url:
                raise SessionExpired(NOT_LOGGED_IN)
            media = self._page.evaluate(_POST_PREFETCH)
        except (SessionExpired, ProviderError):
            raise
        except Exception as exc:                    # noqa: BLE001 - page or JSON broke
            raise ProviderError(f"could not read post {code}: {exc}") from None
        if not isinstance(media, dict):
            return None
        return post_from_media(media)

    def story_tray(self) -> list[TrayEntry]:
        payload = self._call(f"{WEB}/api/v1/feed/reels_tray/")
        out: list[TrayEntry] = []
        for entry in payload.get("tray") or []:
            entry = _dict(entry)
            user = _dict(entry.get("user"))
            pk = str(user.get("pk") or entry.get("id") or "")
            if not pk:
                continue
            out.append(TrayEntry(
                account_pk=pk, username=user.get("username"),
                latest_reel_media=entry.get("latest_reel_media"),
                media_count=entry.get("media_count"),
                media_ids=[str(m) for m in entry.get("media_ids") or []],
                seen=entry.get("seen"), expiring_at=entry.get("expiring_at"),
                ring_thumb=user.get("profile_pic_url")))
        return out

    def user_stories(self, account_pk: str) -> list[StoryDTO]:
        """Read one account's segments off its own story page.

        `/api/v1/feed/reels_media/` answers 500 for web sessions now, and the
        GraphQL replacement speaks a `doc_id` that rotates with Instagram's
        builds. The story page, though, ships its data in a prefetched JSON
        blob — the same bytes the page itself renders — so no private endpoint
        and no doc_id to rot.
        """
        self.connect()
        # /stories/<pk>/ is a dead link — the route only resolves usernames.
        self._page.goto(f"{WEB}/stories/{self._username(account_pk)}/",
                        wait_until="domcontentloaded", timeout=45000)
        if "challenge" in (self._page.url or ""):
            raise SessionExpired(CHALLENGE_MSG)
        reels = self._page.evaluate(_STORY_PREFETCH) or []
        out: list[StoryDTO] = []
        for reel in reels:
            for media in _dict(reel).get("items") or []:
                media = _dict(media)
                pk = str(media.get("pk") or media.get("id") or "")
                if not pk:
                    continue
                user = _dict(media.get("user")) or _dict(_dict(reel).get("user"))
                taken = _epoch(media.get("taken_at"))
                out.append(StoryDTO(
                    pk=pk, account_pk=str(user.get("pk") or user.get("id") or account_pk),
                    media_type=int(media.get("media_type") or 1), taken_at=taken,
                    expiring_at=_epoch(media.get("expiring_at")) or taken + 86400,
                    src_url=_url(_best(media.get("video_versions"))
                                 or _best((media.get("image_versions2") or {}).get("candidates"))),
                    thumb_url=_url(_best((media.get("image_versions2") or {}).get("candidates"))),
                    duration=media.get("video_duration"),
                    links=_story_links(media)))
        return out

    def unfollow(self, account_pk: str) -> None:
        """Unfollow by clicking, for the same reason likes are clicks: Instagram
        has no web route left for it that does not speak a rotating `doc_id`.

        Following → the confirm dialog → verified by the header reading `Follow`.
        A single attempt: a follow change that may have landed must not repeat.
        """
        self.connect()
        page = self._page
        page.goto(f"{WEB}/{self._username(account_pk)}/",
                  wait_until="domcontentloaded", timeout=60000)
        if "challenge" in (page.url or ""):
            raise SessionExpired(CHALLENGE_MSG)

        point = None
        deadline = time.time() + 20.0
        while time.time() < deadline:
            point = page.evaluate(_FOLLOW_BUTTON)
            if point:
                break
            page.wait_for_timeout(500)
        if not point:
            raise ProviderError("could not find the Following button on that profile")
        page.mouse.click(*point)

        confirm = None
        deadline = time.time() + 10.0
        while time.time() < deadline:
            confirm = page.evaluate(_UNFOLLOW_CONFIRM)
            if confirm:
                break
            page.wait_for_timeout(250)
        if not confirm:
            raise ProviderError("the unfollow dialog never appeared")
        page.mouse.click(*confirm)

        deadline = time.time() + self.like_timeout
        while time.time() < deadline:
            if page.evaluate(_FOLLOW_STATE) == "Follow":
                return
            page.wait_for_timeout(250)
        raise ProviderError("the unfollow did not register — the profile still reads Following")

    def _username(self, account_pk: str) -> str:
        if self.conn is not None:
            row = self.conn.execute(
                "SELECT username FROM accounts WHERE pk=?", (account_pk,)).fetchone()
            if row and row["username"]:
                return row["username"]
        return account_pk

    def media_stream(self, url: str, byte_range: str | None = None) -> Iterator[bytes]:
        """The CDN is not Instagram's API: no session, no identity. Plain HTTP."""
        if not host_allowed(url, "instagrapi"):
            raise ProviderError("media host not allowed: " + url)
        import httpx

        headers = {"Range": byte_range} if byte_range else None
        with httpx.Client(follow_redirects=True, timeout=30.0) as http:
            with http.stream("GET", url, headers=headers) as resp:
                if resp.status_code >= 400:
                    raise ProviderError(f"media upstream returned {resp.status_code}")
                yield from resp.iter_bytes()

    # ------------------------------------------------------------- whatsapp
    #
    # WhatsApp Web has no API: these are the hands for `wadirect`, which holds
    # every selector. One method per browser action on purpose — Playwright's
    # sync API is thread-affine, so each call must travel through ThreadProxy on
    # its own, and a whole cycle must not hold the sync lock.

    def wa_page(self):
        page = self.page_for(WA)
        if not (getattr(page, "url", "") or "").startswith(WA):
            page.goto(f"{WA}/", wait_until="domcontentloaded", timeout=60000)
        return page

    def wa_eval(self, js: str, arg=None):
        return self.wa_page().evaluate(js, arg)

    def wa_click(self, x: float, y: float) -> None:
        self.wa_page().mouse.click(x, y)

    def wa_move(self, x: float, y: float) -> None:
        self.wa_page().mouse.move(x, y)

    def wa_type(self, text: str) -> None:
        self.wa_page().keyboard.type(text, delay=15)

    def wa_press(self, key: str) -> None:
        self.wa_page().keyboard.press(key)

    def wa_wait(self, ms: int) -> None:
        self.wa_page().wait_for_timeout(ms)

    def wa_screenshot(self, path: str) -> None:
        self.wa_page().screenshot(path=path)

    # ----------------------------------------------------------------- writes

    like_timeout = 12.0        # seconds allowed for the heart to change

    def like(self, pk: str) -> None:
        self._toggle_like(pk, True)

    def unlike(self, pk: str) -> None:
        self._toggle_like(pk, False)

    def _toggle_like(self, pk: str, want: bool) -> None:
        """Click the heart a person would click.

        Why not the API: `/api/v1/media/<pk>/like/` and the newer
        `/api/v1/web/likes/<pk>/like/` both answer a login redirect even with a
        live session — web likes moved to a GraphQL mutation whose `doc_id`
        rotates with Instagram's builds. A click cannot rot, and it is exactly
        the request Instagram expects from a browser.
        """
        url = self._post_url(pk)
        self.connect()
        self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
        state = self._wait_for_heart()
        if state is None:
            raise ProviderError("no like button on the post page — is the post still there?")
        if (state["label"] == "Unlike") == want:
            return                                  # already in the wanted state
        x, y = state["point"]
        self._page.mouse.click(x, y)
        deadline = time.time() + self.like_timeout
        while time.time() < deadline:
            time.sleep(0.5)
            now = self._page.evaluate(_LIKE_STATE)
            if now and (now["label"] == "Unlike") == want:
                return
        raise ProviderError("the like did not register — the page never changed state")

    def _wait_for_heart(self) -> dict | None:
        """The post page hydrates: the heart is not there at domcontentloaded."""
        for _ in range(24):
            state = self._page.evaluate(_LIKE_STATE)
            if state:
                return state
            time.sleep(0.5)
        return None

    def _post_url(self, pk: str) -> str:
        if self.conn is None:
            raise ProviderError("likes need a database connection")
        row = self.conn.execute("SELECT code, permalink FROM posts WHERE pk=?",
                                (pk,)).fetchone()
        if row is not None:
            if row["permalink"]:
                return str(row["permalink"])
            if row["code"]:
                return f"{WEB}/p/{row['code']}/"
        raise ProviderError(f"no permalink stored for post {pk}")

    def react_to_story(self, story_pk: str, emoji: str) -> None:
        """A story reaction is a DM to the author, same as before. The browser
        posts it same-origin, so it carries the real csrftoken and thread rules."""
        author = self._story_author(story_pk)
        self._write(
            f"{WEB}/api/v1/direct_v2/threads/broadcast/text/",
            {"recipient_users": json.dumps([[author]]), "text": emoji,
             "client_context": uuid.uuid4().hex, "action_source": "post_impression_tracker"},
            "story reaction")

    def _story_author(self, story_pk: str) -> str:
        if self.conn is None:
            raise ProviderError("story reactions need a database connection")
        row = self.conn.execute("SELECT account_pk FROM stories WHERE pk=?",
                                (story_pk,)).fetchone()
        if row is None:
            raise ProviderError(f"unknown story {story_pk}")
        return row["account_pk"]
