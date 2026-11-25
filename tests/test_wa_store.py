"""WhatsApp's four tables: the keys, the id tail, and the echo filter."""
from __future__ import annotations

import sqlite3

import pytest

from app import store


def conn_now():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store.init(conn)
    return conn


def test_tables_are_separate_from_instagram():
    """Two relays, two sets of tables: a shared table would let one cleanup
    delete the other's state, and the two key differently."""
    conn = conn_now()
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"wa_chats", "wa_marks", "wa_sent_map", "wa_reacts"} <= names
    assert {"ig_threads", "ig_sent_map", "ig_reacts"} <= names
    assert conn.execute("SELECT COUNT(*) AS n FROM wa_chats").fetchone()["n"] == 0


def test_topic_roundtrip_and_forgetting():
    conn = conn_now()
    assert store.wa_thread_id(conn, "+30 697 (You)") is None
    store.save_wa_thread(conn, "+30 697 (You)", 12, is_self=True)
    assert store.wa_thread_id(conn, "+30 697 (You)") == 12
    assert store.wa_name(conn, 12) == "+30 697 (You)"
    # A deleted topic is forgotten by writing 0, which reads as falsy, which is
    # how the relay knows to make a new one.
    store.save_wa_thread(conn, "+30 697 (You)", 0, is_self=True)
    assert store.wa_thread_id(conn, "+30 697 (You)") == 0
    assert store.wa_name(conn, 0) is None
    assert conn.execute("SELECT is_self FROM wa_chats").fetchone()["is_self"] == 1


def test_mark_keeps_the_tail_not_the_history():
    conn = conn_now()
    assert store.wa_mark(conn, "Mary") == {}
    store.save_wa_mark(conn, "Mary", [f"m{i}" for i in range(300)],
                       preview="ok", ts="20:17", unread="2")
    mark = store.wa_mark(conn, "Mary")
    assert len(mark["ids"]) == 200
    assert mark["ids"][-1] == "m299" and mark["ids"][0] == "m100"
    assert (mark["preview"], mark["ts"], mark["unread"]) == ("ok", "20:17", "2")


def test_mark_dedups_ids_and_survives_a_repeat():
    conn = conn_now()
    store.save_wa_mark(conn, "Mary", ["a", "b", "a"])
    assert store.wa_mark(conn, "Mary")["ids"] == ["a", "b"]
    store.save_wa_mark(conn, "Mary", ["c"], preview="new")
    mark = store.wa_mark(conn, "Mary")
    assert mark["ids"] == ["c"] and mark["preview"] == "new"


def test_sent_map_is_both_a_react_target_and_an_echo_filter():
    conn = conn_now()
    store.map_wa_message(conn, "-100", 41, "Mary", "3EB0AA")            # relayed
    store.map_wa_message(conn, "-100", 42, "Mary", "3EB0AB", typed=True)  # we typed it
    assert store.wa_message_for(conn, "-100", 41) == ("Mary", "3EB0AA")
    # A relayed message is not an echo to suppress; only one we typed is.
    assert store.wa_message_sent(conn, "3EB0AA") is False
    assert store.wa_message_sent(conn, "3EB0AB") is True
    assert store.wa_message_for(conn, "-100", 43) is None


def test_reaction_queues_are_not_each_other():
    conn = conn_now()
    store.queue_reaction(conn, "-100", 1, "❤", table="wa_reacts")
    store.queue_reaction(conn, "-100", 2, "❤")            # instagram, the default
    assert store.next_reaction(conn, "wa_reacts")["tg_msg_id"] == "1"
    assert store.next_reaction(conn)["tg_msg_id"] == "2"
    store.finish_reaction(conn, store.next_reaction(conn, "wa_reacts")["id"],
                          table="wa_reacts")
    assert store.next_reaction(conn, "wa_reacts") is None
    assert store.next_reaction(conn)["done"] == 0


def test_reaction_table_is_a_whitelist():
    conn = conn_now()
    with pytest.raises(ValueError):
        store.next_reaction(conn, "ig_reacts; DROP TABLE posts")
    with pytest.raises(ValueError):
        store.queue_reaction(conn, "1", 2, "❤", table="wa_reacts--")
