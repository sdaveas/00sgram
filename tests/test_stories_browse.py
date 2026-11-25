"""The browse deck's story cards: one entry per unseen ring, from SQLite only."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app import store
from app.config import Config
from app.dtos import AccountDTO, StoryDTO, TrayEntry
from app.main import create_app

NOW = int(time.time()) - 60   # the list asks what is still live


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


def seed_ring(app, pk="a1", *, latest=NOW, ids=("s1", "s2"), muted=False):
    conn = app.state.conn
    store.upsert_accounts(conn, [AccountDTO(pk=pk, username=pk)])
    if muted:
        conn.execute("UPDATE accounts SET muted=1 WHERE pk=?", (pk,))
        conn.commit()
    store.upsert_ring(conn, TrayEntry(account_pk=pk, latest_reel_media=latest,
                                      media_count=len(ids), media_ids=list(ids)),
                      latest)


def seed_story(app, pk, account="a1", media_type=1, expiring=NOW + 3600):
    store.upsert_story(app.state.conn, StoryDTO(
        pk=pk, account_pk=account, media_type=media_type, taken_at=NOW,
        expiring_at=expiring, src_url="https://cdn/x.jpg"))


def test_a_stored_segment_becomes_one_picture(client, app):
    seed_ring(app, ids=("s1",))
    seed_story(app, "s1", media_type=2)
    body = client.get("/api/browse/stories").json()
    assert len(body["items"]) == 1
    card = body["items"][0]
    assert card["pending"] is False and card["count"] == 1
    assert card["resources"] == [{
        "pk": "s1", "idx": 0, "type": "video", "duration": None,
        "taken_at": NOW, "links": [],
        "full": "/api/media/story/s1", "thumb": "/api/media/story/s1?thumb=1"}]


def test_each_segment_carries_its_own_time(client, app):
    """The card's `when` is the newest segment; the glass may show an older one,
    and its stamp must be its own."""
    seed_ring(app, ids=("s1", "s2"), latest=NOW + 300)
    seed_story(app, "s1")
    store.upsert_story(app.state.conn, StoryDTO(
        pk="s2", account_pk="a1", media_type=1, taken_at=NOW + 300,
        expiring_at=NOW + 3600, src_url="https://cdn/y.jpg"))
    card = client.get("/api/browse/stories").json()["items"][0]
    assert [r["taken_at"] for r in card["resources"]] == [NOW, NOW + 300]
    assert card["when"] != card["resources"][0]["taken_at"]


def test_an_unstored_ring_is_pending_and_still_counts(app, client):
    seed_ring(app, ids=("s1", "s2", "s3"))
    card = client.get("/api/browse/stories").json()["items"][0]
    assert card["pending"] is True and card["count"] == 3
    assert card["resources"] == []
    # Pending still names the account, so the card has something to show.
    assert card["account"]["username"] == "a1"


def test_leaving_a_card_does_not_hide_a_segment_nobody_watched(app, client):
    """`done` is a timestamp, not an observation: swiping past a card used to
    mark the account finished, and its unwatched segments were hidden for ever
    while Instagram kept showing them."""
    seed_ring(app)
    seed_story(app, "s1")
    store.set_local_done(app.state.conn, "a1")
    body = client.get("/api/browse/stories").json()
    assert len(body["items"]) == 1
    assert [r["pk"] for r in body["items"][0]["resources"]] == ["s1"]


def test_a_ring_with_no_live_segment_and_a_done_mark_is_not_a_card(app, client):
    seed_ring(app, ids=())
    store.set_local_done(app.state.conn, "a1")
    assert client.get("/api/browse/stories").json()["items"] == []


def test_a_seen_segment_is_still_a_picture(app, client):
    """A fetched ring has often been watched already; `seen` is not "no bytes".

    Filtering resources by `seen_at` is what reported `pending: true` for a ring
    whose pictures were in the store, and the card then retried forever.
    """
    seed_ring(app, ids=("s1", "s2"))
    seed_story(app, "s1")
    seed_story(app, "s2")
    store.mark_story_seen(app.state.conn, ["s2"], None)
    card = client.get("/api/browse/stories").json()["items"][0]
    assert card["pending"] is False
    assert [r["pk"] for r in card["resources"]] == ["s1", "s2"]


def test_a_ring_with_only_seen_segments_is_not_a_card(app, client):
    """Every live segment seen and the account not finished: nothing to show."""
    seed_ring(app, ids=("s1",))
    seed_story(app, "s1")
    store.mark_story_seen(app.state.conn, ["s1"], None)
    assert client.get("/api/browse/stories").json()["items"] == []


def test_a_muted_account_is_not_a_card(app, client):
    seed_ring(app, muted=True)
    assert client.get("/api/browse/stories").json()["items"] == []


def test_an_expired_segment_is_not_a_picture(app, client):
    seed_ring(app, ids=("s1", "s2"))
    seed_story(app, "s1", expiring=NOW - 1)
    seed_story(app, "s2")
    card = client.get("/api/browse/stories").json()["items"][0]
    assert [r["pk"] for r in card["resources"]] == ["s2"]


def test_a_seen_segment_that_has_expired_is_not_a_picture(app, client):
    """A story watched on the 18th has no bytes now. It used to come back as
    "viewed" and land an eighteen-day-old segment on the deck."""
    seed_ring(app, ids=("s1", "s2"))
    seed_story(app, "s1", expiring=NOW - 1)
    seed_story(app, "s2")
    store.mark_story_seen(app.state.conn, ["s1"], None)
    body = client.get("/api/stories/a1").json()
    assert [i["state"] for i in body["items"]] == ["expired", "available"]
    assert body["items"][0]["src"] is None


def test_the_list_never_touches_instagram(app, client):
    seed_ring(app)

    def boom(*_a, **_k):
        raise AssertionError("the story list must not call the provider")

    provider = app.state.syncer.provider
    provider.story_tray = boom
    provider.user_stories = boom
    assert len(client.get("/api/browse/stories").json()["items"]) == 1
