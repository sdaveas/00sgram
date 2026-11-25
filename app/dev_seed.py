"""Development seeding: fill the DB from MockProvider.

The real ingestion path is sync.py (step 6). This is the dev-only stand-in so
steps 3-5 have a feed to render over the LAN. It creates one closed `manual`
run, so sessions opened afterwards see the posts (the snapshot is a finished
run id) and nothing pretends to be a scheduled cycle.

    python -m app.dev_seed --posts 60
"""
from __future__ import annotations

import argparse
import sys
import time

from . import store
from .config import Config
from .provider import get_provider


def seed(config: Config, pages: int = 4) -> dict:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    conn = store.connect(store.db_path(config.data_dir))
    store.init(conn, config)
    provider = get_provider(config)
    provider.connect()

    run = store.start_run(conn, "manual")
    accounts, complete = provider.following()
    store.upsert_accounts(conn, accounts)

    added = pages_read = 0
    cursor = None
    for _ in range(pages):
        page = provider.timeline_page(cursor)
        pages_read += 1
        for post in page.items:
            added += store.upsert_post(conn, post, run)
        cursor = page.next_max_id
        if not cursor:
            break

    tray = provider.story_tray()
    for entry in tray:
        store.upsert_ring(conn, entry)

    # Segments for every ring but the last, so both tray states are visible:
    # known progress, and the cold account the viewer must open by fetching.
    stories = 0
    for entry in tray[:-1]:
        for story in provider.user_stories(entry.account_pk):
            stories += store.upsert_story(conn, story)

    store.finish_run(conn, run, pages=pages_read, posts_added=added)
    now = int(time.time())
    store.set_meta_json(conn, "sync_state", {
        "last_success_at": now,
        "last_attempt_at": now,
        "new_posts": added, "new_stories": stories,
        "error": None,
    })
    return {"accounts": len(accounts), "complete": complete,
            "pages": pages_read, "posts_added": added, "stories": stories}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pages", type=int, default=4)
    args = ap.parse_args(argv)
    cfg = Config.from_env()
    if cfg.provider != "mock":
        print("refusing: PROVIDER is not mock", file=sys.stderr)
        return 2
    print(seed(cfg, args.pages))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
