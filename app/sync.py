"""The only writer that talks to Instagram: cycle, backfill, tray, lazy stories.

One run per ingest path. A page is one transaction. An item is stored only if
its author is in `accounts` — that allowlist is what removes ads from unfollowed
accounts and suggested posts. A crash leaves an open run; the next start closes
it with `recovered = 1`, and snapshots exclude recovered runs, so partial posts
never leak into a session.

The ranked web timeline is thin and unordered (design §Data source), so the stop
rule is N consecutive already-stored posts, never a `taken_at` cutoff, and a
repeated cursor ends the cycle instead of looping.

    python -m app.sync --once
"""
from __future__ import annotations

import argparse
import random
import sqlite3
import sys
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

from . import store
from .config import Config
from .provider import ProviderError, SessionExpired

STOP_AFTER = 3            # consecutive already-stored posts (design §Sync model)
BACKOFF_CAP = 6 * 3600
ORPHAN_AFTER = 600        # a run older than this with no finish was a crash
BACKFILL_EVERY = 7 * 86400   # one deep pass a week, ~40 requests
# The per-account sweep is gone on purpose: it needed one request per followed
# account (200+) for the same posts the timeline hands out at ~10 a request.
BACKUP_KEEP = 7


class Syncer:
    def __init__(self, config, conn: sqlite3.Connection, provider=None,
                 executor: ThreadPoolExecutor | None = None) -> None:
        self.config = config
        self.conn = conn
        self._provider = provider
        self._connected = False
        self._lock = threading.Lock()
        self._executor = executor or ThreadPoolExecutor(1, thread_name_prefix="sync")

    # ---------------------------------------------------------------- wiring

    @property
    def provider(self):
        if self._provider is None:
            from .provider import get_provider

            self._provider = get_provider(self.config, self.conn)
        return self._provider

    def _connect(self) -> None:
        if self._connected:
            return
        try:
            self.provider.connect()
        except SessionExpired as exc:
            self._session_meta(False, str(exc))
            raise
        except ProviderError as exc:
            self._session_meta(False, str(exc))
            raise
        self._connected = True
        self._session_meta(True, None)

    def _session_meta(self, ok: bool, reason: str | None) -> None:
        prev = store.meta_json(self.conn, "session", {}) or {}
        now = int(time.time())
        store.set_meta_json(self.conn, "session", {
            "session_ok": ok,
            "last_ok_at": now if ok else prev.get("last_ok_at"),
            "failed_at": None if ok else now,
            "reason": reason,
        })

    @property
    def interval(self) -> int:
        """DB first: a Settings change applies without a restart."""
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key='sync_interval'").fetchone()
        try:
            return int(row["value"]) if row else self.config.sync_interval
        except (TypeError, ValueError):
            return self.config.sync_interval

    def allowlist(self) -> set[str]:
        return {r["pk"] for r in self.conn.execute(
            "SELECT pk FROM accounts WHERE is_following=1")}

    def reload_provider(self) -> None:
        """A new cookie pasted in Settings applies without a restart."""
        self._provider = None
        self._connected = False

    @contextmanager
    def borrow(self) -> Iterator[object]:
        """Another thread using the provider (the relay).

        The browser is one page: two navigations at once is a broken scrape, not
        a race. A manual run coalesces instead of waiting, which is why `run`
        takes the lock without blocking.
        """
        with self._lock:
            yield self.provider

    # --------------------------------------------------------------- control

    def run(self, kind: str = "cycle") -> dict:
        """Synchronous one-shot: CLI, scheduler and tests."""
        if not self._lock.acquire(blocking=False):
            return {"kind": kind, "coalesced": True, "pages": 0, "added": 0,
                    "follows": 0, "stopped": "already_running", "error": None}
        try:
            store.close_orphaned_runs(self.conn, older_than=ORPHAN_AFTER)
            return self.backfill() if kind == "backfill" else self.cycle(kind)
        finally:
            self._lock.release()

    def submit(self, kind: str = "manual") -> dict:
        """HTTP path: 202 now, work on the sync executor. Never blocks."""
        if not self._lock.acquire(blocking=False):
            return {"run_id": None, "coalesced": True}
        try:
            run_id = store.start_run(self.conn, kind)
            self._executor.submit(self._started, kind, run_id)
        except Exception:
            self._lock.release()
            raise
        return {"run_id": run_id, "coalesced": False}

    def _started(self, kind: str, run_id: int) -> None:
        try:
            if kind == "backfill":
                self.backfill(run_id)
            else:
                self.cycle(kind, run_id=run_id)
        finally:
            self._lock.release()

    # ----------------------------------------------------------------- cycle

    def cycle(self, kind: str = "cycle", run_id: int | None = None) -> dict:
        run = run_id if run_id is not None else store.start_run(self.conn, kind)
        started = int(time.time())
        pages = added = follows = dropped = 0
        stopped = "max_pages"
        error: str | None = None
        warning: str | None = None
        try:
            self._connect()
            accounts, complete = self.provider.following()
            if complete:
                applied = self._apply_follows(accounts)
                if applied is None:
                    warning = "follow_refresh_incomplete"
                else:
                    follows = applied
            else:
                # Leave flags untouched: a truncated page must never unfollow
                # the tail and empty the allowlist's own input.
                warning = "follow_refresh_incomplete"
            allow = self.allowlist()

            cursor: str | None = None
            seen_cursors: set[str] = set()
            consecutive = 0
            for _ in range(self.config.sync_max_pages):
                page = self.provider.timeline_page(cursor)
                pages += 1
                with store.write(self.conn):        # one page = one transaction
                    for post in page.items:
                        if post.account_pk not in allow:
                            dropped += 1
                            continue
                        new = store.upsert_post(self.conn, post, run)
                        added += int(new)
                        consecutive = 0 if new else consecutive + 1
                        if consecutive >= STOP_AFTER:
                            break
                if consecutive >= STOP_AFTER:
                    stopped = "already_stored"
                    break
                nxt = page.next_max_id
                if not page.more_available or not nxt:
                    stopped = "end_of_feed"
                    break
                if nxt in seen_cursors:
                    # Phase 0's bug: a constant cursor would loop for ever.
                    stopped = "repeated_cursor"
                    break
                seen_cursors.add(nxt)
                cursor = nxt
                if self.config.backfill_sleep:
                    time.sleep(self.config.backfill_sleep)

            entries = self._refresh_tray()
            if entries is None:
                warning = warning or "tray_refresh_incomplete"
            else:
                store.mark_rings_stale(
                    self.conn, [e.account_pk for e in entries])
                self.prune()
        except SessionExpired as exc:
            error, stopped = str(exc), "session_expired"
        except ProviderError as exc:
            error, stopped = str(exc), "error"
        except Exception as exc:                    # noqa: BLE001 - a crash still closes the run
            error, stopped = f"{type(exc).__name__}: {exc}", "error"
        finally:
            store.finish_run(self.conn, run, pages=pages, posts_added=added,
                             error=error or warning)
            self._record_state(started=started, ok=error is None, error=error,
                               pages=pages, added=added)
        return {"kind": kind, "run_id": run, "pages": pages, "added": added,
                "follows": follows, "dropped": dropped, "stopped": stopped,
                "error": error, "warning": warning}

    def _apply_follows(self, accounts) -> int | None:
        """Refuses a truncated list: unfollowing the tail would empty the feed."""
        stored = self.conn.execute(
            "SELECT COUNT(*) AS n FROM accounts WHERE is_following=1").fetchone()["n"]
        if stored and len(accounts) < stored * 0.5:
            return None
        store.upsert_accounts(self.conn, accounts)
        store.reconcile_follows(self.conn, [a.pk for a in accounts])
        return len(accounts)

    # -------------------------------------------------------- tray, backfill

    def tray_with_allowlist(self) -> list:
        entries = self.provider.story_tray()
        allow = self.allowlist()
        return [e for e in entries if e.account_pk in allow]

    def _refresh_tray(self) -> list | None:
        try:
            entries = self.tray_with_allowlist()
        except SessionExpired:
            raise
        except ProviderError:
            return None
        now = int(time.time())
        with store.write(self.conn):
            for entry in entries:
                store.upsert_ring(self.conn, entry, now)
                if entry.media_count is not None:
                    self.conn.execute(
                        "UPDATE accounts SET story_item_count=? WHERE pk=?",
                        (int(entry.media_count), entry.account_pk))
        return entries

    def backfill(self, run_id: int | None = None, pages: int | None = None) -> dict:
        """Walk the timeline *past* what is already stored.

        This replaces the per-account sweep. The sweep asked for 12 posts from
        each of 200 followed accounts — 200 requests — to collect what the
        timeline already returns at roughly ten posts per request, and it needed
        Instagram's `POST /api/graphql` shape with a `doc_id` that rotates, which
        is a moving target nobody can own. The timeline's `max_id` cursor is the
        one primitive that has never moved.

        Difference in kind: the sweep guaranteed "every post from every account",
        this guarantees "a lot of history". The older stream says which one it
        got, and that is the honest trade.
        """
        run = run_id if run_id is not None else store.start_run(self.conn, "backfill")
        started = int(time.time())
        done = added = 0
        stopped, error = "max_pages", None
        limit = pages or self.config.backfill_pages
        try:
            self._connect()
            allow = self.allowlist()
            cursor: str | None = None
            seen_cursors: set[str] = set()
            for _ in range(limit):
                page = self.provider.timeline_page(cursor)
                done += 1
                with store.write(self.conn):        # one page = one transaction
                    for post in page.items:
                        if post.account_pk not in allow:
                            continue
                        added += int(store.upsert_post(self.conn, post, run))
                nxt = page.next_max_id
                if not page.more_available or not nxt:
                    stopped = "end_of_feed"
                    break
                if nxt in seen_cursors:
                    stopped = "repeated_cursor"
                    break
                seen_cursors.add(nxt)
                cursor = nxt
        except SessionExpired as exc:
            error, stopped = str(exc), "session_expired"
        except ProviderError as exc:
            error, stopped = str(exc), "error"
        except Exception as exc:                    # noqa: BLE001 - a crash still closes the run
            error, stopped = f"{type(exc).__name__}: {exc}", "error"
        finally:
            store.finish_run(self.conn, run, pages=done, posts_added=added, error=error)
            self._record_state(started=started, ok=error is None, error=error,
                               pages=done, added=added)
            if error is None:
                state = store.meta_json(self.conn, "sync_state", {}) or {}
                state["last_backfill_at"] = int(time.time())
                store.set_meta_json(self.conn, "sync_state", state)
        return {"kind": "backfill", "run_id": run, "pages": done, "added": added,
                "follows": 0, "stopped": stopped, "error": error}

    def fetch_segments(self, account_pk: str) -> dict:
        """Lazy story fetch; runs on executor B so it never waits for a cycle.

        Calling `user_stories` registers a view — measured, accepted (§Stories).
        """
        run = store.start_run(self.conn, "story_fetch")
        added = segments = 0
        error: str | None = None
        try:
            self._connect()
            stories = self.provider.user_stories(account_pk)
            with store.write(self.conn):
                for story in stories:
                    if story.account_pk != account_pk:
                        continue
                    added += int(store.upsert_story(self.conn, story))
                self.conn.execute(
                    "UPDATE accounts SET story_item_count=? WHERE pk=?",
                    (len(stories), account_pk))
            segments = len(stories)
        except (ProviderError, SessionExpired) as exc:
            error = str(exc)
            raise
        finally:
            store.finish_run(self.conn, run, stories_added=added, error=error)
        return {"added": added, "segments": segments}

    # ---------------------------------------------------------------- prune

    def prune(self) -> dict:
        """Bytes and old rows. Post rows are kept: history depends on them
        (design §Retention says `posts` are indefinite)."""
        now = int(time.time())
        stats = store.retention(self.conn, now=now,
                                media_retention_days=self.config.media_retention_days)
        cutoff = now - self.config.media_retention_days * 86400
        stale = list(self.conn.execute(
            "SELECT id, path FROM media_cache WHERE last_access < ?", (cutoff,)))
        if stale:
            with store.write(self.conn):
                for row in stale:
                    self.conn.execute("DELETE FROM media_cache WHERE id=?", (row["id"],))
            for row in stale:
                try:
                    Path(row["path"]).unlink()
                except OSError:
                    pass
        stats["media_cache_deleted"] = len(stale)
        return stats

    # ---------------------------------------------------------------- state

    def _record_state(self, *, started: int, ok: bool, error: str | None,
                      pages: int, added: int) -> None:
        now = int(time.time())
        state = store.meta_json(self.conn, "sync_state", {}) or {}
        state.update({"last_attempt_at": started, "duration_ms": (now - started) * 1000,
                      "pages": pages, "new_posts": added})
        if ok:
            state.update({"last_success_at": now, "streak": 0,
                          "frozen_until": None, "error": None,
                          "next_sync_at": now + self.interval})
        else:
            streak = int(state.get("streak") or 0) + 1
            challenge = "challenge" in (error or "").lower()
            delay = BACKOFF_CAP if challenge else min(
                self.interval * 2 ** streak, BACKOFF_CAP)
            state.update({"streak": streak, "frozen_until": now + delay,
                          "error": error})
        store.set_meta_json(self.conn, "sync_state", state)


# ---------------------------------------------------------------- scheduler


def next_kind(state: dict, now: float) -> str | None:
    """What the scheduler should run next, or None for "not at all".

    Backfill weekly: it is the only thing that gives the older stream history, so
    it must actually happen — and a failed one does not count as done, because
    `last_backfill_at` is only written on success.

    Paused returns None. Pausing is for a human reason (the account is in a
    security challenge), so nothing else may override it: a stale `frozen_until`
    never expires it, and only `/api/sync/resume` clears it.
    """
    if state.get("paused"):
        return None
    last = int(state.get("last_backfill_at") or state.get("last_sweep_at") or 0)
    return "backfill" if now - last > BACKFILL_EVERY else "cycle"


def scheduler_loop(config, conn: sqlite3.Connection, syncer: Syncer,
                   stop: threading.Event) -> None:
    """Daemon: re-reads the DB interval each iteration, honours a stored freeze."""
    first = True
    while not stop.is_set():
        interval = syncer.interval
        state = store.meta_json(conn, "sync_state", {}) or {}
        frozen = state.get("frozen_until")
        now = int(time.time())
        wait = interval + random.randint(-60, 60) if interval > 120 else interval
        # A restart must not mean "no data for half an hour": sync shortly after
        # boot, then settle into the configured interval.
        if first:
            wait = 15
            first = False
        if frozen and frozen > now:
            wait = min(wait, frozen - now)
        if stop.wait(max(5, wait)):
            return
        state = store.meta_json(conn, "sync_state", {}) or {}
        # Back up first and regardless of freeze: a dead Instagram session must
        # not also mean "no backups".
        _daily_backup(config, conn)
        if (state.get("frozen_until") or 0) > time.time():
            continue
        kind = next_kind(state, time.time())
        if kind:
            syncer.run(kind)


def _daily_backup(config, conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT MAX(created_at) AS t FROM backups WHERE ok=1").fetchone()
    if row and row["t"] and row["t"] > time.time() - 86400:
        return
    try:
        store.backup(config, conn, keep=BACKUP_KEEP)
    except Exception as exc:                 # noqa: BLE001 - record it, keep syncing
        now = int(time.time())
        with store.write(conn):
            conn.execute("INSERT INTO backups (created_at, path, bytes, ok)"
                         " VALUES (?,?,0,0)", (now, f"failed: {type(exc).__name__}"))


def start_scheduler(config, conn: sqlite3.Connection, syncer: Syncer) -> tuple:
    stop = threading.Event()
    thread = threading.Thread(target=scheduler_loop, args=(config, conn, syncer, stop),
                              name="sync-scheduler", daemon=True)
    thread.start()
    return thread, stop


# --------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run one sync cycle and exit.")
    ap.add_argument("--once", action="store_true", help="one cycle, then exit")
    ap.add_argument("--backup", action="store_true", help="one DB snapshot, then exit")
    args = ap.parse_args(argv)
    if not args.once and not args.backup:
        ap.print_usage(sys.stderr)
        return 2
    config = Config.from_env()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    conn = store.connect(store.db_path(config.data_dir))
    store.init(conn, config)
    if args.backup:
        saved = store.backup(config, conn, keep=BACKUP_KEEP)
        print(f"backup path={saved['path']} bytes={saved['bytes']}")
        return 0
    syncer = Syncer(config, conn)
    result = syncer.run("cycle")
    print(f"kind=cycle pages={result['pages']} added={result['added']} "
          f"follows={result['follows']} stopped={result['stopped']}")
    return 1 if result.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
