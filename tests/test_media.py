"""Step 7: media bytes. Mock provider, temp dirs, no network."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import store
from app.config import Config
from app.dtos import AccountDTO, PostDTO, ResourceDTO, StoryDTO
from app.main import create_app
from app.mock import MockProvider

NOW = 1_764_000_000


def make_config(tmp_path, **over):
    env = {"DATA_DIR": str(tmp_path / "data"), "PROVIDER": "mock",
           "API_TOKEN": "tok", "APP_PASSWORD": "pw", "APP_SECRET": "s" * 32}
    env.update(over)
    return Config.from_env(env)


def build(tmp_path, **over):
    app = create_app(make_config(tmp_path, **over))
    client = TestClient(app)
    assert client.post("/login", json={"password": "pw"}).status_code == 200
    return app, client


def seed(app) -> None:
    conn = app.state.conn
    store.upsert_accounts(conn, [AccountDTO(pk="a1", username="alice",
                                            pic_url="mock://avatar/a1")])
    store.upsert_ring(conn, _tray())
    run = store.start_run(conn, "manual")
    store.upsert_post(conn, PostDTO(
        pk="p1", account_pk="a1", media_type=8, product_type="feed", taken_at=NOW,
        resources=[
            ResourceDTO(idx=0, type="image", src_url="mock://post/p1/0",
                        poster_url="mock://post/p1/0?poster=1", w=1080, h=1349),
            ResourceDTO(idx=1, type="video", src_url="mock://video/p1/1",
                        poster_url="mock://post/p1/1?poster=1", w=320, h=568),
        ]), run)
    store.finish_run(conn, run)
    store.upsert_story(conn, StoryDTO(
        pk="s1", account_pk="a1", media_type=1, taken_at=NOW,
        expiring_at=NOW + 3600, src_url="mock://story/s1",
        thumb_url="mock://story/s1?thumb=1"))


def _tray():
    from app.dtos import TrayEntry

    return TrayEntry(account_pk="a1", username="alice", latest_reel_media=NOW,
                     media_count=1, media_ids=["s1"], seen=False,
                     expiring_at=NOW + 3600, ring_thumb="mock://avatar/a1")


@pytest.fixture()
def served(tmp_path):
    app, client = build(tmp_path)
    seed(app)
    return app, client


class Counter:
    """MockProvider that counts upstream fetches."""

    def __init__(self) -> None:
        self._mock = MockProvider(now=NOW)
        self.calls = 0

    def connect(self) -> None:
        pass

    def media_stream(self, url, byte_range=None):
        self.calls += 1
        return self._mock.media_stream(url, byte_range)


# ------------------------------------------------------------------- shapes

KINDS = [("/api/media/post/p1/0", "image/jpeg"),
         ("/api/media/post/p1/0?size=t", "image/jpeg"),
         ("/api/media/post/p1/1", "video/mp4"),
         ("/api/media/story/s1", "image/jpeg"),
         ("/api/media/story/s1?thumb=1", "image/jpeg"),
         ("/api/media/account/a1", "image/jpeg")]


@pytest.mark.parametrize("url,ctype", KINDS)
def test_every_kind_serves_real_bytes(served, url, ctype):
    _, client = served
    r = client.get(url)
    assert r.status_code == 200, url
    assert r.headers["content-type"].startswith(ctype)
    assert r.headers["accept-ranges"] == "bytes"
    assert int(r.headers["content-length"]) > 0
    assert r.content


def test_a_fetch_into_the_cache_happens_exactly_once(served):
    app, client = served
    counter = Counter()
    app.state.media.provider = counter
    first = client.get("/api/media/post/p1/0")
    second = client.get("/api/media/post/p1/0")
    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    assert counter.calls == 1
    row = app.state.conn.execute("SELECT * FROM media_cache").fetchone()
    assert Path(row["path"]).is_file() and row["bytes"] == len(first.content)


# -------------------------------------------------------------------- range

def test_range_1024_matches_the_slice_and_stays_206(served):
    _, client = served
    full = client.get("/api/media/post/p1/1").content
    r = client.get("/api/media/post/p1/1", headers={"Range": "bytes=0-1023"})
    assert r.status_code == 206
    assert r.headers["content-range"] == f"bytes 0-1023/{len(full)}"
    assert r.content == full[:1024]


def test_safari_two_byte_probe_is_206(served):
    _, client = served
    r = client.get("/api/media/post/p1/1", headers={"Range": "bytes=0-1"})
    assert r.status_code == 206
    assert len(r.content) == 2
    assert r.headers["content-range"].startswith("bytes 0-1/")


def test_open_and_suffix_ranges_clamp(served):
    _, client = served
    full = client.get("/api/media/post/p1/1").content
    open_ended = client.get("/api/media/post/p1/1", headers={"Range": "bytes=100-"})
    assert open_ended.status_code == 206
    assert open_ended.content == full[100:]
    suffix = client.get("/api/media/post/p1/1", headers={"Range": "bytes=-100"})
    assert suffix.status_code == 206
    assert suffix.content == full[-100:]
    past_eof = client.get("/api/media/post/p1/1",
                          headers={"Range": f"bytes=0-{len(full) * 2}"})
    assert past_eof.status_code == 206 and past_eof.content == full


def test_unsatisfiable_range_is_416(served):
    _, client = served
    size = len(client.get("/api/media/post/p1/1").content)
    r = client.get("/api/media/post/p1/1",
                   headers={"Range": f"bytes={size + 10}-{size + 99}"})
    assert r.status_code == 416
    assert r.headers["content-range"] == f"bytes */{size}"
    assert r.content == b""


# -------------------------------------------------------------- unavailable

def test_unknown_pk_is_an_honest_404(served):
    _, client = served
    for url in ("/api/media/post/nope/0", "/api/media/story/nope",
                "/api/media/account/nope",
                "/api/media/post/p1/99"):
        r = client.get(url)
        assert r.status_code == 404, url
        assert r.headers["cache-control"] == "no-store"
        assert r.content == b""


def test_post_without_a_url_is_an_honest_404(served):
    app, client = served
    conn = app.state.conn
    run = store.start_run(conn, "manual")
    store.upsert_post(conn, PostDTO(pk="bare", account_pk="a1", media_type=1,
                                    taken_at=NOW,
                                    resources=[ResourceDTO(idx=0, type="image")]),
                      run)
    store.finish_run(conn, run)
    r = client.get("/api/media/post/bare/0")
    assert r.status_code == 404 and r.content == b""


# ------------------------------------------------------------------- budget

def test_tiny_budget_evicts_the_oldest_entry(tmp_path):
    app, client = build(tmp_path)
    media = app.state.media
    folder = tmp_path / "data" / "media" / "post"
    folder.mkdir(parents=True)
    old_file, new_file = folder / "old.jpg", folder / "new.jpg"
    old_file.write_bytes(b"x")
    new_file.write_bytes(b"y")
    with store.write(app.state.conn):
        app.state.conn.executemany(
            "INSERT INTO media_cache (kind, ref, path, bytes, last_access)"
            " VALUES ('post', ?, ?, 1, ?)",
            [("a1:11111111", str(old_file), 100), ("a1:22222222", str(new_file), 200)])
    media.budget_bytes = 1
    media.evict()
    refs = [r["ref"] for r in app.state.conn.execute("SELECT ref FROM media_cache")]
    assert refs == ["a1:22222222"]
    assert not old_file.exists() and new_file.exists()


def test_budget_zero_stores_nothing(tmp_path):
    app, client = build(tmp_path, MEDIA_BUDGET_MB="0")
    seed(app)
    assert client.get("/api/media/post/p1/0").status_code == 200
    assert app.state.conn.execute("SELECT COUNT(*) AS n FROM media_cache"
                                  ).fetchone()["n"] == 0
    media_root = tmp_path / "data" / "media"
    assert not [p for p in media_root.rglob("*") if p.is_file()] if \
        media_root.exists() else True


# -------------------------------------------------------------- cache off

def test_cache_off_proxies_and_writes_nothing(tmp_path):
    app, client = build(tmp_path, MEDIA_CACHE="0")
    seed(app)
    full = client.get("/api/media/post/p1/1")
    assert full.status_code == 200 and full.headers["accept-ranges"] == "bytes"
    r = client.get("/api/media/post/p1/1", headers={"Range": "bytes=0-1023"})
    assert r.status_code == 206
    assert r.content == full.content[:1024]
    assert app.state.conn.execute("SELECT COUNT(*) AS n FROM media_cache"
                                  ).fetchone()["n"] == 0
    assert not (tmp_path / "data" / "media").exists()


# ------------------------------------------------------------- allowlist

def test_non_allowlisted_host_is_404_and_never_fetched(tmp_path):
    app, client = build(tmp_path, PROVIDER="instagrapi", IG_SESSION_COOKIE="x")
    conn = app.state.conn
    run = store.start_run(conn, "manual")
    store.upsert_accounts(conn, [AccountDTO(pk="a1", username="alice")])
    store.upsert_post(conn, PostDTO(
        pk="evil", account_pk="a1", media_type=1, taken_at=NOW,
        resources=[ResourceDTO(idx=0, type="image",
                               src_url="https://evil.example/x.jpg")]), run)
    store.finish_run(conn, run)

    class Boom:
        calls = 0

        def connect(self):
            raise AssertionError("provider must not be used")

        def media_stream(self, url, byte_range=None):
            Boom.calls += 1
            raise AssertionError("outbound request attempted")

    app.state.media.provider = Boom()
    r = client.get("/api/media/post/evil/0")
    assert r.status_code == 404
    assert r.headers["cache-control"] == "no-store"
    assert r.content == b""
    assert Boom.calls == 0


def test_the_same_file_written_twice_at_once_does_not_500(served):
    """Two cards can ask for one story at the same moment. A shared `.tmp` name
    meant the loser's rename raised FileNotFoundError — a 500 for a picture that
    was already on disk."""
    from concurrent.futures import ThreadPoolExecutor
    app, _ = served
    media = app.state.media
    with ThreadPoolExecutor(max_workers=8) as pool:
        paths = list(pool.map(
            lambda _: media._write("story", "mock://story/race", b"bytes",
                                   "image/jpeg"), range(8)))
    assert len({str(p) for p in paths}) == 1
    assert paths[0].read_bytes() == b"bytes"
    assert not list(paths[0].parent.glob("*.tmp"))


def test_prune_forgets_a_row_whose_file_is_gone(served, tmp_path):
    """The archive asks the cache table what it can still show; a row without
    bytes answers yes and paints a black card."""
    from pathlib import Path
    app, client = served
    media = app.state.media
    assert client.get("/api/media/post/p1/0").status_code == 200
    row = app.state.conn.execute("SELECT * FROM media_cache").fetchone()
    Path(row["path"]).unlink()
    assert media.prune() == 1
    assert app.state.conn.execute("SELECT COUNT(*) FROM media_cache").fetchone()[0] == 0


def test_prune_reclaims_files_no_row_points_at(served):
    """Eviction and retention can drop a row and lose its file, and a write can
    land before its row. Either way the bytes are unreachable — and the cap is
    counted in rows, so the disk drifts above it."""
    import os
    app, _ = served
    media = app.state.media
    orphan = media.root / "post" / "orphan.jpg"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_bytes(b"x")
    old = 1_700_000_000
    os.utime(orphan, (old, old))
    fresh = media.root / "post" / "inflight.jpg"
    fresh.write_bytes(b"y")
    media.prune()
    assert not orphan.exists()
    assert fresh.exists(), "a file from a write still in flight is not an orphan"
