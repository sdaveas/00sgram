"""The Telegram edge, offline: one Bot API update in, one message row out.

The `getUpdates` body below is written by hand, because reading that exact
shape is the module's whole job. Nothing here builds a client that could reach
api.telegram.org: the ingest test gets a fake that only implements `updates`.
"""
from __future__ import annotations

import threading
import types

import pytest

from app import store
from app.telegram import Telegram, ingest, normalize_update, start_poller

BOT = "6001"
SENDER = 777
DM_AT = 1_764_000_100
LINKED = "https://www.instagram.com/reel/DAbCdEf123/"
SHARED = "https://www.instagram.com/share/reel/Tok3nAbc/"

GET_UPDATES = {
    "ok": True,
    "result": [
        {
            "update_id": 1,
            "message": {
                "message_id": 101,
                "from": {"id": SENDER, "is_bot": False, "first_name": "Nikos",
                         "last_name": "Papadakis", "username": "npapa",
                         "language_code": "en"},
                "chat": {"id": 555, "first_name": "Nikos", "last_name": "Papadakis",
                         "username": "npapa", "type": "private"},
                "date": DM_AT,
                "text": f"look at this {LINKED}",
            },
        },
        {
            "update_id": 2,
            "message": {
                "message_id": 201,
                "from": {"id": 888, "is_bot": False, "first_name": "Maria",
                         "last_name": "Konsta", "username": "mkonsta"},
                "chat": {"id": -1001234567890, "title": "Reel Swaps",
                         "type": "supergroup"},
                "date": DM_AT + 10,
                "photo": [
                    {"file_id": "AgACAgQ1", "file_unique_id": "aq1", "width": 320,
                     "height": 240, "file_size": 12345},
                    {"file_id": "AgACAgQ2", "file_unique_id": "aq2", "width": 800,
                     "height": 600, "file_size": 54321},
                ],
                "caption": f"this one {SHARED}",
            },
        },
        {"update_id": 3},
        {
            "update_id": 5,
            "edited_message": {
                "message_id": 102,
                "from": {"id": SENDER, "is_bot": False, "first_name": "Nikos",
                         "last_name": "Papadakis"},
                "chat": {"id": 555, "first_name": "Nikos", "last_name": "Papadakis",
                         "type": "private"},
                "date": DM_AT + 20,
                "edit_date": DM_AT + 30,
                "text": "typo fixed",
            },
        },
    ],
}
UPDATES = GET_UPDATES["result"]


class FakeTg:
    """Only what `ingest` calls, and it records the offset it was given."""

    def __init__(self, batch):
        self.batch = batch
        self.offsets: list[int | None] = []

    def updates(self, offset=None):
        self.offsets.append(offset)
        return list(self.batch)


@pytest.fixture()
def conn(tmp_path):
    connection = store.connect(tmp_path / "00sgram.sqlite3")
    store.init(connection)
    return connection


# ---------------------------------------------------------------- normalize


def test_a_private_text_becomes_a_dm_row_with_its_link():
    row = normalize_update(UPDATES[0], BOT)
    assert (row["chat_id"], row["msg_id"], row["kind"]) == ("555", "101", "dm")
    assert row["at"] == DM_AT
    assert row["kind_msg"] == "text" and row["links"] == [LINKED]
    assert row["who"] == "Nikos Papadakis" and row["title"] == "Nikos Papadakis"
    assert row["mine"] is False


def test_a_supergroup_photo_carries_its_caption_and_the_link_in_it():
    row = normalize_update(UPDATES[1], BOT)
    assert (row["kind"], row["kind_msg"]) == ("group", "photo")
    assert row["text"] == f"this one {SHARED}"
    assert row["links"] == [SHARED]
    assert row["title"] == "Reel Swaps" and row["who"] == "Maria Konsta"


def test_only_the_bot_own_messages_are_mine():
    """A bot sends as itself and as nobody else; that is the whole authorship."""
    assert normalize_update(UPDATES[0], str(SENDER))["mine"] is True
    assert normalize_update(UPDATES[1], str(SENDER))["mine"] is False


def test_an_edit_is_a_message_too():
    row = normalize_update(UPDATES[3], BOT)
    assert (row["msg_id"], row["text"]) == ("102", "typo fixed")


def test_an_update_with_no_message_is_dropped():
    assert normalize_update({"update_id": 3}) is None


def test_a_message_with_no_chat_or_id_is_dropped():
    assert normalize_update({"update_id": 9, "message": {"message_id": 5,
                                                         "date": 1}}) is None
    assert normalize_update({"update_id": 10, "message": {"chat": {"id": 1},
                                                          "date": 1}}) is None


def test_a_text_link_entity_adds_the_url_typing_did_not_contain():
    """A hidden link or an inline button holds a URL the message text lacks."""
    update = {"update_id": 11, "message": {
        "message_id": 301, "date": DM_AT,
        "chat": {"id": 555, "type": "private", "first_name": "Nikos"},
        "from": {"id": SENDER, "first_name": "Nikos"},
        "text": "tap here",
        "entities": [{"type": "text_link", "offset": 4, "length": 4,
                      "url": "https://www.instagram.com/reel/Hidden99/"}]}}
    row = normalize_update(update, BOT)
    assert row["text"] == "tap here\nhttps://www.instagram.com/reel/Hidden99/"
    assert row["links"] == ["https://www.instagram.com/reel/Hidden99/"]


# -------------------------------------------------------------------- ingest


def test_ingest_stores_the_batch_then_asks_for_what_came_after_it(conn):
    tg = FakeTg(UPDATES)
    assert ingest(tg, conn, BOT) == 3
    assert conn.execute("SELECT COUNT(*) AS n FROM tg_messages").fetchone()["n"] == 3
    assert tg.offsets == [None]

    ingest(tg, conn, BOT)
    assert tg.offsets == [None, max(u["update_id"] for u in UPDATES) + 1]


def test_the_same_batch_twice_does_not_duplicate_a_row(conn):
    """A crashed run before the offset was saved replays the batch; the unique
    (chat_id, msg_id) has to absorb it."""
    tg = FakeTg(UPDATES)
    ingest(tg, conn, BOT)
    ingest(tg, conn, BOT)
    assert conn.execute("SELECT COUNT(*) AS n FROM tg_messages").fetchone()["n"] == 3


def test_a_reaction_is_filed_in_the_queue_of_the_group_it_was_pressed_in(conn):
    """Topic ids are per group and mean nothing elsewhere, so the ingest has to
    route the reaction now — later there is nothing to ask."""
    update = {"update_id": 9, "message_reaction": {
        "chat": {"id": -100123}, "message_id": 55, "date": 1_764_000_900,
        "new_reaction": [{"type": "emoji", "emoji": "❤"}]}}

    ingest(FakeTg([update]), conn, BOT, wa_chat="-100123")
    assert store.next_reaction(conn, "wa_reacts")["tg_msg_id"] == "55"
    assert store.next_reaction(conn) is None

    ingest(FakeTg([update]), conn, BOT, wa_chat="-100999")
    assert store.next_reaction(conn)["tg_msg_id"] == "55"


def test_a_chat_we_do_not_speak_in_is_dropped_before_it_is_stored(conn):
    """Anyone who finds a bot can message it; a stranger's DM has no business in
    the table or on the screen. The relay's chat is the only door."""
    update = {"update_id": 11, "message": {
        "message_id": 1, "date": 1_764_000_900,
        "from": {"id": 7, "first_name": "someone"},
        "chat": {"id": 7, "type": "private"}, "text": "hi"}}
    tg = FakeTg([update])

    assert ingest(tg, conn, BOT, allow=("-1001234567890",)) == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM tg_messages").fetchone()["n"] == 0
    # The offset still moves: a dropped update that comes back every poll is a
    # loop, not a filter.
    assert tg.offsets == [None]

    ingest(tg, conn, BOT, allow=("-1001234567890",))
    assert tg.offsets == [None, 12]


def test_a_reaction_elsewhere_is_not_queued(conn):
    update = {"update_id": 12, "message_reaction": {
        "chat": {"id": 7}, "message_id": 55, "date": 1_764_000_900,
        "new_reaction": [{"type": "emoji", "emoji": "\u2764"}]}}
    ingest(FakeTg([update]), conn, BOT, allow=("-1001234567890",))
    assert store.next_reaction(conn) is None
    assert store.next_reaction(conn, "wa_reacts") is None


# --------------------------------------------------------------- start_poller


def test_no_token_means_no_poller_and_no_network(conn):
    ev = start_poller(types.SimpleNamespace(telegram_token=""), conn)
    assert isinstance(ev, threading.Event) and not ev.is_set()
    assert "telegram-poll" not in {t.name for t in threading.enumerate()}


def test_constructing_the_client_does_not_call_the_api():
    tg = Telegram("x")
    assert tg.token == "x"
    tg.client.close()
