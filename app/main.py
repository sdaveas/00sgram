"""FastAPI app: auth, the JSON API, static mount.

One connection, all writes through store.write(). No request ever calls
Instagram; everything reads SQLite. Media and the synced stories arrive in
later steps and say so instead of pretending.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import igd, iglink, recognize, store
from .config import Config
from .media import MediaStore, unavailable
from .provider import ProviderError, SessionExpired
from . import relay
from .relay import start_outbox, start_reacts, start_relay
from . import warelay
from .sync import Syncer, start_scheduler
from .telegram import Telegram, TelegramError, start_poller
from .wadirect import Wa

STATIC = Path(__file__).parent / "static"


class _Revalidating(StaticFiles):
    """`no-cache` means revalidate, not "don't store": a redeploy must not
    leave a browser running last week's app.js against today's API."""

    def file_response(self, *a, **kw):
        resp = super().file_response(*a, **kw)
        resp.headers["cache-control"] = "no-cache"
        return resp


KINDS = ("photo", "video", "carousel", "reel", "igtv")


class ApiError(Exception):
    def __init__(self, code: str, status: int, message: str, **extra):
        self.code, self.status, self.message, self.extra = code, status, message, extra


# ------------------------------------------------------------------ auth


def sign(exp: int, secret: str) -> str:
    return hmac.new(secret.encode(), str(exp).encode(), hashlib.sha256).hexdigest()


def make_cookie(secret: str, ttl: int = 7 * 86400, now: int | None = None) -> str:
    exp = int(now if now is not None else time.time()) + ttl
    return f"{exp}.{sign(exp, secret)}"


def cookie_ok(value: str | None, secret: str, now: int | None = None) -> bool:
    if not value or "." not in value:
        return False
    exp_s, _, sig = value.partition(".")
    try:
        exp = int(exp_s)
    except ValueError:
        return False
    if exp < int(now if now is not None else time.time()):
        return False
    return hmac.compare_digest(sig.encode(), sign(exp, secret).encode())


class Auth:
    __slots__ = ("device", "mode")

    def __init__(self, device: str, mode: str):
        self.device, self.mode = device, mode


def resolve_auth(request: Request, config: Config) -> Auth | None:
    if cookie_ok(request.cookies.get("s"), config.app_secret):
        device = request.cookies.get("device") or ""
        return Auth(device, "cookie") if device else None
    token = request.headers.get("x-api-token", "")
    device = request.headers.get("x-device", "")
    if token and device and hmac.compare_digest(token.encode(), config.api_token.encode()):
        return Auth(device, "token")
    return None


def auth(request: Request) -> Auth:
    a = getattr(request.state, "auth", None)
    if a is None:
        raise ApiError("unauthorised", 401, "missing or expired credentials")
    return a


# ---------------------------------------------------------------- bodies


class LoginBody(BaseModel):
    password: str


class ReactBody(BaseModel):
    emoji: str


class SessionBody(BaseModel):
    mode: str = "unseen"
    filters: dict = Field(default_factory=dict)
    take_over: int | None = None


class PatchSession(BaseModel):
    cursor: str | None = None
    last_rendered_pk: str | None = None


class SeenBody(BaseModel):
    pks: list[str]
    session: int | None = None


class StorySeenBody(BaseModel):
    pks: list[str]


class MuteBody(BaseModel):
    muted: bool


class SendMessageBody(BaseModel):
    chat_id: str
    text: str


class ChatSendBody(BaseModel):
    chat_id: str
    text: str


class SettingsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sync_interval: int | None = None
    view_threshold_ms: int | None = None
    story_auto_advance_accounts: bool | None = None
    hide_muted: bool | None = None
    types: list[str] | str | None = None
    ig_session_cookie: str | None = None


# ------------------------------------------------------------------ app


def create_app(config: Config | None = None) -> FastAPI:
    cfg = config or Config.from_env()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    Path(cfg.backup_dir).mkdir(parents=True, exist_ok=True)
    db_file = store.db_path(cfg.data_dir)
    conn = store.connect(db_file)
    store.init(conn, cfg)
    store.close_orphaned_runs(conn)

    @asynccontextmanager
    async def lifespan(_app):
        # One daemon: cycles on the DB interval, plus a daily backup. Tests never
        # enter the lifespan, so nothing here fires under TestClient.
        _app.state.media.prune()
        # The cap is a promise, not a target for the next write: a budget lowered
        # on a full cache has to bite at boot, not at the next picture.
        _app.state.media.evict()
        _thread, stop = start_scheduler(cfg, conn, _app.state.syncer)
        poll = start_poller(cfg, conn)
        relay = start_relay(cfg, conn, _app.state.syncer)
        outbox = start_outbox(cfg, conn, _app.state.syncer)
        reacts = start_reacts(cfg, conn, _app.state.syncer)
        wa_relay = warelay.start_wa_relay(cfg, conn, _app.state.syncer)
        wa_outbox = warelay.start_wa_outbox(cfg, conn, _app.state.syncer)
        wa_reacts = warelay.start_wa_reacts(cfg, conn, _app.state.syncer)
        try:
            yield
        finally:
            stop.set()
            poll.set()
            relay.set()
            outbox.set()
            wa_relay.set()
            wa_outbox.set()
            wa_reacts.set()

    app = FastAPI(title="00sgram", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.config, app.state.conn = cfg, conn
    app.state.media = MediaStore(cfg, conn)
    app.state.syncer = Syncer(cfg, conn)
    # account_pk -> (state, error). The lazy story fetch runs on executor B.
    app.state.story_fetch = {}
    app.state.executor_b = ThreadPoolExecutor(2, thread_name_prefix="user")

    # -------------------------------------------------------------- errors

    @app.exception_handler(ApiError)
    def _api_error(_request: Request, exc: ApiError):
        body = {"error": {"code": exc.code, "message": exc.message, **exc.extra}}
        return JSONResponse(body, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    def _validation(_request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(x) for x in first.get("loc", ()))
        return JSONResponse({"error": {"code": "bad_request",
                                       "message": f"{where}: {first.get('msg', 'invalid')}"}},
                            status_code=400)

    @app.exception_handler(Exception)
    def _unhandled(_request: Request, exc: Exception):
        return JSONResponse({"error": {"code": "internal", "message": str(exc)}},
                            status_code=500)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        if path not in ("/login", "/logout", "/api/health") and not path.startswith("/static") \
                and path not in ("/", "/app.js", "/views.js", "/style.css", "/favicon.ico"):
            request.state.auth = resolve_auth(request, cfg)
            if request.state.auth is None:
                return JSONResponse(
                    {"error": {"code": "unauthorised",
                               "message": "missing or expired credentials"}},
                    status_code=401)
        else:
            request.state.auth = resolve_auth(request, cfg)
        resp = await call_next(request)
        # No inline <script>, no third-party anything: the app is two files and
        # a stylesheet. `style-src` needs 'unsafe-inline' for the handful of
        # style="" attributes in views.js. No HSTS: this is plain HTTP on the LAN.
        resp.headers.setdefault("Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; media-src 'self'; "
            "style-src 'self' 'unsafe-inline'; script-src 'self'; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
            "form-action 'self'")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        return resp

    # ---------------------------------------------------------------- auth

    @app.post("/login")
    def login(body: LoginBody, request: Request):
        if not hmac.compare_digest(body.password.encode(),
                                   cfg.app_password.encode()):
            raise ApiError("unauthorised", 401, "wrong password")
        device = request.cookies.get("device") or secrets.token_hex(8)
        resp = JSONResponse({"ok": True, "device": device})
        common = dict(httponly=True, samesite="lax", secure=cfg.cookie_secure, path="/")
        resp.set_cookie("s", make_cookie(cfg.app_secret), max_age=7 * 86400, **common)
        resp.set_cookie("device", device, max_age=365 * 86400, **common)
        return resp

    @app.post("/logout")
    def logout():
        resp = JSONResponse({"ok": True})
        resp.delete_cookie("s", path="/")
        return resp

    @app.get("/api/health")
    def health():
        return {"ok": True}

    # -------------------------------------------------------------- status

    @app.get("/api/status")
    def status(request: Request, a: Auth = Depends(auth)):
        sess = store.current_session(conn, a.device)
        counts = store.session_counts(conn, sess) if sess else {
            "item_count": 0, "consumed": 0, "remaining": 0, "new_since_start": 0}
        last = None
        if sess and sess["last_rendered_pk"]:
            row = store.post_by_pk(conn, sess["last_rendered_pk"])
            if row:
                last = {"pk": row["pk"], "taken_at": row["taken_at"]}
        sync_state = store.meta_json(conn, "sync_state", {})
        backup = conn.execute("SELECT MAX(created_at) AS t, COUNT(*) AS n FROM backups"
                              " WHERE ok=1").fetchone()
        storage = store.storage_bytes(conn, db_file)
        return {
            "posts": {"unseen": store.unseen_counts(conn)["posts"],
                      "new_since_start": counts["new_since_start"],
                      "accounts_with_new": store.unseen_counts(conn)["accounts"]},
            "stories": store.story_counts(conn, sess),
            "session": None if sess is None else {
                "id": sess["id"], "device": sess["device"],
                "started_at": sess["started_at"], "mode": sess["mode"],
                "items": counts["item_count"], "consumed": counts["consumed"],
                "remaining": counts["remaining"], "last_rendered": last},
            "sessions_open": [dict(r) for r in store.open_sessions(conn)],
            "accounts": {
                "following": conn.execute(
                    "SELECT COUNT(*) AS n FROM accounts WHERE is_following=1").fetchone()["n"],
                "muted": conn.execute(
                    "SELECT COUNT(*) AS n FROM accounts WHERE muted=1").fetchone()["n"]},
            "instagram": store.meta_json(conn, "session", {
                "session_ok": False, "last_ok_at": None, "failed_at": None,
                "reason": "never connected"}),
            "provider": cfg.provider,
            "sync": {"last_success_at": sync_state.get("last_success_at"),
                     "last_attempt_at": sync_state.get("last_attempt_at"),
                     "duration_ms": sync_state.get("duration_ms"),
                     "new_posts": sync_state.get("new_posts", 0),
                     "new_stories": sync_state.get("new_stories", 0),
                     "next_sync_at": sync_state.get("next_sync_at"),
                     "frozen_until": sync_state.get("frozen_until"),
                     "paused": bool(sync_state.get("paused")),
                     "last_backfill_at": sync_state.get("last_backfill_at"),
                     "error": sync_state.get("error")},
            "backup": {"last_ok_at": backup["t"], "count": int(backup["n"] or 0)},
            "storage": {**storage, "media_budget": cfg.media_budget_mb * 1024 * 1024},
        }

    # ------------------------------------------------------------ sessions

    def _filters(raw: dict) -> dict:
        kinds = raw.get("types") or raw.get("kinds") or list(KINDS)
        bad = set(kinds) - set(KINDS)
        if bad:
            raise ApiError("bad_request", 400, f"unknown types: {sorted(bad)}")
        return {"kinds": list(kinds), "hide_muted": bool(raw.get("hide_muted", True)),
                "account": raw.get("account"), "from": raw.get("from"),
                "to": raw.get("to")}

    def _item(row) -> dict:
        acc = conn.execute("SELECT pk, username FROM accounts WHERE pk=?",
                           (row["account_pk"],)).fetchone()
        return {
            "pk": row["pk"],
            "account": {"pk": row["account_pk"],
                        "username": acc["username"] if acc else None,
                        "pic": f"/api/media/account/{row['account_pk']}"},
            "kind": row["kind"], "taken_at": row["taken_at"],
            "caption": row["caption"],
            "permalink": row["permalink"] or f"https://www.instagram.com/p/{row['code']}/",
            "engagement": {"likes": row["like_count"], "comments": row["comment_count"]},
            "seen": row["seen_at"] is not None,
            "liked": bool(row["liked"]),
            "links": json.loads(row["links"] or "[]")
            if "links" in row.keys() else [],
            "resources": [_res(row["pk"], r) for r in store.post_resources(conn, row["pk"])],
        }

    def _res(pk: str, r) -> dict:
        return {"idx": r["idx"], "type": r["type"], "w": r["w"], "h": r["h"],
                "duration": r["duration"],
                "thumb": f"/api/media/post/{pk}/{r['idx']}?size=t",
                "full": f"/api/media/post/{pk}/{r['idx']}?size=f"}

    @app.post("/api/sessions")
    def start_session(body: SessionBody, a: Auth = Depends(auth)):
        existing = store.current_session(conn, a.device)
        if existing and existing["id"] != body.take_over:
            raise ApiError("session_conflict", 409,
                           "a session is already open on this device",
                           session=dict(existing))
        sess = store.open_session(conn, a.device, body.mode, _filters(body.filters))
        rows, nxt = store.feed_page(conn, sess)
        counts = store.session_counts(conn, sess)
        return {"session": sess["id"], "snapshot": sess["snapshot_sync"],
                "item_count": counts["item_count"], "next_cursor": nxt,
                "items": [_item(r) for r in rows],
                "remaining_in_session": counts["remaining"]}

    @app.get("/api/sessions/current")
    def current_session(a: Auth = Depends(auth)):
        """`null` when no deck is open. No deck is a normal state, not a 404 —
        the shell asks this on every load and logged an error for saying so."""
        sess = store.current_session(conn, a.device)
        if sess is None:
            return JSONResponse(None)
        counts = store.session_counts(conn, sess)
        last = None
        if sess["last_rendered_pk"]:
            row = store.post_by_pk(conn, sess["last_rendered_pk"])
            if row:
                last = {"pk": row["pk"], "taken_at": row["taken_at"]}
        return {**dict(sess), **counts, "last_rendered": last,
                "filters": json.loads(sess["filters_json"])}

    def _owned_session(session_id: int, a: Auth):
        sess = store.get_session(conn, session_id)
        if sess is None or sess["device"] != a.device:
            raise ApiError("not_found", 404, "no such session")
        return sess

    # ---------------------------------------------------------------- feed

    @app.post("/api/sync/run")
    def sync_run(a: Auth = Depends(auth)):
        """Pull now instead of waiting for the scheduler.

        One cycle in the request thread: the browser is a single resource, so
        this cannot run beside the scheduler — `borrow` is what makes them take
        turns.
        """
        result = app.state.syncer.run("cycle")
        state = store.meta_json(conn, "sync_state", {})
        return {"result": result, "error": state.get("error"),
                "new_posts": state.get("new_posts", 0)}

    @app.get("/api/feed")
    def feed(request: Request, session: int, cursor: str | None = None,
             around_pk: str | None = None, limit: int = 20, a: Auth = Depends(auth)):
        if not 1 <= limit <= 20:
            raise ApiError("bad_request", 400, "limit must be 1..20")
        sess = _owned_session(session, a)
        rows, nxt = store.feed_page(conn, sess, limit=limit, cursor=cursor,
                                    around_pk=around_pk)
        counts = store.session_counts(conn, sess)
        if around_pk and rows:
            store.touch_last_rendered(conn, sess["id"], rows[0]["pk"])
        # tail_cursor is the key of the last row whether or not another page
        # exists, so "keep scrolling older" continues exactly where the session
        # stopped instead of re-reading its newest posts.
        tail = f"{rows[-1]['taken_at']}_{rows[-1]['rid']}" if rows else None
        return {"session": sess["id"], "snapshot": sess["snapshot_sync"],
                "next_cursor": nxt, "tail_cursor": tail,
                "remaining_in_session": counts["remaining"],
                "items": [_item(r) for r in rows]}

    @app.get("/api/newest")
    def newest(a: Auth = Depends(auth)):
        """The newest post we can show, with or without a session.

        A session holds unseen posts only, so its first card can be a week old
        while the timeline has today's. The deck's first card is today's.
        """
        settings = store.settings_get(conn)
        rows, nxt = store.older_page(
            conn, limit=1, hide_muted=bool(int(settings.get("hide_muted", 1) or 0)))
        return {"items": [_item(r) for r in rows], "next_cursor": nxt}

    @app.get("/api/older")
    def older(cursor: str | None = None, limit: int = 20, a: Auth = Depends(auth)):
        """Opt-in continuation past the end of a session. Not part of one."""
        _limit(limit)
        settings = store.settings_get(conn)
        rows, nxt = store.older_page(
            conn, limit=limit, cursor=cursor,
            hide_muted=bool(int(settings.get("hide_muted", 1) or 0)))
        return {"items": [_item(r) for r in rows], "next_cursor": nxt}

    # --------------------------------------------------------------- posts

    @app.post("/api/posts/seen")
    def posts_seen(body: SeenBody, a: Auth = Depends(auth)):
        sess = (store.get_session(conn, body.session) if body.session is not None
                else store.current_session(conn, a.device))
        updated = store.mark_seen(conn, body.pks, sess["id"] if sess else None)
        return {"updated": updated}

    # Writes to Instagram. One attempt, no retry: a like that may already have
    # landed must not be sent twice. The UI rolls back on a non-2xx.
    # ------------------------------------------------------------- history

    # ------------------------------------------------------------- stories

    # ------------------------------------------------ messages (instagram)
    #
    # Instagram's DM REST path is retired, so the provider reads the inbox page
    # the browser already has. Reading the list changes nothing; opening a
    # thread marks it read, which is why that is a separate call.

    @app.get("/api/relay/thread")
    def relay_thread(ig_id: str, a: Auth = Depends(auth)):
        """One conversation's messages, straight from Instagram's JSON."""
        with app.state.syncer.borrow() as provider:
            return {"ig_id": ig_id,
                    "messages": igd.Direct(provider, conn).messages(ig_id)}

    @app.get("/api/relay/threads")
    def relay_threads(a: Auth = Depends(auth)):
        """The conversations Instagram itself reports, from its own JSON."""
        with app.state.syncer.borrow() as provider:
            return {"threads": igd.Direct(provider, conn).threads()}

    # ------------------------------------------------- chat (instagram, local)
    #
    # The Messages view talks to Instagram through the relay's own reader, and
    # SQLite answers the rest: the list is cached 20 s, a thread 8 s. Send is the
    # relay's proven path — the inbox name into the real conversation.

    def _others(row: dict) -> list[str]:
        """The participants that are not us, in the inbox's own order."""
        viewer = row.get("viewer") or ""
        return [u for fbid, u in (row.get("users") or {}).items()
                if fbid != viewer and u]

    def _chat_title(row: dict) -> str:
        title = (row.get("name") or "").strip()
        if title:
            return title
        return ", ".join(_others(row)[:3]) or "Conversation"

    def _send_name(row: dict) -> str:
        """Who a message goes to: the thread's title, else the one other person."""
        others = _others(row)
        return (row.get("name") or "").strip() or (others[0] if others else "")

    def _chat_row(thread_id: str) -> dict:
        cached = store.meta_json(conn, "ig_chat_list", {}) or {}
        for row in cached.get("rows") or []:
            if str(row.get("id")) == str(thread_id):
                return row
        return {}

    def _chat_kind(row: dict) -> str:
        return "group" if row.get("group") else "dm"

    @app.get("/api/chat")
    def chat_list(a: Auth = Depends(auth)):
        """The DM list from Instagram's JSON, cached; a stale list beats a 500."""
        cached = store.meta_json(conn, "ig_chat_list", {}) or {}
        rows = cached.get("rows")
        now = int(time.time())
        stale = False
        if rows is None or now - int(cached.get("at") or 0) > 20:
            try:
                with app.state.syncer.borrow() as provider:
                    rows = igd.Direct(provider, conn).threads()
                store.set_meta_json(conn, "ig_chat_list", {"at": now, "rows": rows})
            except Exception:               # noqa: BLE001 — a scrape is never a 500
                rows, stale = rows or [], True
        if conn.execute("SELECT COUNT(*) AS n FROM ig_read").fetchone()["n"] == 0:
            # The very first list seeds every thread as read: a fresh install
            # must not greet the reader with forty unread dots for conversations
            # that were old news before the app existed.
            store.ig_seed_read(conn, [r["id"] for r in rows], now)
        chats = [{
            "chat_id": row["id"],
            "title": _chat_title(row),
            "kind": _chat_kind(row),
            "unread": 1 if not row.get("last_mine")
                      and float(row.get("last_ts") or 0) > store.ig_read_at(conn, row["id"])
                      else 0,
            "last_at": row.get("last_ts"),
            "last_text": row.get("last_text") or "",
            "last_kind": row.get("last_kind") or "",
        } for row in rows]
        body = {"configured": True, "chats": chats}
        if stale:
            body["stale"] = True
        return body

    @app.get("/api/chat/thread")
    def chat_thread(id: str, a: Auth = Depends(auth)):
        """One conversation from the store; Instagram at most once per 8 s."""
        now = int(time.time())
        key = f"ig_chat_fetch:{id}"
        fetched_at = int(store.meta_json(conn, key, 0) or 0)
        if now - fetched_at >= 8:
            try:
                with app.state.syncer.borrow() as provider:
                    fetched = igd.Direct(provider, conn).messages(id)
            except Exception as exc:        # noqa: BLE001 — the store may answer
                if not fetched_at:
                    # Never read and Instagram will not talk: an empty thread
                    # would claim the conversation does not exist.
                    raise ApiError("provider", 502, str(exc))
                fetched = None
            if fetched is not None:
                store.save_ig_msgs(conn, id, fetched)
                store.set_meta_json(conn, key, now)
        store.ig_mark_read(conn, id, now)
        row = _chat_row(id)
        return {"chat_id": id, "title": _chat_title(row), "kind": _chat_kind(row),
                "messages": [{**m, "links": [m["url"]] if m["url"] else []}
                             for m in store.ig_msgs(conn, id)]}

    @app.post("/api/chat/send")
    def chat_send(body: ChatSendBody, a: Auth = Depends(auth)):
        """Type into the real conversation, then store the bubble we made."""
        text = body.text.strip()
        if not text:
            raise ApiError("bad_request", 400, "the message is empty")
        row = _chat_row(body.chat_id)
        name = _send_name(row)
        if not name:
            # Writing to an empty name would be sending into the void; the list
            # has not been read for this id, so there is no recipient.
            raise ApiError("not_found", 404, "no such chat")
        with app.state.syncer.borrow() as provider:
            if not hasattr(provider, "send_dm"):
                raise ApiError("unsupported", 400,
                               "this provider cannot send messages")
            try:
                ok = provider.send_dm(name, text)
            except Exception as exc:        # noqa: BLE001 — one attempt, no retry
                raise ApiError("send_failed", 502, str(exc))
        if not ok:
            raise ApiError("send_failed", 502, "instagram refused the message")
        at = int(time.time())
        msg_id = f"local-{int(time.time() * 1000)}"
        store.save_ig_msgs(conn, body.chat_id, [{
            "id": msg_id, "ts": at, "mine": True, "sender": "", "text": text,
            "kind": "text", "url": ""}])
        return {"message": {"msg_id": msg_id, "at": at, "mine": True, "who": "",
                            "text": text, "kind": "text", "links": []}}

    @app.get("/api/inbox/raw")
    def inbox_raw(a: Auth = Depends(auth)):
        """The list's own lines, uncleaned. Diagnosis only."""
        with app.state.syncer.borrow() as provider:
            return {"rows": provider.inbox_raw()}

    @app.get("/api/inbox")
    def inbox(a: Auth = Depends(auth)):
        """The conversation list, cached: one navigation costs a few seconds.

        A stale list beats an empty screen while the browser is busy, so the
        cache is served with `stale: true` when the page cannot be read.
        """
        cached = store.meta_json(conn, "inbox_cache", {}) or {}
        provider = app.state.syncer.provider
        if not hasattr(provider, "inbox"):
            return {"items": cached.get("items", []), "fetched_at": cached.get("at"),
                    "stale": True, "error": "provider"}
        try:
            items = provider.inbox()
        except Exception as exc:            # noqa: BLE001 — a scrape is never a 500
            return {"items": cached.get("items", []), "fetched_at": cached.get("at"),
                    "stale": True, "error": f"{type(exc).__name__}: {exc}"}
        now = int(time.time())
        store.set_meta_json(conn, "inbox_cache", {"items": items, "at": now})
        return {"items": items, "fetched_at": now, "stale": False, "error": None}

    @app.get("/api/inbox/thread")
    def inbox_thread(name: str, a: Auth = Depends(auth)):
        """One conversation, opened on the page — and marked read there."""
        provider = app.state.syncer.provider
        if not hasattr(provider, "thread"):
            raise ApiError("unsupported", 400, "this provider cannot read messages")
        try:
            return provider.thread(name)
        except (ProviderError, SessionExpired) as exc:
            raise ApiError("provider", 502, str(exc))

    # ------------------------------------------------- messages (telegram)
    #
    # Telegram is the message transport: a daemon long-polls the Bot API into
    # two tables and these routes only read them. Sending is one attempt, no
    # retry. The Instagram DM reader is still mounted above.

    def _tg_message(row) -> dict:
        try:
            links = json.loads(row["links"] or "[]")
        except (TypeError, ValueError):
            links = []
        return {"msg_id": row["msg_id"], "at": int(row["at"]),
                "mine": bool(row["mine"]), "who": row["who"] or "",
                "kind": row["kind"], "text": row["text"],
                "links": links if isinstance(links, list) else []}

    def _tg_chat(chat_id: str):
        return conn.execute("SELECT chat_id, title, kind FROM tg_chats WHERE chat_id=?",
                            (chat_id,)).fetchone()

    @app.get("/api/messages")
    def messages(a: Auth = Depends(auth)):
        """No token is a normal state (`configured: false`), never an error."""
        return {"configured": bool(cfg.telegram_token),
                "chats": [{"chat_id": r["chat_id"], "title": r["title"],
                           "kind": r["kind"], "unread": int(r["unread"] or 0),
                           "last_at": r["last_at"], "last_text": r["last_text"],
                           "last_kind": r["last_kind"]}
                          for r in store.tg_chats(conn, limit=40)]}

    @app.get("/api/messages/thread")
    def messages_thread(chat_id: str, a: Auth = Depends(auth)):
        """Opened in the app means read here — not by a call to Instagram."""
        chat = _tg_chat(chat_id)
        if chat is None:
            raise ApiError("not_found", 404, "no such chat")
        rows = store.tg_thread(conn, chat_id)
        store.tg_mark_read(conn, chat_id,
                           int(rows[-1]["at"]) if rows else int(time.time()))
        return {"chat_id": chat_id, "title": chat["title"],
                "messages": [_tg_message(r) for r in rows]}

    @app.post("/api/messages/send")
    def messages_send(body: SendMessageBody, a: Auth = Depends(auth)):
        text = body.text.strip()
        if not text:
            raise ApiError("bad_request", 400, "the message is empty")
        if not cfg.telegram_token:
            raise ApiError("not_configured", 400, "no telegram token")
        # The app speaks in the relay chat and nowhere else: a stored row from
        # some other chat (a stranger's DM, before the poller learned to drop
        # them) must not turn the portal into a megaphone.
        homes = {c for c in (cfg.relay_chat, cfg.wa_relay_chat) if c}
        if homes and body.chat_id not in homes:
            raise ApiError("forbidden", 403, "not a chat this portal speaks in")
        try:
            result = Telegram(cfg.telegram_token).send(body.chat_id, text)
        except TelegramError as exc:
            raise ApiError("telegram", 502, str(exc))
        chat = _tg_chat(body.chat_id)
        # Ours, so the row is built rather than parsed back out of an update.
        row = {"chat_id": body.chat_id,
               "title": chat["title"] if chat else body.chat_id,
               "kind": chat["kind"] if chat else "dm",
               "msg_id": str((result or {}).get("message_id")
                             or f"local-{int(time.time() * 1000)}"),
               "at": int((result or {}).get("date") or time.time()),
               "mine": 1, "who": "", "kind_msg": "text", "text": text,
               "links": iglink.links_in(text)}
        store.save_tg_message(conn, row)
        stored = conn.execute(
            "SELECT * FROM tg_messages WHERE chat_id=? AND msg_id=?",
            (row["chat_id"], row["msg_id"])).fetchone()
        return {"message": _tg_message(stored)}

    @app.post("/api/relay/topics")
    def relay_topics(n: int = 5, a: Auth = Depends(auth)):
        """A topic for each of the newest N conversations, before anything arrives.

        The relay makes topics on first sight of a message; this is the same
        call without waiting, so the group looks like the inbox from minute one.
        Nothing is sent into the topics — an empty topic is the point.
        """
        if not (cfg.telegram_token and cfg.relay_chat):
            raise ApiError("not_configured", 400, "relay is off")
        try:
            with app.state.syncer.borrow() as provider:
                rows = provider.inbox()
        except (ProviderError, SessionExpired) as exc:
            raise ApiError("provider", 502, str(exc))
        tg = Telegram(cfg.telegram_token)
        made = []
        for row in rows[:max(0, min(int(n), 20))]:
            name = (row.get("name") or "").strip()
            if not name:
                continue
            try:
                thread_id = relay.topic_for(tg, conn, cfg.relay_chat, name)
            except TelegramError as exc:
                raise ApiError("telegram", 502, str(exc))
            if thread_id:
                made.append({"name": name, "thread_id": thread_id})
        return {"made": made, "seen": len(rows)}

    @app.post("/api/relay/probe")
    def relay_probe(name: str = "", path: str = "", url: str = "",
                    a: Auth = Depends(auth)):
        try:
            with app.state.syncer.borrow() as provider:
                if url:
                    return provider.fetch_probe(url)
                return provider.probe(name, path)
        except (ProviderError, SessionExpired) as exc:
            raise ApiError("provider", 502, str(exc))

    @app.get("/api/relay/sent")
    def relay_sent(n: int = 20, a: Auth = Depends(auth)):
        """The last blocks the relay handed to Telegram, newest last."""
        return {"sent": (store.meta_json(conn, "ig_sent", []) or [])[-max(1, min(n, 50)):]}

    @app.get("/api/wa/qr")
    def wa_qr(a: Auth = Depends(auth)):
        """The WhatsApp page as a PNG: the login QR, for the one-time scan.

        Rendered from inside the one process that owns the browser profile — a
        second process would fight the lock, so there is no CLI for this.
        """
        path = Path(cfg.data_dir) / "wa-qr.png"
        try:
            with app.state.syncer.borrow() as provider:
                if not hasattr(provider, "wa_screenshot"):
                    raise ApiError("unsupported", 400,
                                   "PROVIDER=browser is required for WhatsApp")
                qr_showing = Wa(provider).qr(str(path))
        except (ProviderError, SessionExpired) as exc:
            raise ApiError("provider", 502, str(exc))
        return FileResponse(path, media_type="image/png",
                            headers={"x-wa-qr": "1" if qr_showing else "0"})

    @app.post("/api/relay/backfill")
    def relay_backfill(n: int = 5, dry: bool = False, only: str = "",
                       max_weeks: float = 26, a: Auth = Depends(auth)):
        """Fill the newest N topics with their conversation, oldest first.

        Read from Instagram's own JSON, so this costs no read receipt and no
        navigation. `dry=1` reads and counts without sending — the way to check
        what will land in the group before it lands.
        """
        if not (cfg.telegram_token and cfg.relay_chat):
            raise ApiError("not_configured", 400, "relay is off")
        tg = Telegram(cfg.telegram_token)
        try:
            with app.state.syncer.borrow() as provider:
                direct = igd.Direct(provider, conn)
                threads = direct.threads()
                if only:
                    want = only.strip().lower()
                    threads = [t for t in threads
                               if want in (t["name"] or "").lower()
                               or any(want in u.lower() for u in (t["users"] or {}).values())]
                chosen = threads[:max(0, min(int(n), 20))]
                loaded = [(t, direct.messages(t["id"])) for t in chosen]
        except (ProviderError, SessionExpired) as exc:
            raise ApiError("provider", 502, str(exc))
        report = []
        for thread, msgs in loaded:
            weeks = (time.time() - (thread.get("last_ts") or 0)) / 604800
            if weeks > max_weeks and not only:
                report.append({"name": thread["name"], "ig_id": thread["id"],
                               "skipped": f"older than {max_weeks:g} weeks"})
                continue
            blocks = relay.batches(msgs, group=bool(thread.get("group")))
            sent = 0
            if not dry:
                thread_id = relay.topic_for(tg, conn, cfg.relay_chat,
                                            thread["name"] or thread["id"],
                                            create=True, ig_id=thread["id"])
                for i, block in enumerate(blocks[:8]):
                    try:
                        # One block is the usual case: it is the topic's history
                        # and a re-run rewrites it instead of adding a copy.
                        if i == 0:
                            relay.send_block(tg, conn, cfg.relay_chat, thread_id,
                                             thread["name"], block)
                        else:
                            tg.send(cfg.relay_chat, block, thread_id=thread_id)
                    except TelegramError as exc:
                        raise ApiError("telegram", 502, str(exc))
                    sent += 1
                    time.sleep(1.5)
            report.append({"name": thread["name"], "ig_id": thread["id"],
                           "thread_id": relay.topic_for(tg, conn, cfg.relay_chat,
                                                        thread["name"] or thread["id"],
                                                        create=False,
                                                        ig_id=thread["id"]) if dry else None,
                           "last_ts": thread.get("last_ts"),
                           "messages": len(msgs),
                           "mine": sum(1 for m in msgs if m["mine"]),
                           "blocks": len(blocks), "sent": sent,
                           "sample": msgs[:4]})
        return {"dry": bool(dry), "topics": report}

    # --------------------------------------------------------------- resolve

    @app.get("/api/resolve")
    def resolve(url: str, a: Auth = Depends(auth)):
        """A link from a message -> the one card the feed would show for it.

        Read-only towards Instagram: a code that is not stored yet is fetched
        once, and the post is marked seen so it never enters the unseen deck.
        """
        parsed = iglink.parse(url)
        if parsed is None:
            raise ApiError("bad_link", 400, "not an instagram link")
        if parsed["kind"] == "story":
            raise ApiError("unsupported_link", 422, "stories do not open by id")
        if parsed["kind"] == "share":
            try:
                resp = httpx.Client(follow_redirects=True, timeout=10).get(
                    parsed["url"])
            except httpx.HTTPError as exc:
                raise ApiError("bad_link", 400, f"{type(exc).__name__}: {exc}")
            if not 200 <= resp.status_code < 300:
                raise ApiError("bad_link", 400,
                               f"share link answered {resp.status_code}")
            parsed = iglink.parse(str(resp.url))
            if not parsed or parsed["kind"] != "post":
                raise ApiError("bad_link", 400, "share link did not resolve to a post")
        code = parsed["code"]
        row = store.post_by_code(conn, code)
        if row is None:
            try:
                dto = app.state.syncer.provider.post_by_code(code)
            except (ProviderError, SessionExpired) as exc:
                raise ApiError("provider", 502, str(exc))
            if dto is not None:
                store.ensure_account(conn, dto.account_pk)
                # No sync run owns it: `first_seen_sync` is NOT NULL, so 0 says
                # "outside every session" instead of claiming a real run.
                store.upsert_post(conn, dto, 0)
                row = store.post_by_code(conn, code)
        if row is None:
            raise ApiError("not_found", 404, "instagram has no post with that code")
        sess = store.current_session(conn, a.device)
        store.mark_seen(conn, [row["pk"]], sess["id"] if sess else None)
        # The answer describes the stored state, which mark_seen just changed.
        row = store.post_by_code(conn, code)
        return {"kind": "post", "item": _item(row)}


    def _story(row) -> dict:
        live = row["expiring_at"] > time.time() and row["unavailable_at"] is None
        # Dead beats seen: a segment watched on the 18th has no bytes now, and
        # calling it "viewed" put an eighteen-day-old story back on the deck.
        return {"pk": row["pk"], "account_pk": row["account_pk"],
                "media_type": row["media_type"], "taken_at": row["taken_at"],
                "expiring_at": row["expiring_at"],
                "seen": row["seen_at"] is not None,
                "state": "expired" if not live
                else ("viewed" if row["seen_at"] else "available"),
                "reaction": row["reaction"],
                "links": json.loads(row["links"] or "[]")
                if "links" in row.keys() else [],
                "src": f"/api/media/story/{row['pk']}" if live else None,
                "thumb": f"/api/media/story/{row['pk']}?thumb=1" if live else None}

    @app.get("/api/stories/{account_pk}")
    def account_stories(account_pk: str, a: Auth = Depends(auth)):
        ring = store.account_ring(conn, account_pk)
        if ring is None:
            raise ApiError("not_found", 404, "no ring for this account")
        state, error = app.state.story_fetch.get(account_pk, ("idle", None))
        acc = store.account_detail(conn, account_pk)
        return {"account": {"pk": account_pk,
                            "username": acc["username"] if acc else None},
                "items": [_story(r) for r in store.stories_for_account(conn, account_pk)],
                "fetch_state": state, "error": error,
                "media_count": ring["media_count"],
                "local_done_upto": acc["local_done_upto"] if acc else None}

    @app.post("/api/stories/{account_pk}/fetch", status_code=202)
    def fetch_stories(account_pk: str, a: Auth = Depends(auth)):
        if store.account_ring(conn, account_pk) is None:
            raise ApiError("not_found", 404, "no ring for this account")
        # Executor B: opening stories must not wait behind a running sync cycle.
        if app.state.story_fetch.get(account_pk, ("idle",))[0] in ("queued", "running"):
            return {"queued": True, "fetch_state": app.state.story_fetch[account_pk][0]}
        app.state.story_fetch[account_pk] = ("queued", None)

        def _job() -> None:
            app.state.story_fetch[account_pk] = ("running", None)
            try:
                app.state.syncer.fetch_segments(account_pk)
                app.state.story_fetch[account_pk] = ("idle", None)
            except Exception as exc:            # noqa: BLE001 - the viewer needs the reason
                app.state.story_fetch[account_pk] = ("failed", str(exc))

        app.state.executor_b.submit(_job)
        return {"queued": True, "fetch_state": "queued"}

    @app.post("/api/stories/{account_pk}/done")
    def story_done(account_pk: str, a: Auth = Depends(auth)):
        if store.account_ring(conn, account_pk) is None:
            raise ApiError("not_found", 404, "no ring for this account")
        return {"local_done_upto": store.set_local_done(conn, account_pk)}

    @app.post("/api/stories/seen")
    def stories_seen(body: StorySeenBody, a: Auth = Depends(auth)):
        sess = store.current_session(conn, a.device)
        return {"updated": store.mark_story_seen(
            conn, body.pks, sess["id"] if sess else None)}

    @app.get("/api/browse/stories")
    def browse_stories(a: Auth = Depends(auth)):
        """Unseen story accounts as cards the browse deck can play.

        One entry per account: its unseen, still-live segments in the deck's
        picture shape. No provider call happens here — a fetch registers a view
        on Instagram, so it is spent only when the person reaches that card.
        """
        now = int(time.time())
        items = []
        for ring in store.story_rings(conn):
            # The stored segments are the truth when we have any: a ring the
            # reader swiped past is not a ring they watched, and "done" used to
            # hide it for ever while its segments sat unwatched. With nothing
            # stored, the tray's own seen flag is all we know.
            if ring["segments_live"]:
                if ring["segments_unseen"] == 0:
                    continue
            elif not ring["unseen"]:
                continue
            # Seen segments are pictures too. A ring is one card, and a ring
            # half-watched (or fetched once, which registers the view) keeps
            # every live segment in it — filtering by `seen_at` here is what
            # made a fetched ring report `pending` forever.
            segs = [s for s in store.stories_for_account(conn, ring["account_pk"])
                    if s["expiring_at"] > now and s["unavailable_at"] is None]
            items.append({
                "account": {"pk": ring["account_pk"], "username": ring["username"],
                            "pic": f"/api/media/account/{ring['account_pk']}"},
                "when": ring["latest_reel_media"],
                "count": len(segs) or len(ring["media_ids"])
                         or int(ring["media_count"] or 0),
                "pending": not segs,
                "resources": [{
                    "pk": s["pk"], "idx": i,
                    "type": "video" if int(s["media_type"] or 1) == 2 else "photo",
                    "duration": None,
                    # Each segment has its own upload time; the card's `when` is
                    # only the newest one, which is not what the glass shows.
                    "taken_at": s["taken_at"],
                    # The stickers belong to the segment, not to the ring.
                    "links": json.loads(s["links"] or "[]"),
                    "full": f"/api/media/story/{s['pk']}",
                    "thumb": f"/api/media/story/{s['pk']}?thumb=1",
                } for i, s in enumerate(segs)],
            })
        return {"items": items}

    # ------------------------------------------------------------ accounts

    # ---------------------------------------------------------------- sync

    # ------------------------------------------------------------ settings

    @app.get("/api/settings")
    def get_settings(a: Auth = Depends(auth)):
        return store.settings_get(conn)

    # --------------------------------------------------------------- media

    media = app.state.media

    # ------------------------------------------------------------ recognition

    @app.post("/api/recognize/{pk}/{idx}")
    def recognize_media(pk: str, idx: int, a: Auth = Depends(auth)):
        """«Τι παίζει;» — one film to Shazam, one Spotify link back.

        The film goes from here, not from the page: the media is usually already
        in the cache, and a phone should not upload a 20 MB reel to ask a
        question. No account and no token — Shazam's own fingerprinting, through
        ShazamIO. A miss is not an error — `found: false` is an answer.
        """
        row = next((r for r in store.post_resources(conn, pk) if r["idx"] == idx), None)
        if row is None:
            raise ApiError("not_found", 404, "unknown media")
        if row["type"] != "video":
            raise ApiError("not_audio", 400, "a picture has no song")
        clip = media.bytes_for(kind="post", pk=pk, url=row["src_url"])
        if clip is None:
            raise ApiError("unavailable", 404, "the media is not here")
        data, ctype = clip
        if len(data) > recognize.MAX_CLIP:
            raise ApiError("too_large", 413, "the film is too big to fingerprint")
        return recognize.identify(data)

    @app.get("/api/media/post/{pk}/{idx}")
    def media_post(pk: str, idx: int, request: Request, size: str = "f",
                   a: Auth = Depends(auth)):
        row = next((r for r in store.post_resources(conn, pk) if r["idx"] == idx), None)
        if row is None:
            return unavailable()
        # `size=t` is the DB's poster/thumb, not a re-encoded image.
        url = row["poster_url"] if size in ("t", "s") and row["poster_url"] \
            else row["src_url"]
        return media.serve(kind="post", pk=pk, url=url,
                           range_header=request.headers.get("range"))

    @app.get("/api/media/account/{pk}")
    def media_account(pk: str, request: Request, a: Auth = Depends(auth)):
        acc = store.account_detail(conn, pk)
        return media.serve(kind="account", pk=pk,
                           url=acc["pic_url"] if acc else None,
                           range_header=request.headers.get("range"))

    @app.get("/api/media/story/{pk}")
    def media_story(pk: str, request: Request, thumb: int = 0,
                    a: Auth = Depends(auth)):
        row = conn.execute("SELECT * FROM stories WHERE pk=?", (pk,)).fetchone()
        if row is None:
            return unavailable()
        url = (row["thumb_url"] or row["src_url"]) if thumb else row["src_url"]
        return media.serve(kind="story", pk=pk, url=url,
                           range_header=request.headers.get("range"))

    # -------------------------------------------------------------- static

    if STATIC.is_dir():
        app.mount("/static", _Revalidating(directory=STATIC), name="static")

        @app.get("/")
        def index():
            return FileResponse(STATIC / "index.html",
                                headers={"cache-control": "no-cache"})

    def _limit(limit: int) -> None:
        if not 1 <= limit <= 20:
            raise ApiError("bad_request", 400, "limit must be 1..20")

    return app



