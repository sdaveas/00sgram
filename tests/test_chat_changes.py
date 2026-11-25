"""`/api/chat/changes`: the relay's feed, answered by the store alone.

No browser, no provider: a poll while Instagram is down must still work. What is
pinned: inbound only, `since` honoured inclusively, `limit` clamped, and a cursor
that moves to the newest row it answered.
"""
from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from app import chat_sync, store
from app.config import Config
from app.main import create_app

NOW = int(time.time())


def make_config(tmp_path, **over):
    env = {"DATA_DIR": str(tmp_path / "data"), "PROVIDER": "mock",
           "API_TOKEN": "tok", "APP_PASSWORD": "pw", "APP_SECRET": "s" * 32,
           "BACKFILL_SLEEP": "0"}
    env.update(over)
    return Config.from_env(env)


class NeverAsked:
    """Stands in for the provider: any use fails the test, not silently."""

    def __getattr__(self, name):
        raise AssertionError(f"the changes route asked the provider for {name}")


@pytest.fixture()
def client(tmp_path):
    c = TestClient(create_app(make_config(tmp_path)))
    assert c.post("/login", json={"password": "pw"}).status_code == 200
    c.app.state.syncer._provider = NeverAsked()
    return c


def seed(conn, thread_id, msg_id, at, mine=0, text="γεια"):
    store.save_ig_msgs(conn, thread_id, [{
        "id": msg_id, "ts": at, "mine": mine, "sender": "mary",
        "text": text, "kind": "text", "url": ""}])


def test_only_inbound_messages_at_or_after_since(client):
    conn = client.app.state.conn
    seed(conn, "t1", "m1", NOW - 7200)          # before since
    seed(conn, "t1", "m2", NOW - 60)            # exactly since
    seed(conn, "t2", "m3", NOW - 30)
    seed(conn, "t2", "mine", NOW - 30, mine=1)  # ours: not inbound

    body = client.get("/api/chat/changes",
                      params={"since": NOW - 60}).json()

    assert [m["msg_id"] for m in body["messages"]] == ["m2", "m3"]
    assert set(body["messages"][0]) == {"thread_id", "msg_id", "at", "mine",
                                        "who", "text", "kind", "url"}
    assert body["messages"][0]["thread_id"] == "t1"
    assert body["cursor"] == NOW - 30


def test_since_defaults_to_the_last_hour(client):
    conn = client.app.state.conn
    seed(conn, "t1", "old", NOW - 7200)
    seed(conn, "t1", "new", NOW - 60)

    body = client.get("/api/chat/changes").json()

    assert [m["msg_id"] for m in body["messages"]] == ["new"]
    assert body["cursor"] == NOW - 60


def test_an_empty_answer_carries_the_since_it_was_given(client):
    body = client.get("/api/chat/changes", params={"since": 1234}).json()
    assert body == {"messages": [], "cursor": 1234}


def test_limit_is_clamped_to_1_200(client):
    conn = client.app.state.conn
    for i in range(205):
        seed(conn, "t1", f"m{i:03d}", NOW - 600 + i)

    capped = client.get("/api/chat/changes",
                        params={"since": NOW - 600, "limit": 9999}).json()
    assert len(capped["messages"]) == 200
    # Oldest first, so the cursor is the 200th row's `at`, not the newest one.
    assert capped["cursor"] == capped["messages"][-1]["at"]

    one = client.get("/api/chat/changes",
                     params={"since": NOW - 600, "limit": 0}).json()
    assert [m["msg_id"] for m in one["messages"]] == ["m000"]
    assert one["cursor"] == NOW - 600


def test_the_route_never_touches_the_provider(client):
    """`NeverAsked` raises on any attribute: reaching it would be a 500."""
    conn = client.app.state.conn
    seed(conn, "t1", "m1", NOW - 60)
    assert client.get("/api/chat/changes").status_code == 200
    assert client.get("/api/chat/changes").json()["messages"]


def test_the_sync_interval_is_configurable_and_zero_disables(tmp_path):
    assert make_config(tmp_path).chat_sync_interval == 120
    assert make_config(tmp_path, CHAT_SYNC_INTERVAL="0").chat_sync_interval == 0
    with pytest.raises(ValueError):
        make_config(tmp_path, CHAT_SYNC_INTERVAL="86401")


def test_a_disabled_loop_starts_no_thread(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite3")
    try:
        store.init(conn)
        stop = chat_sync.start_chat_sync(
            make_config(tmp_path, CHAT_SYNC_INTERVAL="0"), conn, None)
        assert stop.is_set() is False
        assert not [t for t in threading.enumerate() if t.name == "chat-sync"]
    finally:
        conn.close()
