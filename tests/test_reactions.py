"""Reactions: Telegram names a message, Instagram needs its own id for it."""
from __future__ import annotations

import sqlite3

from app import store, telegram


def conn_now():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store.init(conn)
    return conn


def reaction_update(chat_id=-100, msg_id=42, emojis=("❤",), user_id=7):
    return {"update_id": 1, "message_reaction": {
        "chat": {"id": chat_id, "type": "supergroup"},
        "message_id": msg_id, "date": 1_700_000_000,
        "user": {"id": user_id, "is_bot": False, "first_name": "S"},
        "new_reaction": [{"type": "emoji", "emoji": e} for e in emojis]}}


def test_a_reaction_update_becomes_an_emoji_for_a_message():
    row = telegram.normalize_reaction(reaction_update(emojis=("👍", "❤")))
    assert row["chat_id"] == "-100"
    assert row["msg_id"] == "42"
    assert row["emoji"] == "❤"      # the last one pressed


def test_removing_a_reaction_is_an_empty_emoji():
    assert telegram.normalize_reaction(reaction_update(emojis=()))["emoji"] == ""


def test_a_plain_message_is_not_a_reaction():
    assert telegram.normalize_reaction({"update_id": 2, "message": {}}) is None


def test_a_reaction_waits_in_the_table_until_it_is_done():
    conn = conn_now()
    store.queue_reaction(conn, "-100", "42", "❤", now=1)
    row = store.next_reaction(conn)
    assert row["emoji"] == "❤" and row["done"] == 0
    store.finish_reaction(conn, row["id"])
    assert store.next_reaction(conn) is None


def test_a_telegram_message_points_at_the_instagram_message_it_carried():
    conn = conn_now()
    store.map_ig_message(conn, "-100", 42, "1742", "mid.$abc", now=1)
    assert store.ig_message_for(conn, "-100", "42") == ("1742", "mid.$abc")
    assert store.ig_message_for(conn, "-100", "43") is None
