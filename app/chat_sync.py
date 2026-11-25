"""Keep the DM store fresh without anyone opening a conversation.

Nothing fetched thread contents before this: a thread was read when a human
opened it, so an API polling for changes saw nothing. The list row carries the
id of each thread's newest message, and that id is the trigger — a thread whose
id did not change is not opened.

Syncing is not reading: this never moves `ig_read`, so it cannot clear a dot.
"""
from __future__ import annotations

import logging
import sqlite3
import threading

from . import igd, store

log = logging.getLogger(__name__)


def paused(conn: sqlite3.Connection) -> bool:
    """One pause switch for everything Instagram-facing (the scheduler's)."""
    return bool((store.meta_json(conn, "sync_state", {}) or {}).get("paused"))


def sync_once(provider, conn: sqlite3.Connection, max_threads: int = 5) -> dict:
    """One round: list -> changed threads -> messages -> last_id.

    Returns `{"threads", "messages", "skipped"}`; `messages` counts rows fetched
    from Instagram (stored ids already present are upserts, not new). A failing
    thread is only skipped, so one dead conversation cannot stall the rest. A
    failing list returns the error and never raises.
    """
    try:
        rows = igd.Direct(provider, conn).threads()
    except Exception as exc:                # noqa: BLE001 — a scrape is never a crash
        return {"threads": 0, "messages": 0, "skipped": 0,
                "error": f"{type(exc).__name__}: {exc}"}

    seen = store.ig_last_ids(conn)
    # Already newest activity first: `thread_rows` sorts on last_ts.
    changed = [r for r in rows if r["last_id"] and r["last_id"] != seen.get(str(r["id"]))]
    picked = changed[:max(0, max_threads)]
    skipped = len(rows) - len(picked)
    threads = messages = 0
    for row in picked:
        thread_id = str(row["id"])
        try:
            fetched = igd.Direct(provider, conn).messages(thread_id)
            store.save_ig_msgs(conn, thread_id, fetched)
            store.set_ig_last_id(conn, thread_id, row["last_id"])
        except Exception:                   # noqa: BLE001 — try the next thread
            # Counted, not printed: a dead thread retries every round, and a
            # warning per round per thread is the spam the loop must not make.
            skipped += 1
            continue
        threads += 1
        messages += len(fetched)
    return {"threads": threads, "messages": messages, "skipped": skipped}


def sync_loop(config, conn: sqlite3.Connection, syncer, stop: threading.Event) -> None:
    interval = config.chat_sync_interval
    while not stop.wait(interval):
        if paused(conn):
            continue
        try:
            with syncer.borrow() as provider:
                result = sync_once(provider, conn)
        except Exception as exc:            # noqa: BLE001 — one warning, no traceback
            log.warning("chat sync: round failed: %s: %s", type(exc).__name__, exc)
            continue
        if result.get("error"):
            log.warning("chat sync: list failed: %s", result["error"])


def start_chat_sync(config, conn: sqlite3.Connection, syncer) -> threading.Event:
    """Daemon like the other loops; `CHAT_SYNC_INTERVAL=0` disables it."""
    stop = threading.Event()
    if config.chat_sync_interval <= 0:
        return stop
    threading.Thread(target=sync_loop, args=(config, conn, syncer, stop),
                     name="chat-sync", daemon=True).start()
    return stop
