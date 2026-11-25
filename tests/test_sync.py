"""Step 6: the real ingestion path, offline.

No network and no credentials. The provider is a fake that speaks the Protocol;
the timeline mapping is tested from a JSON fixture that mirrors a measured
`www.instagram.com/api/v1/feed/timeline/` response.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import store
from app.config import Config
from app.dtos import AccountDTO, Page, PostDTO, ResourceDTO, TrayEntry
from app.main import create_app
from app.sync import Syncer

ROOT = Path(__file__).resolve().parent.parent

FIXTURES = Path(__file__).parent / "fixtures"
NOW = 1_764_000_000
IMG = "https://scontent.cdninstagram.com/v/x.jpg"


def make_config(tmp_path, **over):
    env = {"DATA_DIR": str(tmp_path / "data"), "PROVIDER": "mock",
           "API_TOKEN": "tok", "APP_PASSWORD": "pw", "APP_SECRET": "s" * 32,
           "BACKFILL_SLEEP": "0"}
    env.update(over)
    return Config.from_env(env)


def post(pk, account, taken=NOW, media_type=1, product_type="feed"):
    return PostDTO(pk=pk, account_pk=account, media_type=media_type,
                   product_type=product_type, taken_at=taken,
                   resources=[ResourceDTO(idx=0, type="image", src_url=IMG)])


class FakeProvider:
    """Cursor -> Page. Records calls, so a loop is visible in `calls`."""

    def __init__(self, pages, accounts, tray=(), complete=True, sweep=None):
        self.pages = pages
        self.accounts = list(accounts)
        self.tray = list(tray)
        self.complete = complete
        self.sweep = sweep or {}
        self.calls: list[str | None] = []
        self.connected = False
        self.fetched: list[str] = []

    def connect(self):
        self.connected = True

    def following(self):
        return list(self.accounts), self.complete

    def timeline_page(self, max_id):
        self.calls.append(max_id)
        page = self.pages[max_id or "start"]
        return page() if callable(page) else page

    def user_recent(self, account_pk, limit):
        return list(self.sweep.get(account_pk, []))

    def story_tray(self):
        return list(self.tray)

    def user_stories(self, account_pk):
        self.fetched.append(account_pk)
        return []

    def media_stream(self, url, byte_range=None):
        return iter([b"x"])


@pytest.fixture()
def db(tmp_path):
    cfg = make_config(tmp_path)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    conn = store.connect(store.db_path(cfg.data_dir))
    store.init(conn, cfg)
    return cfg, conn


def accounts(*pks):
    return [AccountDTO(pk=pk, username=f"u{pk}") for pk in pks]


# ------------------------------------------------------------------ mapping


def test_timeline_fixture_parses_into_dtos_kinds_and_cursor():
    from app.instagram import parse_timeline

    payload = json.loads((FIXTURES / "timeline_page1.json").read_text())
    page = parse_timeline(payload)

    assert [p.pk for p in page.items] == ["502", "503", "504"]
    assert [p.kind for p in page.items] == ["carousel", "reel", "photo"]
    assert [p.account_pk for p in page.items] == ["1001", "1002", "1003"]
    assert page.next_max_id == "QVFEcGFnZT" and page.more_available is True
    carousel = page.items[0]
    assert [r.type for r in carousel.resources] == ["image", "video"]
    assert carousel.resources[1].poster_url.endswith("c2.jpg")
    assert carousel.caption == "two frames"
    assert page.items[1].resources[0].type == "video"
    # An ad and a paid-partnership post are dropped even before the allowlist.
    assert "501" not in [p.pk for p in page.items]
    assert "505" not in [p.pk for p in page.items]


def test_post_links_come_off_the_media_dict():
    """What the author attached, not what the caption says.

    Instagram gives tags, collabs, a place and a song as structures; a mention
    typed into a caption is only text, and the page links it, not this.
    """
    from app.instagram import post_from_media

    media = {
        "pk": "9", "media_type": 1, "code": "abc", "taken_at": 100,
        "user": {"pk": "u1", "username": "u1"},
        "caption": {"text": "thanks @someone #tag"},
        "usertags": {"in": [{"user": {"username": "tagged", "full_name": "Tagged"}},
                            {"user": {"username": "tagged"}}]},
        "coauthor_producers": [{"username": "collab"}],
        "location": {"pk": "77", "name": "Exarchia", "address": "Athens"},
        "clips_metadata": {"music_info": {"music_asset_info": {
            "title": "Little Moon", "display_artist": "Gone Gone Beyond"}}},
    }
    post = post_from_media(media)
    links = {(l["kind"], l["label"]) for l in post.links}
    assert links == {("profile", "tagged"), ("profile", "collab"),
                     ("place", "Exarchia"), ("music", "Little Moon")}
    # A duplicate tag on the same picture is one link, and a caption mention is
    # not one of these at all.
    assert len(post.links) == 4
    assert all(l["label"] not in ("@someone", "#tag") for l in post.links)
    urls = [l["url"] for l in post.links if l["kind"] == "profile"]
    assert urls == ["https://www.instagram.com/tagged/",
                    "https://www.instagram.com/collab/"]
    place = next(l for l in post.links if l["kind"] == "place")
    music = next(l for l in post.links if l["kind"] == "music")
    assert place["url"] == "https://www.instagram.com/explore/locations/77/"
    assert music["detail"] == "Gone Gone Beyond" and music["url"] is None


def test_a_post_with_no_tags_has_an_empty_list():
    from app.instagram import post_from_media

    post = post_from_media({"pk": "8", "media_type": 1, "taken_at": 1,
                            "user": {"pk": "u1"}})
    assert post.links == []


# --------------------------------------------------------------- stop rules


def test_cycle_stops_at_three_already_stored_and_second_cycle_adds_none(db):
    cfg, conn = db
    pages = {"start": Page([post("p1", "a1"), post("p2", "a1"), post("p3", "a1")],
                           next_max_id="c1", more_available=True),
             "c1": Page([post("p4", "a1")])}
    provider = FakeProvider(pages, accounts("a1"))
    syncer = Syncer(cfg, conn, provider=provider)

    first = syncer.run("cycle")
    assert (first["added"], first["pages"], first["follows"]) == (4, 2, 1)
    assert first["stopped"] == "end_of_feed"

    provider.calls.clear()
    second = syncer.run("cycle")
    assert second["added"] == 0
    assert second["pages"] == 1
    assert second["stopped"] == "already_stored"
    assert provider.calls == [None]


def test_repeated_next_max_id_does_not_loop(db):
    """Phase 0 measured a constant `next_max_id`; the cycle must end on it."""
    cfg, conn = db
    counter = {"n": 0}

    def page():
        counter["n"] += 1
        return Page([post(f"r{counter['n']}", "a1")],
                    next_max_id="same", more_available=True)

    provider = FakeProvider({"start": page, "same": page}, accounts("a1"))
    result = Syncer(cfg, conn, provider=provider).run("cycle")
    assert result["stopped"] == "repeated_cursor"
    assert result["pages"] == 2
    assert len(provider.calls) == 2


# ---------------------------------------------------------------- allowlist


def test_unfollowed_author_is_dropped_and_no_orphan_is_stored(db):
    cfg, conn = db
    pages = {"start": Page([post("ok1", "a1"), post("bad", "9999")])}
    provider = FakeProvider(pages, accounts("a1"))
    result = Syncer(cfg, conn, provider=provider).run("cycle")

    assert result["added"] == 1 and result["dropped"] == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM posts").fetchone()["n"] == 1
    orphans = conn.execute(
        "SELECT COUNT(*) AS n FROM posts p LEFT JOIN accounts a ON a.pk=p.account_pk"
        " WHERE a.pk IS NULL").fetchone()["n"]
    assert orphans == 0


def test_tray_is_filtered_through_the_allowlist(db):
    cfg, conn = db
    tray = [TrayEntry(account_pk="a1", username="u1", latest_reel_media=NOW,
                      media_count=2),
            TrayEntry(account_pk="9999", username="stranger", latest_reel_media=NOW)]
    provider = FakeProvider({"start": Page([])}, accounts("a1"), tray=tray)
    Syncer(cfg, conn, provider=provider).run("cycle")
    assert [r["account_pk"] for r in conn.execute("SELECT account_pk FROM story_rings")] \
        == ["a1"]
    assert conn.execute("SELECT story_item_count FROM accounts WHERE pk='a1'"
                        ).fetchone()[0] == 2


def test_backfill_walks_past_what_is_already_stored(db):
    """A cycle stops at the first already-stored page; backfill must not."""
    cfg, conn = db
    store.upsert_accounts(conn, accounts("a1"))
    existing = post("old", "a1")
    run = store.start_run(conn, "manual")
    store.upsert_post(conn, existing, run)
    store.finish_run(conn, run)

    buried = post("buried", "a1")
    provider = FakeProvider({"start": Page([existing], "p1", True),
                             "p1": Page([buried], None, False)}, accounts("a1"))
    result = Syncer(cfg, conn, provider=provider).run("backfill")
    assert result["stopped"] == "end_of_feed"
    assert result["pages"] == 2 and result["added"] == 1
    assert store.post_by_pk(conn, "buried") is not None
    # The weekly gate reads this, so a backfill that worked has to stamp it.
    assert store.meta_json(conn, "sync_state")["last_backfill_at"] > 0


def test_backfill_week_gate_runs_once_a_week_and_retries_a_failed_one(db):
    from app.sync import BACKFILL_EVERY, next_kind
    now = 1_800_000_000
    assert next_kind({}, now) == "backfill"                    # never run
    assert next_kind({"last_backfill_at": now - 60}, now) == "cycle"
    assert next_kind({"last_backfill_at": now - BACKFILL_EVERY - 1}, now) == "backfill"
    # An install that only ever had the old sweep key must not look backfilled.
    assert next_kind({"last_sweep_at": now - 60}, now) == "cycle"
    # A human pause silences everything, whatever the schedule says.
    assert next_kind({"paused": True}, now) is None
    assert next_kind({"paused": True, "last_backfill_at": 0}, now) is None


def test_a_failed_backfill_does_not_count_as_done_and_is_retried(db):
    cfg, conn = db
    store.upsert_accounts(conn, accounts("a1"))

    from app.provider import ProviderError

    class Broken(FakeProvider):
        def connect(self):
            raise ProviderError("session dead")

    result = Syncer(cfg, conn, provider=Broken({"start": Page([])}, accounts("a1"))
                    ).run("backfill")
    assert result["stopped"] == "error"
    assert not (store.meta_json(conn, "sync_state") or {}).get("last_backfill_at")


# -------------------------------------------------------------- follow graph


def test_incomplete_following_list_never_unfollows_the_tail(db):
    cfg, conn = db
    store.upsert_accounts(conn, accounts("a1", "a2", "a3", "a4"))
    provider = FakeProvider({"start": Page([])}, accounts("a1"))
    provider.complete = False
    result = Syncer(cfg, conn, provider=provider).run("cycle")

    assert result["follows"] == 0
    assert result["warning"] == "follow_refresh_incomplete"
    assert conn.execute("SELECT COUNT(*) AS n FROM accounts WHERE is_following=1"
                        ).fetchone()["n"] == 4


def test_real_following_pagination_only_reports_complete_when_it_finished(tmp_path):
    from app.instagram import InstagrapiProvider

    cfg = make_config(tmp_path, PROVIDER="instagrapi", IG_SESSION_COOKIE="sessionid=x")
    provider = InstagrapiProvider(cfg)
    provider._client = type("C", (), {"user_id": "42"})()

    provider._web_get = lambda url, params=None: {
        "users": [{"pk": "1", "username": "one"}], "more_available": True,
        "next_max_id": "next"}
    partial, complete = provider.following()
    assert [a.pk for a in partial] == ["1"] and complete is False

    provider._web_get = lambda url, params=None: {
        "users": [{"pk": "1", "username": "one"}, {"pk": "2", "username": "two"}],
        "more_available": False}
    whole, complete = provider.following()
    assert [a.pk for a in whole] == ["1", "2"] and complete is True


# ------------------------------------------------------------- run lifecycle


def test_crashed_run_is_recovered_and_its_posts_stay_out_of_a_session(db):
    cfg, conn = db
    store.upsert_accounts(conn, accounts("a1"))
    crashed = store.start_run(conn, "cycle", now=NOW - 3600)
    store.upsert_post(conn, post("partial", "a1"), crashed)   # killed mid-page

    # The session opens against the last closed, non-recovered run.
    session = store.open_session(conn, "dev", "all", {})
    assert store.latest_finished_run(conn) == 0
    assert store.session_counts(conn, session)["item_count"] == 0

    provider = FakeProvider({"start": Page([post("fresh", "a1")])}, accounts("a1"))
    Syncer(cfg, conn, provider=provider).run("cycle")

    row = conn.execute("SELECT * FROM sync_runs WHERE id=?", (crashed,)).fetchone()
    assert row["recovered"] == 1 and row["finished_at"] is not None
    # The old session still cannot see the partial post, and neither new one leaks it.
    assert store.session_counts(conn, session)["item_count"] == 0
    rows, _ = store.feed_page(conn, session)
    assert [r["pk"] for r in rows] == []


def test_provider_failure_still_closes_the_run(db):
    cfg, conn = db

    class Boom(FakeProvider):
        def timeline_page(self, max_id):
            from app.provider import ProviderError

            raise ProviderError("upstream down")

    result = Syncer(cfg, conn, provider=Boom({"start": Page([])}, accounts("a1"))
                    ).run("cycle")
    assert result["stopped"] == "error"
    row = conn.execute("SELECT * FROM sync_runs WHERE id=?",
                       (result["run_id"],)).fetchone()
    assert row["finished_at"] is not None and "upstream down" in row["error"]


# ------------------------------------------------------------------- backoff


def test_backoff_sets_and_then_clears_frozen_until(db):
    cfg, conn = db

    class Boom(FakeProvider):
        def connect(self):
            from app.provider import SessionExpired

            raise SessionExpired("Instagram session expired")

    bad = Syncer(cfg, conn, provider=Boom({"start": Page([])}, accounts("a1")))
    result = bad.run("cycle")
    assert result["stopped"] == "session_expired"
    state = store.meta_json(conn, "sync_state", {})
    assert state["frozen_until"] > int(time.time())
    assert state["streak"] == 1
    assert "session expired" in state["error"].lower()

    good = Syncer(cfg, conn, provider=FakeProvider(
        {"start": Page([post("p1", "a1")])}, accounts("a1")))
    good.run("cycle")
    state = store.meta_json(conn, "sync_state", {})
    assert state["frozen_until"] is None
    assert state["streak"] == 0
    assert state["error"] is None


def test_recovered_run_never_counts_as_a_completed_sync(db):
    cfg, conn = db
    store.start_run(conn, "cycle", now=NOW)
    before = store.latest_finished_run(conn)
    store.close_orphaned_runs(conn)
    assert store.latest_finished_run(conn) == before


# -------------------------------------------------------------- media stream


def test_media_stream_refuses_a_non_allowlisted_host_before_any_request():
    from app.instagram import InstagrapiProvider
    from app.provider import ProviderError

    cfg = Config.from_env({"DATA_DIR": "/tmp/none", "PROVIDER": "instagrapi", "BACKFILL_SLEEP": "0",
                           "API_TOKEN": "t", "APP_PASSWORD": "p",
                           "APP_SECRET": "s" * 32})
    provider = InstagrapiProvider(cfg)

    def boom():
        raise AssertionError("a request was made")

    provider._http = boom
    with pytest.raises(ProviderError, match="not allowed"):
        provider.media_stream("https://evil.example/x.jpg", None)


def test_media_stream_raises_session_expired_on_401_and_honours_range():
    from app.instagram import InstagrapiProvider
    from app.provider import SessionExpired

    cfg = Config.from_env({"DATA_DIR": "/tmp/none", "PROVIDER": "instagrapi", "BACKFILL_SLEEP": "0",
                           "IG_SESSION_COOKIE": "sessionid=abc", "API_TOKEN": "t",
                           "APP_PASSWORD": "p", "APP_SECRET": "s" * 32})
    provider = InstagrapiProvider(cfg)
    seen = {}
    assert provider._cookies()["sessionid"] == "abc"

    def handler(request):
        seen["range"] = request.headers.get("range")
        return httpx.Response(401)

    provider._http = lambda: httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(SessionExpired, match="paste a new cookie"):
        list(provider.media_stream(
            "https://scontent-fra3-1.cdninstagram.com/v/x.jpg", "bytes=0-1"))
    assert seen["range"] == "bytes=0-1"


def test_user_stories_converts_instagrapi_datetimes_to_epoch_seconds(tmp_path):
    """instagrapi returns datetimes where the web API returns ints. Story rows
    reached dev_seed only through the mock provider, so the real conversion was
    never exercised: the first real account opened in the viewer spun forever."""
    from datetime import datetime, timezone

    from app.instagram import InstagrapiProvider

    cfg = make_config(tmp_path, PROVIDER="instagrapi")
    provider = InstagrapiProvider(cfg)
    provider.connect = lambda: None

    class Story:                       # shaped like instagrapi's Story.dict()
        def dict(self):
            return {"pk": "s1", "media_type": 2,
                    "taken_at": datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc),
                    "expiring_at": datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc),
                    "user": {"pk": 42}, "video_url": "https://x/v.mp4",
                    "thumbnail_url": "https://x/t.jpg"}

    provider._client = type("C", (), {"user_stories": staticmethod(lambda pk: [Story()])})()
    [story] = provider.user_stories("42")
    assert story.taken_at == 1794830400
    assert story.expiring_at == story.taken_at + 86400
    assert story.account_pk == "42"
    assert story.src_url == "https://x/v.mp4"
    assert story.thumb_url == "https://x/t.jpg"
    assert isinstance(story.src_url, str)   # HttpUrl would not bind in SQLite


def test_connect_without_a_cookie_fails_with_a_clear_message(tmp_path):
    from app.instagram import InstagrapiProvider
    from app.provider import SessionExpired

    cfg = make_config(tmp_path, PROVIDER="instagrapi")
    provider = InstagrapiProvider(cfg)
    with pytest.raises(SessionExpired, match="paste one in Settings"):
        provider.connect()


# -------------------------------------------------------------------- cookie
def test_the_session_cookie_is_not_a_setting(tmp_path):
    """A cookie is a secret, not a screen value. It lives in `meta`, so the
    settings the two screens read can never leak it back."""
    from app.instagram import COOKIE_META, resolve_cookie

    cfg = make_config(tmp_path, PROVIDER="instagrapi")
    app = create_app(cfg)
    client = TestClient(app)
    assert client.post("/login", json={"password": "pw"}).status_code == 200
    secret = "sess-9f8e7d6c5b4a"
    store.set_meta_json(app.state.conn, COOKIE_META, secret)
    assert resolve_cookie(app.state.conn, cfg) == secret
    for path in ("/api/settings", "/api/status"):
        assert secret not in client.get(path).text, path

def test_cookie_resolution_prefers_the_db_over_env(tmp_path):
    from app.instagram import resolve_cookie

    cfg = make_config(tmp_path, PROVIDER="instagrapi", IG_SESSION_COOKIE="from-env")
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    conn = store.connect(store.db_path(cfg.data_dir))
    store.init(conn, cfg)
    assert resolve_cookie(conn, cfg) == "from-env"
    store.set_meta_json(conn, "ig_session_cookie", "from-db")
    assert resolve_cookie(conn, cfg) == "from-db"


def test_story_fetch_endpoint_uses_the_provider_instead_of_the_stub(tmp_path):
    cfg = make_config(tmp_path)
    app = create_app(cfg)
    conn = app.state.conn
    store.upsert_accounts(conn, accounts("a1"))
    store.upsert_ring(conn, TrayEntry(account_pk="a1", username="u1",
                                      latest_reel_media=NOW, media_count=1))
    client = TestClient(app)
    client.post("/login", json={"password": "pw"})
    r = client.post("/api/stories/a1/fetch")
    assert r.status_code == 202
    assert r.json()["fetch_state"] in ("queued", "running", "idle")
    for _ in range(200):
        body = client.get("/api/stories/a1").json()
        if body["fetch_state"] not in ("queued", "running"):
            break
        time.sleep(0.01)
    assert body["fetch_state"] == "idle" and body["error"] is None
    assert body["items"]


# ------------------------------------------------------------------- backup


def test_backup_cli_writes_a_snapshot_that_opens_and_matches(tmp_path):
    """A backup nobody ever opened is a hope, not a backup."""
    import sqlite3
    import subprocess
    import sys

    from app import store

    config = make_config(tmp_path)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    conn = store.connect(store.db_path(config.data_dir))
    store.init(conn, config)
    store.upsert_accounts(conn, accounts("a1"))
    assert store.upsert_post(conn, post("p1", "a1"), 0) is True
    assert store.upsert_post(conn, post("p2", "a1"), 0) is True

    out = subprocess.run([sys.executable, "-m", "app.sync", "--backup"],
                         capture_output=True, text=True,
                         env={**os.environ, "DATA_DIR": str(config.data_dir),
                              "PROVIDER": "mock", "API_TOKEN": "tok",
                              "APP_PASSWORD": "pw", "APP_SECRET": "s" * 32},
                         cwd=ROOT)
    assert out.returncode == 0, out.stderr
    path = out.stdout.split("path=")[1].split(" ")[0]
    copy = sqlite3.connect(path)
    assert copy.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 2
    assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    copy.close()
    assert oct(Path(path).stat().st_mode)[-3:] == "600"


def test_a_challenge_redirect_says_so_instead_of_looping_forever():
    """Instagram signals a checkpoint as a 302 to /challenge/. Chasing it gave
    TooManyRedirects, which named nothing and hid the actual cause."""
    from app.instagram import CHALLENGE_MSG, redirect_error
    from app.provider import ProviderError, SessionExpired

    class Resp:
        def __init__(self, status, location=None):
            self.status_code = status
            self.headers = {"location": location} if location else {}

    challenge = redirect_error(Resp(302, "https://www.instagram.com/challenge/?next=/"))
    assert isinstance(challenge, SessionExpired)
    assert "security check" in str(challenge) and challenge.args[0] == CHALLENGE_MSG

    assert isinstance(redirect_error(Resp(302, "https://www.instagram.com/accounts/login/")),
                      SessionExpired)
    assert isinstance(redirect_error(Resp(301, "https://example.invalid/x")), ProviderError)
    assert redirect_error(Resp(200)) is None
    assert redirect_error(Resp(401)) is None
