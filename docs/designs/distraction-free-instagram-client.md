# Distraction-Free Instagram Client

Design doc. Version 4. Audience: an implementer with no prior context, and any future
session deciding whether to change this.

Source of truth for requirements: `requirements.md` (sections 1–14).

Version 4 resolves the two structural contradictions that v3 still carried: session membership
(`unseen` was both a frozen and a live predicate) and resume-to-post (the cursor could not find
the page containing the recorded position). It also closes the MCP session identity hole, the
`kind` NULL hole, and the three §10 items that v3 wrongly claimed were satisfiable.

---

## Problem

### What breaks today

Instagram's app and web client are optimised for time-on-app, not for "see what the people I
follow posted, then stop". For one user with an existing account and a normal follow list:

1. **The feed is not theirs.** Reels, "Suggested for you", and sponsored posts are interleaved
   into the timeline. No setting removes them.
2. **There is no end.** Scrolling is unbounded and the feed extends behind the cursor, so the
   user can never be *done*. Nothing says "you have seen everything new".
3. **No durable read-state.** Instagram does not expose which posts the user already scrolled
   past. Switching device loses the user's sense of place.
4. **Duplicates.** The same post reappears across sessions because ranking reshuffles it.
5. **Stories navigation is ambiguous.** The boundary between "next segment of this account" and
   "next account" is not signalled, so taps land on the wrong thing, and going back is
   destructive rather than reversible.
6. **No programmatic surface.** Nothing can ask "what is new, and what have I not read", so no
   agent can act on the feed.

For whom: one person, browsing a home LAN from an iPhone and a MacBook. Not a product for other
users. "A single user who wants to stop" is the whole design target.

### The one hard constraint in the source spec

§3.5: *"Instagram's official API does not provide unrestricted access to the complete home feed
or arbitrary Stories from followed accounts… A successful proof of content acquisition is a
prerequisite for claiming full Instagram functionality."*

Everything in this design is arranged so that the fragile, unofficial ingestion path is small,
isolated, rate-limit-friendly, and replaceable at one seam. §11 puts feasibility validation in
Phase 0 for the same reason.

### Requirements we cannot meet, and the acceptance recorded

Three §10 acceptance items cannot be satisfied by this design. They are listed here rather than
ticked, and the first is a compliance statement, not an engineering shortfall.

**1. "Posts … through a permitted content source" (§10), and §3.5's "must respect applicable
Meta permissions and platform terms."**

Unmet, and unmettable. Instagram offers no permitted mechanism to read a personal home feed.
The chosen provider drives the private mobile API — the same one the official app uses —
through an unofficial library. That is a violation of Instagram's terms of service, not a grey
area. The consequence if detected is account suspension or a permanent ban.

- The user has reviewed this and accepted it. That acceptance is what makes the rest of this
  document legitimate to implement.
- The checkbox must **not** be ticked at sign-off.
- Three design choices follow: read-only traffic (§Read-only), the smallest viable request
  profile (§Sync cycle), and the provider confined behind one interface so it can be removed
  entirely (§Provider abstraction).
- **If a future session is asked to make the app compliant, the answer is that the product's
  core feature must be dropped.** A permitted source cannot serve a personal feed.

**2. "PostgreSQL is not exposed to the LAN" (§10), and §8.2's mandatory component list
(Go API, sync worker, MCP server, PostgreSQL).**

There is no PostgreSQL, no Go service, and no separate sync worker container. The §10 checkbox
is vacuously true and must be read as *"the datastore is not exposed to the LAN"* — satisfied,
because SQLite is a file. §8.2's component list is deviated from deliberately; the reasoning
and the cost are in §Stack decision and Alternatives #2. This is a **requirements deviation, not
a implementation gap**, and §10's Deployment block must be signed off against the deviation.

**3. "Restricted access to administrative operations" (§7) — partially met.**

There is one credential for everything: the same password cookie and the same API token can read
the feed, change settings, mute accounts, and trigger a sync. There is no separate admin
principal. For a single-user app on a home LAN this is the honest minimum, but it is not what
§7 asks for. Deviation recorded; the token's full power is stated in §Auth rather than implied
away.

### What the doc cannot deliver

1. **Instant freshness.** Content appears on a sync cycle, not in real time. Default 30 min.
2. **Segment counts for unopened story accounts.** Counting segments requires fetching them, and
   fetching registers views on Instagram. §3.3 says "number of available Story segments, **if
   known**" — this design takes that qualifier seriously (§Story counting).
3. **Other people's expired stories.** We keep what we captured and nothing else. §3.6's "where
   historical access remains possible" is exactly this limitation.
4. **Guaranteed completeness in extreme cases.** The timeline is ranked and thin (~2.5 posts per
   page, 12 pages did not exhaust 7 days). v6 claimed a weekly per-account sweep closed that gap;
   the browser transport deleted it (see *Deep history, not a sweep*), so the honest statement is
   **"a lot of history, not every post"**. An account can also arrive in a batch rather than one
   at a time.
5. **Account safety.** See Risks. This is the risk accepted above — and it was **hit**: after a
   40-page backfill, Instagram revoked every web session on the account (both the Pi profile and a
   laptop browser) while the phone app stayed signed in. Recovery was one login; the account was
   never locked. Three things were too visible and are now fixed: Playwright's default
   `--enable-automation` flag (it sets `navigator.webdriver`), a phone-sized viewport under a desktop
   user agent, and an unpaced backfill (one request every ~5.5 s). Pacing is `BACKFILL_SLEEP=2`.

### Requirements traceability

| Spec | Covered in |
|---|---|
| §3.1 Dashboard | API `/api/status`, Frontend / Dashboard, Story counting |
| §3.2 Following feed | Sync model, Session membership, Feed API, Frontend / Feed |
| §3.3 Stories | Story model, Story counting, Story states, Frontend / Stories |
| §3.4 Accounts | Follow graph, API `/api/accounts` |
| §3.5 Synchronization | Sync cycle, Provider abstraction, Sync status, Sync control |
| §3.6 Previously viewed | History |
| §3.7 Filters and preferences | Filters, Settings |
| §4 UX | Frontend (incl. desktop layout, iOS video) |
| §5 Data and persistence | Storage, Media, Retention |
| §6 MCP | MCP server |
| §7 Security | Auth, Security posture (with the deviation above) |
| §8 Deployment | Deployment, Backups |
| §9 Non-goals | Out of scope |
| §10 Acceptance | Verification, plus the three deviations above |
| §11 Phases | Order of work |
| §12 Open decisions | Decisions resolved |
| §13 Definition of success | Success criteria |
| §14 Architecture deliverables | §14 deliverable map at the end |

### Success criteria

Done when, on an iPhone over the LAN:

1. Dashboard shows unseen posts, accounts with new posts, accounts with new stories, known
   unseen segments, last successful sync, and session progress — from SQLite, no sync required,
   responsive while a sync runs.
2. Posts are strictly reverse-chronological, exclude every non-followed author and every ad,
   and reach a terminal end-of-session state that names the next sync time.
3. Posts discovered mid-session do not join the current session; they appear in the next one.
4. Killing Safari mid-feed and reopening resumes at the **same post**, with the same counts.
5. Stories: tap left/right moves segments, swipe left/right moves accounts, the account boundary
   is visible *before* the tap, per-segment progress persists, and completing the queue shows an
   explicit end state.
6. A local agent reads and writes viewing state over MCP, including its own feed session, and
   sees exactly what the web UI sees.
7. The Instagram account is not challenged over the first 30 days of operation — an operational
   observation, not a build-time verification.

---

## Technical Plan

### Stack decision, and what it costs

The source spec names Go, React, and PostgreSQL (§8.2, §11) and simultaneously states that
service boundaries are *"architectural decisions"*. The stack is not user-visible; the features
are. **Chosen:** Python 3.11 + FastAPI + SQLite + vanilla JS. **One container**, no build step,
no ORM, no Node on the Pi.

Preserved despite the stack: every §3 functional requirement, MCP in V1, and atomic, durable,
consistent writes — `journal_mode=WAL` with **`synchronous=FULL`**. At ~5 k rows/day the fsync
cost is irrelevant, and `NORMAL` would silently allow loss of the last commits on power loss,
which is the exact failure mode of a Pi. v3 claimed durability while using `NORMAL`; that was
wrong.

Given up:

| Given up | Consequence | Trigger to revisit |
|---|---|---|
| PostgreSQL | One host, one writer, ~5 k rows/day. No concurrent multi-host writers. | A second writer process, or DB over ~2 GB. |
| Go | Python is slower per call; irrelevant at one user. | Never at this scale. |
| React/build step | ~250 lines of hand-rolled view code. | Views exceed ~9, or shared state outgrows one object → Preact + Vite. |
| Separate sync-worker container | Sync runs in its own executor thread inside the API process. A sync crash cannot take down serving (caught and recorded); a hard kill stops sync until restart. | Sync interferes with latency, or needs independent restarts. |

### Shape

```
┌─────────────────────── Pi 5, Docker ────────────────────────┐
│                                                              │
│  uvicorn / FastAPI ──┬── /api/*      JSON (reads: SQLite)    │
│    (one container)   ├── /           static SPA              │
│                      ├── executor A: sync cycles + backups   │
│                      └── executor B: interactive upstream    │
│                              │                               │
│              client_sync ────┴──── client_user               │
│                    └──────► Instagram private API ◄──────┘   │
│                              │                               │
│                        SQLite (WAL) + media files            │
└──────────────────────────────────────────────────────────────┘
        ▲ LAN, signed cookie              ▲ LAN, bearer token
   iPhone / MacBook Safari          mcp_server.py (stdio,
                                    run by the agent on the Mac)
```

### Concurrency

`instagrapi` is synchronous: `requests` plus `time.sleep` inside `delay_range`. A cycle takes
25–60 s.

- **Two executors, created explicitly** — `ThreadPoolExecutor(1)` for sync and backups
  (`loop.run_in_executor(POOL_SYNC, …)`, **not** `asyncio.to_thread`, which always uses the
  default pool) and a second `ThreadPoolExecutor(2)` for user-triggered upstream work.
  Without the second pool, opening stories during a sync would wait behind the whole cycle —
  precisely when a user is most likely to do it.
- **Two `Client` instances, never shared across threads.** `client_sync` and `client_user`, both
  initialised from the same `session.json`. instagrapi's client is not thread-safe; two threads
  sharing one object corrupts its state. Two clients on one session is two requests from one
  device, which is not distinguishable from the app doing the same.
- **One process-wide `threading.Lock` (`WRITE_LOCK`) guards every DB write.** SQLite has one
  writer for the whole database; the lock is what makes "single writer" true rather than
  aspirational.
- **Lock scope rule: network and image work happen outside the lock.** Thumbnail download and
  Pillow downscaling happen before the transaction; only INSERT/UPDATE runs inside it. A lock
  held across network I/O would stall every request.
- One transaction per sync page, never per cycle.
- Reads are lock-free (WAL). `busy_timeout=5000` as a backstop.

Test: 50 concurrent `POST /api/posts/seen` succeed during a mock cycle, and no request's latency
exceeds the cycle's duration (no wall-clock millisecond bound — that assertion fails spuriously on
a loaded Pi and proves nothing about the lock).

### Provider abstraction

```python
# app/provider.py
class Provider(Protocol):
    def connect(self) -> None: ...
    def following(self) -> tuple[list[AccountDTO], bool]: ...   # accounts, complete?
    def timeline_page(self, max_id: str | None) -> Page: ...
    def user_recent(self, account_pk: str, limit: int) -> list[PostDTO]: ...
    def story_tray(self) -> list[TrayEntry]: ...
    def user_stories(self, account_pk: str) -> list[StoryDTO]: ...
    def media_stream(self, url: str, byte_range: str | None) -> Iterator[bytes]: ...
```

- `InstagrapiProvider` — production (`app/instagram.py`).
- `MockProvider` — deterministic synthetic data from a seed (`app/mock.py`). Emits account, post
  and story DTOs **and real media bytes**: JPEGs via Pillow, and a **1.4 KB MP4 embedded as a
  base64 constant in `mock.py`** (generated once with `ffmpeg -f lavfi -i color=c=black:s=320x568:d=3`
  at commit time, so there is no fixture file to lose and no licence question). Needed because
  Order-of-work steps 3–5 and the media tests run entirely on it.
- `HikerProvider` — stub raising `NotImplementedError` (Alternatives #18).

DTOs are plain dataclasses in `app/dtos.py`. No instagrapi type escapes `instagram.py`.

`timeline_page()` is the one method that does not go through `Client`: it issues
`GET https://www.instagram.com/api/v1/feed/timeline/` with the session cookie (§Data source).
The seam is unchanged — callers see a `Page`, not a host.

### Data source: Instagram private API, two hosts

Pinned exactly: `instagrapi==3.2.*` with `pillow>=13,<14` (upstream ties Pillow 13 to a fixed
CVE), and every other dependency pinned in `requirements.txt`. A `python:3.11-slim` rebuild must
not silently change the client that talks to Instagram.

Everything in this section is **measured**, not assumed. Phase 0 ran on 2026-11-16 against the
real account; the log is in `README.md`.

**Authentication is a session cookie, not a password.** `Client.login(username, password)` is
refused by Instagram with `error_type: needs_upgrade` — the app profile instagrapi ships is
rejected on the login endpoint, and 3.2.15 is the latest release. There is no password path and
no fix available upstream.

- One interactive browser login yields the `sessionid` cookie. It lives in `.env` as
  `IG_SESSION_COOKIE` and is exchanged for a session with `Client.login_by_sessionid(cookie)`,
  which writes `$DATA/session.json` (mode 600).
- **No password is stored anywhere**, and `IG_USERNAME`, `IG_PASSWORD`, `IG_2FA_CODE` are gone
  from the config. This is strictly safer than the password design v4 had.
- **Timeline comes from the web host, not `Client.get_timeline_feed`.** Measured: the mobile
  timeline (`i.instagram.com`) jams — `next_max_id` is byte-identical on every page,
  `seen_posts` is always empty, 6 pages yield 3 distinct posts, and the newest post is 3 days
  stale while the account demonstrably has newer ones. The same endpoint on
  `www.instagram.com` with the same cookie and `x-ig-app-id: 936619743392459` paginates
  normally: 30 distinct posts over 12 pages, cursor advancing every page. So `timeline_page()`
  issues `GET https://www.instagram.com/api/v1/feed/timeline/` with `requests`; instagrapi is
  used for follows, stories and tray only. Same private API, no extra dependency.

**The web feed is ranked, not chronological, and thin** — ~2.5 posts per page, and 12 pages had
not exhausted 7 days. Two consequences that are not negotiable:

1. Order is imposed by our own `taken_at DESC, rowid DESC` sort, never by response order.
2. The watermark stop condition is **"N consecutive already-stored posts"**, never "oldest
   `taken_at` below the watermark": a ranked page can carry a brand-new post in its tail, and a
   `taken_at` stop would silently miss it.

Because the feed is a ranked subset, a deep pass over it is **load-bearing for history**, not a
backstop: without one, "keep scrolling older" runs out inside a week of posts. What it cannot do is
guarantee "every post from every followed account" (§3.2) — nothing in a ranked feed can, and the
per-account path that could no longer exists for web clients.

Other measured facts the design depends on:

- `user_following(self_pk, use_cache=False)` returns all **226** follows in a single call.
- `user_medias(pk, amount=3)` returns fresh per-account posts. (`user_recent` in the Provider
  protocol is our name; instagrapi's is `user_medias`, and it rounds `amount` up to a page.)
- `user_stories(pk)` returns segments **and registers a view**. Verified with a control: the
  fetched account vanished from the tray while an untouched one stayed unseen. The lazy-fetch
  design and Alternatives #10 stand.
- **The segment source had to move, twice.** `/api/v1/feed/user/<pk>/reel_media/` died first, then
  `/api/v1/feed/reels_media/?reel_ids=<pk>` began answering **500** to web sessions. The GraphQL
  replacement (`PolarisStoriesV3ReelPage`) carries a `doc_id` that rotates with Instagram's builds.
  What works and cannot rot: `GET /stories/<username>/` ships its own data in a
  `script[type="application/json"]` Relay preloader whose `xdt_api__v1__feed__reels_media` node
  holds every segment, `video_versions` included. The provider reads that blob, so it consumes the
  same bytes the page renders. Two constraints: the route resolves **usernames, never pks**
  (`/stories/<pk>/` is "page isn't available"), so the provider looks the username up in `accounts`;
  and a fetch costs one navigation, so it stays on executor B and stays lazy.
- The tray carries `latest_reel_media`, `media_count`, `media_ids`, `seen`, `expiring_at` and
  `user.pk` **on every entry**, so tier-1 segment counts are exact and need no fetching. It is
  paginated: 25 entries shown plus 35 pending reel ids, so one tray refresh is 2+ requests.
- Media bytes are fetchable from the Pi: signed `scontent-*.cdninstagram.com` URLs, HTTP 200.
- `is_paid_partnership` and `sponsor_tags` both exist on timeline items; 0 were observed in a
  12-item sample, so the drop rule is unexercised but cheap to keep.

**Session lifecycle — the one operational cost that cannot be designed away.**

Measured: Instagram re-issues `ds_user_id` on use with `Max-Age=7776000` — a **90-day sliding
window**, so a session that syncs every 30 minutes never dies of dormancy. What kills it is
server-side invalidation (password change, security checkpoint, a device decision Instagram
makes internally), which arrives with no warning and no expiry signal: the next request simply
returns `login_required`.

Therefore:

- `IG_SESSION_COOKIE` is the only credential, and re-auth is **manual**. The app must never
  pretend otherwise, and must never retry a dead session in a loop.
- `meta['session']` holds `{ok, last_ok_at, failed_at, reason}` and `/api/status` exposes it as
  `instagram` (not `session` — that key is the viewer's feed session), the dashboard shows
  "Instagram session expired — paste a new cookie", and Settings has a field
  that accepts a fresh cookie and hot-swaps it without a restart.
- The first failure date is logged, so the real lifetime is measured rather than guessed.
- `LoginRequired` → mark failed, freeze, surface. One attempt only, never a loop.

**Device identity.** `session.json` is a credential and is excluded from backups. Instead, copy
only the `device_settings` / `uuids` sub-dict into `meta['device']` — **never `authorization` or
`sessionid`** — and re-inject it before building the client, so a restore does not look like a
new device. `client.delay_range = [1.5, 3.5]` for every instagrapi request.

### Read-only, with three explicit exceptions

No comments, uploads, or `story_seen()` calls. Three writes exist because the owner asked for them,
and each is a deliberate tap, never automatic:

| Action | How | Effect visible on Instagram |
|---|---|---|
| like / unlike a post | click the post's own heart | yes, a like |
| react to a story segment | `direct_v2/threads/broadcast/text/` | yes, **a DM to the author** |
| unfollow an account | click the profile header, confirm the dialog | yes, the follow is gone |

The like is a **click, not an API call**, and that is a measured decision. `/api/v1/media/<pk>/like/`
and the newer `/api/v1/web/likes/<pk>/like/` both answer a login redirect even with a live session:
web likes moved to a GraphQL mutation whose `doc_id` rotates with Instagram's builds. A click cannot
rot, and it is the request Instagram expects from a browser. Two traps found the hard way:

- A post page carries **one heart per comment plus the post's own**, all labelled `Like`. Taking the
  first one likes a comment. The post's is the largest (24 px vs 16 px), so the selector takes the
  biggest.
- The heart is not in the DOM at `domcontentloaded`; the page hydrates. The provider waits for it,
  clicks its centre, and then **verifies the `aria-label` flipped to `Unlike`** — a click that
  registers nothing raises rather than reporting success.

Each write is a single attempt, no retry, because a like that may already have landed must not be
sent twice. The UI is optimistic and self-reverting, with the server's
sentence in a toast. Story reactions are stored in `stories.reaction` and refused a second time —
one reaction per segment, one DM per person.

Unfollow is a click for the same reason: the web route is gone, and the confirmation dialog is
part of the flow (`Following` → dialog → `Follow`). It is verified by the header's own label and
mirrored into `accounts.is_following`, which is the column the accounts list filters on — so the
account leaves the list because of the write, not because of a guess. Its single attempt rule is
stricter than the like's: a follow change that may have landed is never repeated.

A story's stickers — mentioned profiles, the song, outbound links, hashtags, places — are read from
the same prefetched payload and stored as `stories.links` (a JSON list of `{kind, label, url,
detail}`). The viewer shows them in a grouped sheet per segment; they are display-only, because
following a sticker is the kind of write this client does not do behind a tap.

`user_stories()` still registers a view when an account is opened; that stays, and it is the main
thing keeping the request profile survivable. Adding writes raises the account-risk profile and the
README says so.

### Sync model: snapshot + watermark, never live proxying

The app never calls Instagram on behalf of a page render. A background thread writes into SQLite;
the API reads only SQLite. Page loads are fast, work while Instagram is unreachable (§3.1, §7), the
feed is finite by construction (§3.2), and request volume is bounded.

**Every ingest path opens its own run.** `sync_runs.kind` ∈ `cycle | sweep | backfill |
story_fetch | manual`; `recovered` flags a run closed after a crash.

1. `INSERT sync_runs(kind, started_at, finished_at=NULL)` → `run_id`.
2. Every post inserted during the run is stamped `first_seen_sync = run_id`.
3. Close the run with `finished_at, duration_ms, pages, posts_added, stories_added, error`.
4. `meta['post_watermark']` advances only on success.

`first_seen_sync` is therefore always a real run id — the weekly sweep and the on-demand story
fetch included. Without this, either the sweep violates `NOT NULL` or it stamps an older run's id
and its posts appear inside an already-open session, destroying the reservation guarantee.

A session snapshots `MAX(id) FROM sync_runs WHERE finished_at IS NOT NULL AND recovered = 0`.
On startup, any run with `finished_at IS NULL` older than 10 minutes is closed with
`recovered = 1, error='interrupted'`; **recovered runs are permanently excluded from snapshots**,
so a `kill -9` mid-cycle cannot leak partial posts into a session.

**Watermark.** `meta['post_watermark']` = highest `taken_at` ingested. The loop stops when a page
has nothing newer than the watermark **and** 3 consecutive posts are already stored.

**Author allowlist.** `accounts` is the allowlist: an item is stored only if its author has
`is_following = 1`. This — not URL or class matching — removes "Suggested for you",
recommendations, and ads from non-followed accounts.

**Ads from followed accounts** are separate: drop an item when `product_type = 'ad'`, or
`is_paid_partnership` is true, or `sponsor_tags` is non-empty. §3.2 lists "sponsored content and
advertisements" as its own exclusion, distinct from "content from accounts you do not follow", so
a followed account's paid post must go too.

**Follow graph** (`following()`), step 0 of every cycle:

- Only apply the diff when the fetch reports **complete** and returned at least 50 % of the stored
  following count. A truncated or rate-limited response otherwise silently unfollows the tail —
  which empties the feed and destroys the allowlist's own input.
- On success: upsert every account (`is_following = 1`), and set `is_following = 0` for rows not
  returned. Rows are kept, so history survives (§3.4: muting and unfollowing never delete content).
- On incomplete: leave flags untouched and record `error='follow_refresh_incomplete'`.
- Without this step a fresh install has an empty feed and a new follow is invisible forever.

**Cycle** (`SYNC_INTERVAL`, default 1800 s per §3.5, ±60 s jitter):

0. `following()` — follow graph refresh.
1. `timeline_page()` from `pull_to_refresh`, paginate with `max_id` until the watermark is
   reached, `more_available` is false, or `SYNC_MAX_PAGES` (10). Filter, stamp, upsert.
   **Backfill** (only when `meta['backfill_done']` is unset) uses `kind='backfill'`, ignores
   `SYNC_MAX_PAGES`, and stops at `taken_at < now - BACKFILL_DAYS`, with a hard ceiling of 50
   pages. Then set `backfill_done`.
2. `story_tray()` — one request for every followed account. **Filter through
   `accounts.is_following = 1`**: the ranked tray can include accounts the user does not follow,
   which would otherwise surface in the Stories overview. Upsert `story_rings` with
   `latest_reel_media`, `media_count` (nullable), `media_ids`, `ring_thumb`, `updated_at`, `stale=0`.
3. Prune, **only if step 2 succeeded**: mark rings not returned this cycle `stale = 1` rather than
   deleting them, so an account with locally-known unwatched segments still appears offline.
   Delete expired story **bytes** and set `unavailable_at`; never delete story rows (§Retention).
   Delete media by LRU and by `last_access` age. Null `raw_z` older than 30 days by `taken_at`.
   Delete finished sessions older than 90 days. Close the run.
4. Record `next_sync_at`.

**Deep history, not a sweep** (weekly, enforced by the scheduler): `kind='backfill'`; walk the
timeline with `max_id` for `BACKFILL_PAGES` pages (40 ≈ 400 posts, 40 requests), never stopping at
already-stored posts — that stop rule belongs to `cycle`. This is what feeds "keep scrolling older".

The per-account sweep this replaces is **deleted**, not merely disabled, and the reason is worth
recording. It asked for 12 posts from each of 200 followed accounts: 200 requests for posts the
timeline hands out at ~10 a request. Worse, `/api/v1/feed/user/<pk>/` is now a dead route and its
replacement is `POST /api/graphql` with a `doc_id` that rotates with Instagram's builds — a moving
target that can only be chased by scraping request bodies out of the page. Chasing it produced a 429
against the live account. The timeline cursor has never moved, so the design spends its one reliable
primitive instead.

Trade, stated plainly: the sweep could promise "every post from every account"; backfill promises
"a lot of history". The older stream says which one it got — "No older posts stored" is the visible
edge of that promise.

The gate lives in `app/sync.py:next_kind` — the scheduler takes the backfill instead of the
ordinary cycle whenever `sync_state.last_backfill_at` is more than 7 days old (an install that only
has the old `last_sweep_at` key is treated correctly), and it is written **only on success**, so a
dead session retries instead of skipping a week. There is also `POST /api/sync/backfill` (202,
coalesces) and a **Fetch older history** button on the Sync view.

**Backoff as one function with no composition ambiguity:**

```python
def next_delay(streak, exc) -> float:
    base = settings.sync_interval          # re-read every loop iteration
    if exc is None: return base
    if isinstance(exc, ChallengeRequired): freeze(6 * 3600); return base
    return min(base * 2 ** streak, 6 * 3600)   # cap binds at streak 4
```

- `streak` increments per failed cycle; reset to 0 on success **and** when a freeze expires.
  v3 left `streak ≥ 3` after a freeze, so the next failure re-froze instantly.
- There is no separate "skip the next cycle" — the multiplier *is* the delay, so the two rules
  cannot conflict.
- `frozen_until`, `streak`, `reason`, `detail` persist in `meta['sync_state']`; a restart honours
  a future `frozen_until` rather than resetting it.
- The loop re-reads `settings.sync_interval` at the top of every iteration and is woken by
  `PUT /api/settings`.

**Sync control.** `POST /api/sync` → 202 `{run_id}`, coalescing to the running run, never blocking.
`POST /api/sync/resume` clears `frozen_until`. Both in Settings and in the Sync view.

### Story counting — the two-tier contract

Counting segments requires fetching them, and fetching registers views. So counts are tiered, and
the API names them distinctly. §3.3's *"if known"* is the licence.

**Tier 1, always accurate, from the tray (one request per cycle):** account-level. `story_rings`
holds `latest_reel_media`, `media_count` (nullable), `ring_thumb`, `updated_at`, `stale`.
`accounts` holds `local_done_upto` and `story_item_count` — **on `accounts`, not on `story_rings`**,
because the prune marks rings stale and a completion marker must never live in a table that
retention touches.

An account has unseen stories iff `latest_reel_media > COALESCE(local_done_upto, 0)`.

`local_done_upto` is written by:
- **automatic** completion: the viewer marks the last known segment of that account seen **and**
  the account has no unknown segments (known count ≥ `story_item_count`, or `story_item_count`
  is null) → set to current `latest_reel_media`;
- **explicit** `POST /api/stories/{account_pk}/done` → set unconditionally, which is the user
  asserting they are done even when segments were never fetched.

This deliberately ignores Instagram's `seen` flag, which cannot express per-segment progress
(§3.3). A story watched in the real app still shows here as unseen — the accepted consequence.

**Tier 2, accurate once segments are fetched, with a freshness bound:** per segment, from
`stories`: unseen = `seen_at IS NULL AND expiring_at > now AND unavailable_at IS NULL`.

An account counts as **known** only if its newest `stories.fetched_at >= story_rings.updated_at`.
Rows fetched three days ago are stale: without this bound, tier 2 reports 0 unseen while tier 1
reports a visible ring — the exact lie the design forbids.

**API reports both, never conflated:**

```json
"stories": {
  "accounts_unseen": 5,
  "segments_unseen": 14,
  "segments_known_accounts": 2,
  "segments_unknown_accounts": 3,
  "seen_in_session": 9
}
```

The dashboard renders `5 accounts · 14 segments (3 accounts not opened)`. `get_story_queue` returns
known unseen segments plus `unknown_accounts: [pk…]`.

### Story model

- **Tray at sync:** one request, account-level liveness, no views registered.
- **Segments on open only:** `POST /api/stories/{account_pk}/fetch` returns 202 and queues
  `user_stories(pk)` on **executor B**, so it does not wait behind a sync cycle. The viewer renders
  whatever is cached and shows a spinner.
- **No prefetch of the next account** — that registers views on accounts the user never opened,
  defeating the reason fetching is lazy.

**Story states.** All four are reachable and each has a named writer.

| State | Derivation | Writer |
|---|---|---|
| discovered | ring present, no `stories` rows | `story_tray()` upsert |
| available | rows exist with `fetched_at` | `user_stories()` fetch |
| viewed | `seen_at IS NOT NULL` | viewer completion (below) |
| expired | `expiring_at <= now` or `unavailable_at` set | cycle prune / upstream 404 |

**When a segment becomes viewed:** when it is painted, or for video when playback actually starts
(`playing`). No countdown decides it any more — the segment stays on screen until the viewer leaves
it, so "presented" and "watched" became the same thing, and the threshold stopped being a timer.
`seen_session` is written when a session is current, so `seen_in_session` is
`seen_at >= session.started_at`, one rule for posts and stories alike.

**Playback is ours, and there is no story chrome.** The viewer was rewritten after using it: the
native `<video controls>` overlay is Android's -15 s / play / +15 s strip sitting on the picture
permanently, and the Instagram-shaped controls (segmented countdown bars, tap thirds that fling the
media away, auto-advance timers) fought a deliberate UI. So: one plain player per video segment —
our own play/pause, a real `input[type=range]` seek bar, elapsed/total, mute — and no timers
anywhere. Segments are moved with the two arrows under the stage (or `↑`/`↓`), accounts with a
swipe or `←`/`→`, and a video that ends stays where it is. Autoplay is muted because that is the
only autoplay the policy allows without a live gesture; the speaker button is one tap away. The native control bar owns the bottom 56 px of the
video box, so a tap there is a seek and not a segment change; the left/right third taps still work
above it. Images keep the timer, because there is nothing to scrub.

**Fetch state for the viewer:** `GET /api/stories/{account_pk}` returns
`fetch_state: idle | queued | running | failed` plus `error`. The viewer polls at 500 ms, caps at
10 s, then renders whatever is cached with a retry affordance. A frozen provider or an upstream
404 can never leave a permanent spinner.

### Media

CDN URLs are signed and expire. Per §5 caching is an optimisation, never a prerequisite.

- **Cache on** (`MEDIA_CACHE=1`): post thumbnails fetched at sync while URLs are valid,
  downscaled with Pillow to 320 px, stored as a blur-free placeholder; avatars, ring thumbs and
  story media fetched on demand; full-size post media fetched when its post becomes the active
  item.
- **Cache off or empty:** proxy upstream with the session, streaming.
- **Every media endpoint supports `Range`** — `Accept-Ranges: bytes`, 206 on ranges, on both the
  disk and the proxy path, for every kind. Safari's `<video>` sends `Range: bytes=0-1` before
  playback and refuses a non-206 response, so this is what makes video work on the primary
  device at all. A partial response is never teed to disk.
- **Unavailable:** `404` with `Cache-Control: no-store`, empty body. Never a JSON body where an
  `<img>` expects bytes, and never a cacheable failure.
- **Budget:** `MEDIA_BUDGET_MB` (800) covers post **and** story media through one LRU table.
- **Retention keyed on `last_access`, not `taken_at`.** A 2023 post opened from History is cached
  today; keying on `taken_at` would evict it at the next cycle and re-download on every revisit.
- **Cache keys include a URL hash** (`ref = "<pk>:<sha1(url)[:8]>"`), so a changed avatar or ring
  thumb refetches instead of freezing forever behind `UNIQUE(kind, ref)`.
- **Host allowlist.** `media_stream` attaches the Instagram session, so it refuses any URL whose
  host does not end in `cdninstagram.com` or `fbcdn.net`. Without this, a poisoned or tampered
  `src_url` would exfiltrate the session.
- Degradation: missing full media → thumbnail plus `unavailable`; missing everything → caption and
  metadata. The product works without media.

### Session membership — the single predicate

This is the core of the design and v3 had it self-contradictory (`unseen` was both frozen and
live). One predicate, stated once:

```sql
-- M(session) = membership of post p in session s
p.first_seen_sync <= s.snapshot_sync
AND (s.mode = 'all' OR p.seen_at IS NULL OR p.seen_at >= s.started_at)
AND (p.unseen_at IS NULL OR p.unseen_at < s.started_at)
```

- **`first_seen_sync <= snapshot_sync`** — v3's reservation rule (§3.2's 12 + 3 example). New
  posts are invisible to this session.
- **`seen_at >= started_at`** — a post read *during* this session stays in the set, so the walk is
  monotone and the cursor cannot skip. `unseen` means "not read before this session began", which
  is a stable, computable property; it is not a live `seen_at IS NULL` filter (that was v3's bug:
  reading a post would delete it from under the cursor).
- **`unseen_at < started_at`** — `POST /api/posts/unsee` sets `seen_at = NULL` **and**
  `unseen_at = now`. Without the second column, un-unseeing an old post mid-session would inject it
  into the open session and break the reservation guarantee. With it, the predicate is exact and
  `unsee` is safe at any time.

Derived quantities, all from this predicate, no stored counters:

- `item_count` — `count(M)` at creation, stored for display stability.
- `consumed` — `count(M AND seen_at >= started_at)`.
- `remaining_in_session` — `item_count - consumed`.
- `new_since_start` — `count(M without the first_seen_sync clause AND first_seen_sync > snapshot_sync)`.
  By definition these are the posts *excluded* from M, so it must be a separate count; computing it
  inside M always returns 0.

Frozen at creation: `mode`, `snapshot_sync`, `started_at`, and `filters_json`. Filter or mute
changes while a session is open are refused (§API errors); the UI offers "start a new session".

### Finite-browsing mechanics

- **Session.** `feed_sessions(id, device, started_at, snapshot_sync, mode, filters_json, cursor,
  last_rendered_pk, item_count, finished_at)`.
- **Ordering and cursor.** `taken_at DESC, posts.rowid DESC`, cursor `"{taken_at}_{rowid}"`. Rowid,
  not `pk`: Instagram pks are numeric *strings*, so lexicographic `ORDER BY pk` does not give a
  total order on equal `taken_at`, and v3's test asserted a property its schema could not provide.
  Rowids are monotonic and never updated because posts are never deleted.
- **Resume at the post.** `/api/sessions/current` returns `last_rendered: {pk, taken_at}` and
  `GET /api/feed?session=&around_pk=` returns the page **containing** that post, inclusive. The
  forward cursor alone could not find it — that was v3's gap and it failed success criterion 4.
- **Backward navigation** uses `around_pk` for the page containing the previous position; within a
  loaded page the client navigates its buffer.
- **Two tabs** share one device session; `last_rendered_pk` is last-writer-wins, and each tab keeps
  its own in-memory position. Documented rather than solved — a tab id column would buy nothing for
  one user.
- **Termination.** Short page → `next_cursor: null` → end-of-session card with `new_since_start`
  and `next_sync_at`.
- **The end card always renders.** On sync failure it still appears, titled "End of this session",
  with an error banner. **"You're all caught up" appears only when all three hold:** mode is
  `unseen`, `remaining_in_session == 0`, and the last sync succeeded. A `mode=all` session that
  deliberately includes seen posts must not claim the user has seen everything.
- **Read state is independent of sync.** `posts.seen_at` + `seen_session`. Client reports
  impressions at ≥60 % visible **continuously** for `VIEW_THRESHOLD_MS`, batched every 2 s and
  flushed on `visibilitychange`/`pagehide`.
- **No pull-to-refresh inside the feed** (§3.2, §4.4).
- **Past the end is a separate, explicit list.** The end card carries one opt-in button, "Keep
  scrolling older posts". Tapping it starts `GET /api/older`, which is *not* session-bound: it walks
  `taken_at DESC, rowid DESC` over everything stored from accounts with `is_following = 1` (muted
  hidden per setting), seeded by `tail_cursor` — the key of the session's last row, which
  `GET /api/feed` returns even when `next_cursor` is null. That is what makes the continuation
  continue rather than re-read the session's newest posts. It ends when the sweep's stored history
  ends, and says so. The session itself is untouched: `item_count`, `consumed` and the "all caught
  up" condition keep describing the session, not the scrolling.

### API surface

All JSON under `/api`, requiring the cookie, the device header, or `X-API-Token`, except
`/api/health` and `/login`. **Every list endpoint takes `limit` (1–20, default 20) and a cursor**,
and the MCP tools advertise the same `limit` — v3 promised a fixed page size in one place and a
`limit` parameter in another.

Errors: `{"error":{"code":"…","message":"…"}}`.

| code | HTTP | Condition |
|---|---|---|
| `bad_request` | 400 | malformed args, missing required `session` |
| `not_found` | 404 | unknown pk or route |
| `unauthorised` | 401 | missing/expired cookie or token |
| `session_conflict` | 409 | a session is already open; body carries its id and device |
| `session_filters_locked` | 409 | settings/mute change while a session is open |
| `sync_frozen` | 409 | manual sync while frozen; body carries `reason`, `frozen_until` |
| `upstream` | 502 | a required Instagram call failed |
| `unavailable` | 404 | media not retrievable (empty body, `no-store`) |

| Method | Path | Purpose |
|---|---|---|
| POST | `/login` | `{password}` → signed cookie + `device` cookie |
| POST | `/logout` | clear cookies |
| GET | `/api/health` | `{"ok":true}`, no auth |
| GET | `/api/status` | dashboard aggregate (§3.1) |
| POST | `/api/sessions` | start a session; 409 `session_conflict` unless `take_over` names the open one |
| GET | `/api/sessions/current` | this device's open session, including `last_rendered` |
| PATCH | `/api/sessions/{id}` | `{cursor?, last_rendered_pk?}` |
| POST | `/api/sessions/{id}/finish` | end session |
| GET | `/api/feed` | **requires `session`**; `?session=&cursor=&around_pk=&limit=`; also returns `tail_cursor` |
| GET | `/api/older` | session-free continuation; `?cursor=&limit=` |
| GET | `/api/posts/{pk}` | single post |
| POST | `/api/posts/{pk}/seen` · `/unsee` | explicit state change |
| POST | `/api/posts/seen` | `{pks:[…], session?}` bulk impression report |
| GET | `/api/history` | seen posts; `?account=&from=&to=&kind=&cursor=&limit=` |
| GET | `/api/history/stories` | seen/expired stories with retained metadata; same paging |
| GET | `/api/stories` | tray, unseen-first, tier-1 + tier-2 counts |
| GET | `/api/story-queue` | `?limit=&cursor=` → `{items, unknown_accounts, next_cursor}` |
| GET | `/api/stories/{account_pk}` | segments from SQLite + `fetch_state` |
| POST | `/api/stories/{account_pk}/fetch` | 202, queues an upstream segments fetch |
| POST | `/api/stories/{account_pk}/done` | set `local_done_upto` explicitly |
| POST | `/api/stories/seen` | `{pks:[…]}` |
| GET | `/api/stories/progress` | counts by state, both tiers |
| GET | `/api/accounts` | `?q=&cursor=&limit=`; per account: `{unseen_posts, has_unseen_stories, known_segments_unseen, last_swept_at}` |
| GET | `/api/accounts/{pk}` | one account, its counts and sync status (§3.2 "open the author's account") |
| POST | `/api/accounts/{pk}/mute` | `{muted:bool}`; 409 `session_filters_locked` while a session is open |
| GET | `/api/sync/runs` | history + status; `?cursor=&limit=` |
| POST | `/api/sync` | 202 `{run_id}`, coalesced |
| POST | `/api/sync/resume` | clear a frozen state |
| GET · PUT | `/api/settings` | preferences; 409 `session_filters_locked` when filters are in flight |
| GET | `/api/media/post/{pk}/{idx}` | `?size=t|f`, `Range` |
| GET | `/api/media/account/{pk}` | avatar, `Range` |
| GET | `/api/media/story/{pk}` | story media, `Range` |
| GET | `/api/media/ring/{account_pk}` | ring thumb, `Range` |

`POST /api/sessions` body: `{mode: "unseen"|"all", filters: {types: [...], hide_muted: bool,
account: str|null, from: int|null, to: int|null}, take_over: int|null}`. Response:
`{session, snapshot, item_count, next_cursor, items: [...], remaining_in_session}`.

`GET /api/status`:

```json
{
  "posts": {"unseen": 12, "new_since_start": 3, "accounts_with_new": 4},
  "stories": {"accounts_unseen": 5, "segments_unseen": 14, "segments_known_accounts": 2,
               "segments_unknown_accounts": 3, "seen_in_session": 9},
  "session": {"id": 41, "device": "iphone-a1b2", "started_at": 1762890000, "mode": "unseen",
               "items": 15, "consumed": 12, "remaining": 3,
               "last_rendered": {"pk": "3456…", "taken_at": 1762890000}},
  "sessions_open": [{"id": 41, "device": "iphone-a1b2"}, {"id": 40, "device": "macbook-9f3c"}],
  "accounts": {"following": 226, "muted": 3},
  "instagram": {"session_ok": true, "last_ok_at": 1762889400, "failed_at": null,
               "reason": null},
  "sync": {"last_success_at": 1762887600, "last_attempt_at": 1762889400, "duration_ms": 8421,
            "new_posts": 4, "new_stories": 2, "next_sync_at": 1762891200,
            "frozen_until": null, "error": null},
  "backup": {"last_ok_at": 1762870000, "count": 7},
  "storage": {"media_bytes": 214000000, "media_budget": 838860800, "db_bytes": 3100000}
}
```

`accounts_with_new` is §3.1's "number of followed accounts with new content". `session` is resolved
for the calling device: the `device` cookie in browser mode, the `X-Device` header in token mode
(`mcp`), else `null`. Token mode with no session returns `null` rather than inventing one.

`GET /api/feed`:

```json
{
  "session": 41, "snapshot": 4212,
  "next_cursor": "1762890000_8842",
  "remaining_in_session": 3,
  "items": [{
    "pk": "3456789012345678901",
    "account": {"pk": "25025320", "username": "example", "pic": "/api/media/account/25025320"},
    "kind": "carousel", "taken_at": 1762890000, "caption": "…",
    "permalink": "https://www.instagram.com/p/Cxxxx/",
    "engagement": {"likes": 412, "comments": 7}, "seen": false,
    "resources": [{"idx": 0, "type": "image", "w": 1080, "h": 1350,
                    "thumb": "/api/media/post/3456789012345678901/0?size=t",
                    "full": "/api/media/post/3456789012345678901/0?size=f"}]
  }]
}
```

### Filters (§3.7)

**One derived `kind` column, assigned by ordered precedence** so no input can fail the
`NOT NULL` constraint and no two kinds overlap:

```python
def kind_of(m) -> str:
    if m.product_type == "clips":          return "reel"
    if m.product_type == "igtv":           return "igtv"
    if m.media_type == 8:                  return "carousel"
    if m.media_type == 2:                  return "video"     # feed video, product_type NULL
    return "photo"                                            # media_type 1, and the total fallback
```

Toggles map 1:1 to `kind` and are disjoint. Filtering is `posts.kind IN (…)`. Default: all five.

| Filter | Mechanism |
|---|---|
| Hide muted accounts | `accounts.muted = 0` join — hides only, never deletes (§3.4) |
| Content types | `posts.kind IN (…)` |
| Account | `posts.account_pk = ?` |
| Date range | `taken_at BETWEEN ? AND ?` |
| Unseen / all | the `mode` term of M(session), fixed at creation |

Filtering never deletes rows (§3.7).

### Auth and security posture (§7)

- `APP_PASSWORD`, `APP_SECRET` (≥32 random bytes), `API_TOKEN` from env. `POST /login` compares
  **bytes** (`.encode()` on both sides — `compare_digest` raises `TypeError` on a non-ASCII `str`)
  with `hmac.compare_digest`, then sets:
  - `s` = `"<exp>.<hmac_sha256(exp, APP_SECRET)>"`, HttpOnly, SameSite=Lax, **`Path=/`**,
    7-day expiry, `Secure` iff `COOKIE_SECURE=1`.
  - `device` = random 8-byte id, HttpOnly, `Path=/`, 1 year.
- Validation compares the supplied signature to the recomputed one with `compare_digest`; expiry
  parsed and checked separately.
- Middleware accepts a valid `s` cookie, or `X-API-Token` plus a required `X-Device`. One code
  path, so MCP and the browser cannot diverge.
- **`API_TOKEN` is root-equivalent: it can read everything, change settings, mute accounts and
  trigger syncs.** It is a permanent, unscoped bearer in a plaintext config file on the Mac, over
  plain HTTP. Stated here rather than implied away, because §7's "restricted access to
  administrative operations" is the deviation recorded in
  §Requirements we cannot meet. A read/write token split would be the fix, and would cost more than
  it is worth for one user; if the agent ever runs on a shared host, split it.
- **Rate limiting is global in practice.** Behind Docker's port NAT every client appears as the
  bridge gateway, so "5 attempts/min per IP" degenerates to 5/min for everyone. That is the correct
  behaviour for this threat model (a LAN neighbour cannot brute force), and it is stated so nobody
  later reads it as per-client.
- **Also stated plainly:** over plain LAN HTTP the password crosses the wire in cleartext, and a
  signed cookie cannot be revoked before expiry — logout only clears the client's copy.
  Mitigations: 7-day expiry, LAN-only binding, no port forwarding, and `COOKIE_SECURE=1` the moment
  HTTPS exists. §7 permits future remote access and excludes it from V1; if it is added, it is
  HTTPS or a Tailscale sidecar first.
- Instagram credentials and `session.json` are never returned by any endpoint, never logged
  (`session.json`, `authorization`, `last_json`, `password` redacted), and never reachable from the
  frontend. `meta['device']` holds device fields only, never `authorization` or `sessionid`. MCP has
  no route to any of it.

### Storage

SQLite, `journal_mode=WAL`, `synchronous=FULL`, `foreign_keys=ON`, `busy_timeout=5000`. All writes
through `WRITE_LOCK`.

```sql
CREATE TABLE accounts (
  pk TEXT PRIMARY KEY, username TEXT NOT NULL, full_name TEXT, pic_url TEXT,
  is_following INTEGER NOT NULL DEFAULT 1, muted INTEGER NOT NULL DEFAULT 0,
  local_done_upto INTEGER,           -- tier-1 completion marker (survives ring pruning)
  story_item_count INTEGER,          -- last known segment count, nullable
  last_swept_at INTEGER
);
CREATE INDEX accounts_name ON accounts (username);

CREATE TABLE posts (
  pk TEXT PRIMARY KEY, account_pk TEXT NOT NULL,
  code TEXT, media_type INTEGER NOT NULL, product_type TEXT,
  kind TEXT NOT NULL CHECK (kind IN ('photo','video','carousel','reel','igtv')),
  caption TEXT, taken_at INTEGER NOT NULL,
  like_count INTEGER, comment_count INTEGER, permalink TEXT,
  -- No FK here on purpose: AUTOINCREMENT already guarantees run ids are never
  -- reused, and an enforced FK would make pruning sync_runs at 90 days fail.
  first_seen_sync INTEGER NOT NULL,
  -- ON DELETE SET NULL: sessions are pruned at 90 days; the post must survive.
  seen_at INTEGER, seen_session INTEGER REFERENCES feed_sessions(id) ON DELETE SET NULL,
  unseen_at INTEGER,                 -- set by /unsee; excludes it from open sessions
  raw_z BLOB
);
-- rowid cannot appear in a SQLite index definition; every index carries it
-- implicitly, so ORDER BY taken_at DESC, rowid DESC needs no sort step.
CREATE INDEX posts_chrono  ON posts (taken_at DESC);
CREATE INDEX posts_unseen  ON posts (taken_at DESC) WHERE seen_at IS NULL;
CREATE INDEX posts_account ON posts (account_pk, taken_at DESC);
CREATE INDEX posts_snap    ON posts (first_seen_sync);
CREATE INDEX posts_kind    ON posts (kind, taken_at DESC);
-- posts is never deleted; rowid is therefore stable and is the tiebreaker, not pk (a string).

CREATE TABLE media_cache (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,          -- post_thumb|post_full|avatar|ring|story
  ref TEXT NOT NULL,           -- "<pk>:<idx>:<sha1(url)[:8]>"
  path TEXT NOT NULL, bytes INTEGER NOT NULL,
  last_access INTEGER NOT NULL,
  UNIQUE (kind, ref)
);
CREATE INDEX media_lru ON media_cache (last_access);

CREATE TABLE media_resources (
  post_pk TEXT NOT NULL, idx INTEGER NOT NULL, type TEXT NOT NULL,
  src_url TEXT, poster_url TEXT, w INTEGER, h INTEGER, duration REAL,
  PRIMARY KEY (post_pk, idx)
);

CREATE TABLE stories (
  pk TEXT PRIMARY KEY, account_pk TEXT NOT NULL,
  media_type INTEGER NOT NULL, taken_at INTEGER NOT NULL,
  expiring_at INTEGER NOT NULL, src_url TEXT, thumb_url TEXT, duration REAL,
  media_ref TEXT,                    -- media_cache ref for the bytes
  fetched_at INTEGER, seen_at INTEGER, seen_session INTEGER,
  unavailable_at INTEGER, raw_z BLOB
);
CREATE INDEX stories_live   ON stories (account_pk, expiring_at);
CREATE INDEX stories_unseen ON stories (account_pk) WHERE seen_at IS NULL;

CREATE TABLE story_rings (
  account_pk TEXT PRIMARY KEY,
  latest_reel_media INTEGER, media_count INTEGER, media_ids TEXT,
  ring_thumb TEXT, updated_at INTEGER NOT NULL, stale INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE feed_sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, device TEXT NOT NULL,
  started_at INTEGER NOT NULL, snapshot_sync INTEGER NOT NULL,
  mode TEXT NOT NULL CHECK (mode IN ('unseen','all')), filters_json TEXT NOT NULL,
  cursor TEXT, last_rendered_pk TEXT,
  item_count INTEGER NOT NULL, finished_at INTEGER
);
CREATE UNIQUE INDEX sessions_one_open ON feed_sessions (device) WHERE finished_at IS NULL;

CREATE TABLE sync_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL CHECK (kind IN ('cycle','sweep','backfill','story_fetch','manual')),
  started_at INTEGER NOT NULL, finished_at INTEGER, duration_ms INTEGER,
  pages INTEGER DEFAULT 0, posts_added INTEGER DEFAULT 0, stories_added INTEGER DEFAULT 0,
  recovered INTEGER NOT NULL DEFAULT 0,
  error TEXT
);
-- AUTOINCREMENT guarantees ids are never reused, so posts.first_seen_sync stays valid
-- after sync_runs rows are pruned at 90 days.

CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE meta     (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE backups  (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at INTEGER NOT NULL,
                       path TEXT NOT NULL, bytes INTEGER, ok INTEGER);
```

Each of these columns has a writer and a reader; v3 shipped four that had neither.

### Retention (§14 item 9)

| Data | Retention | Why |
|---|---|---|
| `posts` rows | indefinite | A few hundred bytes each; history depends on them (§3.6) |
| `posts.raw_z` | 30 days by `taken_at`, then nulled | Size; needed fields are columns |
| `stories` rows | indefinite | §5 "expired content may still have historical metadata"; §3.6 |
| story media bytes | until expiry, then deleted | `unavailable_at` set, row kept |
| post media | LRU, and `last_access` older than 30 days | Regenerable cache |
| `feed_sessions` | finished, older than 90 days | Growth; open sessions never pruned |
| `sync_runs` | 90 days (closed only) | History UI; ids never reused |
| `media_cache` | LRU to `MEDIA_BUDGET_MB` | Disk ceiling |
| backups | 7 newest | §8.4 |

### Settings precedence

Env seeds a setting **once**, on first run, and never again; afterwards the `settings` row is the
only source of truth. This removes v3's duplicate-source-of-truth defect.

| Setting | Env seed | Range |
|---|---|---|
| `sync_interval` | `SYNC_INTERVAL` (1800) | 300–86400 s |
| `view_threshold_ms` | `VIEW_THRESHOLD_MS` (1000) | 0–10000 |
| `story_auto_advance_accounts` | `0` | bool |
| `types` | `photo,video,carousel,reel,igtv` | subset |
| `hide_muted` | `1` | bool |

`PUT /api/settings` accepts a partial object, validates ranges, rejects unknown keys with
`bad_request`, and returns 409 `session_filters_locked` when the change would alter an open
session's frozen filters — the UI then offers "start a new session". v3 referenced that 409 without
giving it a route to fire on.

### Frontend

Vanilla HTML/CSS/JS, no framework, no bundler. Nine views in a hash router plus one `render()` per
view. Files: `index.html`, `app.js` (router, state, API client, keyboard map, polling),
`views.js`, `style.css`.

- **Login** — shown on any 401. Password only.
- **Dashboard** (`/`) — §3.1: unseen posts, accounts with new posts, seen-in-session, accounts with
  new stories, known unseen segments with the "not opened" qualifier, last successful sync, sync
  error or frozen banner, backup age, session progress with a resume link. Reads SQLite only. Polls
  `/api/status` every 10 s while visible; the feed does not poll.
- **Feed** (`/#feed`) — one column, max 640 px on mobile; at ≥1024 px two columns with a sidebar
  (accounts + filters, §4.3) and larger media. Author, avatar, timestamp, media, carousel arrows +
  dots + `1/3`, caption clamped to 3 lines with tap-to-expand, permalink and engagement in a
  collapsed footer, explicit "mark unseen", and "open author" (which starts a new filtered session
  — §3.2's "open the author's account", and the only way to do it without breaking frozen filters).
  Keyboard: `j`/`↓` next, `k`/`↑` previous, `←`/`→` carousel, `o` open, `m` toggle seen, `Esc` back.
  A sentinel loads one more page only while `next_cursor` is non-null, then renders the end card and
  stops — no infinite scroll (§4.4).
- **Post** (`/#post/{pk}`) — single post, full metadata, permalink out.
- **Stories** (`/#stories`) — full-screen, black. Per-segment bar, avatar, username, relative time.
  Interaction map implemented literally from §3.3:

  | Input | Action |
  |---|---|
  | tap right / tap left | next / previous segment (**within** the account) |
  | swipe left / swipe right | next / previous account |
  | `→` / `←` | next / previous account |
  | `↓` / `↑` | next / previous segment |
  | `Space` | pause / resume |
  | `Esc` | close |

  Tap zones are the outer thirds with the middle inert. A tap is `pointerup` within 10 px and
  250 ms of `pointerdown`; a swipe needs 40 px of horizontal travel. The viewer sets
  `touch-action: none` and `overscroll-behavior: none`, and pushes one history entry so `Esc`/close
  pops it instead of leaving the app — Safari's edge-back gesture must not fire while swiping
  between accounts. **Video elements carry `playsinline muted autoplay`**; iOS blocks unmuted
  autoplay, so `play()` rejection falls back to a tap-to-play surface and the tap is the viewed
  trigger. Without these three details the story state machine silently never advances on the
  primary device.

  The account boundary is visible *before* the tap: the segment bar is per-account and labelled, and
  a chevron marks the last segment. Advancing past the last segment stops at an account-complete
  state; auto-advance is a setting, off by default. From segment 1, back never crosses accounts.
  A cold account shows the fetch spinner (500 ms poll, 10 s cap) then cached content.
- **Accounts** (`/#accounts`) — search, per-account unseen posts, story state, mute, `last_swept_at`
  (§3.4), "open this account's posts", "open this account's stories" (jumps the viewer to that
  account).
- **History** (`/#history`) — Posts and Stories tabs; account/date/type filters; paginated.
  Reopening does not change seen state; changing it is explicit (§3.6). Unavailable story media is a
  metadata row, never a broken player.
- **Sync** (`/#sync`) — §3.5 status plus run history and a "resume" button when frozen.
- **Settings** (`/#settings`) — filters, thresholds, auto-advance, sync interval, "Check now",
  storage, backups, logout.

Mobile-first: `100dvh`, `env(safe-area-inset-*)`, tap targets ≥44 px, no hover-only affordances,
`prefers-reduced-motion`, `aria-live` on progress counters.

### MCP server (§6)

`mcp/mcp_server.py`, run by the agent as a stdio subprocess. A thin HTTP client: `API_BASE`,
`API_TOKEN`, and `X-Device: mcp` on every call. No Instagram credentials, no DB access
(§6.1, §6.3, §7) — which is also why it cannot disagree with REST (Alternatives #16).

**MCP has its own session identity.** `device = "mcp"`, so `GET /api/sessions/current` resolves
for it, and `get_feed` auto-creates a session with defaults when none is open. Without this the
tool could not obtain the `session` id it requires — v3's hole. `get_story_queue` calls the
dedicated `/api/story-queue`, not the tray.

Schemas are generated by the SDK from typed signatures. Shape:

```json
{
  "name": "get_feed",
  "description": "One page of the MCP device's current feed session, chronological, cached-only.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "cursor": {"type": "string"},
      "limit":  {"type": "integer", "minimum": 1, "maximum": 20, "default": 20}
    }
  }
}
```

| Tool | Args | Endpoint | Paginated |
|---|---|---|---|
| `get_feed` | `cursor?, limit?` | `GET /api/feed` (auto-session) | yes |
| `get_feed_status` | — | `GET /api/status` | n/a |
| `get_post` | `pk` | `GET /api/posts/{pk}` | n/a |
| `mark_post_seen` | `pks[]` | `POST /api/posts/seen` | n/a |
| `get_accounts` | `q?, cursor?, limit?` | `GET /api/accounts` | yes |
| `get_stories` | `account?, cursor?, limit?` | `GET /api/stories` or `/api/stories/{pk}` | yes |
| `get_story_queue` | `limit?, cursor?` | `GET /api/story-queue` | yes |
| `mark_story_seen` | `pks[]` | `POST /api/stories/seen` | n/a |
| `get_story_progress` | — | `GET /api/stories/progress` | n/a |
| `get_sync_status` | — | `GET /api/sync/runs` | yes |
| `request_sync` | — | `POST /api/sync` | n/a |
| `get_feed_summary` | — | `GET /api/status` + `/api/sync/runs` | n/a |

§6.3 rules: structured data only; every list paginated (as marked); explicit errors as
`{isError, code, message}`; write args validated (non-empty `pks`, pk shape, unknown pk → error
naming it); bulk writes return `{"affected": [...], "skipped": [...]}`. Versioning: `v1` in the MCP
initialize handshake, and `"schema_version": 1` in every list response, so an agent can branch
without a handshake change.

Wiring (README). The venv is created in step 2 of the order of work; the path below is created by
that step, not assumed:

```json
{"mcpServers": {"00sgram": {
  "command": "/Users/stelios/venvs/00sgram/bin/python",
  "args": ["/Users/stelios/Projects/stelios/00sgram/mcp/mcp_server.py"],
  "env": {"API_BASE": "http://pi:8091", "API_TOKEN": "…"}}}}
```

### Deployment (§8)

`Dockerfile`: `python:3.11-slim`, `pip install -r requirements.txt`, non-root user (UID 1000),
`HEALTHCHECK` on `/api/health`. No build stage and no apt packages — backups use stdlib `sqlite3`,
and `tzdata` is a pip dependency so `ZoneInfo("Europe/Athens")` resolves in the slim base.

`docker-compose.yml`: one service — `build: .`, `restart: unless-stopped`, `ports: ["8091:8080"]`,
`env_file: .env`, `volumes: ["/srv/00sgram/data:/data"]`, healthcheck as above.

- Own compose project and bridge network; no `network_mode: host`. Verify the port with
  `ss -ltnp` — not `docker ps`, which cannot see host listeners. Home Assistant keeps 8123 and its
  supervisor untouched (§8.1).
- Data on the host at `/srv/00sgram/data`. First README step:
  `mkdir -p /srv/00sgram/data && sudo chown 1000:1000 /srv/00sgram/data`, otherwise a non-root
  process cannot write a bind mount.
- Idle RSS target < 200 MB. No browser process (§8.3).
- Startup self-test (`PRAGMA integrity_check`, media dir writable, provider connect, orphaned runs
  closed) logs and serves degraded rather than crash-looping.

### Backups and restore (§8.4)

In-process daily task at 04:00 local, on the sync executor:

1. `sqlite3.Connection.backup()` to `$BACKUP_DIR/db-YYYY-MM-DD.sqlite3` — online-consistent,
   WAL-safe, and needs **no external binary** (v3 shelled out to a `sqlite3` CLI that
   `python:3.11-slim` does not contain, so backups would have failed silently every night).
2. gzip in Python, record the row in `backups`, delete all but the 7 newest.
3. `/api/status` reports `backup.last_ok_at`; the dashboard warns when it is older than 26 h.

`$BACKUP_DIR` defaults to `/data/backups`, and that is **not real protection** — same volume, same
disk. The README says so plainly and asks for a different host path or an off-box copy; otherwise
the backup only covers logical corruption.

`session.json` is excluded (a credential, and multiplying it multiplies the leak surface). Device
identity instead lives in `meta['device']` (device fields only), so a restore does **not** look like
a new device — the challenge trigger.

Restore, exercised once in verification: `docker compose down`, gunzip over `data/db.sqlite3`,
delete `-wal` and `-shm`, `docker compose up -d`, confirm counts, confirm the next sync adds no
duplicates and no re-login is demanded.

### Configuration

| Env | Default | Notes |
|---|---|---|
| `IG_SESSION_COOKIE` | — | required; `sessionid` from a browser login. No password is stored |
| `APP_PASSWORD`, `APP_SECRET` | — | required; secret ≥32 random bytes |
| `API_TOKEN` | — | required; bearer for MCP, root-equivalent |
| `COOKIE_SECURE` | `0` | `1` the moment HTTPS exists |
| `PROVIDER` | `instagrapi` | `mock` for order-of-work steps 1–5 and tests |
| `DATA_DIR` | `/data` | db, media, session.json |
| `BACKUP_DIR` | `/data/backups` | point elsewhere for real protection |
| `SYNC_INTERVAL` | `1800` | seeds `settings.sync_interval` once |
| `SYNC_MAX_PAGES` | `10` | per cycle |
| `VIEW_THRESHOLD_MS` | `1000` | seeds `settings.view_threshold_ms` |
| `MEDIA_CACHE` | `1` | `0` = pure proxying (§5) |
| `MEDIA_BUDGET_MB` | `800` | LRU ceiling, posts **and** stories |
| `MEDIA_RETENTION_DAYS` | `30` | keyed on `last_access` |
| `BACKFILL_DAYS` | `7` | first run; ceiling 50 pages |
| `TZ` | `Europe/Athens` | display, weekly sweep, backup |

### Out of scope (V1, per §9)

Likes, comments, DMs, follows, uploads, story publishing, multiple users, public SaaS, cloud
hosting, push or engagement notifications, recommendations, semantic search, AI inside the app.
§6.4's future capabilities are additive: the API's cursor and filters already accept the parameters
those tools would need.

### Decisions resolved (§12)

| Decision | Chosen | Why |
|---|---|---|
| Feed ordering | Newest first | §12 default. |
| Feed session | Snapshot at start, resumable per post, per device | §3.2 example; §2.3; §2.1 names two devices. |
| Content types | All five kinds, disjoint toggles | Reels are posts by followed accounts. |
| Story advancement | Manual; auto-advance off | §3.3 says configurable; default off avoids accidental skips. |
| Story playback | Video on `ended`; images 5 s | §12 default. |
| Viewing threshold | 60 % continuous for 1 s; duration configurable | §3.2. |
| Synchronization | 30 min, configurable | §3.5. |
| Media storage | Metadata local; caching optional | §5. |
| Feed refresh | Explicit only, never on scroll | §3.2, §4.4. |
| Previous content | History, posts and stories | §3.6. |
| Muting | Hides from feed; keeps rows | §3.4. |
| Auth | Password cookie + device cookie + API token | §7 wants auth, not a user system. |
| Multi-device | One open session per device, explicit take-over | Sharing one cursor corrupts resume. |

### Risks and containment

| Risk | Containment |
|---|---|
| **ToS violation → suspension** | Accepted and stated. Read-only, one stable IP, 1.5–3.5 s delays, ≤16 requests per 30 min, weekly sweep, exponential backoff, freeze-on-challenge. Residual risk is real and not fully mitigable. |
| Upstream `max_id` cursor bug | **Hit, and bypassed.** Mobile `get_timeline_feed` jams on a constant `next_max_id`; `timeline_page()` uses the web host instead (§Data source). Residual risk: the web endpoint could be deprecated like the mobile one — the Provider seam absorbs it. |
| `instagrapi` breaks against a new Instagram build | All access in `instagram.py`; `Provider` is the seam; DB and API keep serving. Swap = one class (Alternatives #18). |
| Signed media URLs expire | Thumbnails persisted at sync; full media degrades to thumbnail + `unavailable`; never a cacheable failure. |
| Session file leaks | `session.json` is a browser session cookie now, not a password: file mode 600, volume behind password auth, redacted from logs, excluded from backups. `meta['device']` holds device fields only. |
| Session cookie expires or is invalidated | No automatic recovery is possible (password login is refused by Instagram). `meta['session']` is surfaced as `instagram` in `/api/status` with `{session_ok,last_ok_at,failed_at,reason}`; the dashboard says "session expired — paste a new cookie"; Settings hot-swaps it with no restart. One attempt per cycle, never a retry loop. First failure date is logged so the real lifetime is measured. |
| Disk fills | 800 MB ceiling across posts and stories, LRU, `last_access` retention, gzipped `raw_z` nulled at 30 days. |
| Silent sync failure fakes "all caught up" | Card always renders; the phrase needs mode `unseen`, zero remaining, and a successful last sync. |
| MCP and REST diverge | MCP is an HTTP client of REST; one write path. |
| Home Assistant disturbed | Separate project and network, verified-free port, no host networking. |
| Backup gives false comfort | `backup.last_ok_at` surfaced; README states the same-volume limitation. |

---

## Alternatives

Each entry: what it was, why rejected. Do not re-propose without new information.

### 1. Instagram Graph API (official)

The only permitted API. Exposes content *you* own, insights, comment moderation. Cannot read the
feed of accounts you follow, and cannot read other users' stories. **Rejected: technically
impossible.** This is why the acceptance in §Requirements we cannot meet exists instead of a
workaround.

### 2. Go + PostgreSQL + React + separate sync worker + reverse proxy

What §8.2 and §11 name. Rejected on measured grounds: one user, one writer, ~5 k rows/day. Postgres
buys concurrency this app does not have and costs a second container, a migration tool, and a backup
path. Go buys throughput at one user and costs the only ecosystem where the private-API wrapper is
maintained. React buys components for nine views; the proxy is unnecessary because FastAPI serves
the static files. Kept from the spec: an independently invocable sync and explicit module
boundaries. **This is the deviation this document makes; re-open it here rather than rewriting
silently.** Trigger: a second writer, a second user, or mobile UX outgrowing vanilla.

### 3. Logged-out scraping (`instaloader` public paths)

Works for public profiles' recent posts. Fails for stories, private accounts you follow, and any
personalised feed; anonymous scraping is throttled to uselessness within minutes. **Rejected:
cannot satisfy stories or the follow graph.**

### 4. Browser extension re-skinning instagram.com

Fails self-hosting, fails iPhone, fails cross-device progress, breaks on DOM changes, cannot be
reached by an agent. **Rejected: wrong host, wrong clients, and it deletes the features that need a
server.**

### 5. Headless Chromium / Playwright on the Pi

A permanent tax on a Pi using most of 8 GB; ~1.5 GB images; tens of seconds per sync; a larger
detection surface than the private API; breaks more often than API changes. **Rejected: more
fragile than #6 at 10× the cost.**

### 6. `instagrapi` private mobile API — **chosen**

Reads a personal feed *and* the story tray in 1–2 calls per cycle, typed models, session reuse,
actively maintained. **As measured in Phase 0**, it is used for follows, stories and the tray
only: password login is refused (`needs_upgrade`) so auth is `login_by_sessionid`, and the mobile
timeline cursor is broken so `timeline_page()` targets the web host (§Data source). Its caveats
are what §Risks mitigates; its legality is what §Requirements we cannot meet records.

### 7. Live proxying on every page load

Breaks the finite feed, makes traffic bursty and user-driven, and fails when Instagram is
unreachable (§3.1, §7). **Rejected: breaks the central requirement.**

### 8. `feed_timeline` only, no per-account reconciliation

Ranking can bury a followed account below the pagination horizon. **Rejected as the only path** —
primary path plus weekly sweep.

### 9. Per-account `user_medias` polling every cycle

150+ calls every 30 min, sustained. **Rejected: correct data, unsustainable rate.**

### 10. Poll story segments for all accounts at sync

Would complete tier-2 counts without a tap, but every call registers a view and it is O(follows) per
cycle. **Rejected: bot-shaped traffic, and it marks the tray seen before the user looks.** *Phase 0
may invalidate the premise:* if `user_stories` turns out not to register a view, this alternative
reopens and the two-tier machinery collapses into one tier.

### 11. Call `story_seen()` to mirror read state to Instagram

Extra writes for no user-visible benefit. **Rejected: writes are the risky half of the API.**

### 12. Persist seen state in `localStorage` only

Fails §3.2 and §5, and cannot be read by an agent. **Rejected.**

### 13. React + Vite SPA

A toolchain, `node_modules`, and a Docker build stage for nine views. **Rejected for V1.**
Narrowed: past ~9 views, add Preact + Vite; the router and API client survive.

### 14. Storing media as SQLite BLOBs

One file to back up and atomic with the DB, but `VACUUM` rewrites the whole file, WAL doubles during
writes, and HTTP `Range` needs `substr()` round-trips that are slow for video. **Rejected:
filesystem paths stream properly and cheaply.**

### 15. Deferring MCP to a later phase

§10 lists seven MCP acceptance criteria and §11 puts MCP in V1. **Rejected: it is a V1
requirement**, and it is ~180 lines because it is a client of an API written first.

### 16. An MCP server reading SQLite directly

Creates a second writer, duplicates validation, and can disagree with REST — against §6.1 and
§10. **Rejected: two write paths for one user's data.**

### 17. Blocking the event loop with in-task sync

`asyncio.create_task(sync_loop())` with a synchronous library blocks every request for 25–60 s per
cycle, violating §3.5. **Rejected:** dedicated executors plus a write lock. Kept here because it is
the obvious first implementation and it is wrong.

### 18. HikerAPI or another hosted provider

Handles sessions, proxies and challenges for a fee. **Rejected for V1, kept as the documented
fallback** with a stub provider. It does not resolve compliance — the source is still not
permitted — so it is an availability fallback only.

### 19. A dedicated throwaway Instagram account

A throwaway follows nobody, so the feed is empty; following the real list from it doubles the graph.
**Rejected: defeats the purpose.**

### 20. OFFSET-based pagination

An insert above the cursor shifts every later page, producing skips and duplicates. **Rejected:
violates §3.5's "duplicate content must not be created".**

### 21. Materialising each session's eligible post list

Guarantees immutability but writes and garbage-collects hundreds of rows per session. **Rejected:
the single membership predicate in §Session membership achieves the same guarantee with columns.**

### 22. One shared feed session across devices

Two browsers would share one cursor and one `last_rendered_pk`, so each overwrites the other's
position and success criterion 4 fails on both. **Rejected: per-device sessions with explicit
take-over.**

---

## Detailed Implementation

### Files

```
00sgram/
├── requirements.md
├── docs/designs/distraction-free-instagram-client.md
├── README.md                  # first run, creds, restore, challenge triage, MCP wiring, Phase 0 log
├── requirements.txt           # all pinned: fastapi, uvicorn[standard], instagrapi, pillow,
│                              #   httpx, mcp, tzdata
├── requirements-dev.txt       # pytest
├── Dockerfile
├── docker-compose.yml
├── .env.example               # placeholders for every required key
├── app/
│   ├── __init__.py
│   ├── main.py                # FastAPI app, routes, auth middleware, static mount
│   ├── config.py              # env → dataclass, settings seeding
│   ├── dtos.py                # AccountDTO, PostDTO, StoryDTO, TrayEntry, Page
│   ├── provider.py            # Provider protocol + factory
│   ├── instagram.py           # InstagrapiProvider, login, device identity, retries, DTO mapping
│   ├── mock.py                # MockProvider incl. embedded MP4 constant
│   ├── sync.py                # cycle, follow refresh, watermark, sweep, backoff, scheduler, backup
│   ├── store.py               # schema, WRITE_LOCK, queries, sessions, history, retention
│   ├── media.py               # normalise, cache, LRU, Range, allowlist, proxying
│   ├── static/{index.html, app.js, views.js, style.css}
├── mcp/
│   └── mcp_server.py          # 12 tools, stdio, HTTP client of /api
└── tests/
    ├── test_store.py          # membership predicate, pagination, sessions, filters, retention
    ├── test_sync.py           # follow refresh, run lifecycle, backoff, prune, backfill
    ├── test_api.py            # routes, auth, errors, concurrency, media, Range
    └── test_mcp.py            # tool ↔ REST payload equality, MCP session identity
```

### Prerequisites the implementer cannot invent

1. **The Instagram session cookie.** `IG_SESSION_COOKIE` is the user's and is never committed.
   Obtained by logging into instagram.com in a browser and copying the `sessionid` cookie.
   `.env.example` lists it with a placeholder. It is already present on the Pi for step 0.
   It expires eventually and must then be replaced by hand (§Data source).
2. **Pi access.** `br3@pi` with Docker group membership (confirmed); `sudo` for the one `chown`
   on `/srv/00sgram/data` (already done, owned 1000:1000).
3. **The Mac venv.** `python3 -m venv ~/venvs/00sgram && ~/venvs/00sgram/bin/pip install mcp httpx`
   — created in step 2, not assumed to exist.
4. **A free host port.** 8080 is *not* free: `pihole-FTL` holds it. The deployment uses
   **8091** (verified free), published to the container's 8080. Re-verify with `ss -ltnp`.

### Milestones and dependencies (§14 item 10)

`S0` feasibility gate → everything. `S1` store → API, sync, UI. `S2` API + auth + compose → UI, MCP.
`S3` mock provider → UI steps (which must not wait for `S0`). `S4` real provider + sync → media,
acceptance. `S5` MCP → acceptance. `S6` backup/restore/hardening → acceptance.

### Order of work

**0. Feasibility gate (§11 Phase 0). ✅ DONE 2026-11-16 — passed with one substitution.**
Findings are in `README.md`. Timeline paging is broken on the mobile host and works on the web
host, so `timeline_page()` targets `www.instagram.com`. Story view registration confirmed with a
control account; the tray carries exact `media_count`. Follow count is 226, not 148.
**No stop condition triggered.**

**1. Skeleton, mock provider, store** (`config.py`, `dtos.py`, `provider.py`, `mock.py`, `store.py`,
`test_store.py`). Schema, `kind_of`, the membership predicate, keyset ordering on rowid, retention.
Verify: `pytest tests/test_store.py`.

**2. API + auth + compose. ✅ DONE 2026-11-16.** `app/main.py`, `app/asgi.py`, `tests/test_api.py`,
`Dockerfile`, `docker-compose.yml`. 45 tests pass. Running on the Pi at
`http://pi:8091`, `PROVIDER=mock`, seeded with `python -m app.dev_seed`.
Media endpoints return `404 no-store` and `POST /api/sync` closes its run with
"worker not attached (step 6)" — both are deliberate, not silent stubs. Port 8091 because
`pihole-FTL` owns 8080.

**3. Feed UI. ✅ DONE 2026-11-16.** `static/index.html`, `app.js`, `views.js`, `style.css`,
`tests/test_ui.py` (49 tests pass). Dashboard with real counts, feed, post, end card, keyboard
(`j`/`k`/`←`/`→`/`o`/`m`/`Esc`), carousel, `around_pk` resume, desktop sidebar. Verified in headless
Chrome against the mock at 20→34 posts: sentinel stops exactly at `next_cursor`, the card reads
"End of this session · 34 posts in this snapshot · N seen", and reads "You're all caught up." once
`remaining_in_session == 0`. Four implementation notes that were not obvious in the design:

- **Intersection ratio cannot drive "viewed".** A 4:5 post is taller than the viewport, so its
  `intersectionRatio` never reaches 0.6 and nothing would ever be marked seen. Both observers use
  `rootMargin: "-40% 0px -40% 0px"` with `threshold: 0` — the post has to cross the middle band, and
  the *duration* in the band is the threshold.
- **Static assets must revalidate.** `no-cache` on `/static` and `/` (via a `StaticFiles`
  subclass). Without it a redeploy leaves a browser running last week's `app.js` against today's
  API, which is a silent, confusing breakage.
- **`history.scrollRestoration = "manual"`, set inline in `<head>`**, plus a re-assert on
  `rAF`/`load`. Otherwise `around_pk` resumes at the right post and the browser then jumps to the
  remembered pixel offset.
- **Two session DTO shapes.** `GET /api/sessions/current` returns `item_count`,
  `GET /api/status` returns `session.items` (both as documented above). The UI reads each from its
  own source; unifying them would have meant editing the doc's payloads for no gain.

`last_rendered_pk` is by design the post that owns the *middle* of the viewport, which is why the
resume test scrolls the target to `top == 0` rather than reproducing the old pixel offset.

**4. Stories UI. ✅ DONE 2026-11-16, viewer reworked.** Tray (2-up at 390 px, ring, unseen dot,
`n/m seen`, progress bar), full-screen viewer at `100dvh` with safe-area padding. The story-style
chrome is gone on purpose — no segmented countdown bars, no tap thirds, no timers — replaced by a
plain player and segment arrows (see *Playback is ours*). Kept: 40 px swipe between accounts,
`←`/`→`, `↑`/`↓`, `Space`, `Esc`,
account-boundary chevron before the tap, completion card, cold-open spinner with a 500 ms poll and
10 s cap, and one pushed history entry so `Esc`/back never leave the app. Auto-advance between
accounts is off by default (`story_auto_advance_accounts`); segment advance on `ended`/timer is not
optional — that is §3.3's natural duration.

Two things found by running it rather than reading it:
- **A 404 media segment was never marked seen**, so the ring stayed permanently one short of
  complete. A segment that was *presented* counts as viewed even when its media failed; only
  `v.play()` rejection on iOS still requires the tap.
- `dev_seed` now seeds story segments for every ring but the last, so the tray shows real progress
  in development and one cold account still exercises the fetch path.

Caveats, all honest: real video `ended`/autoplay is unverified until step 7 serves media; a cold
account cannot resolve yet because `POST /api/stories/{pk}/fetch` closes with "no provider worker
attached (step 6)" — the viewer shows that error with a retry instead of hanging; notch clearance
is CSS-reasoned, not measured on a device because headless reports `safe-area-inset-*` as 0.

**5. Remaining UIs. ✅ DONE 2026-11-16.** Accounts (search, unseen count, story state, mute,
`last_swept_at`, jump to posts or to that account's stories in the existing viewer), History (Posts
and Stories tabs, account/type/date filters, cursor paging, expired media as a metadata row),
Sync (§3.5 status, run history, verbatim "sync worker not attached yet (step 6)", resume only when
`frozen_until` is set), Settings (filters, thresholds, auto-advance, sync interval, storage/backup
figures, logout, and a 409 `session_filters_locked` that offers a new session or thresholds-only).

Three API additions this step needed, all backward compatible:
- `GET /api/accounts?show_muted=1`. Mute was one-way: the default hides muted accounts, so without
  the flag a muted account could never be unmuted.
- `GET /api/history/stories` now carries `username`. A history row labelled only with a numeric pk
  is unusable.
- `POST /api/sessions/{id}/finish` no longer requires the session's own device. The filter lock is
  global, so the release has to be global too — otherwise a session abandoned by another browser
  profile freezes mute and filters with no way out. Found by walking into it: within a day the Pi
  had an orphaned session from an earlier browser profile and every mute attempt returned 409.
  `PATCH` stays device-scoped. The accounts view turns that 409 into a "Finish that session" button
  instead of telling the user to go find it.

Verified in Chrome at 390×844 against the deployed Pi: no horizontal overflow on any view, smallest
button 44 px, mute → hidden → shown again with "show muted" → unmuted, both history tabs, run
history and the honest sync error, and the settings 409 gate through to "Start a new session".
Not exercised: the resume button (no endpoint can set `frozen_until` yet) and logout beyond the
cookie clearing tested in the API suite.

**6. Real provider + sync. ✅ DONE 2026-11-16.** `app/instagram.py` (sessionid login, persisted device
identity, direct call to the web timeline host, `SessionExpired` on 401/403, allowlisted
`media_stream`) and `app/sync.py` (cycle with the stop rule, weekly sweep, tray + lazy segment fetch,
run lifecycle with recovery, backoff into `frozen_until`, background scheduler thread, daily
backup, `python -m app.sync --once`).

Measured on the Pi with the mock provider: `kind=cycle pages=10 added=30 follows=12
stopped=max_pages`, second run `pages=1 added=0 stopped=already_stored`. With `PROVIDER=instagrapi`
and no cookie: `stopped=session_expired`, exit 1, app still boots and `/api/status` names the reason.
`POST /api/sync` now runs a real cycle instead of closing its run with the step-6 message.

Invariants proved by tests rather than by eye: a repeated `next_max_id` terminates instead of
looping (the exact Phase 0 bug); an author outside `accounts` is dropped with no orphan `account_pk`;
a second cycle adds 0; a crashed run is `recovered=1` and its posts are absent from both the open and
the next session; backoff sets and then clears `frozen_until`; an incomplete following page never
unfollows the tail.

Deliberate deviation: post rows are never pruned. §Retention keeps posts indefinitely for History, so
`prune()` drops sessions and runs at 90 days and evicts media by `last_access` instead. The cookie
lives in `sync_state` (DB wins over env, so it can be pasted in Settings on the phone) and is never
returned by any GET or error body.

**Found while looking at the deployed app, both fixed here:** the media placeholder was rendered
*behind* the media rather than only on failure, so a 1:1 photo or a 9:16 reel inside the old
`aspect-ratio: 4/5` box left "igtv · 1080×1350" floating over black — the exact symptom that
prompted this pass. The placeholder is now `hidden` until an `error` fires, and `.media` sizes itself
from the media instead of forcing 4:5.

**Verified against the real account, 2026-11-16.** Mock data wiped, `PROVIDER=instagrapi`, cookie
pasted in Settings. First cycle: `kind=cycle pages=10 added=20 follows=200 stopped=max_pages`; second:
`pages=2 added=0 follows=200 stopped=already_stored`. `/api/status` → `instagram.session_ok: true`.
20 real posts, `/api/media` proxying real CDN bytes: photo 200/603 393 B `image/jpeg`, reel
200/4 129 932 B `video/mp4`, thumb 200/215 092 B, `-r 0-1023` → 206/1024 B. In Chrome at 390×844 the
feed shows real carousels (20 slides, arrows move it), 10 reels at `readyState 4`, 720×1280, playing;
tray shows 21 real accounts with real avatars and real segment counts; a 20-segment story account
plays its real MP4 in the viewer and advances the bar.

Three real-only bugs the mock could not produce, all fixed here:

1. `user_stories` did `int(story.taken_at)`, but instagrapi returns `datetime` — the viewer spun
   forever on every account. `_epoch()` converts datetime/str/int.
2. instagrapi's `Story` exposes `video_url`/`thumbnail_url`, not `video_versions`/`image_versions2`,
   so every segment stored `src_url = NULL` and the viewer said "video unavailable". Both shapes are
   now read, and `_url()` stringifies pydantic `HttpUrl` (it will not bind in SQLite).
3. The Dashboard session card read `s.item_count`, which the API calls `items` — "NaN of undefined
   left". Only reachable once a session had posts.

**7. Media. ✅ DONE 2026-11-16.** `app/media.py` (289 lines): URL resolution from the DB so the
browser never sees an upstream URL, disk cache under `DATA_DIR/media/<kind>/<sha1>`, `Range`/206 with
`Content-Range` and `416` when unsatisfiable, one `last_access` LRU across posts and stories against
`MEDIA_BUDGET_MB`, `MEDIA_CACHE=0` pure proxy, and an unavailable list (no URL, upstream 404/410,
provider error, non-allowlisted host) that is always `404` + `Cache-Control: no-store` + empty body.

Proven with curl on the deployed Pi: post photo 200/49 141 B, post thumb 200/59 860 B, story
200/43 661 B, avatar 200/1 709 B, `-r 0-1023` → 206/1024 B, `bytes=0-1` → 206/2 B (the Safari
`<video>` case), `bytes=99999999-` → 416 `bytes */<size>`, unknown pk → 404 `no-store` 0 B. In Chrome
at 390×844 the feed renders 1080×1350 photos, 256×256 avatars and a `<video>` at `readyState 4` with
no console media errors.

Deviations, both deliberate: no Pillow downscaling yet (`?size=t` means "the poster/thumb URL the DB
has, else full"; downscaling is a sync-time job that belongs with step 6's thumbnail pass), and
`MEDIA_CACHE=0` buffers the upstream body so `Content-Range` can be exact, because `media_stream`
exposes no upstream size or status.

**8. MCP. ✅ DONE 2026-11-16.** `mcp/mcp_server.py` (250 lines, stdio) + `tests/test_mcp.py`. A thin
HTTP client: `X-API-Token` + `X-Device: mcp` on every call, no DB, no Instagram, so it cannot
disagree with REST (Alternatives #16). 12 tools, `schema_version: 1` on every list, errors as
`{isError, code, message}` with the credential redacted, `get_feed` creating its own session on 404
and reusing it after (asserted: exactly one POST). The `mcp` 2.3.0 surface is `MCPServer`, not
`FastMCP` — `mcp.server.fastmcp` deliberately raises on import. Wired per README `## MCP`.

**9. Backup, restore, hardening. ✅ DONE 2026-11-16, except the 24 h soak.** Two defects found and
fixed, both visible only on a long-lived real deployment:

- the scheduler slept a full `SYNC_INTERVAL` *before* its first cycle, so a restart meant no sync for
  30 minutes; the first iteration now waits 15 s;
- `_daily_backup` ran only after a successful cycle, so a frozen session also meant no backups. It
  now runs first, before the freeze check, and `python -m app.sync --backup` exists for drills.

Drill, done on the Pi against the live 442 KB database: snapshot → copied into a scratch volume →
`docker run` on port 8092 → `health 200`, `PRAGMA integrity_check ok`, identical counts
(21 posts / 200 accounts / 31 stories / 64 media / 9 sessions) → `/api/history` served real pks and
`/api/accounts` real usernames → torn down. A backup nobody opened is a hope, not a backup, so the
suite now asserts the snapshot opens, matches and is mode 600.

Hardening: `Content-Security-Policy` (`default-src 'self'`, no inline script, `frame-ancestors
'none'`), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`
on every response, asserted by test. Cookie was already `httponly` + `samesite=lax` + `secure` under
`COOKIE_SECURE`, the container was already non-root UID 1000, and `.env` is mode 600. No HSTS: plain
HTTP on the LAN. Idle RSS and the 24 h / no-error-rows soak are not yet measured; that needs a real
day of uptime, not a test.

### Verification

**Automated** — pytest, mock provider, temp dirs, no network:

1. Keyset pagination over 30 rows returns each exactly once, in `taken_at DESC, rowid DESC` order,
   and terminates. Rows sharing a `taken_at` are all returned; the cursor skips and repeats none.
2. Session membership: a post read during the session stays in the set (`seen_at >= started_at`);
   `item_count` and the walk agree; `remaining_in_session` reaches 0 exactly at the last item.
3. `unsee` on a pre-snapshot post does not inject it into an open session (`unseen_at`).
4. `first_seen_sync > snapshot` rows are excluded; a `recovered` run's posts never appear.
5. `around_pk` returns the page containing the post, inclusive; resume after a restart lands on the
   same post.
6. Filters frozen: a mid-session `PUT /api/settings` returns `session_filters_locked`; a new session
   picks up the change.
7. `mark_seen` idempotent; `unsee` reverses; `seen_session` set only when a session was current.
8. Allowlist drops a non-followed author; `is_following = 0` after a complete refresh removes it from
   later sessions while keeping the row; an **incomplete** refresh changes no flags and records an
   error.
9. Sponsored drops: `product_type='ad'`, `is_paid_partnership`, `sponsor_tags`.
10. `kind_of` is total and disjoint over: photo, feed video with NULL `product_type`, reel, igtv,
    carousel, and an unknown `product_type` — every case yields exactly one kind and each toggle
    filters only its own.
11. Filters never delete rows.
12. Story states: all four reachable; `unavailable_at` from upstream 404; expired segments absent from
    the queue and present in `/api/history/stories`.
13. Tier-1 counting works with zero `stories` rows; an account whose newest `fetched_at` predates
    `story_rings.updated_at` is counted unknown, not zero-unseen.
14. `local_done_upto` survives ring staleness and an automatic prune; explicit `/done` overrides.
15. Segment `seen` is written on completion, not on render; a sub-threshold swipe-away leaves it
    unseen.
16. Run lifecycle: an open run is invisible to the snapshot; an orphaned run is recovered and marked;
    every ingest kind opens its own run.
17. Backoff: `next_delay` is the single source; cap binds at streak 4; `streak` resets on success and
    on freeze expiry; a persisted freeze survives a restart; `settings.sync_interval` changes take
    effect on the next iteration.
18. Concurrency: 50 concurrent `POST /api/posts/seen` succeed during a mock cycle, and no request's
    latency exceeds the cycle's duration (no millisecond bound).
19. Media: LRU evicts least-recent first across posts and stories; a ref touched by an open session is
    exempt; stale URL → 404 `no-store`; `Range` → 206 on disk and proxy paths; `MEDIA_CACHE=0` never
    tees a partial; a non-allowlisted host is refused.
20. Backup: the file opens with identical row counts; the 8th prunes the oldest; a stale
    `last_ok_at` surfaces.
21. `test_mcp.py`: every tool payload equals the corresponding REST payload, and `get_feed` with no
    open session creates one for device `mcp`.

**Manual, on the iPhone and MacBook over the LAN** — the six build-time success criteria, plus:

- Kill Safari mid-feed, reopen: same post, same counts.
- Two devices hold independent sessions; take-over moves one without corrupting the other.
- Sync runs while browsing: the session's item count does not change; the dashboard stays responsive.
- Watch a story account fully; the ring moves to done; the next account starts at segment 1.
- Mute an account: posts vanish, count drops, history keeps rows; unmute restores without a resync.
- `kill -9` mid-sync, restart: no duplicates, no leaked posts, no reset backoff.
- Disconnect the container's outbound network: dashboard, feed, stories and history still work, with
  a sync banner (§3.1, §7).
- Restore from backup: counts match, no duplicates, no re-login.
- Video plays in Safari on the iPhone from `/api/media/post/…?size=f`.

**Operational, over the first 30 days** (not a build-time criterion): weekly, confirm no challenge,
no suspicious-login email, no forced reset in the real app. If any appear, halve the sync frequency
before changing anything else.

### Time estimate

| Step | Estimate |
|---|---|
| 0 Feasibility gate | 2 h |
| 1 Store + mock + tests | 4 h |
| 2 API + auth + compose | 5 h |
| 3 Feed UI | 6 h |
| 4 Stories UI (incl. iOS video) | 7 h |
| 5 Remaining UIs | 5 h |
| 6 Real provider + sync | 6 h |
| 7 Media | 3 h |
| 8 MCP | 3 h |
| 9 Backup/restore/hardening | 3 h |
| — | **≈44 h, about 5.5 focused days** |

### §14 deliverable map

| §14 asks for | Where |
|---|---|
| 1 Architecture and component boundaries | Technical Plan / Shape, Concurrency |
| 2 Domain model and schema | Storage, Retention |
| 3 REST API specification | API surface |
| 4 MCP tool schemas and transport | MCP server |
| 5 Content provider abstraction | Provider abstraction |
| 6 Sync and session lifecycle | Sync model, Session membership |
| 7 Story navigation and viewing state | Story model, Story states, Frontend / Stories |
| 8 Docker deployment for Pi 5 | Deployment |
| 9 Security and data retention | Auth, Retention, Backups |
| 10 Epics, milestones, dependencies | Milestones, Order of work |
