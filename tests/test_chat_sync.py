"""The chat sync loop's one round: list -> changed threads -> store -> last_id.

The fake provider sits at `capture`/`graphql`, so `igd`'s own extraction runs.
What is pinned: a changed thread is fetched once, an unchanged one is not
fetched at all, the per-call cap holds (newest activity first), one dead thread
does not stop the rest, a dead list returns an error instead of raising, and
syncing never moves the read dot.
"""
from __future__ import annotations

import json
import sqlite3
import urllib.parse

import pytest

from app import chat_sync, igd, store
from app.config import Config

NOW = 1_764_000_000


def env(**over):
    base = {"DATA_DIR": "/tmp/x", "PROVIDER": "mock",
            "API_TOKEN": "t", "APP_PASSWORD": "p", "APP_SECRET": "s" * 32,
            "BACKFILL_SLEEP": "0"}
    base.update(over)
    return base


@pytest.fixture()
def conn(tmp_path) -> sqlite3.Connection:
    c = store.connect(tmp_path / "t.sqlite3")
    store.init(c, Config.from_env(env()))
    yield c
    c.close()


class FakeIg:
    """The page's two queries, answered from memory."""

    def __init__(self, inbox, threads=None, fail=()):
        self.inbox = inbox                 # inbox thread nodes
        self.threads = threads or {}       # thread id -> message nodes
        self.fail = set(fail)              # thread ids whose fetch raises
        self.calls = {"threads": 0, "messages": []}

    def capture(self, path, name):
        return f"q={name}&variables=%7B%7D"

    def graphql(self, body):
        params = urllib.parse.parse_qs(body)
        name = params["q"][0]
        variables = json.loads(params["variables"][0] or "{}")
        if name == igd.INBOX:
            self.calls["threads"] += 1
            return json.dumps({"data": {"get_slide_mailbox_for_iris_subscription": {
                "threads_by_folder": {"edges": [
                    {"node": {"as_ig_direct_thread": t}} for t in self.inbox]}}}})
        tid = str(variables["thread_fbid"])
        self.calls["messages"].append(tid)
        if tid in self.fail:
            raise RuntimeError("thread unavailable")
        return json.dumps({"data": {"get_slide_thread_nullable": {"as_ig_direct_thread": {
            "viewer": {"interop_messaging_user_fbid": "me"},
            "users": [{"interop_messaging_user_fbid": "peer", "username": "mary"}],
            "slide_messages": {"edges": [
                {"node": m} for m in self.threads.get(tid, [])]}}}}})


def thread(tid, last_id, last_at=NOW - 60):
    return {"id": tid, "thread_title": tid, "is_group": False,
            "last_activity_timestamp_ms": last_at * 1000,
            "users": [{"interop_messaging_user_fbid": "peer", "username": "mary"}],
            "viewer": {"interop_messaging_user_fbid": "me"},
            "slide_messages": {"edges": [{"node": {
                "id": last_id, "timestamp_ms": last_at * 1000,
                "sender_fbid": "peer", "content_type": "TEXT",
                "text_body": "γεια"}}]}}


def message(mid, at=NOW - 60, sender="peer", text="γεια"):
    return {"id": mid, "timestamp_ms": at * 1000, "sender_fbid": sender,
            "content_type": "TEXT", "text_body": text, "content": {}}


def test_a_changed_thread_is_fetched_and_stored_once(conn):
    page = FakeIg([thread("t1", "m2")], {"t1": [message("m1"), message("m2")]})

    result = chat_sync.sync_once(page, conn)

    assert result == {"threads": 1, "messages": 2, "skipped": 0}
    assert page.calls["messages"] == ["t1"]
    assert [m["msg_id"] for m in store.ig_msgs(conn, "t1")] == ["m1", "m2"]
    assert store.ig_last_ids(conn) == {"t1": "m2"}
    # Syncing is not reading: no read watermark was invented.
    assert store.ig_read_at(conn, "t1") == 0


def test_the_same_last_id_fetches_nothing_and_counts_as_skipped(conn):
    page = FakeIg([thread("t1", "m2")], {"t1": [message("m1"), message("m2")]})
    chat_sync.sync_once(page, conn)

    result = chat_sync.sync_once(page, conn)

    assert result == {"threads": 0, "messages": 0, "skipped": 1}
    assert page.calls["messages"] == ["t1"]


def test_only_max_threads_are_fetched_newest_activity_first(conn):
    page = FakeIg([thread("t1", "a", NOW - 300), thread("t2", "b", NOW - 60),
                   thread("t3", "c", NOW - 120)],
                  {t: [message("x")] for t in ("t1", "t2", "t3")})

    result = chat_sync.sync_once(page, conn, max_threads=2)

    assert page.calls["messages"] == ["t2", "t3"]
    assert result == {"threads": 2, "messages": 2, "skipped": 1}


def test_one_failing_thread_does_not_stop_the_others(conn):
    page = FakeIg([thread("t1", "a", NOW - 60), thread("t2", "b", NOW - 120)],
                  {"t1": [message("m1")], "t2": [message("m2")]}, fail={"t1"})

    result = chat_sync.sync_once(page, conn)

    assert result == {"threads": 1, "messages": 1, "skipped": 1}
    assert store.ig_msgs(conn, "t2")
    assert store.ig_last_ids(conn) == {"t2": "b"}   # the failed one retries next round


def test_a_failing_list_returns_the_error_dict(conn):
    page = FakeIg([])
    page.graphql = lambda body: (_ for _ in ()).throw(RuntimeError("browser busy"))

    result = chat_sync.sync_once(page, conn)

    assert result["threads"] == 0 and result["messages"] == 0
    assert result["skipped"] == 0
    assert "browser busy" in result["error"]


def test_a_thread_with_no_last_id_is_never_fetched(conn):
    empty = thread("t1", "")
    page = FakeIg([empty], {"t1": [message("m1")]})

    result = chat_sync.sync_once(page, conn)

    assert result == {"threads": 0, "messages": 0, "skipped": 1}
    assert page.calls["messages"] == []


def test_the_pause_guard_follows_the_sync_state(conn):
    assert chat_sync.paused(conn) is False
    store.set_meta_json(conn, "sync_state", {"paused": True})
    assert chat_sync.paused(conn) is True
