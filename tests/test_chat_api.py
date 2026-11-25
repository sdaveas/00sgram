"""The in-app chat surface, offline: list, thread, send.

Instagram is the source, SQLite is the answer to every tick after the first. The
fake provider sits at the lowest seam (`capture`/`graphql`) so `igd`'s own
extraction runs for real; nothing here reaches instagram.com.

What is pinned: the list's shape and its unread dots (including the first-run
seed), the thread's store shape and its read watermark, the 8 s throttle, and
one send — no retry, to the resolved name, stored as a bubble.
"""
from __future__ import annotations

import json
import time
import types
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from app import igd, store
from app.config import Config
from app.main import create_app

NOW = int(time.time())


def make_config(tmp_path, **over):
    env = {"DATA_DIR": str(tmp_path / "data"),
           "PROVIDER": "mock",
           "API_TOKEN": "tok", "APP_PASSWORD": "pw", "APP_SECRET": "s" * 32,
           "BACKFILL_SLEEP": "0"}
    env.update(over)
    return Config.from_env(env)


class FakeIg:
    """One page: query names in, the JSON `igd` reads back out."""

    def __init__(self, inbox, threads=None):
        self.inbox = inbox                 # inbox thread nodes
        self.threads = threads or {}       # thread id -> message nodes
        self.calls = {"threads": 0, "messages": []}
        self.sent = []

    def capture(self, path, name):
        return f"q={name}&variables=%7B%7D"

    def graphql(self, body):
        params = urllib.parse.parse_qs(body)
        name = params["q"][0]
        variables = json.loads(params["variables"][0] or "{}")
        if name == igd.INBOX:
            self.calls["threads"] += 1
            js = {"data": {"get_slide_mailbox_for_iris_subscription": {
                "threads_by_folder": {"edges": [
                    {"node": {"as_ig_direct_thread": t}} for t in self.inbox]}}}}
        else:
            tid = str(variables["thread_fbid"])
            self.calls["messages"].append(tid)
            js = {"data": {"get_slide_thread_nullable": {"as_ig_direct_thread": {
                "viewer": {"interop_messaging_user_fbid": "me"},
                "users": [{"interop_messaging_user_fbid": "peer",
                           "username": "mary__levine"},
                          {"interop_messaging_user_fbid": "me",
                           "username": "me"}],
                "slide_messages": {"edges": [
                    {"node": m} for m in self.threads.get(tid, [])]}}}}}
        return json.dumps(js)

    def send_dm(self, name, text):
        self.sent.append((name, text))
        return True


def ig_thread(tid="t1", title="Mary Levine", users=(("peer", "mary__levine"),),
              last_text="γεια", last_sender="peer", last_kind="TEXT",
              last_at=NOW - 60, group=False):
    last_ms = last_at * 1000
    return {"id": tid, "thread_title": title, "is_group": group,
            "last_activity_timestamp_ms": last_ms,
            "users": [{"interop_messaging_user_fbid": f, "username": u,
                       "full_name": u} for f, u in users],
            "viewer": {"interop_messaging_user_fbid": "me"},
            "slide_messages": {"edges": [{"node": {
                "id": f"{tid}-last", "timestamp_ms": last_ms,
                "sender_fbid": last_sender, "content_type": last_kind,
                "text_body": last_text}}]}}


def ig_message(mid, text, at, sender="peer", kind="TEXT"):
    return {"id": mid, "timestamp_ms": at * 1000, "sender_fbid": sender,
            "content_type": kind, "text_body": text, "content": {}}


@pytest.fixture()
def client(tmp_path):
    c = TestClient(create_app(make_config(tmp_path)))
    assert c.post("/login", json={"password": "pw"}).status_code == 200
    return c


def use_provider(client, page):
    client.app.state.syncer._provider = page
    return page


def expire_list_cache(conn):
    """A cache older than the 20 s window: the next call refetches."""
    cached = store.meta_json(conn, "ig_chat_list", {}) or {}
    store.set_meta_json(conn, "ig_chat_list", {"at": 0, "rows": cached.get("rows")})


def chats(client):
    return {c["chat_id"]: c for c in client.get("/api/chat").json()["chats"]}


# -------------------------------------------------------------------- list


def test_the_list_is_shaped_for_the_screen_and_a_fresh_install_has_no_dots(client):
    conn = client.app.state.conn
    use_provider(client, FakeIg([
        ig_thread("t1", "Mary Levine"),
        ig_thread("t2", "", last_sender="me", last_text="hi"),
        ig_thread("t3", "", users=(("peer", "nikos"), ("peer2", "maria")),
                  last_text=""),
    ]))

    body = client.get("/api/chat").json()
    assert body["configured"] is True
    by_id = {c["chat_id"]: c for c in body["chats"]}
    assert list(by_id) == ["t1", "t2", "t3"]
    assert list(by_id["t1"]) == ["chat_id", "title", "kind", "unread", "last_at",
                                 "last_text", "last_kind"]
    assert (by_id["t1"]["title"], by_id["t1"]["kind"]) == ("Mary Levine", "dm")
    assert (by_id["t1"]["last_text"], by_id["t1"]["last_kind"]) == ("γεια", "text")
    # No thread_title: the other participant, else up to three of them.
    assert by_id["t2"]["title"] == "mary__levine"
    assert by_id["t3"]["title"] == "nikos, maria"
    # Nothing is new on a fresh install, however old the conversations are.
    assert [c["unread"] for c in body["chats"]] == [0, 0, 0]
    assert conn.execute("SELECT COUNT(*) AS n FROM ig_read").fetchone()["n"] == 3


def test_a_message_after_the_seed_is_one_dot_and_our_own_never_is(client):
    conn = client.app.state.conn
    page = use_provider(client, FakeIg([
        ig_thread("t1", "Mary"), ig_thread("t2", "Nikos", last_sender="me")]))
    assert {c: v["unread"] for c, v in chats(client).items()} == {"t1": 0, "t2": 0}

    page.inbox[0] = ig_thread("t1", "Mary", last_text="new", last_at=NOW + 60)
    expire_list_cache(conn)
    unread = {c: v["unread"] for c, v in chats(client).items()}
    assert unread == {"t1": 1, "t2": 0}


def test_a_failed_list_serves_the_stale_cache_instead_of_a_500(client):
    conn = client.app.state.conn
    page = use_provider(client, FakeIg([ig_thread("t1")]))
    assert chats(client)["t1"]["title"] == "Mary Levine"

    expire_list_cache(conn)
    page.graphql = lambda body: (_ for _ in ()).throw(RuntimeError("browser busy"))
    r = client.get("/api/chat")
    assert r.status_code == 200
    body = r.json()
    assert body["stale"] is True
    assert [c["chat_id"] for c in body["chats"]] == ["t1"]


# ------------------------------------------------------------------ thread


def test_a_thread_is_stored_and_read_back_in_the_store_shape(client):
    conn = client.app.state.conn
    use_provider(client, FakeIg(
        [ig_thread("t1", "Mary Levine")],
        {"t1": [ig_message("m1", "γεια", NOW - 60),
                ig_message("m2", "hi", NOW - 30, sender="me")]}))
    chats(client)

    body = client.get("/api/chat/thread", params={"id": "t1"}).json()
    assert (body["chat_id"], body["title"], body["kind"]) == ("t1", "Mary Levine", "dm")
    msgs = body["messages"]
    assert [m["msg_id"] for m in msgs] == ["m1", "m2"]
    assert set(msgs[0]) == {"msg_id", "at", "mine", "who", "text", "kind", "url", "links"}
    assert (msgs[0]["mine"], msgs[0]["who"], msgs[1]["mine"]) == (False, "mary__levine", True)
    assert conn.execute("SELECT COUNT(*) AS n FROM ig_msgs").fetchone()["n"] == 2

    # Opening a conversation means read here; Instagram hears nothing about it.
    assert store.ig_read_at(conn, "t1") >= NOW
    assert chats(client)["t1"]["unread"] == 0


def test_a_second_thread_call_within_eight_seconds_does_not_ask_instagram(client):
    page = use_provider(client, FakeIg(
        [ig_thread("t1")], {"t1": [ig_message("m1", "γεια", NOW - 60)]}))
    chats(client)

    assert client.get("/api/chat/thread", params={"id": "t1"}).status_code == 200
    assert client.get("/api/chat/thread", params={"id": "t1"}).status_code == 200
    assert page.calls["messages"] == ["t1"]


def test_a_thread_that_never_loaded_reports_the_provider_error(client):
    page = use_provider(client, FakeIg([]))
    page.graphql = lambda body: (_ for _ in ()).throw(RuntimeError("no session"))
    r = client.get("/api/chat/thread", params={"id": "t9"})
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "provider"


# -------------------------------------------------------------------- send


def test_send_goes_to_the_resolved_name_once_and_returns_the_bubble(client):
    conn = client.app.state.conn
    page = use_provider(client, FakeIg([
        ig_thread("t1", "Mary Levine"),
        # No thread_title: the recipient is the one other person.
        ig_thread("t2", "", users=(("peer", "nikos"),), last_sender="me"),
    ]))
    chats(client)

    r = client.post("/api/chat/send", json={"chat_id": "t1", "text": "  hi there  "})
    assert r.status_code == 200
    assert page.sent == [("Mary Levine", "hi there")]
    msg = r.json()["message"]
    assert (msg["mine"], msg["who"], msg["text"], msg["kind"], msg["links"]) == \
        (True, "", "hi there", "text", [])
    assert msg["msg_id"].startswith("local-")

    assert client.post("/api/chat/send",
                       json={"chat_id": "t2", "text": "yo"}).status_code == 200
    assert page.sent[-1] == ("nikos", "yo")

    stored = store.ig_msgs(conn, "t1")
    assert (stored[-1]["msg_id"], stored[-1]["mine"]) == (msg["msg_id"], True)


@pytest.mark.parametrize("text", ["", "   ", "\n\t "])
def test_empty_text_is_a_bad_request(client, text):
    r = client.post("/api/chat/send", json={"chat_id": "t1", "text": text})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_request"


def test_a_provider_that_cannot_send_is_refused(client):
    conn = client.app.state.conn
    use_provider(client, FakeIg([ig_thread("t1")]))
    chats(client)
    # The page is swapped after the list: the cache still names the recipient.
    client.app.state.syncer._provider = types.SimpleNamespace()

    r = client.post("/api/chat/send", json={"chat_id": "t1", "text": "hi"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "unsupported"
    assert conn.execute("SELECT COUNT(*) AS n FROM ig_msgs").fetchone()["n"] == 0
