"""The static UI contract: what is served, and what must never come back.

Two screens, no chrome: `#/browse` is the deck and `#/messages` is the inbox.
There is no window, no menu bar, no status bar and no bulletin, and this file is
what stops any of them from drifting back in. No browser here — these are the
cheap invariants, run in every CSS/JS commit because they pin literals in files
whose rename looks unrelated.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.test_api import make_config

# Router + seen + dates: the seams both screens plug into.
APP_KEPT = ("flushSeen", "markSeenLocally", "views.messages",
            'history.scrollRestoration = "manual"',
            'import("/static/browse.js")',
            "beginSession: views.beginSession",
            'document.documentElement.classList.add("mode-browse")')

# What the two screens are made of, by name. A rename here is a rename in the
# screen, which is the point of pinning code markers rather than copy.
VIEWS_KEPT = ("mutedPref", "rememberMute", "blankDeck", "beginSession",
              "/api/messages", "/api/messages/thread", "/api/messages/send",
              "/api/resolve", "data-chat", "data-resolve", "mthread",
              'class="msgs"', "login")

# The program *writes* one thing to Instagram: that a post or a story was seen.
# A link out is not a write, so a permalink is allowed; every control that used
# to send something is gone, and must stay gone.
NO_WRITES = ("/like", "/react", "/follow", "/unfollow")

CSS_MARKERS = ("min-height: 44px", "--face: #c0c0c0", ".browse",
               "html.mode-browse", ".bavatar", ".bwho", ".bmarks",
               ".bmark.is-on", ".bheard", ".bstage", ".inbox-row", ".transcript",
               ".msgs", ".mb.theirs", ".mb.mine", ".mcomposer", ".msend",
               ".login")

SHIPPED = ("app.js", "views.js", "browse.js", "str.js", "index.html", "style.css")

# Inline handlers, inline script and javascript: URLs all fail silently under
# CSP script-src 'self', so they are asserted absent rather than tested live.
DEAD_EVERYWHERE = ("onclick", "javascript:", "<script>")
# Vocabulary of the windowed program and of v1: chrome, a bulletin, a bulletin
# player, a tray, a dashboard.
DEAD_IN_CODE = ("#topbar", "#statusbar", "paintShell", "menubar", ".files",
                ".toast", ".ring", ".carousel", ".dots", "prefers-color-scheme",
                "data-car", "watchPlayback", "autoAdvance",
                'data-act="like"')


@pytest.fixture()
def client(tmp_path):
    return TestClient(create_app(make_config(tmp_path)))


def shipped(client, name):
    return client.get("/").text if name == "index.html" else client.get(f"/static/{name}").text


def test_index_is_public_and_uncached(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"
    html = r.text
    assert 'lang="el"' in html
    assert "/static/app.js" in html
    # No chrome to draw: the deck owns the glass and the inbox is a sheet.
    assert "topbar" not in html and "statusbar" not in html
    assert "menubar" not in html and "shell.js" not in html
    # CSP: an inline <style> or <script> is blocked, and fails silently.
    assert "<style" not in html
    assert "<script>" not in html


def test_the_old_frame_is_not_served(client):
    assert client.get("/static/shell.js").status_code == 404


def test_static_js_is_served_uncached(client):
    for name in ("app.js", "views.js", "browse.js", "str.js", "style.css"):
        r = client.get(f"/static/{name}")
        assert r.status_code == 200, name
        # No-cache means revalidate: a redeploy must not run stale JS.
        assert r.headers["cache-control"] == "no-cache", name


def test_static_assets_carry_their_contract(client):
    app_js = shipped(client, "app.js")
    missing = [m for m in APP_KEPT if m not in app_js]
    assert not missing, f"app.js is missing {missing}"

    views_js = shipped(client, "views.js")
    missing = [m for m in VIEWS_KEPT if m not in views_js]
    assert not missing, f"views.js is missing {missing}"

    css = shipped(client, "style.css")
    missing = [m for m in CSS_MARKERS if m not in css]
    assert not missing, f"style.css is missing {missing}"


def test_two_screens_and_a_login(client):
    """Three hashes, and nothing else: the deck, the inbox, the way in. An old
    `#/feed` bookmark lands on the deck rather than a screen that no longer
    exists, and the deck's module is still a lazy import."""
    app_js = shipped(client, "app.js")
    assert 'raw === "/messages"' in app_js, "the inbox is a route"
    assert 'raw !== "/browse"' in app_js, "everything else is the deck"
    assert 'raw === "/login"' in app_js, "the login screen is a route"
    assert 'import("/static/browse.js")' in app_js, \
        "a lazy import: a broken deck cannot take the inbox down"
    for gone in ("/feed", "/post/", "/stories", "/accounts", "/history",
                 "/sync", "/settings", "/help", "/about"):
        assert f'"{gone}"' not in app_js, f"{gone} is still a route"


def test_the_program_writes_only_seen(client):
    """One write to Instagram in the whole program: seen. A like, a reaction and
    a follow are absent from the code, not merely unlinked."""
    browse_js = shipped(client, "browse.js")
    views_js = shipped(client, "views.js")
    for path in NO_WRITES:
        assert path not in browse_js, path
        assert path not in views_js, path
    assert '/api/posts/seen' in shipped(client, "app.js"), \
        "a post is seen through the one bulk endpoint"
    assert '/api/stories/seen' in browse_js, \
        "a story segment is seen through its own endpoint"
    assert '/done' in browse_js, "leaving a story card finishes that account"
    # The card's way out to Instagram is a plain outbound link, not a write.
    assert 'rel="noopener"' in views_js, "the link out carries rel=noopener"
    assert '/api/messages/send' in views_js, \
        "the chat screen sends a message, and that is its only POST"


def test_no_dead_vocabulary(client):
    for name in SHIPPED:
        text = shipped(client, name)
        for word in DEAD_EVERYWHERE:
            assert word not in text, f"{word} in {name}"
    for name in SHIPPED:
        if name == "index.html":
            continue
        text = shipped(client, name)
        for word in DEAD_IN_CODE:
            assert word not in text, f"{word} in {name}"


def test_static_is_public_but_api_is_not(client):
    anon = TestClient(client.app)
    assert anon.get("/static/app.js").status_code == 200
    assert anon.get("/api/status").status_code == 401
