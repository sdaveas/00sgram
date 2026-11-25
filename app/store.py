"""SQLite: schema, the one membership predicate, keyset paging, retention.

All writes go through `write()` (one RLock, one transaction). Reads are
lock-free on WAL. The feed's total order is `taken_at DESC, rowid DESC` — rowid,
not pk, because Instagram pks are numeric strings and would tie.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from .dtos import AccountDTO, PostDTO, ResourceDTO, StoryDTO, TrayEntry

WRITE_LOCK = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL CHECK (kind IN ('cycle','sweep','backfill','story_fetch','manual')),
  started_at INTEGER NOT NULL, finished_at INTEGER, duration_ms INTEGER,
  pages INTEGER DEFAULT 0, posts_added INTEGER DEFAULT 0, stories_added INTEGER DEFAULT 0,
  recovered INTEGER NOT NULL DEFAULT 0,
  error TEXT
);

CREATE TABLE IF NOT EXISTS accounts (
  pk TEXT PRIMARY KEY, username TEXT NOT NULL, full_name TEXT, pic_url TEXT,
  is_following INTEGER NOT NULL DEFAULT 1, muted INTEGER NOT NULL DEFAULT 0,
  local_done_upto INTEGER,
  story_item_count INTEGER,
  last_swept_at INTEGER
);
CREATE INDEX IF NOT EXISTS accounts_name ON accounts (username);

CREATE TABLE IF NOT EXISTS feed_sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, device TEXT NOT NULL,
  started_at INTEGER NOT NULL, snapshot_sync INTEGER NOT NULL,
  mode TEXT NOT NULL CHECK (mode IN ('unseen','all')), filters_json TEXT NOT NULL,
  cursor TEXT, last_rendered_pk TEXT,
  item_count INTEGER NOT NULL, finished_at INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS sessions_one_open
  ON feed_sessions (device) WHERE finished_at IS NULL;

CREATE TABLE IF NOT EXISTS posts (
  pk TEXT PRIMARY KEY, account_pk TEXT NOT NULL,
  code TEXT, media_type INTEGER NOT NULL, product_type TEXT,
  kind TEXT NOT NULL CHECK (kind IN ('photo','video','carousel','reel','igtv')),
  caption TEXT, taken_at INTEGER NOT NULL,
  like_count INTEGER, comment_count INTEGER, permalink TEXT,
  -- No FK on purpose: run ids are never reused (AUTOINCREMENT), and an enforced
  -- FK would make pruning sync_runs at 90 days impossible.
  first_seen_sync INTEGER NOT NULL,
  -- ON DELETE SET NULL: sessions are pruned at 90 days; the post must survive.
  seen_at INTEGER, seen_session INTEGER REFERENCES feed_sessions(id) ON DELETE SET NULL,
  unseen_at INTEGER,
  -- Our like, as Instagram reports it. Source of truth is the server; this is
  -- the last thing a write told us.
  liked INTEGER NOT NULL DEFAULT 0,
  raw_z BLOB
);
-- SQLite rejects rowid in an index definition; every index carries the rowid
-- implicitly, so the ORDER BY still resolves the tiebreak without a sort.
CREATE INDEX IF NOT EXISTS posts_chrono  ON posts (taken_at DESC);
CREATE INDEX IF NOT EXISTS posts_unseen  ON posts (taken_at DESC) WHERE seen_at IS NULL;
CREATE INDEX IF NOT EXISTS posts_account ON posts (account_pk, taken_at DESC);
CREATE INDEX IF NOT EXISTS posts_snap    ON posts (first_seen_sync);
CREATE INDEX IF NOT EXISTS posts_kind    ON posts (kind, taken_at DESC);

CREATE TABLE IF NOT EXISTS media_cache (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL, ref TEXT NOT NULL, path TEXT NOT NULL, bytes INTEGER NOT NULL,
  last_access INTEGER NOT NULL,
  UNIQUE (kind, ref)
);
CREATE INDEX IF NOT EXISTS media_lru ON media_cache (last_access);

CREATE TABLE IF NOT EXISTS media_resources (
  post_pk TEXT NOT NULL, idx INTEGER NOT NULL, type TEXT NOT NULL,
  src_url TEXT, poster_url TEXT, w INTEGER, h INTEGER, duration REAL,
  PRIMARY KEY (post_pk, idx)
);

CREATE TABLE IF NOT EXISTS stories (
  pk TEXT PRIMARY KEY, account_pk TEXT NOT NULL,
  media_type INTEGER NOT NULL, taken_at INTEGER NOT NULL,
  expiring_at INTEGER NOT NULL, src_url TEXT, thumb_url TEXT, duration REAL,
  media_ref TEXT, fetched_at INTEGER, seen_at INTEGER,
  seen_session INTEGER REFERENCES feed_sessions(id) ON DELETE SET NULL,
  unavailable_at INTEGER, raw_z BLOB,
  -- The emoji we DM'd the author, or NULL. A story is reacted to at most once.
  reaction TEXT,
  -- JSON list of the stickers the author attached (profiles, music, links).
  links TEXT
);
CREATE INDEX IF NOT EXISTS stories_live   ON stories (account_pk, expiring_at);
CREATE INDEX IF NOT EXISTS stories_unseen ON stories (account_pk) WHERE seen_at IS NULL;

CREATE TABLE IF NOT EXISTS story_rings (
  account_pk TEXT PRIMARY KEY,
  latest_reel_media INTEGER, media_count INTEGER, media_ids TEXT,
  ring_thumb TEXT, updated_at INTEGER NOT NULL, stale INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS meta     (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS backups  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                                     created_at INTEGER NOT NULL,
                                     path TEXT NOT NULL, bytes INTEGER, ok INTEGER);

CREATE TABLE IF NOT EXISTS tg_chats (
  chat_id TEXT PRIMARY KEY, title TEXT, kind TEXT, read_at INTEGER
);
CREATE TABLE IF NOT EXISTS tg_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL, msg_id TEXT NOT NULL,
  at INTEGER NOT NULL, mine INTEGER NOT NULL DEFAULT 0, who TEXT,
  kind TEXT, text TEXT, links TEXT, thread_id INTEGER,
  UNIQUE (chat_id, msg_id)
);
CREATE INDEX IF NOT EXISTS tg_messages_thread ON tg_messages (chat_id, at);

-- One Telegram forum topic per Instagram conversation. The name is the key the
-- inbox gives us; the topic itself can be renamed in Telegram without breaking
-- the mapping, because nothing reads the topic's title back.
CREATE TABLE IF NOT EXISTS ig_threads (
  name TEXT PRIMARY KEY, thread_id INTEGER NOT NULL,
  title TEXT, created_at INTEGER NOT NULL
);

-- Which Telegram message stands for which Instagram message. Written when the
-- relay sends, read when a reaction arrives in Telegram: a reaction names a
-- Telegram message, and Instagram wants the id of the Instagram one.
CREATE TABLE IF NOT EXISTS ig_sent_map (
  chat_id TEXT NOT NULL, tg_msg_id TEXT NOT NULL,
  ig_id TEXT NOT NULL, ig_msg_id TEXT NOT NULL, created_at INTEGER NOT NULL,
  PRIMARY KEY (chat_id, tg_msg_id)
);

-- Reactions typed in Telegram, waiting to be replayed on Instagram. A table and
-- not a queue in memory: a restart must not swallow one.
CREATE TABLE IF NOT EXISTS ig_reacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id TEXT NOT NULL, tg_msg_id TEXT NOT NULL,
  emoji TEXT NOT NULL, at INTEGER NOT NULL, done INTEGER NOT NULL DEFAULT 0,
  error TEXT
);

-- WhatsApp lives in its own four tables, not behind a `kind` column. The two
-- relays key their state differently (Instagram: a monotonic timestamp; WhatsApp:
-- a set of ids), they post into different groups, and a shared table would let
-- one relay's cleanup delete the other's marks.
--
-- One topic per conversation, and the name *is* the key: WhatsApp Web has no chat
-- id anywhere in the DOM. A rename on either side therefore starts a new topic.
CREATE TABLE IF NOT EXISTS wa_chats (
  name TEXT PRIMARY KEY, thread_id INTEGER NOT NULL,
  is_self INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL
);

-- Per conversation: the message ids already relayed (JSON, newest last), plus the
-- list row's preview/timestamp/unread. The triple is a *trigger* only — it says
-- which conversations to open, never what to send.
-- `pending` means a burst was cut short: the conversation has more unseen
-- messages than one cycle sends, so it must be opened again even though its
-- list row will not change.
CREATE TABLE IF NOT EXISTS wa_marks (
  name TEXT PRIMARY KEY, ids TEXT NOT NULL DEFAULT '[]',
  preview TEXT, ts TEXT, unread TEXT, pending INTEGER NOT NULL DEFAULT 0,
  updated_at INTEGER NOT NULL
);

-- Which Telegram message stands for which WhatsApp message, and which WhatsApp
-- message the relay itself typed. The second use is the echo filter: the self
-- chat relays our own messages, so our own sends must not come back.
-- `typed=1` means the relay typed it into WhatsApp (a reply from Telegram). A
-- relayed message is `typed=0`: it came from the phone, and only the id set
-- keeps it from being posted twice.
CREATE TABLE IF NOT EXISTS wa_sent_map (
  chat_id TEXT NOT NULL, tg_msg_id TEXT NOT NULL,
  name TEXT NOT NULL, wa_msg_id TEXT NOT NULL, created_at INTEGER NOT NULL,
  typed INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (chat_id, tg_msg_id)
);
CREATE INDEX IF NOT EXISTS wa_sent_wa ON wa_sent_map (wa_msg_id);

-- Same shape as ig_reacts, separate table: two relays, two queues, one worker each.
CREATE TABLE IF NOT EXISTS wa_reacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id TEXT NOT NULL, tg_msg_id TEXT NOT NULL,
  emoji TEXT NOT NULL, at INTEGER NOT NULL, done INTEGER NOT NULL DEFAULT 0,
  error TEXT
);
"""


def db_path(data_dir: Path | str) -> Path:
    return Path(data_dir) / "00sgram.sqlite3"


def connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


# Columns added after the first deploy. CREATE TABLE IF NOT EXISTS cannot add a
# column to a file that already has the table, and the Pi has real data in it.
NEW_COLUMNS = (
    ("posts", "liked", "INTEGER NOT NULL DEFAULT 0"),
    ("posts", "links", "TEXT"),
    ("stories", "reaction", "TEXT"),
    ("stories", "links", "TEXT"),
    ("tg_messages", "thread_id", "INTEGER"),
    ("ig_threads", "ig_id", "TEXT"),
)


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    for table, column, decl in NEW_COLUMNS:
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init(conn: sqlite3.Connection, config=None) -> None:
    """Create the schema, then let env seed the settings exactly once."""
    with write(conn):
        conn.executescript(SCHEMA)
        _add_missing_columns(conn)
        if config is not None:
            for key, value in config.seed_values().items():
                conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                             (key, str(value)))


@contextmanager
def write(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """One transaction per outermost block; nested calls join the caller's.

    Explicit BEGIN IMMEDIATE so a writer takes the lock up front (no upgrade
    deadlock on WAL), and so a sync page is one atomic unit.
    """
    with WRITE_LOCK:
        if conn.in_transaction:
            yield conn
            return
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.rollback()
            raise
        else:
            conn.commit()


# --------------------------------------------------------------------- runs


def start_run(conn: sqlite3.Connection, kind: str, now: int | None = None) -> int:
    now = int(now if now is not None else time.time())
    with write(conn):
        cur = conn.execute("INSERT INTO sync_runs (kind, started_at) VALUES (?, ?)",
                           (kind, now))
        return int(cur.lastrowid)


def finish_run(conn: sqlite3.Connection, run_id: int, *, pages: int = 0,
               posts_added: int = 0, stories_added: int = 0,
               error: str | None = None, now: int | None = None) -> None:
    now = int(now if now is not None else time.time())
    with write(conn):
        conn.execute(
            "UPDATE sync_runs SET finished_at=?, duration_ms=?, pages=?, posts_added=?,"
            " stories_added=?, error=? WHERE id=?",
            (now, (now - _run_started(conn, run_id)) * 1000, pages, posts_added,
             stories_added, error, run_id))


def _run_started(conn: sqlite3.Connection, run_id: int) -> int:
    row = conn.execute("SELECT started_at FROM sync_runs WHERE id=?", (run_id,)).fetchone()
    return int(row["started_at"]) if row else 0


def latest_finished_run(conn: sqlite3.Connection) -> int:
    """Snapshot: closed and not recovered. A crashed run's posts stay invisible."""
    row = conn.execute("SELECT MAX(id) AS id FROM sync_runs WHERE finished_at IS NOT NULL"
                       " AND recovered = 0").fetchone()
    return int(row["id"] or 0)


def close_orphaned_runs(conn: sqlite3.Connection, now: int | None = None,
                        older_than: int = 0) -> int:
    """`older_than` keeps a live run from being closed by a concurrent starter."""
    now = int(now if now is not None else time.time())
    with write(conn):
        cur = conn.execute(
            "UPDATE sync_runs SET finished_at=?, recovered=1, error=COALESCE(error,'crash')"
            " WHERE finished_at IS NULL AND started_at <= ?", (now, now - older_than))
        return cur.rowcount


# ----------------------------------------------------------------- accounts


def upsert_accounts(conn: sqlite3.Connection,
                    accounts: Iterable[AccountDTO]) -> None:
    with write(conn):
        for a in accounts:
            conn.execute(
                "INSERT INTO accounts (pk, username, full_name, pic_url, is_following, muted)"
                " VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(pk) DO UPDATE SET username=excluded.username,"
                " full_name=excluded.full_name, pic_url=excluded.pic_url,"
                " is_following=excluded.is_following",
                (a.pk, a.username, a.full_name, a.pic_url,
                 int(a.is_following), int(a.muted)))


def reconcile_follows(conn: sqlite3.Connection, current_pks: Sequence[str]) -> int:
    """Mark accounts no longer in the follow list; keeps their posts and history."""
    with write(conn):
        if not current_pks:
            cur = conn.execute(
                "UPDATE accounts SET is_following=0 WHERE is_following=1")
            return cur.rowcount
        marks = ",".join("?" * len(current_pks))
        conn.execute(f"UPDATE accounts SET is_following=1 WHERE pk IN ({marks})",
                     tuple(current_pks))
        cur = conn.execute(
            f"UPDATE accounts SET is_following=0 WHERE is_following=1 AND pk NOT IN ({marks})",
            tuple(current_pks))
        return cur.rowcount


def set_muted(conn: sqlite3.Connection, account_pk: str, muted: bool) -> None:
    with write(conn):
        conn.execute("UPDATE accounts SET muted=? WHERE pk=?", (int(muted), account_pk))


# -------------------------------------------------------------------- posts


def upsert_post(conn: sqlite3.Connection, post: PostDTO, run_id: int,
                raw_z: bytes | None = None) -> bool:
    """True when the post is new to us. Existing rows keep first_seen_sync."""
    with write(conn):
        links = json.dumps(post.links or [], ensure_ascii=False)
        cur = conn.execute(
            "INSERT OR IGNORE INTO posts (pk, account_pk, code, media_type, product_type,"
            " kind, caption, taken_at, like_count, comment_count, permalink,"
            " first_seen_sync, raw_z, links) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (post.pk, post.account_pk, post.code, post.media_type, post.product_type,
             post.kind, post.caption, post.taken_at, post.like_count,
             post.comment_count, post.permalink, run_id, raw_z, links))
        if cur.rowcount:
            _upsert_resources(conn, post)
            return True
        conn.execute("UPDATE posts SET like_count=?, comment_count=?, caption=?,"
                     " code=COALESCE(?, code), permalink=COALESCE(?, permalink),"
                     " links=? WHERE pk=?",
                     (post.like_count, post.comment_count, post.caption, post.code,
                      post.permalink, links, post.pk))
        _upsert_resources(conn, post)
        return False


def _upsert_resources(conn: sqlite3.Connection, post: PostDTO) -> None:
    for r in post.resources:
        conn.execute(
            "INSERT INTO media_resources (post_pk, idx, type, src_url, poster_url, w, h,"
            " duration) VALUES (?,?,?,?,?,?,?,?)"
            " ON CONFLICT(post_pk, idx) DO UPDATE SET type=excluded.type,"
            " src_url=excluded.src_url, poster_url=excluded.poster_url,"
            " w=excluded.w, h=excluded.h, duration=excluded.duration",
            (post.pk, r.idx, r.type, r.src_url, r.poster_url, r.w, r.h, r.duration))


def post_resources(conn: sqlite3.Connection, post_pk: str) -> list[sqlite3.Row]:
    return list(conn.execute(
        "SELECT * FROM media_resources WHERE post_pk=? ORDER BY idx", (post_pk,)))


def mark_seen(conn: sqlite3.Connection, pks: Sequence[str], session_id: int,
              now: int | None = None) -> int:
    """First read wins: seen_at is never overwritten."""
    if not pks:
        return 0
    now = int(now if now is not None else time.time())
    with write(conn):
        cur = conn.execute(
            "UPDATE posts SET seen_at=?, seen_session=?"
            " WHERE seen_at IS NULL AND pk IN (%s)" % ",".join("?" * len(pks)),
            (now, session_id, *pks))
        return cur.rowcount


# -------------------------------------------------------------------- stories


def upsert_story(conn: sqlite3.Connection, story: StoryDTO) -> bool:
    now = int(time.time())
    with write(conn):
        links = json.dumps(story.links or [], ensure_ascii=False)
        cur = conn.execute(
            "INSERT OR IGNORE INTO stories (pk, account_pk, media_type, taken_at,"
            " expiring_at, src_url, thumb_url, duration, fetched_at, links)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (story.pk, story.account_pk, story.media_type, story.taken_at,
             story.expiring_at, story.src_url, story.thumb_url, story.duration, now,
             links))
        if not cur.rowcount:
            conn.execute("UPDATE stories SET expiring_at=?, src_url=COALESCE(?,src_url),"
                         " thumb_url=COALESCE(?,thumb_url), links=? WHERE pk=?",
                         (story.expiring_at, story.src_url, story.thumb_url, links,
                          story.pk))
        return bool(cur.rowcount)


def upsert_ring(conn: sqlite3.Connection, entry: TrayEntry,
                now: int | None = None) -> None:
    now = int(now if now is not None else time.time())
    with write(conn):
        conn.execute(
            "INSERT INTO story_rings (account_pk, latest_reel_media, media_count,"
            " media_ids, ring_thumb, updated_at, stale) VALUES (?,?,?,?,?,?,0)"
            " ON CONFLICT(account_pk) DO UPDATE SET latest_reel_media=excluded.latest_reel_media,"
            " media_count=excluded.media_count, media_ids=excluded.media_ids,"
            " ring_thumb=COALESCE(excluded.ring_thumb, ring_thumb),"
            " updated_at=excluded.updated_at, stale=0",
            (entry.account_pk, entry.latest_reel_media, entry.media_count,
             json.dumps(entry.media_ids), entry.ring_thumb, now))


def mark_story_seen(conn: sqlite3.Connection, pks: Sequence[str], session_id: int | None,
                    now: int | None = None) -> int:
    if not pks:
        return 0
    now = int(now if now is not None else time.time())
    with write(conn):
        cur = conn.execute(
            "UPDATE stories SET seen_at=COALESCE(seen_at,?), seen_session=COALESCE(seen_session,?)"
            " WHERE pk IN (%s)" % ",".join("?" * len(pks)), (now, session_id, *pks))
        return cur.rowcount


# -------------------------------------------------------------- feed sessions


def open_session(conn: sqlite3.Connection, device: str, mode: str,
                 filters: dict, now: int | None = None) -> sqlite3.Row:
    """Freeze mode, snapshot, filters and item_count. One open session per device."""
    if mode not in ("unseen", "all"):
        raise ValueError("mode must be unseen or all")
    now = int(now if now is not None else time.time())
    snapshot = latest_finished_run(conn)
    filters_json = json.dumps(filters, sort_keys=True)
    with write(conn):
        conn.execute("UPDATE feed_sessions SET finished_at=? WHERE device=? AND finished_at IS NULL",
                     (now, device))
        row = _pseudo_session(snapshot, now, mode, filters_json)
        where, params = _membership(row)
        count = conn.execute(
            f"SELECT COUNT(*) AS n FROM posts p JOIN accounts a ON a.pk=p.account_pk"
            f" WHERE {where}", params).fetchone()["n"]
        if not count and filters.get("from"):
            # A quiet day is not an empty app: the window is a filter, and the
            # newest stored post is still the latest thing to show. Dropped here
            # rather than in the client so the count and the rows agree.
            filters = {k: v for k, v in filters.items() if k != "from"}
            filters_json = json.dumps(filters, sort_keys=True)
            row = _pseudo_session(snapshot, now, mode, filters_json)
            where, params = _membership(row)
            count = conn.execute(
                f"SELECT COUNT(*) AS n FROM posts p JOIN accounts a ON a.pk=p.account_pk"
                f" WHERE {where}", params).fetchone()["n"]
        cur = conn.execute(
            "INSERT INTO feed_sessions (device, started_at, snapshot_sync, mode,"
            " filters_json, item_count) VALUES (?,?,?,?,?,?)",
            (device, now, snapshot, mode, filters_json, count))
    return get_session(conn, int(cur.lastrowid))


def _pseudo_session(snapshot: int, started_at: int, mode: str,
                    filters_json: str) -> dict:
    return {"snapshot_sync": snapshot, "started_at": started_at, "mode": mode,
            "filters_json": filters_json}


def get_session(conn: sqlite3.Connection, session_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM feed_sessions WHERE id=?", (session_id,)).fetchone()


def current_session(conn: sqlite3.Connection, device: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM feed_sessions WHERE device=? AND finished_at IS NULL",
                        (device,)).fetchone()


def touch_last_rendered(conn: sqlite3.Connection, session_id: int, pk: str) -> None:
    with write(conn):
        conn.execute("UPDATE feed_sessions SET last_rendered_pk=? WHERE id=?", (pk, session_id))


def _membership(session, reservation: bool = True) -> tuple[str, list]:
    """§Session membership, written once. Every feed query uses this function.

    `reservation=False` drops the first_seen_sync clause for `new_since_start`,
    which by definition counts posts the snapshot deliberately excludes.
    """
    started = int(session["started_at"])
    filters = json.loads(session["filters_json"])
    conds, params = [], []
    if reservation:
        conds.append("p.first_seen_sync <= ?")
        params.append(int(session["snapshot_sync"]))
    conds += ["(p.unseen_at IS NULL OR p.unseen_at < ?)"]
    params.append(started)
    if session["mode"] != "all":
        conds.append("(p.seen_at IS NULL OR p.seen_at >= ?)")
        params.append(started)
    kinds = list(filters.get("kinds") or ["photo", "video", "carousel", "reel", "igtv"])
    conds.append("p.kind IN (%s)" % ",".join("?" * len(kinds)))
    params.extend(kinds)
    if filters.get("account"):
        conds.append("p.account_pk = ?")
        params.append(filters["account"])
    if filters.get("from"):
        conds.append("p.taken_at >= ?")
        params.append(int(filters["from"]))
    if filters.get("to"):
        conds.append("p.taken_at <= ?")
        params.append(int(filters["to"]))
    if filters.get("hide_muted", True):
        conds.append("a.muted = 0")
    return " AND ".join(conds), params


_PAGE_SQL = ("SELECT p.pk, p.account_pk, p.kind, p.caption, p.taken_at, p.code,"
             " p.media_type, p.product_type, p.permalink, p.like_count, p.comment_count,"
             " p.seen_at, p.liked, p.links, p.rowid AS rid FROM posts p"
             " JOIN accounts a ON a.pk = p.account_pk")


def feed_page(conn: sqlite3.Connection, session, limit: int = 20,
              cursor: str | None = None, around_pk: str | None = None
              ) -> tuple[list[sqlite3.Row], str | None]:
    """Keyset page in `taken_at DESC, rowid DESC`. Returns (rows, next_cursor)."""
    where, params = _membership(session)
    where_sql = f" WHERE {where}"
    args = list(params)
    offset = 0
    if cursor:
        taken, _, rid = cursor.partition("_")
        where_sql += " AND (p.taken_at < ? OR (p.taken_at = ? AND p.rowid < ?))"
        args.extend([int(taken), int(taken), int(rid)])
    elif around_pk:
        target = conn.execute(_PAGE_SQL + where_sql + " AND p.pk=?",
                              [*params, around_pk]).fetchone()
        if target is None:
            # Not a member of this session (seen, or filtered out): show that one
            # card instead of silently answering with the first page.
            target = post_by_pk(conn, around_pk)
            if target is not None:
                return [target], None
        if target is not None:
            newer = conn.execute(
                "SELECT COUNT(*) AS n FROM posts p JOIN accounts a ON a.pk=p.account_pk"
                + where_sql + " AND (p.taken_at > ? OR (p.taken_at = ? AND p.rowid > ?))",
                [*params, target["taken_at"], target["taken_at"], target["rid"]]
            ).fetchone()["n"]
            # ponytail: OFFSET only on the around_pk path, bounded to a page
            # boundary. Swap for a keyset seek if random access ever gets big.
            offset = (newer // limit) * limit
    sql = (_PAGE_SQL + where_sql + " ORDER BY p.taken_at DESC, p.rowid DESC LIMIT ?"
           + (" OFFSET ?" if offset else ""))
    args.append(limit + 1)
    if offset:
        args.append(offset)
    rows = list(conn.execute(sql, args))
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = f"{last['taken_at']}_{last['rid']}"
    return rows, next_cursor


def older_page(conn: sqlite3.Connection, limit: int = 20, cursor: str | None = None,
               hide_muted: bool = True) -> tuple[list[sqlite3.Row], str | None]:
    """Older posts from accounts you follow, session and snapshot ignored.

    This is the "keep scrolling" list: it exists so the end of a finite session
    is a choice, not a wall. It only knows what the sweep has stored, so it runs
    out where the sweep's history runs out — which is honest, and visible.
    """
    where = ["a.is_following = 1"]
    args: list = []
    if hide_muted:
        where.append("a.muted = 0")
    # Only what we can actually show: an instagram URL dies within a day, so a
    # post whose bytes were never cached is a black card with a retry that can
    # never work. The archive ends where the cached media ends.
    # ponytail: a LIKE per row; index media_cache(kind, ref) if the archive ever
    # grows past a few thousand files.
    where.append("EXISTS (SELECT 1 FROM media_cache m"
                 " WHERE m.kind = 'post' AND m.ref LIKE p.pk || ':%')")
    if cursor:
        taken, _, rid = cursor.partition("_")
        where.append("(p.taken_at < ? OR (p.taken_at = ? AND p.rowid < ?))")
        args.extend([int(taken), int(taken), int(rid)])
    rows = list(conn.execute(
        _PAGE_SQL + " WHERE " + " AND ".join(where)
        + " ORDER BY p.taken_at DESC, p.rowid DESC LIMIT ?", [*args, limit + 1]))
    nxt = None
    if len(rows) > limit:
        rows = rows[:limit]
        nxt = f"{rows[-1]['taken_at']}_{rows[-1]['rid']}"
    return rows, nxt


def session_counts(conn: sqlite3.Connection, session) -> dict:
    """Every number in the session card is derived from the predicate, never stored."""
    where, params = _membership(session)
    row = conn.execute(
        f"SELECT COUNT(*) AS remaining,"
        f" SUM(CASE WHEN p.seen_at >= ? THEN 1 ELSE 0 END) AS consumed"
        f" FROM posts p JOIN accounts a ON a.pk=p.account_pk WHERE {where}",
        [int(session["started_at"]), *params]).fetchone()
    new_where, new_params = _membership(session, reservation=False)
    newer = conn.execute(
        f"SELECT COUNT(*) AS n FROM posts p JOIN accounts a ON a.pk=p.account_pk"
        f" WHERE {new_where} AND p.first_seen_sync > ?",
        [*new_params, int(session["snapshot_sync"])]).fetchone()["n"]
    item_count = int(session["item_count"])
    consumed = int(row["consumed"] or 0)
    return {
        "item_count": item_count,
        "consumed": consumed,
        "remaining": max(0, item_count - consumed),
        "new_since_start": int(newer or 0),
    }


def unseen_counts(conn: sqlite3.Connection, hide_muted: bool = True) -> dict:
    sql = ("SELECT COUNT(*) AS posts, COUNT(DISTINCT p.account_pk) AS accounts"
           " FROM posts p JOIN accounts a ON a.pk=p.account_pk"
           " WHERE p.seen_at IS NULL AND a.is_following=1")
    if hide_muted:
        sql += " AND a.muted=0"
    row = conn.execute(sql).fetchone()
    return {"posts": int(row["posts"]), "accounts": int(row["accounts"])}


# ------------------------------------------------------------------ retention


def retention(conn: sqlite3.Connection, now: int | None = None,
              media_retention_days: int = 30) -> dict:
    """§Retention. Bytes on disk are the media module's job; this prunes rows."""
    now = int(now if now is not None else time.time())
    raw_cutoff = now - media_retention_days * 86400
    session_cutoff = now - 90 * 86400
    stats: dict[str, int] = {}
    with write(conn):
        stats["raw_nulled"] = conn.execute(
            "UPDATE posts SET raw_z=NULL WHERE raw_z IS NOT NULL AND taken_at < ?",
            (raw_cutoff,)).rowcount
        stats["media_released"] = conn.execute(
            "UPDATE stories SET media_ref=NULL, unavailable_at=?,"
            " raw_z=NULL WHERE expiring_at < ? AND unavailable_at IS NULL",
            (now, now)).rowcount
        stats["sessions_deleted"] = conn.execute(
            "DELETE FROM feed_sessions WHERE finished_at IS NOT NULL AND started_at < ?",
            (session_cutoff,)).rowcount
        stats["runs_deleted"] = conn.execute(
            "DELETE FROM sync_runs WHERE finished_at IS NOT NULL AND finished_at < ?",
            (session_cutoff,)).rowcount
    return stats


# ------------------------------------------------------------------- reads


def post_by_pk(conn: sqlite3.Connection, pk: str) -> sqlite3.Row | None:
    return conn.execute(_PAGE_SQL + " WHERE p.pk=?", (pk,)).fetchone()


def account_detail(conn: sqlite3.Connection, pk: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT a.*,"
        " (SELECT COUNT(*) FROM posts p WHERE p.account_pk=a.pk) AS posts,"
        " (SELECT COUNT(*) FROM posts p WHERE p.account_pk=a.pk AND p.seen_at IS NULL)"
        "   AS unseen_posts,"
        " (SELECT MAX(p.taken_at) FROM posts p WHERE p.account_pk=a.pk) AS newest_post_at"
        " FROM accounts a WHERE a.pk=?", (pk,)).fetchone()


# ------------------------------------------------------------------ stories


def story_rings(conn: sqlite3.Connection, hide_muted: bool = True) -> list[dict]:
    """One row per tray entry: tier-1 liveness plus tier-2 counts where known.

    `known` is a freshness test, not a fetch test: rows captured before the last
    ring update are stale, and reporting 0 unseen for a visible ring is the lie
    the design forbids.
    """
    now = int(time.time())
    sql = ("SELECT r.*, a.username, a.muted, a.local_done_upto, a.story_item_count,"
           " (SELECT MAX(s.fetched_at) FROM stories s WHERE s.account_pk=r.account_pk)"
           "   AS newest_fetch,"
           " (SELECT COUNT(*) FROM stories s WHERE s.account_pk=r.account_pk"
           "   AND s.seen_at IS NULL AND s.expiring_at > ?"
           "   AND s.unavailable_at IS NULL) AS segments_unseen,"
           " (SELECT COUNT(*) FROM stories s WHERE s.account_pk=r.account_pk"
           "   AND s.expiring_at > ?"
           "   AND s.unavailable_at IS NULL) AS segments_live"
           " FROM story_rings r JOIN accounts a ON a.pk=r.account_pk"
           " WHERE a.is_following=1")
    args: list = [now, now]
    if hide_muted:
        sql += " AND a.muted=0"
    rows = []
    for r in conn.execute(sql + " ORDER BY r.latest_reel_media DESC", args):
        known = bool(r["newest_fetch"]) and r["newest_fetch"] >= r["updated_at"]
        unseen = (r["latest_reel_media"] or 0) > (r["local_done_upto"] or 0)
        rows.append({
            "account_pk": r["account_pk"], "username": r["username"],
            "latest_reel_media": r["latest_reel_media"],
            "media_count": r["media_count"],
            "media_ids": json.loads(r["media_ids"] or "[]"),
            "expiring_at": _ring_expiring(conn, r["account_pk"]),
            "ring_thumb": f"/api/media/ring/{r['account_pk']}" if r["ring_thumb"] else None,
            "updated_at": r["updated_at"],
            "unseen": unseen, "known": known,
            "segments_unseen": int(r["segments_unseen"] or 0),
            "segments_live": int(r["segments_live"] or 0),
        })
    return rows


def _ring_expiring(conn: sqlite3.Connection, account_pk: str) -> int | None:
    row = conn.execute("SELECT MAX(expiring_at) AS e FROM stories WHERE account_pk=?",
                       (account_pk,)).fetchone()
    return int(row["e"]) if row and row["e"] else None


def story_counts(conn: sqlite3.Connection, session=None) -> dict:
    rings = story_rings(conn, hide_muted=_hide_muted(conn))
    now = int(time.time())
    accounts_unseen = sum(1 for r in rings if r["unseen"])
    known = [r for r in rings if r["unseen"] and r["known"]]
    unknown = [r for r in rings if r["unseen"] and not r["known"]]
    segments = sum(r["segments_unseen"] for r in known)
    segments += sum(int(r["media_count"] or 0) for r in unknown)
    seen_in_session = 0
    if session is not None:
        seen_in_session = conn.execute(
            "SELECT COUNT(*) AS n FROM stories WHERE seen_at >= ?",
            (int(session["started_at"]),)).fetchone()["n"]
    return {
        "accounts_unseen": accounts_unseen,
        "segments_unseen": int(segments),
        "segments_known_accounts": len(known),
        "segments_unknown_accounts": len(unknown),
        "seen_in_session": int(seen_in_session),
    }


def _hide_muted(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT value FROM settings WHERE key='hide_muted'").fetchone()
    return row is None or row["value"] == "1"


def stories_for_account(conn: sqlite3.Connection, account_pk: str) -> list[sqlite3.Row]:
    return list(conn.execute(
        "SELECT * FROM stories WHERE account_pk=? ORDER BY taken_at", (account_pk,)))


def account_ring(conn: sqlite3.Connection, account_pk: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM story_rings WHERE account_pk=?",
                        (account_pk,)).fetchone()


def mark_rings_stale(conn: sqlite3.Connection, keep: Sequence[str]) -> int:
    """Step 3 of the cycle: a ring not returned this time is offline, not deleted."""
    with write(conn):
        if not keep:
            return conn.execute("UPDATE story_rings SET stale=1 WHERE stale=0").rowcount
        marks = ",".join("?" * len(keep))
        return conn.execute(
            f"UPDATE story_rings SET stale=1 WHERE stale=0 AND account_pk NOT IN ({marks})",
            tuple(keep)).rowcount


def set_local_done(conn: sqlite3.Connection, account_pk: str,
                   upto: int | None = None) -> int:
    ring = account_ring(conn, account_pk)
    value = int(upto if upto is not None else (ring["latest_reel_media"] if ring else 0) or 0)
    with write(conn):
        conn.execute("UPDATE accounts SET local_done_upto=? WHERE pk=?", (value, account_pk))
    return value


# ----------------------------------------------------------------- settings


SETTING_RANGES = {
    "sync_interval": (300, 86400),
    "view_threshold_ms": (0, 10000),
    "story_auto_advance_accounts": (0, 1),
    "hide_muted": (0, 1),
}


def settings_get(conn: sqlite3.Connection) -> dict:
    out: dict = {}
    for row in conn.execute("SELECT key, value FROM settings ORDER BY key"):
        out[row["key"]] = row["value"]
    return out


def open_sessions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute(
        "SELECT id, device, mode, started_at FROM feed_sessions WHERE finished_at IS NULL"
        " ORDER BY started_at DESC"))


# --------------------------------------------------------------------- meta


def meta_json(conn: sqlite3.Connection, key: str, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_meta_json(conn: sqlite3.Connection, key: str, value) -> None:
    with write(conn):
        conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)"
                     " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (key, json.dumps(value)))


# ------------------------------------------------------------------- backup


def backup(config, conn: sqlite3.Connection, keep: int = 7,
           now: int | None = None) -> dict:
    """One consistent snapshot via sqlite's own API; same volume, stated in README."""
    now = int(now if now is not None else time.time())
    folder = Path(config.backup_dir)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"00sgram-{now}.sqlite3"
    tmp = dest.with_name(dest.name + ".tmp")
    with WRITE_LOCK:
        target = sqlite3.connect(str(tmp))
        try:
            conn.backup(target)
        finally:
            target.close()
    tmp.replace(dest)
    try:
        os.chmod(dest, 0o600)
    except OSError:
        pass
    size = dest.stat().st_size
    with write(conn):
        conn.execute("INSERT INTO backups (created_at, path, bytes, ok) VALUES (?,?,?,1)",
                     (now, str(dest), size))
        old = [r["id"] for r in conn.execute(
            "SELECT id FROM backups WHERE ok=1 ORDER BY created_at DESC, id DESC"
            " LIMIT -1 OFFSET ?", (keep,))]
        if old:
            marks = ",".join("?" * len(old))
            conn.execute(f"DELETE FROM backups WHERE id IN ({marks})", tuple(old))
    return {"created_at": now, "path": str(dest), "bytes": size}


def storage_bytes(conn: sqlite3.Connection, db_file: Path | str) -> dict:
    media = conn.execute("SELECT COALESCE(SUM(bytes),0) AS n FROM media_cache").fetchone()["n"]
    db = 0
    for suffix in ("", "-wal", "-shm"):
        try:
            db += os.path.getsize(f"{db_file}{suffix}")
        except OSError:
            pass
    return {"media_bytes": int(media), "db_bytes": int(db)}


# ------------------------------------------------------------------ telegram


def map_ig_message(conn: sqlite3.Connection, chat_id: str, tg_msg_id,
                   ig_id: str, ig_msg_id: str, now: int | None = None) -> None:
    """Remember which Telegram message carries which Instagram message."""
    if not tg_msg_id:
        return
    with write(conn):
        conn.execute(
            "INSERT OR REPLACE INTO ig_sent_map (chat_id, tg_msg_id, ig_id,"
            " ig_msg_id, created_at) VALUES (?,?,?,?,?)",
            (str(chat_id), str(tg_msg_id), str(ig_id), str(ig_msg_id),
             int(now if now is not None else time.time())))


def ig_message_for(conn: sqlite3.Connection, chat_id: str,
                   tg_msg_id) -> tuple[str, str] | None:
    row = conn.execute(
        "SELECT ig_id, ig_msg_id FROM ig_sent_map WHERE chat_id=? AND tg_msg_id=?",
        (str(chat_id), str(tg_msg_id))).fetchone()
    return (row["ig_id"], row["ig_msg_id"]) if row else None


def queue_reaction(conn: sqlite3.Connection, chat_id: str, tg_msg_id,
                   emoji: str, now: int | None = None,
                   table: str = "ig_reacts") -> None:
    _reaction_table(table)
    with write(conn):
        conn.execute(
            f"INSERT INTO {table} (chat_id, tg_msg_id, emoji, at, done)"
            " VALUES (?,?,?,?,0)",
            (str(chat_id), str(tg_msg_id), emoji or "",
             int(now if now is not None else time.time())))


def next_reaction(conn: sqlite3.Connection, table: str = "ig_reacts"):
    _reaction_table(table)
    return conn.execute(
        f"SELECT * FROM {table} WHERE done=0 ORDER BY id LIMIT 1").fetchone()


def finish_reaction(conn: sqlite3.Connection, row_id: int,
                    error: str = "", table: str = "ig_reacts") -> None:
    _reaction_table(table)
    with write(conn):
        conn.execute(f"UPDATE {table} SET done=1, error=? WHERE id=?",
                     (error or None, int(row_id)))


def _reaction_table(table: str) -> None:
    """The table name comes from a caller, so it is a two-name whitelist, not a
    string to format into SQL."""
    if table not in ("ig_reacts", "wa_reacts"):
        raise ValueError(f"unknown reaction table {table!r}")


def save_tg_message(conn: sqlite3.Connection, row: dict) -> None:
    """One message plus its chat row. An edit is the same message (chat_id, msg_id)."""
    links = json.dumps(row.get("links") or [], ensure_ascii=False)
    with write(conn):
        conn.execute(
            "INSERT INTO tg_messages (chat_id, msg_id, at, mine, who, kind, text,"
            " links, thread_id) VALUES (?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(chat_id, msg_id) DO UPDATE SET text=excluded.text,"
            " links=excluded.links, at=excluded.at, kind=excluded.kind,"
            " who=excluded.who, mine=excluded.mine,"
            " thread_id=COALESCE(excluded.thread_id, thread_id)",
            (row["chat_id"], row["msg_id"], int(row["at"]), int(row.get("mine") or 0),
             row.get("who"), row.get("kind_msg"), row.get("text"), links,
             row.get("thread_id")))
        # Never touches read_at: saving a message must not mark a chat unread.
        conn.execute(
            "INSERT INTO tg_chats (chat_id, title, kind) VALUES (?,?,?)"
            " ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title, kind=excluded.kind",
            (row["chat_id"], row.get("title"), row.get("kind")))


def tg_chats(conn: sqlite3.Connection, limit: int = 40) -> list[sqlite3.Row]:
    """Chats by last message (newest first, SQLite sorts NULL last in DESC)."""
    return list(conn.execute(
        "SELECT c.chat_id, c.title, c.kind, c.read_at,"
        " (SELECT COUNT(*) FROM tg_messages m WHERE m.chat_id=c.chat_id AND m.mine=0"
        "   AND m.at > COALESCE(c.read_at, 0)) AS unread,"
        " l.at AS last_at, l.text AS last_text, l.kind AS last_kind"
        " FROM tg_chats c"
        " LEFT JOIN tg_messages l ON l.id = (SELECT m2.id FROM tg_messages m2"
        "   WHERE m2.chat_id=c.chat_id ORDER BY m2.at DESC, m2.id DESC LIMIT 1)"
        " ORDER BY l.at DESC, c.chat_id LIMIT ?", (limit,)))


def ig_thread_id(conn: sqlite3.Connection, name: str,
                 ig_id: str = "") -> int | None:
    """The Telegram topic for a conversation, by Instagram thread id first.

    The id survives a rename on either side; the name is only a fallback for
    rows written before the id was known.
    """
    if ig_id:
        row = conn.execute("SELECT thread_id FROM ig_threads WHERE ig_id=?",
                           (str(ig_id),)).fetchone()
        if row:
            return int(row["thread_id"])
    row = conn.execute("SELECT thread_id FROM ig_threads WHERE name=?",
                       (name,)).fetchone()
    return int(row["thread_id"]) if row else None


def save_ig_thread(conn: sqlite3.Connection, name: str, thread_id: int,
                   title: str = "", now: int | None = None,
                   ig_id: str = "") -> None:
    with write(conn):
        conn.execute(
            "INSERT INTO ig_threads (name, thread_id, title, created_at, ig_id)"
            " VALUES (?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET"
            " thread_id=excluded.thread_id, title=excluded.title,"
            " ig_id=COALESCE(NULLIF(excluded.ig_id,''), ig_threads.ig_id)",
            (name, int(thread_id), title or name,
             int(now if now is not None else time.time()),
             str(ig_id or "")))


# ------------------------------------------------------------------ whatsapp


def wa_thread_id(conn: sqlite3.Connection, name: str) -> int | None:
    """The Telegram topic for a WhatsApp conversation. The name is the only key
    there is: WhatsApp Web never shows a chat id."""
    row = conn.execute("SELECT thread_id FROM wa_chats WHERE name=?",
                       (name,)).fetchone()
    return int(row["thread_id"]) if row else None


def wa_name(conn: sqlite3.Connection, thread_id) -> str | None:
    """The conversation a topic belongs to. None for General, or a topic we did
    not make — writing there would be guessing at a recipient."""
    if not thread_id:
        return None
    row = conn.execute("SELECT name FROM wa_chats WHERE thread_id=?",
                       (int(thread_id),)).fetchone()
    return row["name"] if row else None


def save_wa_thread(conn: sqlite3.Connection, name: str, thread_id: int,
                   is_self: bool = False, now: int | None = None) -> None:
    with write(conn):
        conn.execute(
            "INSERT INTO wa_chats (name, thread_id, is_self, created_at)"
            " VALUES (?,?,?,?) ON CONFLICT(name) DO UPDATE SET"
            " thread_id=excluded.thread_id, is_self=excluded.is_self",
            (name, int(thread_id), int(is_self),
             int(now if now is not None else time.time())))


def wa_mark(conn: sqlite3.Connection, name: str) -> dict:
    """What we know about a conversation: relayed ids and the list-row triple.

    Empty dict means never read. `ids` empty means "known, nothing read yet".
    """
    row = conn.execute("SELECT * FROM wa_marks WHERE name=?", (name,)).fetchone()
    if row is None:
        return {}
    return {"ids": json.loads(row["ids"] or "[]"),
            "preview": row["preview"] or "", "ts": row["ts"] or "",
            "unread": row["unread"] or "", "pending": bool(row["pending"])}


def save_wa_mark(conn: sqlite3.Connection, name: str, ids: Sequence[str],
                 preview: str = "", ts: str = "", unread: str = "",
                 now: int | None = None, keep: int = 200,
                 pending: bool = False) -> None:
    """Newest `keep` ids. A conversation's history in Telegram is not a ledger to
    replay, so the tail is all the dedup this needs."""
    tail = list(dict.fromkeys(str(i) for i in ids))[-keep:]
    with write(conn):
        conn.execute(
            "INSERT INTO wa_marks (name, ids, preview, ts, unread, pending,"
            " updated_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET"
            " ids=excluded.ids, preview=excluded.preview, ts=excluded.ts,"
            " unread=excluded.unread, pending=excluded.pending,"
            " updated_at=excluded.updated_at",
            (name, json.dumps(tail), preview or "", ts or "", unread or "",
             int(pending), int(now if now is not None else time.time())))


def map_wa_message(conn: sqlite3.Connection, chat_id: str, tg_msg_id,
                   name: str, wa_msg_id: str, now: int | None = None,
                   typed: bool = False) -> None:
    """Relayed (`typed=False`) and typed (`typed=True`) are different facts: only
    the second is an echo to suppress."""
    if not tg_msg_id:
        return
    with write(conn):
        conn.execute(
            "INSERT OR REPLACE INTO wa_sent_map (chat_id, tg_msg_id, name,"
            " wa_msg_id, created_at, typed) VALUES (?,?,?,?,?,?)",
            (str(chat_id), str(tg_msg_id), name, str(wa_msg_id),
             int(now if now is not None else time.time()), int(typed)))


def wa_message_for(conn: sqlite3.Connection, chat_id: str,
                   tg_msg_id) -> tuple[str, str] | None:
    row = conn.execute(
        "SELECT name, wa_msg_id FROM wa_sent_map WHERE chat_id=? AND tg_msg_id=?",
        (str(chat_id), str(tg_msg_id))).fetchone()
    return (row["name"], row["wa_msg_id"]) if row else None


def wa_message_sent(conn: sqlite3.Connection, wa_msg_id: str) -> bool:
    """True when the relay itself typed this message: the echo filter."""
    row = conn.execute(
        "SELECT 1 FROM wa_sent_map WHERE wa_msg_id=? AND typed=1 LIMIT 1",
        (str(wa_msg_id),)).fetchone()
    return row is not None


def tg_thread(conn: sqlite3.Connection, chat_id: str,
              limit: int = 300) -> list[sqlite3.Row]:
    """The newest `limit` messages, oldest first. `links` stays raw JSON text."""
    return list(conn.execute(
        "SELECT * FROM (SELECT * FROM tg_messages WHERE chat_id=?"
        " ORDER BY at DESC, id DESC LIMIT ?) ORDER BY at ASC, id ASC",
        (chat_id, limit)))


def tg_mark_read(conn: sqlite3.Connection, chat_id: str, at: int) -> None:
    with write(conn):
        conn.execute("UPDATE tg_chats SET read_at=MAX(COALESCE(read_at,0), ?)"
                     " WHERE chat_id=?", (int(at), chat_id))


def post_by_code(conn: sqlite3.Connection, code: str) -> sqlite3.Row | None:
    return conn.execute(_PAGE_SQL + " WHERE p.code=? ORDER BY p.rowid DESC LIMIT 1",
                        (code,)).fetchone()


def ensure_account(conn: sqlite3.Connection, pk: str) -> None:
    """A post fetched by link needs its account row for the `accounts` JOIN.

    INSERT OR IGNORE on purpose: a never-swept author shows the pk as its name,
    and a real sweep later fills the row in.
    """
    with write(conn):
        conn.execute("INSERT OR IGNORE INTO accounts (pk, username, is_following, muted)"
                     " VALUES (?,?,1,0)", (pk, pk))
