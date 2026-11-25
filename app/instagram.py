"""The real provider: instagrapi for the mobile API, the web host for the timeline.

Measured in Phase 0 (design §Data source): `Client.get_timeline_feed` jams on a
constant `next_max_id`; the same endpoint on `www.instagram.com` paginates. So
`timeline_page` issues that request itself, with the session cookies.
`parse_timeline` is pure, so the mapping is tested from a JSON fixture offline.

Nothing instagrapi-shaped leaves this module: every return value is a DTO.
instagrapi is imported lazily so `PROVIDER=mock` and the tests never need it.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from . import store
from .dtos import AccountDTO, Page, PostDTO, ResourceDTO, StoryDTO, TrayEntry
from .provider import ProviderError, SessionExpired

WEB = "https://www.instagram.com"
TIMELINE_URL = f"{WEB}/api/v1/feed/timeline/"
FOLLOWING_URL = f"{WEB}/api/v1/friendships/{{uid}}/following/"
WEB_HEADERS = {
    "x-ig-app-id": "936619743392459",
    "Accept": "*/*",
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
}
ALLOWED_HOSTS = ("cdninstagram.com", "fbcdn.net")
PAGE_LIMIT = 50           # following(): hard ceiling, one page is ~200 users

# meta, not settings: `GET /api/settings` returns the settings table verbatim,
# and the cookie must never be echoed by any API.
COOKIE_META = "ig_session_cookie"
SESSION_EXPIRED_MSG = "Instagram session expired — paste a new cookie in Settings"


def host_allowed(url: str, provider: str = "instagrapi") -> bool:
    """The provider's own copy of the media allowlist. `media_stream` attaches
    the session, so a tampered URL must die here even if media.py were bypassed."""
    parts = urlsplit(url)
    if provider == "mock" and parts.scheme == "mock":
        return True
    if parts.scheme != "https":
        return False
    host = (parts.hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)


def resolve_cookie(conn, config) -> str:
    """DB then env: a cookie pasted in Settings wins without a restart."""
    if conn is not None:
        try:
            value = store.meta_json(conn, COOKIE_META, None)
        except Exception:
            value = None
        if isinstance(value, str) and value.strip():
            return value.strip()
    return (getattr(config, "ig_session_cookie", "") or "").strip()


CHALLENGE_MSG = ("Instagram is asking for a security check on this account — finish it in "
                 "the Instagram app, then paste a fresh sessionid")


def redirect_error(resp) -> Exception | None:
    """A challenge arrives as a 302 to /challenge/, never as a JSON error.

    Chasing that redirect (the old behaviour) produced `TooManyRedirects` and a
    dead session instead of the one sentence that explains both.
    """
    if resp.status_code not in (301, 302, 303, 307, 308):
        return None
    location = (resp.headers.get("location") or "").lower()
    if "challenge" in location:
        return SessionExpired(CHALLENGE_MSG)
    if "login" in location or "accounts" in location:
        return SessionExpired(SESSION_EXPIRED_MSG)
    return ProviderError(f"Instagram redirected the API to {location or 'nowhere'}")


def cookie_header(raw: str) -> dict[str, str]:
    """A bare `sessionid` value and a full `a=b; c=d` header are both accepted."""
    raw = (raw or "").strip()
    if not raw:
        return {}
    if "=" not in raw:
        return {"sessionid": raw}
    out = {}
    for part in raw.split(";"):
        key, _, val = part.partition("=")
        if key.strip():
            out[key.strip()] = val.strip()
    return out


# ------------------------------------------------------------------ parsing


def _best(candidates) -> str | None:
    """Insta lists candidates largest first."""
    if not isinstance(candidates, list):
        return None
    for cand in candidates:
        if isinstance(cand, dict) and cand.get("url"):
            return cand["url"]
    return None


def _is_ad(media: dict) -> bool:
    """Own exclusion: a followed account's paid post is still an ad (§3.2)."""
    return (media.get("product_type") == "ad"
            or bool(media.get("is_paid_partnership"))
            or bool(media.get("sponsor_tags")))


def _resources(media: dict) -> list[ResourceDTO]:
    carousel = media.get("carousel_media")
    parts = carousel if isinstance(carousel, list) and carousel else [media]
    out: list[ResourceDTO] = []
    for idx, part in enumerate(parts):
        image = _best((part.get("image_versions2") or {}).get("candidates"))
        video = _best(part.get("video_versions"))
        if not image and not video:
            continue
        out.append(ResourceDTO(
            idx=idx, type="video" if video else "image",
            src_url=video or image, poster_url=image if video else None,
            w=part.get("original_width"), h=part.get("original_height"),
            duration=part.get("video_duration")))
    return out


def _dict(x) -> dict:
    return x if isinstance(x, dict) else {}


def _user(node) -> dict:
    """A tagged-user entry, in either shape Instagram sends it: `{user: {...}}`
    for a usertag, the user itself for a coauthor."""
    node = _dict(node)
    return _dict(node["user"]) if isinstance(node.get("user"), dict) else node


def post_links(media: dict) -> list[dict]:
    """The accounts, places and songs a post carries.

    Read off the same media dict the timeline already sends, and shaped like a
    story's stickers: `{kind, label, url, detail}`. Instagram publishes no
    structured mention list for caption text, so an `@name` typed in a caption
    stays text and the page turns it into a link; everything here is a real tag
    the author attached to the picture, and every url is read-only.
    """
    out: list[dict] = []

    def add(kind: str, label: str, url: str | None = None,
            detail: str | None = None) -> None:
        label = (label or "").strip()
        if not label or any(l["kind"] == kind and l["label"] == label for l in out):
            return
        out.append({"kind": kind, "label": label, "url": url, "detail": detail})

    def profiles(entries) -> None:
        for entry in entries or []:
            user = _user(_dict(entry).get("node") or entry)
            name = user.get("username")
            if name:
                add("profile", name, f"{WEB}/{name}/", user.get("full_name"))

    tags = media.get("usertags")
    if isinstance(tags, dict):
        profiles(tags.get("in"))
    elif isinstance(tags, list):
        profiles(tags)
    # The timeline speaks the web API's snake case; older payloads nest edges.
    edges = _dict(media.get("edge_media_to_tagged_user")).get("edges")
    profiles([_dict(e) for e in edges or []])
    profiles(media.get("coauthor_producers"))
    profiles(media.get("coauthor_producers_v2"))

    place = _dict(media.get("location"))
    if place.get("name"):
        pk = place.get("pk") or place.get("id")
        add("place", place.get("name"),
            f"{WEB}/explore/locations/{pk}/" if pk else None, place.get("address"))

    info = _dict(_dict(media.get("clips_metadata")).get("music_info"))
    asset = _dict(info.get("music_asset_info")) or _dict(info.get("music_consumption_info"))
    if asset.get("title"):
        add("music", asset.get("title"), None, asset.get("display_artist"))
    return out


def post_from_media(media: dict) -> PostDTO | None:
    """One web-API media dict -> PostDTO. `None` when it cannot be stored."""
    user = media.get("user") or {}
    account_pk = str(user.get("pk") or user.get("id") or "")
    pk = str(media.get("pk") or media.get("id") or "")
    if not pk or not account_pk:
        return None
    caption = media.get("caption")
    if isinstance(caption, dict):
        caption = caption.get("text")
    taken = media.get("taken_at") or media.get("taken_at_timestamp") or 0
    code = media.get("code")
    return PostDTO(
        pk=pk, account_pk=account_pk,
        media_type=int(media.get("media_type") or 1),
        taken_at=int(taken), code=code,
        product_type=media.get("product_type"), caption=caption,
        like_count=media.get("like_count"),
        comment_count=media.get("comment_count"),
        permalink=f"{WEB}/p/{code}/" if code else None,
        links=post_links(media),
        resources=_resources(media))


def parse_timeline(payload: dict) -> Page:
    """Pure: fixture in, Page out. No client, no network."""
    items: list[PostDTO] = []
    for entry in payload.get("feed_items") or []:
        if not isinstance(entry, dict):
            continue
        media = entry.get("media_or_ad")
        if not isinstance(media, dict) or _is_ad(media):
            continue
        post = post_from_media(media)
        if post is not None and post.resources:
            items.append(post)
    return Page(items=items, next_max_id=payload.get("next_max_id") or None,
                more_available=bool(payload.get("more_available")))


# ----------------------------------------------------------------- provider


class InstagrapiProvider:
    def __init__(self, config, conn=None) -> None:
        self.config = config
        self.conn = conn
        self._client = None
        self._settings_path = Path(config.data_dir) / "session.json"

    # ----------------------------------------------------------- connection

    def connect(self) -> None:
        if self._client is not None:
            return
        cookie = resolve_cookie(self.conn, self.config)
        if not cookie:
            # Checked before the import: PROVIDER=instagrapi with no cookie must
            # say what is missing, not crash on a missing module or a network call.
            raise SessionExpired("no Instagram session cookie — paste one in Settings")
        from instagrapi import Client

        client = Client()
        client.delay_range = [1.5, 3.5]
        self._inject_device(client)
        if self._settings_path.is_file():
            client.load_settings(self._settings_path)
        try:
            client.login_by_sessionid(cookie)
        except Exception as exc:          # noqa: BLE001 - one attempt, never a loop
            raise _map_error(exc) from None
        self._client = client
        self._persist_identity(client)

    def _inject_device(self, client) -> None:
        """Design: only device fields ever leave disk, and they survive a restore."""
        device = store.meta_json(self.conn, "device", None) if self.conn else None
        if not isinstance(device, dict):
            return
        if device.get("device_settings"):
            client.set_device(device["device_settings"])
        if device.get("uuids"):
            client.set_uuids(device["uuids"])

    def _persist_identity(self, client) -> None:
        try:
            self._settings_path.parent.mkdir(parents=True, exist_ok=True)
            client.dump_settings(self._settings_path)
            os.chmod(self._settings_path, 0o600)
        except Exception:          # noqa: BLE001 - a read-only volume must not break a sync
            pass
        if self.conn is None:
            return
        try:
            settings = client.get_settings()
        except Exception:          # noqa: BLE001
            return
        store.set_meta_json(self.conn, "device", {
            "device_settings": settings.get("device_settings"),
            "uuids": settings.get("uuids"),
        })

    @property
    def client(self):
        self.connect()
        return self._client

    def _web_get(self, url: str, params: dict | None = None) -> dict:
        with self._http(follow=False) as http:
            resp = http.get(url, params=params)
        redirected = redirect_error(resp)
        if redirected is not None:
            raise redirected
        if resp.status_code in (401, 403):
            raise SessionExpired(SESSION_EXPIRED_MSG)
        if resp.status_code != 200:
            raise ProviderError(f"Instagram web API returned {resp.status_code}")
        try:
            return resp.json()
        except ValueError:
            raise ProviderError("Instagram web API returned non-JSON") from None

    def _http(self, follow: bool = True) -> httpx.Client:
        cookies = self._cookies()
        headers = dict(WEB_HEADERS)
        if cookies.get("csrftoken"):
            headers["x-csrftoken"] = cookies["csrftoken"]
        return httpx.Client(cookies=cookies, headers=headers,
                            follow_redirects=follow, timeout=30.0)

    def _cookies(self) -> dict[str, str]:
        if self._client is not None:
            try:
                return dict(self._client.session.cookies.get_dict())
            except Exception:      # noqa: BLE001
                pass
        return cookie_header(resolve_cookie(self.conn, self.config))

    # -------------------------------------------------------------- protocol

    def following(self) -> tuple[list[AccountDTO], bool]:
        self.connect()
        uid = str(self.client.user_id or self._cookies().get("ds_user_id") or "")
        if not uid:
            raise ProviderError("logged in but Instagram returned no user id")
        accounts: list[AccountDTO] = []
        seen: set[str] = set()
        cursor: str | None = None
        complete = False
        try:
            for _ in range(PAGE_LIMIT):
                batch = self._web_get(FOLLOWING_URL.format(uid=uid),
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
                    complete = True
                    break
        except ProviderError:
            # A partial list must never look complete: the caller would unfollow
            # the tail and empty the allowlist.
            return accounts, False
        return accounts, complete

    def timeline_page(self, max_id: str | None) -> Page:
        self.connect()
        return parse_timeline(self._web_get(TIMELINE_URL,
                                            {"max_id": max_id} if max_id else None))

    def post_by_code(self, code: str) -> PostDTO | None:
        """One post, by shortcode. None when Instagram has no such code."""
        self.connect()
        try:
            pk = self.client.media_pk_from_code(code)
            info = self.client.media_info(pk)
        except Exception as exc:      # noqa: BLE001
            # A code that does not decode cannot exist; anything else is mapped.
            if isinstance(exc, ValueError) or "notfound" in type(exc).__name__.lower():
                return None
            raise _map_error(exc) from None
        media = info.dict() if hasattr(info, "dict") else dict(info)
        post = post_from_media(media)
        if post is None or not post.resources:
            raise ProviderError(f"could not read post {code}")
        return post

    def story_tray(self) -> list[TrayEntry]:
        self.connect()
        try:
            payload = _dict(self.client.get_reels_tray_feed())
        except Exception as exc:      # noqa: BLE001
            raise _map_error(exc) from None
        out: list[TrayEntry] = []
        for entry in payload.get("tray") or []:
            entry = _dict(entry)
            user = entry.get("user") or {}
            pk = str(user.get("pk") or entry.get("id") or "")
            if not pk:
                continue
            media_ids = entry.get("media_ids") or []
            out.append(TrayEntry(
                account_pk=pk, username=user.get("username"),
                latest_reel_media=entry.get("latest_reel_media"),
                media_count=entry.get("media_count"),
                media_ids=[str(m) for m in media_ids],
                seen=entry.get("seen"), expiring_at=entry.get("expiring_at"),
                ring_thumb=user.get("profile_pic_url")))
        return out

    def user_stories(self, account_pk: str) -> list[StoryDTO]:
        # Registering a view is measured, accepted and documented (design §Stories).
        self.connect()
        try:
            stories = self.client.user_stories(account_pk)
        except Exception as exc:      # noqa: BLE001
            raise _map_error(exc) from None
        out = []
        for story in stories or []:
            media = _dict(story)
            pk = str(media.get("pk") or media.get("id") or "")
            if not pk:
                continue
            user = _dict(media.get("user")) or {}
            taken = _epoch(media.get("taken_at"))
            out.append(StoryDTO(
                pk=pk, account_pk=str(user.get("pk") or user.get("id") or account_pk),
                media_type=int(media.get("media_type") or 1),
                taken_at=taken,
                expiring_at=_epoch(media.get("expiring_at")) or taken + 86400,
                # instagrapi's Story carries `video_url`/`thumbnail_url`; the web
                # dict carries `video_versions`/`image_versions2`. Both shapes land
                # here, because dev_seed only ever produced the web shape.
                src_url=_url(_best(media.get("video_versions"))
                             or media.get("video_url")
                             or _best((media.get("image_versions2") or {}).get("candidates"))
                             or media.get("thumbnail_url")),
                thumb_url=_url(_best((media.get("image_versions2") or {}).get("candidates"))
                               or media.get("thumbnail_url")),
                duration=media.get("video_duration")))
        return out

    # ---------------------------------------------------------------- writes

    def like(self, pk: str) -> None:
        self._write(lambda c: c.media_like(pk), "like")

    def unlike(self, pk: str) -> None:
        self._write(lambda c: c.media_unlike(pk), "unlike")

    def react_to_story(self, story_pk: str, emoji: str) -> None:
        """A story emoji reaction is a DM to the author, which is what Instagram
        itself sends. `story_like` exists and is lighter, but it is a silent
        like, not a reaction someone can read."""
        author = self._story_author(story_pk)
        self._write(lambda c: c.direct_send(emoji, user_ids=[int(author)]), "story reaction")

    def _story_author(self, story_pk: str) -> str:
        if self.conn is None:
            raise ProviderError("story reactions need a database connection")
        row = self.conn.execute(
            "SELECT account_pk FROM stories WHERE pk=?", (story_pk,)).fetchone()
        if row is None:
            raise ProviderError(f"unknown story {story_pk}")
        return row["account_pk"]

    def _write(self, call, what: str) -> None:
        # One attempt, no retry: a write that may have landed must not be sent
        # twice. The caller rolls the UI back and the human decides.
        self.connect()
        try:
            call(self.client)
        except Exception as exc:      # noqa: BLE001
            err = _map_error(exc)
            raise type(err)(f"{what} failed: {err}") from None

    def media_stream(self, url: str, byte_range: str | None = None) -> Iterator[bytes]:
        # Checked before any request: the allowlist inside the provider too.
        if not host_allowed(url, self.config.provider):
            raise ProviderError(f"media host not allowed: {urlsplit(url).hostname}")
        return self._stream(url, byte_range)

    def _stream(self, url: str, byte_range: str | None) -> Iterator[bytes]:
        headers = {"Range": byte_range} if byte_range else None
        with self._http() as http:
            with http.stream("GET", url, headers=headers) as resp:
                if resp.status_code in (401, 403):
                    raise SessionExpired(SESSION_EXPIRED_MSG)
                if resp.status_code >= 400:
                    raise ProviderError(f"media upstream returned {resp.status_code}")
                yield from resp.iter_bytes()


def _url(value) -> str | None:
    """Pydantic gives `HttpUrl` objects; SQLite only takes str/int/bytes."""
    if value is None or value == "":
        return None
    return str(value)


def _epoch(value) -> int:
    """instagrapi hands back datetimes where the web API hands back seconds.
    One helper, so a story timestamp cannot explode inside int()."""
    if isinstance(value, datetime):
        return int(value.timestamp())
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return int(value or 0)


def _dict(obj) -> dict:
    if isinstance(obj, dict):
        return obj
    dump = getattr(obj, "dict", None)
    if callable(dump):
        return dump()
    model_dump = getattr(obj, "model_dump", None)
    if callable(model_dump):
        return model_dump()
    return {}


def _map_error(exc: Exception) -> ProviderError:
    name = type(exc).__name__.lower()
    if "loginrequired" in name or "session" in name or "challenge" in name:
        return SessionExpired(SESSION_EXPIRED_MSG)
    return ProviderError(f"Instagram error: {type(exc).__name__}")
