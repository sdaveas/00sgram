> Historical: the README as it stood while the project was being built —
> phase logs, decisions and measurements. Kept for the record; setup lives
> in `README.md` now.

# 00sgram

A distraction-free, self-hosted Instagram client. Design doc:
`docs/designs/distraction-free-instagram-client.md`. Requirements: `requirements.md`.

**Status: steps 1-9 of 10 done — API, auth, Docker, every view, media, the real provider + sync,
the MCP server, backups/restore/hardening, a real story video player, likes + story reactions, deep
history backfill, and "keep scrolling older" past the end of a session; 119 tests pass.

`PROVIDER=browser` is the new read path: a real Chromium in the container, logged in once, so no
cookie is ever copied. It is built and tested (timeline, tray, following verified against the live
account). Switching it on needs one interactive login on the Pi
(`docker compose stop web` first, then
`docker run --rm -p 5900:5900 -v /srv/00sgram/data:/data --env-file .env 00sgram:local python -m app.browser_login`;
the window closes itself when the login is saved). Step 10 (the 24 h soak) remains.**

**Writes.** Off by default in spirit, on by request: the heart on a post likes it on Instagram (a
click on the post's own heart — both HTTP like routes are dead for web clients), and
an emoji in the story viewer sends a DM to the author. Both are one deliberate tap, never automatic
and never retried. This raises the account-risk profile of the whole project — say so if you would
rather the heart were local-only.

```
python3 -m venv ~/venvs/00sgram && ~/venvs/00sgram/bin/pip install -r requirements-dev.txt
~/venvs/00sgram/bin/python -m pytest tests -q
```


## Phase 0 log — 2026-11-16

Host: Raspberry Pi (`br3@pi`), Python 3.11.2, venv `~/.venv-00sgram`, session at
`/srv/00sgram/data/session.json` (mode 600).
Provider: `instagrapi` 3.2.15 (latest release). Auth: `login_by_sessionid` with a cookie
grabbed from a browser login on the Mac. **Password login is refused by Instagram**
(`error_type: needs_upgrade`) — not a credentials problem, and unfixable in this version.

```
provider/version: instagrapi 3.2.15 + direct web endpoint, sessionid auth
timeline page 2 differs (y/n), pages for 7 days: MOBILE NO / WEB YES.
  `get_timeline_feed()` (i.instagram.com) jams: next_max_id is byte-identical on every page,
  seen_posts always empty, 3 distinct posts across 6 pages, newest post 3 days stale.
  `GET www.instagram.com/api/v1/feed/timeline/` with the same session advances properly:
  30 distinct posts over 12 pages, dates 2026-11-03..2026-11-16, cursor changes every page.
  Feed is RANKED, not chronological, and ~2.5 posts/page. more_available stayed true at 12 pages.
follows complete (y/n), count: YES, 226 in a single pass, no pagination needed
stories returned (y/n), registers a view (y/n), tray keys observed: YES / YES (verified against
  a control account that stayed unseen) / media_count, media_ids, latest_reel_media, seen,
  expiring_at, user.pk. Tray is paginated: 25 entries + 35 pending reel ids.
paid partnerships seen in timeline (y/n): NO — 0 of 12 items (sample too small; both
  is_paid_partnership and sponsor_tags exist on timeline items)
blockers: none for ingestion. Operational: web sessionid expiry needs a manual re-auth.
```

### What passed

| Claim | Result |
|---|---|
| Session-cookie auth works | yes |
| Follow graph complete and cheap | 226 accounts, 1 call |
| Followed-account stories retrievable | yes |
| Fetching segments registers a view | **yes** — target vanished from the tray, control stayed unseen |
| Tray carries exact segment counts | **yes** — `media_count` on all 25 entries, no fetch needed |
| Media bytes fetchable from the Pi | yes, 265 KB JPEG, signed CDN URL, 200 |
| Per-account post fetch works and is fresh | yes — `user_medias(pk, 3)` returned a post from today |

### What failed, and the substitution

`instagrapi`'s mobile timeline (`i.instagram.com/api/v1/feed/timeline/` via
`get_timeline_feed`) is broken for this session: the cursor never advances. The same
endpoint on `www.instagram.com`, called directly with the session cookie and
`x-ig-app-id: 936619743392459`, paginates normally. Same private API, no new dependency.

Design consequence: `InstagrapiProvider.timeline_page()` calls the web host directly with
`requests` instead of `Client.get_timeline_feed`. Everything above the provider seam is
unchanged. The per-account sweep stays as the completeness backstop, because the web feed
is ranked and therefore incomplete by construction.

### Known operational costs

- **Manual re-auth when the cookie dies.** The sessionid is a browser cookie with a finite
  life (weeks to months, unknown). Password login is blocked, so there is no automatic
  refresh: when it expires the app stalls until the user grabs a new cookie. The UI must
  detect this and say exactly that, not show an empty feed.
- **Ranked, not complete.** The timeline surfaces a ranked subset. The weekly per-account
  sweep is the only path that guarantees "every post from every followed account".
- **226 follows**, not the 148 the design assumed.

## Running (Pi)

```
rsync -a --exclude .env ./ br3@pi:~/00sgram/
ssh br3@pi 'cd ~/00sgram && docker compose up -d --build'
```

- URL: `http://pi:8091` (host 8091 → container 8080; 8080 belongs to `pihole-FTL`).
- `.env` lives on the Pi, mode 600, generated locally. `PROVIDER=mock` shows generated data;
  `PROVIDER=instagrapi` shows your real feed (see below).
- Seed mock data (dev only): `docker compose exec web python -m app.dev_seed --pages 12`.
- One-off sync: `docker compose exec web python -m app.sync --once` prints
  `kind=cycle pages=N added=M follows=K stopped=<rule>`.
- Tests: `~/venvs/00sgram/bin/python -m pytest tests -q`.

## Real provider

Instagram blocks password login from this client (`needs_upgrade`), so the app authenticates with a
`sessionid` cookie. Nothing else is needed.

1. In a browser where you are logged in to Instagram: DevTools → Application → Cookies →
   `https://www.instagram.com` → copy the value of `sessionid`.
2. Open <http://pi:8091/#/settings>, paste it into **Instagram session cookie**, Save. It is stored in
   the database (env is the fallback) and is never returned by any API or shown again.
3. Set `PROVIDER=instagrapi` in `/home/br3/00sgram/.env` and
   `docker compose up -d` (no rebuild needed), then press **Check now** on Sync, or
   `docker compose exec web python -m app.sync --once`.

Symptom of an expired cookie: `/api/status` shows `instagram.reason`, Settings offers the cookie
field again, and Sync shows the failure instead of a fake success. Paste a fresh cookie and retry —
there is no automatic re-login by design.

## MCP

`mcp/mcp_server.py` is a stdio MCP server for the agent: a thin HTTP client of the REST API, with
its own session identity (`X-Device: mcp`). It has no database and no Instagram credentials, and it
opens a feed session by itself when none is open. Add this to the agent's MCP config (Claude Desktop,
Codex, etc.), adjusting `API_BASE` if the Pi moves:

```json
{"mcpServers": {"00sgram": {
  "command": "/Users/stelios/venvs/00sgram/bin/python",
  "args": ["/Users/stelios/Projects/stelios/00sgram/mcp/mcp_server.py"],
  "env": {"API_BASE": "http://pi:8091", "API_TOKEN": "…"}}}}
```

`API_TOKEN` is the same value as `API_TOKEN` in the Pi's `.env` (`/home/br3/00sgram/.env`), not the
dashboard password: `ssh br3@pi 'grep ^API_TOKEN ~/00sgram/.env'`. It is root-equivalent — keep it in
the MCP config (mode 600), never in a shell history.

12 tools: `get_feed`, `get_feed_status`, `get_post`, `mark_post_seen`, `get_accounts`, `get_stories`,
`get_story_queue`, `mark_story_seen`, `get_story_progress`, `get_sync_status`, `request_sync`,
`get_feed_summary`. List results carry `schema_version: 1` and a `next_cursor`; failures come back as
`isError: true` with `{code, message}` and never echo the token.

## Backups and restore

One snapshot a day, kept 7, written by `sqlite3.Connection.backup` into
`/srv/00sgram/data/backups` (mode 600, same volume — stated, not hidden).

```
docker compose exec web python -m app.sync --backup   # path=… bytes=…
```

The scheduler backs up **before** it syncs and regardless of a frozen session, so a dead Instagram
login never also means no backups.

Restore drill, safe to run against a copy:

```
BK=$(ls -t /srv/00sgram/data/backups/*.sqlite3 | head -1)
sudo mkdir -p /srv/00sgram/restore-test && sudo cp "$BK" /srv/00sgram/restore-test/00sgram.sqlite3
sudo chown -R br3:br3 /srv/00sgram/restore-test
docker run -d --name 00sgram-restore-test --env-file .env -e DATA_DIR=/data \
  -p 8092:8080 -v /srv/00sgram/restore-test:/data 00sgram:local
curl -s localhost:8092/api/health
docker rm -f 00sgram-restore-test && sudo rm -rf /srv/00sgram/restore-test
```

To restore for real: `docker compose down`, copy the snapshot over `data/00sgram.sqlite3`, `docker
compose up -d`. The snapshot is a complete database — likes, sessions, rings and settings included.

## Stories viewer

No Instagram chrome: no segmented countdown bars, no tap thirds, no timers. A video segment is a
plain player — play/pause, a seek bar that seeks, elapsed/total, mute — and segments move with the
arrows under the stage (or `↑`/`↓`), accounts with a swipe or `←`/`→`. A video that ends stays put.
Nothing autoplays here: a segment waits for the play button. The one exception in the whole program
is [Browse mode](#browse-mode), where a card's video starts muted — a full-screen feed whose videos
wait for a press is not a feed.

## Browse mode

The second appearance, for anyone who reads this as a feed and not as a 2000 bulletin. **View →
Περιήγηση** (`#/browse`) drops the title bar, the menu bar and the status bar and puts one post on
black:

- swipe up (or `↓`, or scroll down) for the next older post, swipe down (or `↑`) for the newer
  one;
- press the note in a film's transport to ask what it is playing: the film goes to Shazam from the
  server (ffmpeg + [ShazamIO](https://github.com/shazamio/ShazamIO), no key or account) and the answer
  is the track, a copy-the-title button and Spotify's search for it;
- swipe left (or `→`) for the post's other pictures, swipe right (or `←`) for the previous one — the
  second axis never leaves the post;
- captions clamp to two lines and a press opens them; a row of up to five marks
  under the counter shows where in an album you are and how much is to the right;
- a video plays on arrival, loops, and rewinds when you leave the card. It carries its own transport — pause, a
  seek bar, the clock and mute — the same bar for every source, with the description laid out under the
  film instead of over it. Muting or unmuting there writes the program's one audio preference (the same
  `00sgram.muted` the player uses), so unmuting one film is not forgotten by the next;
- the stream is the session's **unseen** posts and stops at the last one. One more move shows the end
  block and one button, **Παλαιότερα…**, which appends ten older posts per press — never more;
- the exit control (or `Escape`) returns to the bulletin and remembers that this device prefers the
  window.

The choice is per device (`localStorage`) and the exit is what changes it back, so a link to
`#/browse` is a decision, not an accident. No like, reaction, comment, follow or Instagram write
lives in the stream; seen is the only thing it records, through the same path the bulletin uses.


## When Instagram challenges the account

A security checkpoint arrives as a 302 to `/challenge/`, not as a JSON error. The web client no
longer chases that redirect, so the sync run says "Instagram is asking for a security check on this
account — finish it in the Instagram app, then paste a fresh sessionid" instead of
`TooManyRedirects`. **Pause sync** on the Sync view stops everything until you resume: a checkpoint
is a human problem, and retrying through it is how a temporary one becomes permanent.

## Deep history

A cycle stops as soon as it meets posts it already has, which is right for "what's new" and useless
for "what came before". So once a week (and on demand, **Fetch older history** on the Sync view, or
`POST /api/sync/backfill`) the scheduler walks the timeline back `BACKFILL_PAGES` pages — 40 pages,
roughly 400 stored posts, 40 requests — and stores everything it meets. `last_backfill_at` is written
only on success, so a dead session retries rather than skipping a week.

This replaced the per-account sweep. The sweep wanted 12 posts from each of 200 accounts: 200
requests for the same posts, and it needed `POST /api/graphql` with a rotating `doc_id`. It is gone.
The honest trade: a lot of history, not every post from every account.

## Past the end of a session## Past the end of a session

The end card has one opt-in: **Keep scrolling older posts**. It reads `GET /api/older`, which is
not session-bound — everything stored from accounts you follow, older than the session's last post,
muted hidden per setting. The session keeps its own numbers; this is labelled as stored history and
ends where the sweep's history ends.

## Reactions

- **Feed:** the ♡ on each post likes it on Instagram (one attempt, no retry, self-reverting with the
  server's message in a toast).
- **Stories:** five emoji under the stage send `direct_send(emoji)` to the author — a real DM, once
  per segment. The row then shows `reacted ❤️` instead of the buttons.

`GET /api/posts/{pk}` reports `liked`; `GET /api/stories/{pk}` reports `reaction`.
