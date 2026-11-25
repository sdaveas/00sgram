"""`wadirect`, against a fake browser.

The fake answers by script identity, so the tests pin behaviour — which
conversation gets opened, what a bubble becomes, whether a reaction is proven —
and not the shape of a JavaScript string.
"""
from __future__ import annotations

import threading

import pytest

from app import wadirect as wd


class FakeHands:
    def __init__(self, chats=None, messages=None, header=None, emoji_present=False):
        self._chats = chats or []
        self._messages = messages            # None: no panel open at all
        self.pending: list[dict] = []        # what Enter would add to the chat
        self._header = header
        self._emoji_present = emoji_present
        self.clicks: list[tuple[float, float]] = []
        self.moves: list[tuple[float, float]] = []
        self.typed: list[str] = []
        self.pressed: list[str] = []
        self.shots: list[str] = []
        self.header_after: list[str] = []      # what _header returns, step by step

    # ---------------------------------------------------------------- hands
    def wa_eval(self, js, arg=None):
        if js is wd._MESSAGES and self._messages is None:
            return None
        if js is wd._CHATS:
            return self._chats
        if js is wd._HEADER:
            return self.header_after.pop(0) if self.header_after else self._header
        if js is wd._MESSAGES:
            return self._messages
        if js is wd._COMPOSER:
            return {"x": 10, "y": 20}
        if js is wd._BUBBLE:
            return {"x": 30, "y": 40, "w": 100, "h": 20}
        if js is wd._ENTRY:
            return {"x": 50, "y": 25}
        if js is wd._BAR:
            return {"x": 60, "y": 25} if arg in wd.SIX else None
        if js is wd._PILL:
            return "❤️"
        if js is wd._HAS:
            return self._emoji_present
        if js is wd._QR:
            return True
        return None

    def wa_click(self, x, y):
        self.clicks.append((x, y))

    def wa_move(self, x, y):
        self.moves.append((x, y))

    def wa_type(self, text):
        self.typed.append(text)

    def wa_press(self, key):
        self.pressed.append(key)
        if key == "Enter" and self.pending:
            self._messages = list(self._messages or []) + self.pending
            self.pending = []

    def wa_wait(self, ms):
        pass

    def wa_screenshot(self, path):
        self.shots.append(path)


def chat(name, preview="", ts="20:17", unread="", self=False, y=100):
    return {"name": name, "preview": preview, "ts": ts, "unread": unread,
            "self": self, "x": 100, "y": y, "top": y - 30, "bottom": y + 30}


def test_fold_is_the_key_because_there_is_no_chat_id():
    assert wd.key("+30 697\n(You)") == "+30 697 (You)"
    assert wd.key("  Νεφέλη   ") == "Νεφέλη"
    assert wd.bare("+30 697 (You)") == "+30 697"


def test_two_rows_with_one_name_are_refused_not_guessed():
    """The name is the state key, so two chats sharing one cannot have separate
    marks. The preview cannot fix that: skip the name entirely."""
    hands = FakeHands(chats=[chat("Μαμά", "πάρε με"), chat("Μαμά", "τι κάνεις")])
    assert wd.Wa(hands).find("Μαμά", "τι κάνεις") is None


def test_open_proves_the_chat_by_its_own_header():
    hands = FakeHands(chats=[chat("Μαμά")], header="Μαμά")
    assert wd.Wa(hands).open("Μαμά") is True
    assert hands.clicks == [(100, 100)]


def test_open_refuses_a_chat_that_did_not_open():
    """A click that lands on the wrong row is a read receipt on a stranger and a
    message in the wrong topic. Two attempts, then no."""
    hands = FakeHands(chats=[chat("Μαμά")], header="Κάποιος Άλλος")
    assert wd.Wa(hands).open("Μαμά") is False
    assert len(hands.clicks) == 2


def test_messages_take_direction_from_you_and_fall_back_to_the_tail_icon():
    rows = [{"id": "a", "text": "γεια", "mine": True, "sender": "", "icons": []},
            {"id": "b", "text": "τι κάνεις", "mine": False, "sender": "Γιώργος",
             "icons": []},
            {"id": "c", "text": "", "mine": False, "sender": "", "icons": ["tail-in"]},
            {"id": "d", "text": "", "mine": False, "sender": "", "icons": ["photo"]}]
    got = wd.Wa(FakeHands(messages=rows)).messages()
    assert [m["id"] for m in got] == ["a", "b", "c", "d"]
    assert got[0]["mine"] is True and got[1]["mine"] is False
    assert got[1]["sender"] == "Γιώργος"
    assert got[2]["text"] == "[μέσο]" and got[3]["text"] == "[φωτογραφία]"


def test_no_panel_is_not_an_empty_chat():
    assert wd.Wa(FakeHands(messages=None)).messages() is None


def test_labels_cover_what_we_said_we_would():
    assert wd.label_for(["audio-play"]) == "[φωνητικό]"
    assert wd.label_for(["sticker"]) == "[sticker]"
    assert wd.label_for(["weird-new-icon"]) == "[μέσο]"


def test_send_proves_itself_by_the_new_id():
    hands = FakeHands(chats=[chat("Μαμά")], header="Μαμά",
                      messages=[{"id": "a", "text": "x", "mine": True,
                                 "sender": "", "icons": []}])
    wa = wd.Wa(hands)
    assert wa.send("Μαμά", "  γεια   σου ") == ""      # the id did not change
    hands.pending = [{"id": "b", "text": "γεια σου", "mine": True,
                      "sender": "", "icons": []}]
    assert wa.send("Μαμά", "γεια\nσου") == "b"         # one line, and proven
    assert hands.typed == ["γεια σου", "γεια σου"]
    assert hands.pressed == ["Enter", "Enter"]


def test_send_refuses_an_empty_message():
    assert wd.Wa(FakeHands(chats=[chat("Μαμά")], header="Μαμά")).send("Μαμά", "   ") == ""


def test_react_clicking_the_matching_tile_is_the_whole_feature():
    hands = FakeHands(chats=[chat("Μαμά")], header="Μαμά", emoji_present=True)
    assert wd.Wa(hands).react("Μαμά", "a", "❤️") is True
    assert hands.moves == [(30, 40)]                  # hovered the bubble
    assert hands.clicks[1] == (50, 25)                # the entry point
    assert hands.clicks[2] == (60, 25)                # the emoji tile


def test_react_unproven_is_a_failure_not_a_shrug():
    hands = FakeHands(chats=[chat("Μαμά")], header="Μαμά", emoji_present=False)
    assert wd.Wa(hands).react("Μαμά", "a", "❤️") is False


def test_react_refuses_an_emoji_it_cannot_click():
    with pytest.raises(ValueError):
        wd.Wa(FakeHands()).react("Μαμά", "a", "🔥")


def test_removing_a_reaction_clicks_the_emoji_already_there():
    hands = FakeHands(chats=[chat("Μαμά")], header="Μαμά", emoji_present=False)
    assert wd.Wa(hands).react("Μαμά", "a", "") is True   # the pill said ❤️
    assert hands.clicks[-1] == (60, 25)


def test_removing_a_reaction_that_did_not_go_is_a_failure():
    hands = FakeHands(chats=[chat("Μαμά")], header="Μαμά", emoji_present=True)
    assert wd.Wa(hands).react("Μαμά", "a", "") is False


def test_qr_writes_a_file_and_says_whether_a_code_is_showing():
    hands = FakeHands()
    assert wd.Wa(hands).qr("/tmp/wa-qr.png") is True
    assert hands.shots == ["/tmp/wa-qr.png"]


def test_a_whole_send_holds_one_lock():
    """`open` -> type -> verify is one operation. Another daemon's `open` in the
    middle would make `before` and `after` two different conversations, and its
    newest id would be recorded as ours."""
    hands = FakeHands(chats=[chat("Μαμά")], header="Μαμά",
                      messages=[{"id": "a", "text": "x", "mine": True,
                                 "sender": "", "icons": []}])
    hands.wa_lock = threading.RLock()

    def press(key):
        assert hands.wa_lock._is_owned()          # the lock covers the typing
        FakeHands.wa_press(hands, key)

    hands.wa_press = press
    hands.pending = [{"id": "b", "text": "y", "mine": True, "sender": "", "icons": []}]
    assert wd.Wa(hands).send("Μαμά", "y") == "b"
    assert not hands.wa_lock._is_owned()          # and is released afterwards


def test_the_heart_from_telegram_is_the_heart_whatsapp_shows():
    """Telegram sends U+2764; the quick bar's image is U+2764 U+FE0F."""
    hands = FakeHands(chats=[chat("Μαμά")], header="Μαμά", emoji_present=True)
    hands_map = dict(wd.ALIAS)
    assert hands_map["❤"] == "❤️"
    assert wd.Wa(hands).react("Μαμά", "a", " ❤ ") is True
