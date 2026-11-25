"""Schema, the membership predicate, keyset paging, retention.

One file, plain pytest, no fixtures beyond tmp_path. If the predicate or the
ordering breaks, these fail.
"""
from __future__ import annotations

import sqlite3

import pytest

from app import store
from app.config import Config
from app.dtos import AccountDTO, PostDTO, ResourceDTO, kind_of

NOW = 1_764_000_000


def env(**over):
    base = {
        "DATA_DIR": "/tmp/x", "PROVIDER": "mock",
        "API_TOKEN": "t", "APP_PASSWORD": "p", "APP_SECRET": "s" * 32,
        "BACKFILL_SLEEP": "0",
    }
    base.update(over)
    return base


@pytest.fixture()
def conn(tmp_path) -> sqlite3.Connection:
    c = store.connect(tmp_path / "t.sqlite3")
    store.init(c, Config.from_env(env()))
    yield c
    c.close()


def finish(conn, session_id, now):
    """Close a session. The program opens one and leaves it open; only a test
    needs yesterday's session to be over."""
    with store.write(conn):
        conn.execute("UPDATE feed_sessions SET finished_at=? WHERE id=?",
                     (now, session_id))


def seed(conn, n=1, taken_at=NOW - 100, kind_pairs=(1, "feed"), account="a1",
         resources=0) -> list[str]:
    store.upsert_accounts(conn, [AccountDTO(pk=account, username=account)])
    run = store.start_run(conn, "manual", NOW - 1000)
    pks = []
    for i in range(n):
        p = PostDTO(pk=f"{account}p{i}", account_pk=account, media_type=kind_pairs[0],
                    product_type=kind_pairs[1], taken_at=taken_at,
                    resources=[ResourceDTO(idx=k, type="image", src_url="u")
                               for k in range(resources)])
        store.upsert_post(conn, p, run)
        pks.append(p.pk)
    store.finish_run(conn, run, now=NOW - 1000)
    return pks


# ------------------------------------------------------------------- schema


def test_pragmas(conn):
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_kind_of_precedence():
    assert kind_of(2, "clips") == "reel"
    assert kind_of(1, "igtv") == "igtv"
    assert kind_of(8, "feed") == "carousel"
    assert kind_of(2, None) == "video"
    assert kind_of(1, "feed") == "photo"
    assert kind_of(99, "weird") == "photo"   # total fallback, never raises


def test_post_kind_is_filled_on_construction():
    assert PostDTO(pk="1", account_pk="a", media_type=8, taken_at=0).kind == "carousel"


def test_upsert_is_idempotent_and_keeps_first_seen(conn):
    store.upsert_accounts(conn, [AccountDTO(pk="a1", username="a1")])
    r1 = store.start_run(conn, "cycle", NOW - 10)
    p = PostDTO(pk="p1", account_pk="a1", media_type=1, taken_at=NOW - 50,
                like_count=1)
    assert store.upsert_post(conn, p, r1) is True
    store.finish_run(conn, r1, now=NOW - 10)
    r2 = store.start_run(conn, "cycle", NOW - 5)
    p.like_count = 99
    assert store.upsert_post(conn, p, r2) is False
    row = conn.execute("SELECT first_seen_sync, like_count FROM posts").fetchone()
    assert row["first_seen_sync"] == r1
    assert row["like_count"] == 99
    store.finish_run(conn, r2, now=NOW - 5)


def test_settings_seed_once(conn, tmp_path):
    first = conn.execute("SELECT value FROM settings WHERE key='sync_interval'").fetchone()[0]
    assert first == "1800"
    store.init(conn, Config.from_env(env(SYNC_INTERVAL="900")))
    assert conn.execute(
        "SELECT value FROM settings WHERE key='sync_interval'").fetchone()[0] == "1800"


# -------------------------------------------------------------- membership


def test_new_post_after_snapshot_is_invisible(conn):
    seed(conn, n=2, taken_at=NOW - 500)
    s = store.open_session(conn, "mac", "unseen", {"kinds": ["photo"]}, now=NOW)
    assert s["item_count"] == 2

    later = store.start_run(conn, "cycle", NOW + 10)
    store.upsert_post(conn, PostDTO(pk="new", account_pk="a1", media_type=1,
                                    taken_at=NOW + 5), later)
    store.finish_run(conn, later, now=NOW + 10)

    rows, _ = store.feed_page(conn, store.get_session(conn, s["id"]))
    assert {r["pk"] for r in rows} == {"a1p0", "a1p1"}
    assert "new" not in {r["pk"] for r in rows}
    counts = store.session_counts(conn, store.get_session(conn, s["id"]))
    assert counts["new_since_start"] == 1


def test_post_read_during_session_stays_in_session(conn):
    pks = seed(conn, n=2, taken_at=NOW - 500)
    s = store.open_session(conn, "mac", "unseen", {}, now=NOW)
    assert store.mark_seen(conn, [pks[0]], s["id"], now=NOW + 60) == 1
    rows, _ = store.feed_page(conn, store.get_session(conn, s["id"]))
    assert pks[0] in {r["pk"] for r in rows}          # read, still in this session
    counts = store.session_counts(conn, store.get_session(conn, s["id"]))
    assert counts["consumed"] == 1 and counts["remaining"] == 1


def test_post_read_before_session_is_excluded_from_unseen(conn):
    pks = seed(conn, n=2, taken_at=NOW - 500)
    early = store.open_session(conn, "mac", "unseen", {}, now=NOW - 400)
    store.mark_seen(conn, [pks[1]], early["id"], now=NOW - 350)
    finish(conn, early["id"], NOW - 300)

    s = store.open_session(conn, "mac", "unseen", {}, now=NOW)
    assert s["item_count"] == 1
    assert [r["pk"] for r in store.feed_page(conn, s)[0]] == [pks[0]]


def test_mode_all_includes_seen_posts(conn):
    pks = seed(conn, n=2, taken_at=NOW - 500)
    early = store.open_session(conn, "mac", "unseen", {}, now=NOW - 400)
    store.mark_seen(conn, pks, early["id"], now=NOW - 350)
    finish(conn, early["id"], NOW - 300)

    assert store.open_session(conn, "tv", "unseen", {}, now=NOW)["item_count"] == 0
    assert store.open_session(conn, "mac", "all", {}, now=NOW)["item_count"] == 2


def test_unseen_count_and_mute(conn):
    seed(conn, n=3, taken_at=NOW - 500, account="a1")
    seed(conn, n=2, taken_at=NOW - 400, account="a2")
    assert store.unseen_counts(conn)["posts"] == 5
    store.set_muted(conn, "a2", True)
    assert store.unseen_counts(conn)["posts"] == 3

    s = store.open_session(conn, "mac", "unseen", {}, now=NOW)
    assert s["item_count"] == 3
    finish(conn, s["id"], NOW)
    s = store.open_session(conn, "mac", "unseen", {"hide_muted": False}, now=NOW)
    assert s["item_count"] == 5


def test_filter_kinds_are_disjoint(conn):
    seed(conn, n=2, taken_at=NOW - 500, kind_pairs=(1, "feed"))
    s = store.open_session(conn, "mac", "unseen", {"kinds": ["reel"]}, now=NOW)
    assert s["item_count"] == 0
    s = store.open_session(conn, "mac", "unseen", {"kinds": ["photo", "reel"]}, now=NOW)
    assert s["item_count"] == 2


# ---------------------------------------------------------------- ordering


def test_keyset_total_order_with_tied_taken_at(conn):
    store.upsert_accounts(conn, [AccountDTO(pk="a1", username="a1")])
    run = store.start_run(conn, "manual", NOW - 1000)
    for i in range(25):
        store.upsert_post(conn, PostDTO(pk=f"p{i:02d}", account_pk="a1",
                                        media_type=1, taken_at=NOW - 100), run)
    store.finish_run(conn, run, now=NOW - 1000)

    s = store.open_session(conn, "mac", "unseen", {}, now=NOW)
    seen, cursor = [], None
    while True:
        rows, cursor = store.feed_page(conn, s, limit=7, cursor=cursor)
        seen.extend(r["pk"] for r in rows)
        if cursor is None:
            break
    assert len(seen) == 25 and len(set(seen)) == 25     # no dups, no skips
    assert seen == [f"p{i:02d}" for i in range(24, -1, -1)]  # rowid desc tiebreak


def test_around_pk_returns_page_containing_the_post(conn):
    store.upsert_accounts(conn, [AccountDTO(pk="a1", username="a1")])
    run = store.start_run(conn, "manual", NOW - 1000)
    for i in range(20):
        store.upsert_post(conn, PostDTO(pk=f"p{i:02d}", account_pk="a1",
                                        media_type=1, taken_at=NOW - i * 10), run)
    store.finish_run(conn, run, now=NOW - 1000)
    s = store.open_session(conn, "mac", "unseen", {}, now=NOW)

    rows, _ = store.feed_page(conn, s, limit=5, around_pk="p12")
    assert "p12" in {r["pk"] for r in rows}
    assert rows[0]["pk"] == "p10" and rows[-1]["pk"] == "p14"
    assert len(rows) == 5


def test_one_open_session_per_device(conn):
    seed(conn, n=1)
    first = store.open_session(conn, "mac", "unseen", {}, now=NOW)
    second = store.open_session(conn, "mac", "unseen", {}, now=NOW + 10)
    assert store.get_session(conn, first["id"])["finished_at"] == NOW + 10
    assert store.current_session(conn, "mac")["id"] == second["id"]
    assert store.current_session(conn, "tv") is None


# --------------------------------------------------------------- retention


def test_retention_null_raw_and_prune_runs_without_breaking_posts(conn):
    store.upsert_accounts(conn, [AccountDTO(pk="a1", username="a1")])
    old = store.start_run(conn, "cycle", NOW - 100 * 86400)
    store.upsert_post(conn, PostDTO(pk="p1", account_pk="a1", media_type=1,
                                    taken_at=NOW - 40 * 86400), old, raw_z=b"\x00" * 10)
    store.finish_run(conn, old, now=NOW - 100 * 86400 + 1000)

    stats = store.retention(conn, now=NOW)
    assert stats["raw_nulled"] == 1
    assert stats["runs_deleted"] == 1                   # no FK blocks the prune
    row = conn.execute("SELECT first_seen_sync, raw_z FROM posts WHERE pk='p1'").fetchone()
    assert row["first_seen_sync"] == old and row["raw_z"] is None


def test_pruning_sessions_nulls_seen_session_not_the_post(conn):
    pks = seed(conn, n=1, taken_at=NOW - 100 * 86400)
    s = store.open_session(conn, "mac", "unseen", {}, now=NOW - 100 * 86400)
    store.mark_seen(conn, pks, s["id"], now=NOW - 100 * 86400 + 5)
    finish(conn, s["id"], NOW - 100 * 86400 + 10)

    stats = store.retention(conn, now=NOW)
    assert stats["sessions_deleted"] == 1
    row = conn.execute("SELECT seen_at, seen_session FROM posts").fetchone()
    assert row["seen_at"] is not None and row["seen_session"] is None


# ------------------------------------------------------------------- mock


def test_mock_is_deterministic_and_serves_real_bytes():
    from app.mock import MockProvider

    a, b = MockProvider(seed=3, now=NOW), MockProvider(seed=3, now=NOW)
    assert [p.pk for p in a.timeline_page(None).items] == \
           [p.pk for p in b.timeline_page(None).items]
    jpg = a.media_bytes("mock://post/10000000p0/0")
    assert jpg[:2] == b"\xff\xd8" and jpg[-2:] == b"\xff\xd9"
    mp4 = a.video_bytes()
    assert len(mp4) > 1000 and mp4[4:8] == b"ftyp"

    tail = b"".join(a.media_stream("mock://post/10000000p0/0", "bytes=10-19"))
    assert len(tail) == 10


def test_mock_story_fetch_registers_a_view():
    from app.mock import MockProvider

    m = MockProvider(seed=1, now=NOW)
    first = m.tray_entries[0]
    assert first.seen is False
    m.user_stories(first.account_pk)
    assert next(e for e in m.story_tray() if e.account_pk == first.account_pk).seen is True


def test_mock_timeline_pages_advance():
    from app.mock import MockProvider

    m = MockProvider(seed=5, now=NOW)
    page = m.timeline_page(None)
    seen = [p.pk for p in page.items]
    while page.next_max_id:
        page = m.timeline_page(page.next_max_id)
        seen.extend(p.pk for p in page.items)
    assert len(seen) == len(set(seen)) == len(m.feed)


def test_a_quiet_day_still_has_a_latest_post(conn):
    """The 24h window is a filter, not a cliff: nothing in it means the newest
    stored post is what "latest" shows."""
    seed(conn, n=1, taken_at=NOW - 5 * 86400)          # a post from last week
    sess = store.open_session(conn, "d1", "unseen", {"from": NOW - 86400}, now=NOW)
    assert sess["item_count"] == 1
    assert '"from"' not in sess["filters_json"]         # the window was dropped


def test_the_archive_only_offers_posts_it_can_show(conn):
    """An instagram URL dies within a day. A post whose bytes were never cached
    is a black card with a retry that can never work, so it is not offered."""
    pks = seed(conn, n=2)
    with store.write(conn):
        conn.execute(
            "INSERT INTO media_cache (kind, ref, path, bytes, last_access)"
            " VALUES ('post', ?, '/tmp/x.jpg', 1, 0)", (pks[1] + ":abc12345",))
    rows, _ = store.older_page(conn, limit=10)
    assert [r["pk"] for r in rows] == [pks[1]]
