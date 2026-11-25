"""The WhatsApp relay's one decision: which messages become Telegram messages.

The list row is a trigger, the ids are the truth. These tests drive `relay_once`
with a fake page that answers like the real one — primed or not, one chat or
three — and with a fake Telegram that records what it was told to say.
"""
from __future__ import annotations

import sqlite3

import pytest

from app import store, warelay
from app.wadirect import Wa


class FakeTG:
    def __init__(self, fail_threads: bool = False):
        self.sent: list[tuple[int | None, str]] = []
        self.topics: list[str] = []
        self.fail_threads = fail_threads
        self.next_topic = 100

    def send(self, chat_id, text, thread_id=None):
        from app.telegram import TelegramError

        if self.fail_threads and thread_id:
            raise TelegramError("Bad Request: message thread not found")
        self.sent.append((thread_id, text))
        return {"message_id": len(self.sent)}

    def create_topic(self, chat_id, name):
        self.topics.append(name)
        self.next_topic += 1
        return {"message_thread_id": self.next_topic}


class FakeWa:
    """`Wa` as `relay_once` uses it: ready, open, messages."""

    def __init__(self, chats, threads, logged_in=True):
        self._chats = chats
        self._threads = threads
        self.logged_in = logged_in
        self.opened: list[str] = []
        self.messages_calls = 0

    def ready(self, tries=15, step=1000):
        return self._chats if self.logged_in else None

    def chats(self):
        return self._chats if self.logged_in else None

    def open(self, name, preview=""):
        self.opened.append(name)
        return name in self._threads

    def messages(self):
        self.messages_calls += 1
        return self._threads.get(self.opened[-1], []) if self.opened else None


def conn_now():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store.init(conn)
    return conn


def chat(name, preview="hi", ts="20:17", unread="", self=False):
    return {"name": name, "preview": preview, "ts": ts, "unread": unread,
            "self": self, "x": 100, "y": 100, "top": 70, "bottom": 130}


def msg(mid, text, mine=False, sender="", icons=None):
    return {"id": mid, "text": text, "mine": mine, "sender": sender,
            "icons": icons or []}


def prime(conn, wa, tg=None):
    """The first ever cycle: adopt the list, send nothing."""
    sent = warelay.relay_once(tg or FakeTG(), conn, "-100", wa)
    assert sent == 0


def seed(conn, name, ids):
    """A conversation already read: these ids are what Telegram has."""
    store.save_wa_mark(conn, name, ids, preview="old", ts="20:00")


def test_first_cycle_adopts_and_opens_nothing():
    wa = FakeWa([chat("Mary"), chat("Bob")], {"Mary": [msg("m1", "παλιό")]})
    tg = FakeTG()
    assert warelay.relay_once(tg, conn := conn_now(), "-100", wa) == 0
    assert tg.sent == [] and wa.opened == []
    assert store.wa_mark(conn, "Mary")["ids"] == []


def test_a_new_message_is_one_telegram_message_not_two():
    conn = conn_now()
    wa = FakeWa([chat("Mary")], {"Mary": [msg("m1", "γεια")]})
    prime(conn, wa)
    wa._chats = [chat("Mary", preview="τι κάνεις")]
    wa._threads = {"Mary": [msg("m1", "γεια"), msg("m2", "τι κάνεις")]}
    tg = FakeTG()
    assert warelay.relay_once(tg, conn, "-100", wa) == 1
    assert [t for _, t in tg.sent] == ["τι κάνεις"]
    assert store.wa_mark(conn, "Mary")["ids"] == ["m1", "m2"]


def test_the_same_cycle_twice_posts_nothing_the_second_time():
    conn = conn_now()
    wa = FakeWa([chat("Mary", preview="old")], {"Mary": [msg("m1", "γεια"), msg("m2", "x")]})
    prime(conn, wa)
    seed(conn, "Mary", ["m1"])
    wa._chats = [chat("Mary", preview="x")]
    tg = FakeTG()
    assert warelay.relay_once(tg, conn, "-100", wa) == 1
    assert warelay.relay_once(tg, conn, "-100", wa) == 0
    assert len(tg.sent) == 1


def test_a_chat_never_read_yields_only_its_newest_message():
    """A hundred messages of history are not news. The first look at a
    conversation sends one bubble, then it is just a conversation."""
    conn = conn_now()
    wa = FakeWa([chat("Mary", preview="old")], {"Mary": []})
    prime(conn, wa)                       # Mary was in the list, never read
    wa._chats = [chat("Mary", preview="first")]
    wa._threads = {"Mary": [msg(f"m{i}", f"line {i}") for i in range(50)]}
    tg = FakeTG()
    assert warelay.relay_once(tg, conn, "-100", wa) == 1
    assert tg.sent[0][1] == "line 49"


def test_a_conversation_outside_the_primed_list_still_gets_its_newest():
    conn = conn_now()
    wa = FakeWa([chat("Mary")], {"Mary": []})
    prime(conn, wa)
    wa._chats = [chat("Bob", preview="νέο"), chat("Mary")]
    wa._threads = {"Bob": [msg("b1", "παλιό"), msg("b2", "νέο")], "Mary": []}
    tg = FakeTG()
    assert warelay.relay_once(tg, conn, "-100", wa) == 1
    assert tg.sent[0][1] == "νέο"


def test_restart_does_not_repost():
    conn = conn_now()
    wa = FakeWa([chat("Mary", preview="x")], {"Mary": [msg("m1", "γεια"), msg("m2", "x")]})
    prime(conn, wa)
    warelay.relay_once(FakeTG(), conn, "-100", wa)
    tg = FakeTG()
    assert warelay.relay_once(tg, conn, "-100", FakeWa(wa._chats, wa._threads)) == 0
    assert tg.sent == []


def test_direct_messages_are_bare_and_groups_name_the_sender():
    conn = conn_now()
    wa = FakeWa([chat("Μαμά"), chat("Οικογένεια")],
                {"Μαμά": [msg("d1", "γεια")],
                 "Οικογένεια": [msg("g1", "έφτασα", sender="Γιώργος")]})
    prime(conn, wa)
    wa._chats = [chat("Μαμά", preview="γεια σου"), chat("Οικογένεια", preview="έφτασα!")]
    tg = FakeTG()
    warelay.relay_once(tg, conn, "-100", wa)
    assert [t for _, t in tg.sent] == ["γεια", "Γιώργος: έφτασα"]


def test_the_self_chat_relays_our_own_messages():
    conn = conn_now()
    name = "+30 697 (You)"
    wa = FakeWa([chat(name, self=True)], {name: []})
    prime(conn, wa)
    wa._chats = [chat(name, preview="σημείωση", self=True)]
    wa._threads = {name: [msg("s1", "σημείωση", mine=True)]}
    tg = FakeTG()
    assert warelay.relay_once(tg, conn, "-100", wa) == 1
    assert tg.sent[0][1] == "σημείωση"          # no «εγώ:» in a chat that is only us


def test_the_self_chat_does_not_echo_what_the_relay_typed():
    conn = conn_now()
    name = "+30 697 (You)"
    wa = FakeWa([chat(name, self=True)], {name: []})
    prime(conn, wa)
    store.map_wa_message(conn, "-100", 7, name, "s1", typed=True)  # typed in TG
    wa._chats = [chat(name, preview="από TG", self=True)]
    wa._threads = {name: [msg("s1", "από TG", mine=True)]}
    tg = FakeTG()
    assert warelay.relay_once(tg, conn, "-100", wa) == 0
    assert tg.sent == []
    assert store.wa_mark(conn, name)["ids"] == ["s1"]      # and it is not retried


def test_our_own_reply_in_a_direct_chat_is_not_relayed():
    conn = conn_now()
    wa = FakeWa([chat("Mary")], {"Mary": []})
    prime(conn, wa)
    wa._chats = [chat("Mary", preview="ok")]
    wa._threads = {"Mary": [msg("m1", "ok", mine=True)]}
    tg = FakeTG()
    assert warelay.relay_once(tg, conn, "-100", wa) == 0


def test_a_media_bubble_arrives_as_its_label():
    conn = conn_now()
    wa = FakeWa([chat("Mary")], {"Mary": []})
    prime(conn, wa)
    wa._chats = [chat("Mary", preview="φωτογραφία")]
    wa._threads = {"Mary": [msg("m1", "[φωτογραφία]", icons=["photo"])]}
    tg = FakeTG()
    assert warelay.relay_once(tg, conn, "-100", wa) == 1
    assert tg.sent[0][1] == "[φωτογραφία]"


def test_a_burst_is_cut_and_finished_next_cycle():
    conn = conn_now()
    wa = FakeWa([chat("Mary", preview="old")], {"Mary": []})
    prime(conn, wa)
    seed(conn, "Mary", ["m0"])
    wa._chats = [chat("Mary", preview="line 24")]
    wa._threads = {"Mary": [msg(f"m{i}", f"line {i}") for i in range(25)]}
    tg = FakeTG()
    assert warelay.relay_once(tg, conn, "-100", wa) == warelay.MAX_PER_CYCLE
    # The cut is where the relay stopped: the rest are still unseen.
    mark = store.wa_mark(conn, "Mary")["ids"]
    assert len(mark) == warelay.MAX_PER_CYCLE + 1        # + the one already known
    assert mark[-1] == f"m{warelay.MAX_PER_CYCLE}"
    assert warelay.relay_once(tg, conn, "-100", wa) == 4
    assert tg.sent[-1][1] == "line 24"


def test_a_stale_topic_is_forgotten_not_retried_forever():
    conn = conn_now()
    wa = FakeWa([chat("Mary")], {"Mary": []})
    prime(conn, wa)
    store.save_wa_thread(conn, "Mary", 55)
    wa._chats = [chat("Mary", preview="νέο")]
    wa._threads = {"Mary": [msg("m1", "νέο")]}
    tg = FakeTG(fail_threads=True)
    assert warelay.relay_once(tg, conn, "-100", wa) == 0
    assert store.wa_thread_id(conn, "Mary") == 0           # falsy: a new one next time
    assert tg.sent == []


def test_topics_are_created_once_and_reused():
    conn = conn_now()
    wa = FakeWa([chat("Mary")], {"Mary": [msg("m1", "α")]})
    prime(conn, wa)
    tg = FakeTG()
    wa._chats = [chat("Mary", preview="α")]
    warelay.relay_once(tg, conn, "-100", wa)
    wa._chats = [chat("Mary", preview="β")]
    wa._threads = {"Mary": [msg("m1", "α"), msg("m2", "β")]}
    warelay.relay_once(tg, conn, "-100", wa)
    assert tg.topics == ["Mary"]
    assert [t for t, _ in tg.sent] == [101, 101]


def test_a_chat_that_will_not_open_is_skipped_without_reading_it():
    conn = conn_now()
    wa = FakeWa([chat("Mary")], {"Mary": []})
    prime(conn, wa)
    wa._chats = [chat("Mary", preview="νέο")]
    wa._threads = {}                                     # open() returns False
    tg = FakeTG()
    assert warelay.relay_once(tg, conn, "-100", wa) == 0
    assert wa.messages_calls == 0
    assert store.wa_mark(conn, "Mary")["ids"] == []


def test_logged_out_is_an_exception_not_an_empty_inbox():
    conn = conn_now()
    with pytest.raises(warelay.NotLoggedIn):
        warelay.relay_once(FakeTG(), conn, "-100", FakeWa([], {}, logged_in=False))


def test_watch_only_opens_what_moved():
    chats = [chat("A", preview="x", unread="2"), chat("B", preview="y")]
    marks = {"A": {"preview": "x", "ts": "20:17", "unread": ""},
             "B": {"preview": "y", "ts": "20:17", "unread": ""}}
    assert [c["name"] for c in warelay.watch(chats, marks)] == ["A"]
    assert [c["name"] for c in warelay.watch(chats, {})] == ["A", "B"]


def test_fresh_takes_the_tail_only_on_a_first_read():
    rows = [msg("1", "a"), msg("2", "b"), msg("3", "c")]
    assert warelay.fresh(rows, set(), first=True) == [rows[-1]]
    assert warelay.fresh(rows, {"1", "2"}, first=False) == [rows[-1]]
    assert warelay.fresh(rows, {"1", "2", "3"}, first=False) == []


def test_hands_borrow_per_call_not_per_cycle():
    """A cycle of clicks must not hold the lock the Instagram sync needs."""
    class Syncer:
        def __init__(self):
            self.depth = self.borrowed = 0

        class _Ctx:
            def __init__(self, s):
                self.s = s

            def __enter__(self):
                self.s.depth += 1
                self.s.borrowed += 1
                return self.s.provider

            def __exit__(self, *a):
                self.s.depth -= 1
                return False

        def borrow(self):
            return Syncer._Ctx(self)

    class Provider:
        def wa_eval(self, js, arg=None):
            assert syncer.depth == 1
            return 1

    syncer = Syncer()
    syncer.provider = Provider()
    hands = warelay._Hands(syncer)
    assert hands.wa_eval("1") == 1
    assert syncer.depth == 0 and syncer.borrowed == 1
    with pytest.raises(AttributeError):
        hands.inbox()


def test_the_provider_without_a_whatsapp_page_says_so():
    class Syncer:
        class _Ctx:
            def __enter__(self):
                return object()

            def __exit__(self, *a):
                return False

        def borrow(self):
            return Syncer._Ctx()

    with pytest.raises(Exception) as exc:
        warelay._Hands(Syncer()).wa_eval("1")
    assert "WhatsApp" in str(exc.value)
