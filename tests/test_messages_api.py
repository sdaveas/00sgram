"""The Telegram message surface, offline: list, thread, send, resolve.

These routes are the only place a message row becomes something a screen draws,
so they are pinned here: the list order and unread count, the thread order (a
later `at` can be stored before an earlier one), the single-attempt send, and
`/api/resolve` fetching one code without touching the network.

`PROVIDER=mock` and a temp dir. `Telegram` is monkeypatched where sending is
exercised, and the one share-link hop is replaced with a refusal: no test here
may reach api.telegram.org or instagram.com.
"""
from __future__ import annotations

import types

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main, store, telegram
from app.config import Config
from app.main import create_app

AT = 1_764_000_000
SENT_AT = 1_700_000_000
LINK = "https://www.instagram.com/reel/DAbCdEf123/"


def make_config(tmp_path, **over):
    env = {"DATA_DIR": str(tmp_path / "data"),
           "PROVIDER": "mock",
           "API_TOKEN": "tok", "APP_PASSWORD": "pw", "APP_SECRET": "s" * 32,
           "BACKFILL_SLEEP": "0"}
    env.update(over)
    return Config.from_env(env)


@pytest.fixture()
def app(tmp_path):
    return create_app(make_config(tmp_path))


@pytest.fixture()
def client(app):
    c = TestClient(app)
    assert c.post("/login", json={"password": "pw"}).status_code == 200
    return c


@pytest.fixture()
def tg_client(tmp_path):
    c = TestClient(create_app(make_config(tmp_path, TELEGRAM_TOKEN="1:x")))
    assert c.post("/login", json={"password": "pw"}).status_code == 200
    return c


def seed_message(conn, chat_id, msg_id, at, *, mine=False, text="", title=None,
                 kind="dm", who="", kind_msg="text", links=None):
    store.save_tg_message(conn, {
        "chat_id": chat_id, "msg_id": msg_id, "at": at, "mine": mine,
        "who": who, "kind_msg": kind_msg, "text": text, "links": links or [],
        "title": chat_id if title is None else title, "kind": kind})


def count_messages(conn):
    return conn.execute("SELECT COUNT(*) AS n FROM tg_messages").fetchone()["n"]


# -------------------------------------------------------------------- list


def test_a_fresh_app_says_not_configured_and_has_no_chats(client):
    assert client.get("/api/messages").json() == {"configured": False, "chats": []}


def test_chats_are_newest_last_message_first_with_their_unread_count(client):
    conn = client.app.state.conn
    seed_message(conn, "dm2", "1", AT - 500, text="old", title="Maria", who="Maria")
    seed_message(conn, "grp", "1", AT, text="swap", title="Reel Swaps",
                 kind="group", kind_msg="photo", who="Maria")
    seed_message(conn, "dm1", "1", AT - 300, text="yo", title="Nikos", who="Nikos")
    seed_message(conn, "dm1", "2", AT - 200, text=f"look {LINK}", title="Nikos",
                 who="Nikos", links=[LINK])
    seed_message(conn, "dm1", "3", AT - 100, text="nice", title="Nikos", mine=True)

    body = client.get("/api/messages").json()
    assert body["configured"] is False
    assert [c["chat_id"] for c in body["chats"]] == ["grp", "dm1", "dm2"]

    by_id = {c["chat_id"]: c for c in body["chats"]}
    group = by_id["grp"]
    assert (group["title"], group["kind"]) == ("Reel Swaps", "group")
    assert (group["last_at"], group["last_text"]) == (AT, "swap")
    assert group["last_kind"] == "photo"

    dm = by_id["dm1"]
    assert (dm["kind"], dm["last_at"], dm["last_text"]) == ("dm", AT - 100, "nice")
    # Three rows, but only the two somebody else wrote count as unread.
    assert dm["unread"] == 2
    assert by_id["dm2"]["unread"] == 1


# ------------------------------------------------------------------ thread


def chat_thread(client, chat_id):
    return client.get("/api/messages/thread", params={"chat_id": chat_id})


def thread_unread(client, chat_id):
    chats = client.get("/api/messages").json()["chats"]
    return {c["chat_id"]: c["unread"] for c in chats}[chat_id]


def test_the_thread_is_oldest_first_even_when_stored_out_of_order(client):
    conn = client.app.state.conn
    seed_message(conn, "c1", "m1", AT + 100, text="first")
    seed_message(conn, "c1", "m2", AT + 300, text="third")
    seed_message(conn, "c1", "m3", AT + 200, text=f"second {LINK}", links=[LINK])
    seed_message(conn, "c1", "m4", AT + 400, text="fourth")

    r = chat_thread(client, "c1")
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert [m["at"] for m in msgs] == [AT + 100, AT + 200, AT + 300, AT + 400]
    assert [m["msg_id"] for m in msgs] == ["m1", "m3", "m2", "m4"]
    # `links` is stored as JSON text and handed out decoded; an empty column is [].
    assert msgs[1]["links"] == [LINK]
    assert msgs[2]["links"] == []


def test_reading_a_thread_marks_it_read_and_repeating_it_is_harmless(client):
    conn = client.app.state.conn
    for i, offset in enumerate((0, 60, 120)):
        seed_message(conn, "c1", str(i), AT + offset, text=f"m{i}")
    assert thread_unread(client, "c1") == 3

    assert chat_thread(client, "c1").status_code == 200
    assert thread_unread(client, "c1") == 0
    assert chat_thread(client, "c1").status_code == 200
    assert thread_unread(client, "c1") == 0


def test_a_message_that_arrives_after_the_read_is_unread_again(client):
    conn = client.app.state.conn
    seed_message(conn, "c1", "1", AT, text="read me")
    assert chat_thread(client, "c1").status_code == 200
    assert thread_unread(client, "c1") == 0

    seed_message(conn, "c1", "2", AT + 30, text="new")
    assert thread_unread(client, "c1") == 1


def test_an_unknown_chat_is_a_404(client):
    r = chat_thread(client, "nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# -------------------------------------------------------------------- send


def test_sending_without_a_token_is_not_configured_and_stores_nothing(client):
    conn = client.app.state.conn
    seed_message(conn, "c1", "1", AT, text="theirs")
    before = count_messages(conn)

    r = client.post("/api/messages/send", json={"chat_id": "c1", "text": "hi"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "not_configured"
    assert count_messages(conn) == before


def test_sending_outside_the_relay_chat_is_refused(tmp_path, monkeypatch):
    """A stored row from some other chat must not turn the portal into a
    megaphone: the bot speaks where the relay lives and nowhere else."""
    c = TestClient(create_app(make_config(
        tmp_path, TELEGRAM_TOKEN="1:x", TELEGRAM_RELAY_CHAT="-1001234567890")))
    assert c.post("/login", json={"password": "pw"}).status_code == 200
    seed_message(c.app.state.conn, "777", "1", AT, text="theirs")

    sent = []
    monkeypatch.setattr(main, "Telegram", types.SimpleNamespace(
        send=lambda *a: sent.append(a)))

    r = c.post("/api/messages/send", json={"chat_id": "777", "text": "hi"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"
    assert sent == []


@pytest.mark.parametrize("text", ["", "   ", "\n\t "])
def test_empty_text_is_a_bad_request(tg_client, text):
    r = tg_client.post("/api/messages/send", json={"chat_id": "c1", "text": text})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_request"


def test_send_calls_telegram_once_and_stores_the_row_last(tg_client, monkeypatch):
    conn = tg_client.app.state.conn
    seed_message(conn, "777", "1", SENT_AT - 200, text="earlier", title="Nikos")
    seed_message(conn, "777", "2", SENT_AT - 100, text="and earlier", title="Nikos")

    sent = []

    class FakeTelegram:
        def __init__(self, token):
            self.token = token

        def send(self, chat_id, text):
            sent.append((chat_id, text))
            return {"message_id": 4242, "date": SENT_AT}

    monkeypatch.setattr(main, "Telegram", FakeTelegram)

    r = tg_client.post("/api/messages/send",
                       json={"chat_id": "777", "text": "hi there"})
    assert r.status_code == 200
    msg = r.json()["message"]
    assert msg["msg_id"] == "4242"
    assert msg["mine"] is True
    assert msg["text"] == "hi there"
    # One attempt, no retry: a send that may have landed must not go twice.
    assert sent == [("777", "hi there")]

    msgs = chat_thread(tg_client, "777").json()["messages"]
    assert msgs[-1]["msg_id"] == "4242"
    assert msgs[-1]["text"] == "hi there"


def test_a_refused_send_is_a_502_and_stores_nothing(tg_client, monkeypatch):
    conn = tg_client.app.state.conn
    seed_message(conn, "c1", "1", AT, text="theirs")
    before = count_messages(conn)

    class RefusingTelegram:
        def __init__(self, token):
            self.token = token

        def send(self, chat_id, text):
            raise telegram.TelegramError("nope", 400)

    monkeypatch.setattr(main, "Telegram", RefusingTelegram)

    r = tg_client.post("/api/messages/send", json={"chat_id": "c1", "text": "hi"})
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "telegram"
    assert count_messages(conn) == before


# ----------------------------------------------------------------- resolve


def fresh_code(client):
    code = client.app.state.syncer.provider.feed[0].code
    assert store.post_by_code(client.app.state.conn, code) is None
    return code


def resolve(client, url):
    return client.get("/api/resolve", params={"url": url})


def count_by_code(conn, code):
    return conn.execute("SELECT COUNT(*) AS n FROM posts WHERE code=?",
                        (code,)).fetchone()["n"]


def test_resolving_a_new_code_stores_the_post_and_looks_at_it(client):
    conn = client.app.state.conn
    code = fresh_code(client)

    r = resolve(client, f"https://www.instagram.com/reel/{code}/")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "post"
    item = body["item"]
    assert item["pk"]
    assert item["resources"]
    assert item["account"]["username"]

    row = store.post_by_code(conn, code)
    assert row is not None and row["seen_at"] is not None
    # The answer describes the stored row as it is now: mark_seen ran, so the
    # post is reported seen and stays out of the unseen deck.
    assert item["seen"] is True


def test_resolving_twice_is_a_200_and_stores_one_post(client):
    conn = client.app.state.conn
    code = fresh_code(client)
    url = f"https://www.instagram.com/p/{code}/"

    assert resolve(client, url).status_code == 200
    second = resolve(client, url)
    assert second.status_code == 200
    assert second.json()["item"]["seen"] is True
    assert count_by_code(conn, code) == 1


def test_resolve_refuses_links_it_cannot_open(client):
    unknown = resolve(client, "https://www.instagram.com/reel/CZZZZZZZZZ/")
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "not_found"

    elsewhere = resolve(client, "https://example.com/p/abc/")
    assert elsewhere.status_code == 400
    assert elsewhere.json()["error"]["code"] == "bad_link"

    story = resolve(client, "https://www.instagram.com/stories/nikos/3344556677/")
    assert story.status_code == 422
    assert story.json()["error"]["code"] == "unsupported_link"


def test_resolve_requires_auth(client):
    code = fresh_code(client)
    anon = TestClient(client.app).get(
        "/api/resolve", params={"url": f"https://www.instagram.com/p/{code}/"})
    assert anon.status_code == 401
    assert anon.json()["error"]["code"] == "unauthorised"


def test_a_share_link_is_not_followed_by_the_test(client, monkeypatch):
    """`/share/reel/<token>/` only resolves by following one real HTTP hop, so
    the client is replaced with one that refuses to connect: offline, and the
    route must answer an error rather than reach instagram.com."""
    class Offline:
        def __init__(self, **kwargs):
            pass

        def get(self, url):
            raise httpx.ConnectError("the test must stay offline")

    monkeypatch.setattr(main, "httpx", types.SimpleNamespace(
        Client=Offline, HTTPError=httpx.HTTPError))

    r = resolve(client, "https://www.instagram.com/share/reel/Tok3nAbc/")
    assert 400 <= r.status_code < 600


# ------------------------------------------------------------ not configured


def test_a_missing_token_is_not_an_error_anywhere(client):
    """No token is a normal state, not a 4xx, and it must not stop startup."""
    r = client.get("/api/messages")
    assert r.status_code == 200
    assert r.json() == {"configured": False, "chats": []}


def test_the_app_boots_without_a_telegram_token(tmp_path):
    app = create_app(make_config(tmp_path))
    assert TestClient(app).get("/api/health").status_code == 200
