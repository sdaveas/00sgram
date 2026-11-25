"""The HTTP surface the two screens use: auth, the session handshake, the feed,
seen, stories, media, and the failures that must stay honest.

Everything runs against the mock provider and a temp dir. No network.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app import store
from app.config import Config
from app.dtos import AccountDTO, PostDTO, StoryDTO, TrayEntry
from app.main import create_app

NOW_ISH = 1_764_000_000


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


def seed_posts(app, posts=3, account="a1", kind=(1, "feed"), taken_at=None):
    conn = app.state.conn
    store.upsert_accounts(conn, [AccountDTO(pk=account, username=account,
                                            full_name=account)])
    run = store.start_run(conn, "manual")
    pks = []
    for i in range(posts):
        pk = f"{account}p{i}"
        store.upsert_post(conn, PostDTO(
            pk=pk, account_pk=account, media_type=kind[0], product_type=kind[1],
            taken_at=int(taken_at or NOW_ISH - i * 60), caption=f"c{i}"), run)
        pks.append(pk)
    store.finish_run(conn, run)
    return pks


def seed_ring(conn, pk="a1"):
    """An account with a live ring: a story endpoint needs someone to belong to."""
    store.upsert_accounts(conn, [AccountDTO(pk=pk, username=pk, full_name=pk)])
    store.upsert_ring(conn, TrayEntry(account_pk=pk, latest_reel_media=NOW_ISH,
                                      media_count=1, media_ids=["s1"]), NOW_ISH)


def open_session(client, **body):
    body.setdefault("mode", "unseen")
    body.setdefault("filters", {})
    return client.post("/api/sessions", json=body)


# -------------------------------------------------------------------- auth


def test_health_is_public_and_status_is_not(app):
    c = TestClient(app)
    assert c.get("/api/health").json() == {"ok": True}
    r = c.get("/api/status")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorised"


def test_login_rejects_wrong_password(app):
    assert TestClient(app).post("/login", json={"password": "nope"}).status_code == 401


def test_login_sets_both_cookies_and_grants_access(app, client):
    assert {"s", "device"} <= set(client.cookies.keys())
    assert client.get("/api/status").status_code == 200


def test_logout_clears_the_session_cookie(app, client):
    client.post("/logout")
    assert client.get("/api/status").status_code == 401


def test_token_auth_requires_the_device_header(app):
    c = TestClient(app)
    assert c.get("/api/status", headers={"X-API-Token": "tok"}).status_code == 401
    ok = c.get("/api/status", headers={"X-API-Token": "tok", "X-Device": "mcp"})
    assert ok.status_code == 200
    bad = c.get("/api/status", headers={"X-API-Token": "nope", "X-Device": "mcp"})
    assert bad.status_code == 401


def test_token_mode_resolves_session_for_its_device(app):
    c = TestClient(app)
    h = {"X-API-Token": "tok", "X-Device": "mcp"}
    seed_posts(app)
    r = c.post("/api/sessions", json={"mode": "unseen", "filters": {}}, headers=h)
    assert r.status_code == 200
    status = c.get("/api/status", headers=h).json()
    assert status["session"]["device"] == "mcp"


# ---------------------------------------------------------------- sessions


def test_missing_session_param_is_bad_request(client):
    r = client.get("/api/feed")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_request"


def test_session_conflict_then_take_over(client):
    seed_posts(client.app)
    first = open_session(client)
    assert first.status_code == 200
    conflict = open_session(client)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "session_conflict"
    assert conflict.json()["error"]["session"]["id"] == first.json()["session"]
    taken = open_session(client, take_over=first.json()["session"])
    assert taken.status_code == 200
    assert taken.json()["session"] != first.json()["session"]


def test_reservation_new_posts_do_not_enter_an_open_session(app, client):
    seed_posts(app, posts=2)
    r = open_session(client).json()
    assert r["item_count"] == 2

    conn = app.state.conn
    run = store.start_run(conn, "cycle")
    store.upsert_post(conn, PostDTO(pk="new", account_pk="a1", media_type=1,
                                    taken_at=NOW_ISH + 10), run)
    store.finish_run(conn, run)

    feed = client.get(f"/api/feed?session={r['session']}").json()
    assert {i["pk"] for i in feed["items"]} == {"a1p0", "a1p1"}
    status = client.get("/api/status").json()
    assert status["posts"]["new_since_start"] == 1


def test_a_post_carries_its_tags_place_and_song(client):
    """The same list a story gets from its stickers, read off the media dict."""
    conn = client.app.state.conn
    store.upsert_accounts(conn, [AccountDTO(pk="a1", username="a1")])
    run = store.start_run(conn, "manual")
    store.upsert_post(conn, PostDTO(
        pk="p1", account_pk="a1", media_type=1, taken_at=NOW_ISH,
        caption="me and @nobody",
        links=[{"kind": "profile", "label": "xara.gian",
                "url": "https://www.instagram.com/xara.gian/", "detail": "ΧΑΡΑ"},
               {"kind": "music", "label": "Theme", "url": None,
                "detail": "The Rembrandts"}]), run)
    store.finish_run(conn, run)
    s = open_session(client).json()
    item = client.get(f"/api/feed?session={s['session']}").json()["items"][0]
    assert [l["kind"] for l in item["links"]] == ["profile", "music"]
    assert item["links"][0]["url"] == "https://www.instagram.com/xara.gian/"


def test_a_post_without_links_reports_an_empty_list(client):
    conn = client.app.state.conn
    store.upsert_accounts(conn, [AccountDTO(pk="a1", username="a1")])
    run = store.start_run(conn, "manual")
    store.upsert_post(conn, PostDTO(pk="p1", account_pk="a1", media_type=1,
                                    taken_at=NOW_ISH), run)
    store.finish_run(conn, run)
    s = open_session(client).json()
    item = client.get(f"/api/feed?session={s['session']}").json()["items"][0]
    assert item["links"] == []


def test_story_segments_carry_their_stickers(client):
    conn = client.app.state.conn
    seed_ring(conn)
    store.upsert_story(conn, StoryDTO(
        pk="s1", account_pk="a1", media_type=1, taken_at=NOW_ISH,
        expiring_at=NOW_ISH + 3600,
        links=[{"kind": "music", "label": "Theme", "url": None,
                "detail": "The Rembrandts"}]))
    items = client.get("/api/stories/a1").json()["items"]
    assert items[0]["links"] == [{"kind": "music", "label": "Theme", "url": None,
                                  "detail": "The Rembrandts"}]


def test_a_story_without_stickers_reports_an_empty_list(client):
    conn = client.app.state.conn
    seed_ring(conn)
    store.upsert_story(conn, StoryDTO(pk="s1", account_pk="a1", media_type=1,
                                      taken_at=NOW_ISH, expiring_at=NOW_ISH + 3600))
    assert client.get("/api/stories/a1").json()["items"][0]["links"] == []


# ------------------------------------------------------------------- media


def test_media_is_an_honest_404_for_an_unknown_pk(client):
    r = client.get("/api/media/post/nope/0")
    assert r.status_code == 404
    assert r.headers["cache-control"] == "no-store"
    assert r.content == b""


def test_story_endpoints_work_on_an_empty_db(client):
    assert client.get("/api/browse/stories").json()["items"] == []
    assert client.get("/api/stories/nope").status_code == 404


# ------------------------------------------------------------------ status


def test_every_response_carries_the_hardening_headers(client):
    for path in ("/api/health", "/"):
        h = client.get(path).headers
        assert h["x-content-type-options"] == "nosniff"
        assert h["referrer-policy"] == "no-referrer"
        assert h["x-frame-options"] == "DENY"
        assert "default-src 'self'" in h["content-security-policy"]
        assert "frame-ancestors 'none'" in h["content-security-policy"]


# ------------------------------------------------------------- whatsapp qr


class FakeWaProvider:
    """A provider that can only screenshot — which is all the QR route needs."""

    def __init__(self, showing=True, path_written=True):
        self.showing, self.written = showing, path_written
        self.shots: list[str] = []

    def wa_eval(self, js, arg=None):
        return self.showing

    def wa_wait(self, ms):
        return None

    def wa_screenshot(self, path):
        self.shots.append(path)
        if self.written:
            from pathlib import Path
            Path(path).write_bytes(b"\x89PNG\r\n\x1a\n")

    def wa_page(self):
        return None


def test_the_qr_route_says_unsupported_for_a_provider_without_a_browser(app, client):
    """PROVIDER=mock has no page: a 400 with a reason beats a stack trace."""
    r = client.get("/api/wa/qr")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "unsupported"


def test_the_qr_route_returns_the_png_and_whether_a_code_is_showing(app, client):
    app.state.syncer._provider = FakeWaProvider(showing=True)
    r = client.get("/api/wa/qr")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.headers["x-wa-qr"] == "1"
    assert r.content.startswith(b"\x89PNG")

    app.state.syncer._provider = FakeWaProvider(showing=False)
    assert client.get("/api/wa/qr").headers["x-wa-qr"] == "0"
