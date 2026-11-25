"""Greek is one table, and the table is `str.js`.

A string a screen writes for itself is a string nobody can fix in one place,
and v1 shipped English inside a Greek window. So: the deck lives in one file,
every key in it is used by a screen, and no other shipped file matches the
Greek block. Parameterised strings are asserted by their fixed fragment —
the deck pins the words, not the numbers.
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.test_api import make_config

GREEK = re.compile(r"[\u0370-\u03ff]")
# Two-space indented `key: ` is a table entry; nothing else in str.js is.
KEY = re.compile(r"^\s{2}(\w+): ", re.M)
USE = re.compile(r"STR\.(\w+)")

# Verbatim fragments of the copy deck. The ones with a value in them are cut at
# the fixed part: `φωτό` covers `φωτό 2 από 3`.
DECK = (
    "Περιήγηση",
    "Μηνύματα",
    "Τα νέα τελείωσαν.",
    "Παλαιότερα…",
    "Δεν υπάρχουν παλαιότερα αποθηκευμένα.",
    "φωτό",
    "Φορτώνω την ιστορία…",
    "ιστορ",
    "Η ιστορία δεν φόρτωσε.",
    "Η εικόνα δεν κατέβηκε.",
    "Το βίντεο δεν άνοιξε.",
    "Αναπαραγωγή",
    "Παύση",
    "Θέση βίντεο",
    "Ήχος κλειστός",
    "Ήχος ανοιχτός",
    "Αναγνώριση τραγουδιού",
    "Ακούω…",
    "Δεν το αναγνώρισα.",
    "Δεν μπόρεσα να την αναγνωρίσω.",
    "Πολλές προσπάθειες",
    "Αναζήτηση στο Spotify",
    "Αντιγραφή τίτλου",
    "Αντιγράφηκε",
    "Δεν φόρτωσε.",
    "Δοκιμή ξανά",
    "Δεν υπάρχει σύνδεση.",
    "Φορτώνω…",
    "Σύνδεση",
    "Κωδικός",
    "Λάθος κωδικός.",
    "Κανένα μήνυμα.",
    "Δεν φόρτωσαν τα μηνύματα.",
    "Πίσω",
    "Λείπει το token",
    "Αποστολή",
    "Γράψε ένα μήνυμα",
    "Στέλνω",
    "Το μήνυμα δεν στάλθηκε.",
    "Φορτώνω το ποστ…",
    "Το ποστ δεν φόρτωσε.",
    "ιστορία — δεν ανοίγει εδώ",
    "Άνοιγμα στην περιήγηση",
    "Άνοιγμα στο Instagram",
)

@pytest.fixture()
def client(tmp_path):
    return TestClient(create_app(make_config(tmp_path)))


def test_table_keys_are_unique(client):
    keys = KEY.findall(client.get("/static/str.js").text)
    assert len(keys) > 30, "the whole deck lives in one table"
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    assert not dupes, f"duplicate keys: {dupes}"


def test_deck_strings_are_present_verbatim(client):
    table = client.get("/static/str.js").text
    missing = [s for s in DECK if s not in table]
    assert not missing, f"not in str.js: {missing}"


def test_greek_never_leaves_the_table(client):
    for name in ("views.js", "app.js", "browse.js", "index.html"):
        text = client.get("/").text if name.endswith(".html") else client.get(f"/static/{name}").text
        words = GREEK.findall(text)
        assert not words, f"Greek in {name}: {words[:5]}"


def test_every_key_is_used_and_no_use_is_undefined(client):
    keys = set(KEY.findall(client.get("/static/str.js").text))
    used = set()
    for name in ("views.js", "browse.js", "app.js"):
        used |= set(USE.findall(client.get(f"/static/{name}").text))
    unknown = sorted(used - keys)
    assert not unknown, f"used but not in str.js: {unknown}"
    unused = sorted(keys - used)
    assert not unused, f"in str.js but no screen uses it: {unused}"
