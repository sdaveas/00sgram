"""The Instagram inbox, relayed into one Telegram topic per conversation.

Incoming only, and read from Instagram's own JSON (`igd.Direct`): a conversation
is fresh when its *last message id* changes, which is exact, and the messages
themselves carry real timestamps, senders and permalinks. Nothing here looks at
a rendered pixel — the DOM said `Mary sent an attachment.` for every photo since
forever, which is why the older scraper could not tell a new message from an old
one.

A conversation is identified by its Instagram thread id, so a rename on either
side does not orphan a topic.
"""
from __future__ import annotations

import logging
import random
import threading
import time

from . import igd, store
from .telegram import Telegram, TelegramError

log = logging.getLogger("relay")

MAX_PER_CYCLE = 20          # a burst is not a reason to be rate limited
# A thread seen for the first time is not a backlog to replay: only a message
# this recent is "arriving now" rather than "history we found".
CATCHUP_H = 6.0


class _Reader:
    """`messages(ig_id)`, borrowing the browser page per conversation."""

    def __init__(self, fn) -> None:
        self.fn = fn

    def messages(self, ig_id: str) -> list[dict]:
        return self.fn(ig_id)


def topic_for(tg: Telegram, conn, chat_id: str, name: str,
              create: bool = True, ig_id: str = "") -> int | None:
    """The topic's id, made on first sight. None means "stay in General"."""
    known = store.ig_thread_id(conn, name, ig_id)
    if known:
        if ig_id:
            # Bind the id to the topic once; after that a rename on either side
            # is just a label.
            store.save_ig_thread(conn, name, known, ig_id=ig_id)
        return known
    if not create:
        return None
    try:
        topic = tg.create_topic(chat_id, name)
    except TelegramError:
        # Not a forum, or no Manage Topics: a relay that posts to General beats
        # a relay that stops.
        return None
    thread_id = int((topic or {}).get("message_thread_id") or 0)
    if not thread_id:
        return None
    store.save_ig_thread(conn, name, thread_id, ig_id=ig_id)
    return thread_id


def new_messages(rows: list[dict], mark: dict,
                 catchup_h: float = CATCHUP_H) -> list[dict]:
    """What arrived since the watermark: everything newer, minus our own.

    A watermark is a timestamp, so a message deleted on the phone cannot shift
    anything. An unknown conversation has no watermark to trust, so it yields
    only the newest message and only if it is recent — never a backlog.
    """
    theirs = [m for m in rows if not m.get("mine")]
    if not mark:
        recent = [m for m in theirs if time.time() - m["ts"] <= catchup_h * 3600]
        return recent[-1:]
    since = float(mark.get("ts") or 0)
    return [m for m in theirs if m["ts"] > since]


def relay_once(tg: Telegram, conn, chat_id: str, threads: list[dict],
               direct, max_weeks: float | None = 26,
               catchup_h: float = CATCHUP_H) -> tuple[int, bool]:
    """One inbox listing -> one Telegram message per Instagram message.

    `threads` is `igd.Direct.threads()`; `direct` reads a conversation.
    """
    state = store.meta_json(conn, "ig_relay", {}) or {}
    marks: dict = dict(state.get("marks") or {})
    primed = bool(state.get("primed"))
    if not marks:
        # The state from the scraper has no watermarks: adopt everything on this
        # first look instead of replaying a day of it.
        primed = False
    sent = 0
    for thread in threads[:MAX_PER_CYCLE]:
        ig_id = thread["id"]
        if not thread.get("last_id"):
            continue
        mark = marks.get(ig_id) or {}
        if mark.get("last_id") == thread["last_id"]:
            continue
        if not primed:
            # The first look adopts the inbox instead of replaying it: no
            # conversation is read at all.
            marks[ig_id] = {"last_id": thread["last_id"],
                            "ts": thread.get("last_ts") or 0,
                            "name": thread.get("name")}
            continue
        if max_weeks is not None:
            age_weeks = (time.time() - (thread.get("last_ts") or 0)) / 604800
            if age_weeks > max_weeks:
                marks[ig_id] = {"last_id": thread["last_id"],
                                "ts": thread.get("last_ts") or 0,
                                "name": thread.get("name")}
                continue
        try:
            rows = direct.messages(ig_id)
        except Exception as exc:       # noqa: BLE001 — one bad thread, not a dead cycle
            log.warning("thread %s unreadable: %s: %s", ig_id, type(exc).__name__, exc)
            continue
        if not rows:
            continue
        fresh = new_messages(rows, mark, catchup_h)
        thread_tg = None
        for msg in fresh[:MAX_PER_CYCLE]:
            thread_tg = thread_tg or topic_for(tg, conn, chat_id,
                                               thread.get("name") or ig_id,
                                               ig_id=ig_id)
            block = line_for(msg, group=bool(thread.get("group")))
            try:
                sent_msg = tg.send(chat_id, block, thread_id=thread_tg) or {}
                # A reaction in Telegram names this message; the map is what
                # turns it back into the Instagram id.
                store.map_ig_message(conn, chat_id, sent_msg.get("message_id"),
                                     ig_id, msg["id"])
            except TelegramError:
                # A stale topic id: forget it so the next cycle can make a new
                # one. The message is not retried — a lost bubble beats a loop.
                if thread_tg:
                    store.save_ig_thread(conn, thread.get("name") or ig_id, 0,
                                         ig_id=ig_id)
                thread_tg = None
                continue
            record_sent(conn, thread.get("name") or ig_id, block)
            sent += 1
        marks[ig_id] = {"last_id": thread["last_id"],
                        "ts": max(m["ts"] for m in rows),
                        "name": thread.get("name")}
    store.set_meta_json(conn, "ig_relay", {"marks": marks, "primed": True})
    return sent, bool(sent)


def record_sent(conn, name: str, text: str) -> None:
    """What actually left for Telegram, so "did it arrive?" is answerable.

    The Bot API cannot read back the bot's own messages, so the relay keeps its
    own log: the last 50 sends, by conversation and text.
    """
    log = list(store.meta_json(conn, "ig_sent", []) or [])
    log.append({"at": int(time.time()), "name": name, "text": text})
    store.set_meta_json(conn, "ig_sent", log[-50:])


def line_for(msg: dict, group: bool = False, limit: int = 3500) -> str:
    """One Instagram message as one Telegram message, its link under it.

    A shared post is two facts — what was said and what was sent — and Telegram
    has nowhere else to put the second, so the permalink goes under the text.
    A group writes who is speaking; a one-to-one chat has no one else it could be.
    """
    text = " ".join((msg.get("text") or "").split())
    if msg.get("mine"):
        text = f"εγώ: {text}"
    sibling = (msg.get("sender") or "").strip()
    if group and not msg.get("mine") and sibling:
        text = f"{sibling}: {text}"
    url = (msg.get("url") or (msg.get("hrefs") or [""])[0] or "").strip()
    if url and url not in text:
        text = f"{text}\n{url}" if text else url
    return text[:limit]


def batches(messages: list[dict], limit: int = 3000,
            group: bool = False) -> list[str]:
    """A transcript as Telegram-sized blocks: several bubbles per message.

    One Telegram message per bubble would be hundreds of requests per
    conversation; history does not need that fidelity. Ours are marked, theirs
    are bare — the same shape the live relay sends.
    """
    out: list[str] = []
    buf = ""
    for msg in messages or []:
        line = line_for(msg, group=group)
        if not line:
            continue
        if len(buf) + len(line) + 1 > limit:
            out.append(buf)
            buf = ""
        buf = f"{buf}\n{line}".strip()
    if buf:
        out.append(buf)
    return out


def send_block(tg: Telegram, conn, chat_id: str, thread_id: int | None,
               name: str, block: str) -> int:
    """The backfill's block for a conversation: sent once, edited after that.

    A re-run is a correction, not a second copy — the previous block is kept in
    `meta` by topic id and rewritten in place.
    """
    saved = store.meta_json(conn, "ig_backfill", {}) or {}
    key = str(thread_id or name)
    msg_id = saved.get(key)
    if msg_id:
        try:
            tg.call("editMessageText", chat_id=chat_id, message_id=msg_id,
                    text=block)
            return int(msg_id)
        except TelegramError:
            pass                            # deleted by hand: send a new one
    result = tg.send(chat_id, block, thread_id=thread_id)
    msg_id = int((result or {}).get("message_id") or 0)
    if msg_id:
        saved[key] = msg_id
        store.set_meta_json(conn, "ig_backfill", saved)
    return msg_id


def ig_name(conn, thread_id: int | None) -> str | None:
    """The conversation a topic belongs to. None for General, or a topic we did
    not make — writing there would be guessing at a recipient."""
    if not thread_id:
        return None
    row = conn.execute("SELECT name FROM ig_threads WHERE thread_id=?",
                       (int(thread_id),)).fetchone()
    return row["name"] if row else None


def send_row(syncer, conn, row) -> bool:
    """One Telegram message -> the Instagram conversation it belongs to."""
    name = ig_name(conn, row["thread_id"])
    text = (row["text"] or "").strip()
    if not name or not text:
        return False
    with syncer.borrow() as provider:
        if not hasattr(provider, "send_dm"):
            return False
        return bool(provider.send_dm(name, text))


def outbox_rows(conn, cursor: int, chat_id: str, limit: int = 5):
    """What is waiting to be written back, for one group only.

    Topic ids are per group and start low, so an Instagram topic and a WhatsApp
    topic can both be `7`. Without the chat filter this query would hand a
    WhatsApp topic id to the Instagram relay, which would find an `ig_threads`
    row that happens to own that number and write into the wrong conversation.
    """
    return list(conn.execute(
        "SELECT * FROM tg_messages WHERE id > ? AND mine=0"
        " AND thread_id IS NOT NULL AND chat_id=?"
        " ORDER BY id LIMIT ?", (int(cursor), chat_id, int(limit))))


def start_outbox(config, conn, syncer) -> threading.Event:
    """A daemon that carries what was typed in Telegram over to Instagram.

    Cursor, not a flag: the row id of the last message considered, kept in
    `meta` so a restart neither repeats nor skips. The first run starts at the
    newest row — the history in Telegram is not a backlog to replay.
    """
    stop = threading.Event()
    if not (getattr(config, "relay_send", False)
            and getattr(config, "telegram_token", "")):
        return stop

    def loop() -> None:
        cursor = store.meta_json(conn, "ig_outbox", None)
        if cursor is None:
            row = conn.execute("SELECT MAX(id) AS id FROM tg_messages").fetchone()
            cursor = int((row and row["id"]) or 0)
            store.set_meta_json(conn, "ig_outbox", cursor)
        # Scoped to this relay's own group: topic ids are per group, so a number
        # from the WhatsApp group can collide with a number here and would
        # otherwise address the wrong conversation.
        own_chat = (getattr(config, "relay_chat", "") or "").strip()
        while not stop.is_set():
            try:
                rows = outbox_rows(conn, cursor, own_chat)
                for row in rows:
                    if stop.is_set():
                        break
                    try:
                        send_row(syncer, conn, row)
                    except Exception:      # noqa: BLE001 — one bad send, not a dead loop
                        pass
                    cursor = int(row["id"])
                    store.set_meta_json(conn, "ig_outbox", cursor)
            except Exception:              # noqa: BLE001
                pass
            stop.wait(5)

    threading.Thread(target=loop, name="ig-outbox", daemon=True).start()
    return stop


def start_reacts(config, conn, syncer) -> threading.Event:
    """Carry reactions pressed in Telegram over to Instagram.

    The Bot API hands us "user reacted ❤ to message 42 in chat X"; the map from
    `ig_sent_map` says which Instagram message 42 stood for. A reaction with no
    map entry is a message this relay never sent, so there is nothing to do.
    """
    stop = threading.Event()
    if not (getattr(config, "relay_send", False)
            and getattr(config, "telegram_token", "")):
        return stop

    def loop() -> None:
        while not stop.is_set():
            row = store.next_reaction(conn)
            if row is None:
                stop.wait(3)
                continue
            pair = store.ig_message_for(conn, row["chat_id"], row["tg_msg_id"])
            if pair is None:
                store.finish_reaction(conn, row["id"], "no instagram message")
                continue
            ig_id, ig_msg_id = pair
            try:
                with syncer.borrow() as provider:
                    igd.Direct(provider, conn).react(ig_id, ig_msg_id,
                                                     row["emoji"] or "")
                store.finish_reaction(conn, row["id"])
            except Exception as exc:       # noqa: BLE001 — one reaction, never a dead loop
                log.warning("reaction %s on %s failed: %s: %s", row["emoji"],
                            ig_msg_id, type(exc).__name__, exc)
                store.finish_reaction(conn, row["id"], str(exc)[:200])
                stop.wait(2)

    threading.Thread(target=loop, name="ig-reacts", daemon=True).start()
    return stop


def start_relay(config, conn, syncer) -> threading.Event:
    """A daemon that reads the inbox list and mirrors it into the group.

    Two speeds, because a scrape is a browser navigation: calm when nothing has
    happened, quick for a while after something has.
    """
    stop = threading.Event()
    chat_id = (getattr(config, "relay_chat", "") or "").strip()
    if not (getattr(config, "telegram_token", "") and chat_id):
        return stop

    max_weeks = float(getattr(config, "relay_max_weeks", 26) or 26)
    fast = int(getattr(config, "relay_fast", 60))
    slow = int(getattr(config, "relay_slow", 600))
    active = int(getattr(config, "relay_active", 900))

    def loop() -> None:
        tg = Telegram(config.telegram_token)
        hot_until = 0.0
        first = True
        while not stop.is_set():
            rows: list[dict] = []
            try:
                # One browser page: never a second navigation while a sync runs.
                with syncer.borrow() as provider:
                    if not hasattr(provider, "graphql"):
                        return          # instagrapi cannot read DMs
                    rows = igd.Direct(provider, conn).threads()

                def read(ig_id, _syncer=syncer):
                    # A second borrow per conversation: the first one is over so
                    # a sync can slip in between, and the template is cached.
                    with _syncer.borrow() as provider2:
                        return igd.Direct(provider2, conn).messages(ig_id)

                _sent, hot = relay_once(tg, conn, chat_id, rows,
                                        _Reader(read), max_weeks=max_weeks)
                log.warning("relay cycle: %d rows, %d sent", len(rows), _sent)
                if hot:
                    hot_until = time.time() + active
                first = False
            except Exception as exc:       # noqa: BLE001 — a scrape never dies
                # A failed navigation is not news: wait a whole slow interval,
                # and try again. Login walls surface in the app, not here.
                log.warning("relay cycle failed: %s: %s", type(exc).__name__, exc)
                if first:
                    stop.wait(slow)
                    continue
            base = fast if time.time() < hot_until else slow
            stop.wait(base * random.uniform(0.9, 1.1))

    threading.Thread(target=loop, name="ig-relay", daemon=True).start()
    return stop
