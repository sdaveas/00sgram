"""Instagram Direct as JSON, not as pixels.

The DM page is a React app that fetches everything it renders from
`POST /api/graphql`. Two operations cover the relay:

- `PolarisDirectInboxQuery` — every conversation with its id, its real
  `last_activity_timestamp_ms`, its users, and the id of its last message.
- `IGDThreadDetailQuery` — one conversation's last 20 messages with
  `timestamp_ms`, `sender_fbid`, `text_body`, and, for anything shared, a
  `content.xma.target_url` that is the actual permalink.

Nothing here interprets a pixel: an id never repeats, a preview string does.

Replay: the page's own request body is captured once and cached in
`meta["ig_gql"]`; only its `variables` parameter is swapped. `doc_id` rotates
every few weeks, so a failed replay refreshes the template and retries once.
"""
from __future__ import annotations

import json
import re
import urllib.parse

from . import store
from .provider import ProviderError

INBOX = "PolarisDirectInboxQuery"
THREAD = "IGDThreadDetailQuery"
REACT = "IGDirectReactionSendMutation"
INBOX_PATH = "/direct/inbox/"

# A conversation's last message tells nothing about what the message *is*; the
# content type does. These are the ones that are not text.
KINDS = {
    "MEDIA": "[φωτογραφία]",
    "MEDIA_SHARE": "[φωτογραφία]",
    "RAVEN_MEDIA": "[φωτογραφία]",
    "ANIMATED_MEDIA": "[gif]",
    "VOICE_MEDIA": "[φωνητικό]",
    "STICKER": "[sticker]",
    "HSCROLL_CARD": "[κάρτα]",
    "LINK": "",
    "ACTION_LOG": "",
    "REACTION_LOG": "",
}

_VAR = re.compile(r"variables=[^&]*")


def _swap(body: str, over: dict) -> str:
    """The same captured request, with a different `variables` payload."""
    params = urllib.parse.parse_qs(body, keep_blank_values=True)
    variables = json.loads((params.get("variables") or ["{}"])[0])
    variables.update(over)
    params["variables"] = [json.dumps(variables, separators=(",", ":"))]
    return urllib.parse.urlencode(params, doseq=True)


def _users(thread: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for user in thread.get("users") or []:
        fbid = str(user.get("interop_messaging_user_fbid") or "")
        if fbid:
            out[fbid] = (user.get("username") or user.get("full_name") or "").lstrip("@")
    return out


def _clean_url(url: str) -> str:
    """A permalink without the query Instagram hangs on it."""
    url = (url or "").split("?")[0].strip()
    return url


def thread_rows(js: dict) -> list[dict]:
    """The inbox answer -> one row per conversation, newest activity first."""
    data = ((js or {}).get("data") or {}).get("get_slide_mailbox_for_iris_subscription") or {}
    edges = ((data.get("threads_by_folder") or {}).get("edges")) or []
    out: list[dict] = []
    for edge in edges:
        thread = (((edge or {}).get("node") or {}).get("as_ig_direct_thread")) or {}
        if not thread.get("id"):
            continue
        viewer = str((thread.get("viewer") or {}).get("interop_messaging_user_fbid") or "")
        last_edges = ((thread.get("slide_messages") or {}).get("edges")) or []
        last = (((last_edges[0] or {}).get("node")) if last_edges else {}) or {}
        text, kind, _url = _body(last)
        out.append({
            "id": str(thread["id"]),
            "name": (thread.get("thread_title") or "").strip(),
            "group": bool(thread.get("is_group")),
            "users": _users(thread),
            "viewer": viewer,
            "last_id": str(last.get("id") or ""),
            "last_ts": int(last.get("timestamp_ms")
                           or thread.get("last_activity_timestamp_ms") or 0) / 1000,
            # The list row's own preview; the relay ignores these three.
            "last_text": text,
            "last_kind": kind,
            "last_mine": bool(viewer) and str(last.get("sender_fbid") or "") == viewer,
        })
    out.sort(key=lambda t: t["last_ts"], reverse=True)
    return out


def _body(node: dict) -> tuple[str, str, str]:
    """One message node -> (text, kind, url). No text and no url means nothing to show."""
    content = node.get("content") or {}
    xma = content.get("xma") or {}
    kind = (node.get("content_type") or "").upper()
    text = (node.get("text_body") or "").strip()
    url = _clean_url(xma.get("target_url"))
    if not text:
        text = (xma.get("caption_body_text") or xma.get("title_text") or "").strip()
        # Instagram prefixes a shared post's title with its author's handle
        # ("mary__levine το caption"). The header already carries it, so the
        # prefix is furniture — and it is the exact string, not a guess.
        who = (xma.get("header_title_text") or "").strip()
        if who and text.lower().startswith(who.lower() + " "):
            text = text[len(who):].lstrip()
    if not text and kind in KINDS:
        text = KINDS[kind]
    return text, kind.lower(), url


def message_rows(js: dict) -> list[dict]:
    """One conversation's answer -> `[{id, ts, mine, sender, text, url}]`, oldest first."""
    thread = ((js or {}).get("data") or {}).get("get_slide_thread_nullable") or {}
    thread = thread.get("as_ig_direct_thread") or {}
    users = _users(thread)
    viewer = str((thread.get("viewer") or {}).get("interop_messaging_user_fbid") or "")
    edges = ((thread.get("slide_messages") or {}).get("edges")) or []
    out: list[dict] = []
    for edge in edges:
        node = (edge or {}).get("node") or {}
        if not node.get("id"):
            continue
        sender = str(node.get("sender_fbid") or "")
        text, _kind, url = _body(node)
        if not text and not url:
            # A placeholder ("Message unavailable") is Instagram saying it has
            # nothing to show; relaying the wrapper would be noise.
            continue
        out.append({
            "id": str(node["id"]),
            "reactions": _reactions(node),
            "ts": int(node.get("timestamp_ms") or 0) / 1000,
            "mine": bool(viewer) and sender == viewer,
            "sender": users.get(sender, ""),
            "text": text,
            "url": url,
        })
    out.sort(key=lambda m: m["ts"])
    return out


def _reactions(node: dict) -> list[dict]:
    """Who reacted with what. Two fields carry it, depending on the query."""
    out: list[dict] = []
    for key in ("reactions", "msg_reactions"):
        for item in node.get(key) or []:
            emoji = (item.get("emoji") or item.get("reaction") or "").strip()
            if not emoji:
                continue
            who = (item.get("sender_fbid") or item.get("sender_id")
                   or (item.get("user") or {}).get("id") or "")
            out.append({"emoji": emoji, "sender": str(who)})
    return out


class Direct:
    """The two queries the relay needs, replayed in the page's own session."""

    def __init__(self, provider, conn) -> None:
        self.provider = provider
        self.conn = conn

    # ------------------------------------------------------------- transport

    def _template(self, name: str, path: str) -> str:
        saved = (store.meta_json(self.conn, "ig_gql", {}) or {}).get(name) or ""
        return saved or self._capture(name, path)

    def _capture(self, name: str, path: str) -> str:
        body = self.provider.capture(path, name)
        if not body:
            raise ProviderError(f"the page never asked for {name}")
        saved = dict(store.meta_json(self.conn, "ig_gql", {}) or {})
        saved[name] = body
        store.set_meta_json(self.conn, "ig_gql", saved)
        return body

    def _call(self, name: str, path: str, **over) -> dict:
        for attempt in (1, 2):
            body = self._template(name, path)
            text = self.provider.graphql(_swap(body, over))
            try:
                js = json.loads(text)
            except ValueError:
                js = {"errors": [{"message": (text or "")[:200]}]}
            if not js.get("errors"):
                return js
            # A rotated doc_id or a stale session token: one fresh capture, one
            # retry. Anything else is a real error and should be seen.
            if attempt == 2:
                raise ProviderError(
                    f"{name} failed: {json.dumps(js.get('errors'))[:300]}")
            saved = dict(store.meta_json(self.conn, "ig_gql", {}) or {})
            saved.pop(name, None)
            store.set_meta_json(self.conn, "ig_gql", saved)
        raise ProviderError(f"{name} failed")   # unreachable, keeps mypy honest

    # ----------------------------------------------------------------- data

    def threads(self) -> list[dict]:
        return thread_rows(self._call(INBOX, INBOX_PATH))

    def messages(self, thread_id: str) -> list[dict]:
        """One conversation's recent messages. No navigation, no read receipt."""
        return message_rows(self._call(THREAD, INBOX_PATH, thread_fbid=str(thread_id)))

    def react(self, thread_id: str, message_id: str, emoji: str = "❤") -> dict:
        """React to one Instagram message, or take the reaction back.

        Same mutation the page fires; an empty emoji means "remove mine".
        """
        return self._call(REACT, f"/direct/t/{thread_id}/", input={
            "emoji": (emoji or "❤")[:8],
            "item_id": "",
            "message_id": str(message_id),
            "reaction_status": "created" if emoji else "deleted",
            "thread_id": str(thread_id),
        })
