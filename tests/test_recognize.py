"""Song recognition: the film goes out, a track comes back.

No network here — ShazamIO and ffmpeg are stubbed at their own seams, so what is
tested is the mapping from Shazam's answer to the line the reader sees.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import recognize, store
from app.config import Config
from app.dtos import AccountDTO, PostDTO, ResourceDTO
from app.main import create_app

NOW = 1_764_000_000
TRACK = {
    "matches": [{"id": "x", "offset": 5.1}],
    "track": {
        "title": "MARKET PASS",
        "subtitle": "Ena Dyo & Zetel",
        "hub": {"providers": [
            {"type": "APPLE", "actions": [{"type": "uri", "uri": "https://music.apple.com/x"}]},
            {"type": "SPOTIFY", "actions": [
                {"type": "uri", "uri": "spotify:search:MARKET%20PASS%20Ena%20Dyo"}]},
        ]},
    },
}


def build(tmp_path):
    env = {"DATA_DIR": str(tmp_path / "data"), "PROVIDER": "mock",
           "API_TOKEN": "tok", "APP_PASSWORD": "pw", "APP_SECRET": "s" * 32}
    app = create_app(Config.from_env(env))
    client = TestClient(app)
    assert client.post("/login", json={"password": "pw"}).status_code == 200
    return app, client


def seed(app) -> None:
    conn = app.state.conn
    store.upsert_accounts(conn, [AccountDTO(pk="a1", username="alice")])
    run = store.start_run(conn, "manual")
    store.upsert_post(conn, PostDTO(
        pk="p1", account_pk="a1", media_type=8, product_type="feed",
        taken_at=NOW, resources=[
            ResourceDTO(idx=0, type="image", src_url="mock://post/p1/0"),
            ResourceDTO(idx=1, type="video", src_url="mock://video/p1/1"),
        ]), run)
    store.finish_run(conn, run)


@pytest.fixture()
def heard(monkeypatch):
    """Stands in for ffmpeg + Shazam and remembers what reached them."""
    box = {"wav": b"RIFF-test", "answer": TRACK, "clip": None}

    monkeypatch.setattr(recognize, "to_wav", lambda clip: (box.update(clip=clip), box["wav"])[1])

    def fake_shazam(wav):
        box["sent"] = wav
        if isinstance(box["answer"], Exception):
            raise box["answer"]
        return box["answer"]

    monkeypatch.setattr(recognize, "_shazam", fake_shazam)
    monkeypatch.setattr(recognize.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    return box


def test_a_film_is_recognised_and_answered_with_a_track(tmp_path, heard):
    app, client = build(tmp_path)
    seed(app)
    r = client.post("/api/recognize/p1/1")
    assert r.status_code == 200
    assert r.json() == {"found": True, "artist": "Ena Dyo & Zetel",
                        "title": "MARKET PASS"}
    assert heard["sent"] == b"RIFF-test", "the decoded clip is what Shazam sees"
    assert heard["clip"], "and the film's own bytes reached the decoder"


def test_a_quiet_film_is_an_answer_not_an_error(tmp_path, heard):
    heard["answer"] = {"matches": [], "track": {}}
    app, client = build(tmp_path)
    seed(app)
    r = client.post("/api/recognize/p1/1")
    assert r.status_code == 200 and r.json()["found"] is False


def test_a_service_that_breaks_is_said_plainly(tmp_path, heard):
    heard["answer"] = RuntimeError("connector closed")
    app, client = build(tmp_path)
    seed(app)
    r = client.post("/api/recognize/p1/1")
    assert r.status_code == 200
    assert r.json() == {"found": False, "error": "RuntimeError"}


def test_no_ffmpeg_is_said_plainly(tmp_path, heard, monkeypatch):
    monkeypatch.setattr(recognize.shutil, "which", lambda name: None)
    app, client = build(tmp_path)
    seed(app)
    body = client.post("/api/recognize/p1/1").json()
    assert body == {"found": False, "error": "ffmpeg missing"}


def test_an_undecodable_film_is_an_answer(tmp_path, heard):
    heard["wav"] = None
    app, client = build(tmp_path)
    seed(app)
    assert client.post("/api/recognize/p1/1").json() == {
        "found": False, "error": "undecodable"}


def test_a_busy_service_is_not_retried_for_minutes():
    """The library defaults to 20 attempts and 60 s of backoff on 429/5xx. A press
    is not allowed to sit behind that: two tries, four seconds."""
    import aiohttp_retry
    import shazamio
    import shazamio.client

    seen = {}

    class FakeRetry:
        def __init__(self, **kw):
            seen.update(kw)

    class FakeShazam:
        def __init__(self, http_client=None):
            seen["client"] = http_client

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def recognize(self, wav):
            seen["wav"] = wav
            return TRACK

    import pytest as _pytest
    monkeypatch = _pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(aiohttp_retry, "ExponentialRetry", FakeRetry)
        monkeypatch.setattr(shazamio.client, "HTTPClient",
                            lambda retry_options=None: "client")
        monkeypatch.setattr(shazamio, "Shazam", FakeShazam)
        assert recognize._shazam(b"RIFF") == TRACK
    finally:
        monkeypatch.undo()
    assert seen["client"] == "client", "the client is the one we configured"
    assert seen["wav"] == b"RIFF"
    assert seen["attempts"] <= 2 and seen["max_timeout"] <= 5
    assert recognize.WAIT <= 25, "and the whole ask has a ceiling"


def test_a_slow_service_is_an_answer_not_a_hang(tmp_path, heard, monkeypatch):
    def slow(wav):
        raise TimeoutError()

    monkeypatch.setattr(recognize, "_shazam", slow)
    app, client = build(tmp_path)
    seed(app)
    assert client.post("/api/recognize/p1/1").json() == {
        "found": False, "error": "timeout"}


def test_a_picture_has_no_song(tmp_path, heard):
    app, client = build(tmp_path)
    seed(app)
    r = client.post("/api/recognize/p1/0")
    assert r.status_code == 400 and r.json()["error"]["code"] == "not_audio"
    assert heard["clip"] is None, "and nothing was decoded to find that out"


def test_an_unknown_post_is_a_404(tmp_path, heard):
    app, client = build(tmp_path)
    seed(app)
    assert client.post("/api/recognize/nope/0").status_code == 404
