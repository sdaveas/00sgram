"""WhatsApp, relayed into one Telegram topic per conversation.

A sibling of `relay.py`, not a generalisation of it: the two apps hand out
different evidence and the two relays key their state differently. What they
share is `line_for` (one bubble as one Telegram message), the topic idea, and the
shape of the daemons.

The list row is a *trigger*, never a source of truth. Its preview and timestamp
only decide which conversations are worth opening; what gets posted is decided by
message ids, which are exact. That is the same lesson `docs/designs/ig-relay-json.md`
records: a repeated string cannot mean "new", an id can.

No history is backfilled. The first cycle adopts the visible list without opening
anything (`primed`), and the first time a conversation is read it yields only its
newest message — everything older is "history we found", not "news that arrived".
"""
from __future__ import annotations

import logging
import random
import threading
import time

from . import store
from .provider import ProviderError
from .relay import line_for, outbox_rows
from .telegram import Telegram, TelegramError
from .wadirect import Wa

log = logging.getLogger("warelay")

MAX_PER_CYCLE = 20          # a burst is not a reason to be rate limited
MAX_CHATS = 5               # conversations opened per cycle (each is a click)
KEEP_IDS = 200              # ids remembered per conversation


class NotLoggedIn(ProviderError):
    """The WhatsApp list is not on screen: still loading, or waiting for a QR."""


def topic_for(tg: Telegram, conn, chat_id: str, name: str,
              create: bool = True, is_self: bool = False) -> int | None:
    """The topic's id, made on first sight. None means "stay in General".

    `wa_chats` and not `ig_threads`: topic ids are per group, so the same number
    can exist in both relays and means nothing outside its own table.
    """
    known = store.wa_thread_id(conn, name)
    if known:
        return known
    if not create:
        return None
    try:
        topic = tg.create_topic(chat_id, name)
    except TelegramError:
        # Not a forum, or no Manage Topics: posting to General beats stopping.
        return None
    thread_id = int((topic or {}).get("message_thread_id") or 0)
    if not thread_id:
        return None
    store.save_wa_thread(conn, name, thread_id, is_self=is_self)
    return thread_id


def watch(chats: list[dict], marks: dict) -> list[dict]:
    """Which conversations to open: the list row changed since last time.

    A chat that has never been seen is always worth a look. A chat whose preview,
    timestamp or unread badge moved probably has something new. Both are guesses,
    and both are checked against message ids before anything is sent.
    """
    out: list[dict] = []
    for chat in chats:
        mark = marks.get(chat["name"])
        if mark is None:
            out.append(chat)
        elif mark.get("pending") or (
                chat.get("preview", ""), chat.get("ts", ""), chat.get("unread", "")) != (
                mark.get("preview", ""), mark.get("ts", ""), mark.get("unread", "")):
            out.append(chat)
    return out


def fresh(rows: list[dict], known: set[str], first: bool) -> list[dict]:
    """Unseen messages. A conversation read for the first time yields its newest
    one only: we cannot tell old from new there, and a backlog is worse than a
    gap."""
    unseen = [m for m in rows or [] if m["id"] not in known]
    return unseen[-1:] if first else unseen


def relay_once(tg: Telegram, conn, chat_id: str, wa: Wa) -> int:
    """One look at the list -> one Telegram message per new WhatsApp message."""
    state = store.meta_json(conn, "wa_relay", {}) or {}
    chats = wa.ready()
    if not chats:
        raise NotLoggedIn("the WhatsApp chat list is not on screen")
    if not state.get("primed"):
        # First look ever: adopt, do not replay. Nothing is opened, so no read
        # receipt is spent on a history we are not going to send anyway.
        for chat in chats:
            store.save_wa_mark(conn, chat["name"], [], chat.get("preview", ""),
                               chat.get("ts", ""), chat.get("unread", ""))
        store.set_meta_json(conn, "wa_relay", {"primed": True})
        log.warning("wa relay primed with %d conversations", len(chats))
        return 0

    marks = {c["name"]: store.wa_mark(conn, c["name"]) for c in chats}
    sent = 0
    budget = MAX_PER_CYCLE                  # one budget for the cycle, not per chat
    for chat in watch(chats, marks)[:MAX_CHATS]:
        name = chat["name"]
        mark = marks.get(name) or {}
        is_self = bool(chat.get("self"))
        try:
            if not wa.open(name, chat.get("preview", "")):
                log.warning("wa: could not open %r (renamed, or a duplicate name)", name)
                continue
            rows = wa.messages() or []
        except Exception as exc:                # noqa: BLE001 — one chat, not a dead cycle
            log.warning("wa: %r unreadable: %s: %s", name, type(exc).__name__, exc)
            continue
        if not rows:
            continue
        todo = fresh(rows, set(mark.get("ids") or []), first=not mark.get("ids"))
        if is_self:
            # The self chat is the one place every message is the account's own,
            # so it relays ours too — minus the ones this relay typed itself.
            todo = [m for m in todo
                    if not m["mine"] or not store.wa_message_sent(conn, m["id"])]
        else:
            todo = [m for m in todo if not m["mine"]]
        thread_tg = None
        done = 0                            # how many of `todo` are settled
        for msg in todo:
            if budget <= 0:
                break
            thread_tg = thread_tg or topic_for(tg, conn, chat_id, name,
                                               is_self=is_self)
            block = line_for({**msg, "mine": False} if is_self else msg,
                             group=bool(msg.get("sender")))
            if not block:
                done += 1
                continue
            try:
                sent_msg = tg.send(chat_id, block, thread_id=thread_tg) or {}
                store.map_wa_message(conn, chat_id, sent_msg.get("message_id"),
                                     name, msg["id"])
            except TelegramError:
                # A stale topic id: forget it so the next cycle can make a new
                # one. The message is not retried — a lost bubble beats a loop.
                if thread_tg:
                    store.save_wa_thread(conn, name, 0, is_self=is_self)
                thread_tg = None
                break
            done += 1
            budget -= 1
            sent += 1
        # Advance only past what was actually settled. A burst cut short, or a
        # send that failed, is finished next cycle instead of being dropped.
        if done:
            last = todo[done - 1]["id"]
            cut = max(i for i, m in enumerate(rows) if m["id"] == last) + 1
            ids = [m["id"] for m in rows[:cut]]
        elif not todo:
            ids = [m["id"] for m in rows]
        else:
            ids = list(mark.get("ids") or [])
        # Opening the chat clears the badge, so store the *post-open* triple:
        # keeping the old unread count would make `watch` open it again for
        # nothing — a second read receipt for one message.
        store.save_wa_mark(conn, name, ids, chat.get("preview", ""),
                           chat.get("ts", ""), "", pending=len(todo) > done)
    return sent


class _Hands:
    """The provider's WhatsApp methods, borrowed per call.

    Never one borrow for a whole cycle: a cycle is seconds of clicks and waits,
    and the Instagram sync would be waiting behind it for no reason. `ThreadProxy`
    already serialises individual calls, so per-call borrowing is safe and enough.
    """

    def __init__(self, syncer) -> None:
        self.syncer = syncer
        # One lock for every compound operation: `Wa.open()` then `messages()`
        # must not be split by another daemon's `open()`, or one conversation's
        # messages land in another conversation's topic. An RLock because
        # `Wa.send` calls `Wa.open`.
        self.wa_lock = threading.RLock()

    def __getattr__(self, name: str):
        if not name.startswith("wa_"):
            raise AttributeError(name)

        def call(*args, **kwargs):
            with self.syncer.borrow() as provider:
                fn = getattr(provider, name, None)
                if fn is None:
                    raise ProviderError(
                        "this provider has no WhatsApp page (PROVIDER=browser only)")
                return fn(*args, **kwargs)

        return call


def start_wa_relay(config, conn, syncer) -> threading.Event:
    """A daemon that mirrors the WhatsApp list into its own forum group."""
    stop = threading.Event()
    chat_id = (getattr(config, "wa_relay_chat", "") or "").strip()
    if not (getattr(config, "telegram_token", "") and chat_id):
        return stop

    fast = int(getattr(config, "wa_relay_fast", 20) or 20)
    slow = int(getattr(config, "wa_relay_slow", 90) or 90)

    def loop() -> None:
        tg = Telegram(config.telegram_token)
        wa = Wa(_Hands(syncer))
        hot_until = 0.0
        while not stop.is_set():
            try:
                sent = relay_once(tg, conn, chat_id, wa)
                log.warning("wa relay cycle: %d sent", sent)
                if sent:
                    hot_until = time.time() + 300
            except NotLoggedIn as exc:
                # Logged out, or a QR nobody scanned. Retry, never crash.
                log.warning("wa relay idle: %s", exc)
            except Exception as exc:            # noqa: BLE001 — a scrape never dies
                log.warning("wa relay cycle failed: %s: %s", type(exc).__name__, exc)
            base = fast if time.time() < hot_until else slow
            stop.wait(base * random.uniform(0.9, 1.1))

    threading.Thread(target=loop, name="wa-relay", daemon=True).start()
    return stop


def start_wa_outbox(config, conn, syncer) -> threading.Event:
    """A daemon that carries what was typed in a WhatsApp topic to WhatsApp.

    Cursor, not a flag, and scoped to this relay's own group: topic ids are per
    group, so a number from the Instagram group means nothing here.
    """
    stop = threading.Event()
    chat_id = (getattr(config, "wa_relay_chat", "") or "").strip()
    if not (getattr(config, "wa_relay_send", False) and chat_id
            and getattr(config, "telegram_token", "")):
        return stop
    wa = Wa(_Hands(syncer))

    def loop() -> None:
        cursor = store.meta_json(conn, "wa_outbox", None)
        if cursor is None:
            row = conn.execute("SELECT MAX(id) AS id FROM tg_messages").fetchone()
            cursor = int((row and row["id"]) or 0)
            store.set_meta_json(conn, "wa_outbox", cursor)
        while not stop.is_set():
            try:
                rows = outbox_rows(conn, cursor, chat_id)
                for row in rows:
                    if stop.is_set():
                        break
                    name = store.wa_name(conn, row["thread_id"])
                    if name and (row["text"] or "").strip():
                        # Two attempts, then move on: an unproven send must not
                        # jam the queue forever, but one retry covers a slow
                        # composer.
                        for attempt in (1, 2):
                            try:
                                wa_id = wa.send(name, row["text"])
                            except Exception as exc:    # noqa: BLE001 — one send
                                log.warning("wa send to %r failed: %s", name, exc)
                                wa_id = ""
                            if wa_id:
                                store.map_wa_message(conn, chat_id, row["msg_id"],
                                                     name, wa_id, typed=True)
                                break
                            if attempt == 1:
                                stop.wait(2)
                        else:
                            log.warning("wa send to %r unproven: not delivered", name)
                    cursor = int(row["id"])
                    store.set_meta_json(conn, "wa_outbox", cursor)
            except Exception:                       # noqa: BLE001
                pass
            stop.wait(5)

    threading.Thread(target=loop, name="wa-outbox", daemon=True).start()
    return stop


def start_wa_reacts(config, conn, syncer) -> threading.Event:
    """Carry reactions pressed in Telegram over to WhatsApp."""
    stop = threading.Event()
    chat_id = (getattr(config, "wa_relay_chat", "") or "").strip()
    if not (getattr(config, "wa_relay_send", False) and chat_id
            and getattr(config, "telegram_token", "")):
        return stop
    wa = Wa(_Hands(syncer))

    def loop() -> None:
        while not stop.is_set():
            row = store.next_reaction(conn, "wa_reacts")
            if row is None:
                stop.wait(3)
                continue
            pair = store.wa_message_for(conn, row["chat_id"], row["tg_msg_id"])
            if pair is None:
                store.finish_reaction(conn, row["id"], "no whatsapp message",
                                      table="wa_reacts")
                continue
            name, wa_id = pair
            try:
                wa.react(name, wa_id, row["emoji"] or "")
                store.finish_reaction(conn, row["id"], table="wa_reacts")
            except Exception as exc:            # noqa: BLE001 — one reaction, never a dead loop
                log.warning("wa reaction %s on %s failed: %s: %s", row["emoji"],
                            wa_id, type(exc).__name__, exc)
                store.finish_reaction(conn, row["id"], str(exc)[:200],
                                      table="wa_reacts")
                stop.wait(2)

    threading.Thread(target=loop, name="wa-reacts", daemon=True).start()
    return stop
