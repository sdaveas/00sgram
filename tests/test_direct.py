"""Direct messages: the normalisers, and the two endpoints behind a stub.

The DOM rows below are the shapes measured on the real inbox page:
`name / preview / · / 2h`, an unread row, a row that has never been written
to (`Active 3h ago`), and a transcript with a `Seen by` line. No network.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import direct
from app.config import Config
from app.main import create_app
from app.provider import ProviderError


def make_config(tmp_path):
    return Config.from_env({
        "DATA_DIR": str(tmp_path / "data"), "PROVIDER": "mock",
        "API_TOKEN": "tok", "APP_PASSWORD": "pw", "APP_SECRET": "s" * 32,
        "BACKFILL_SLEEP": "0"})


@pytest.fixture()
def app(tmp_path):
    return create_app(make_config(tmp_path))


@pytest.fixture()
def client(app):
    c = TestClient(app)
    assert c.post("/login", json={"password": "pw"}).status_code == 200
    return c


# ------------------------------------------------------------------ fixtures
ROWS = [
    {"lines": ["monday five", "g.papadakis__: καλησπέρα σε όλους", "·", "2h"],
     "unread": True},
    {"lines": ["Konstantinos Dimitros", "Active 3h ago"], "unread": False},
    {"lines": ["Mary Levine", "Mary sent an attachment.", "\u00a0", "·", "15h"],
     "unread": False},
    {"lines": ["The Plug", "You: 🔥", "·", "6w"], "unread": False},
    # The list can be in the DOM twice; the name decides.
    {"lines": ["monday five", "newer preview", "1h"], "unread": True},
]

THREAD = {"url": "https://www.instagram.com/direct/t/1070027318988571/",
          "lines": ["Mon 23:17", "Giorgos Papadakis", "καλησπέρα",
                    "\u00a0", "·", "12:06", "nika", "Seen by nika"]}


def test_a_row_is_name_preview_when_and_unread():
    items = direct.clean_inbox(ROWS)
    assert items[0] == {"name": "monday five",
                        "preview": "g.papadakis__: καλησπέρα σε όλους",
                        "when": "2h", "unread": True}
    assert len(items) == 4, "a duplicate name is one conversation"


def test_a_row_without_a_message_keeps_its_active_line_as_when():
    row = direct.clean_inbox(ROWS)[1]
    assert row == {"name": "Konstantinos Dimitros", "preview": "",
                   "when": "Active 3h ago", "unread": False}


def test_a_row_without_a_time_is_not_a_row_with_a_broken_one():
    assert direct.clean_inbox([{"lines": ["Your note"], "unread": False}]) == \
        [{"name": "Your note", "preview": "", "when": "", "unread": False}]


def test_the_thread_keeps_its_lines_and_finds_the_id():
    got = direct.clean_thread(THREAD)
    assert got["thread_id"] == "1070027318988571"
    assert got["lines"] == ["Mon 23:17", "Giorgos Papadakis", "καλησπέρα",
                            "12:06", "nika", "Seen by nika"]


def test_a_thread_that_did_not_open_has_no_id():
    got = direct.clean_thread({"url": "https://www.instagram.com/direct/inbox/",
                               "lines": []})
    assert got["thread_id"] is None and got["lines"] == []


# ------------------------------------------------------------------ endpoints
def test_the_list_is_read_then_served_from_cache(app, client):
    provider = app.state.syncer.provider
    provider.inbox = lambda: [{"name": "monday five", "preview": "γεια",
                               "when": "2h", "unread": True}]
    first = client.get("/api/inbox").json()
    assert first["stale"] is False and first["items"][0]["name"] == "monday five"

    # The browser is busy: the last list beats an empty screen, and says so.
    def boom():
        raise ProviderError("browser is busy")

    provider.inbox = boom
    second = client.get("/api/inbox").json()
    assert second["stale"] is True and "busy" in second["error"]
    assert second["items"] == first["items"] and second["fetched_at"] == first["fetched_at"]


def test_a_provider_that_cannot_read_messages_says_so(client):
    body = client.get("/api/inbox").json()
    assert body["items"] == [] and body["stale"] is True
    assert body["error"] == "provider"


def test_the_thread_answers_what_the_browser_read(app, client):
    provider = app.state.syncer.provider
    provider.thread = lambda name: {"thread_id": "1", "url": "…",
                                    "lines": [f"hi {name}"]}
    body = client.get("/api/inbox/thread", params={"name": "monday five"}).json()
    assert body["lines"] == ["hi monday five"]


def test_a_thread_failure_is_a_sentence_not_a_stack(app, client):
    provider = app.state.syncer.provider
    provider.thread = lambda name: (_ for _ in ()).throw(
        ProviderError("no conversation named 'nobody'"))
    r = client.get("/api/inbox/thread", params={"name": "nobody"})
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "provider"
