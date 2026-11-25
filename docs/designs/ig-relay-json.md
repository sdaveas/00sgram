# Instagram relay: read the JSON, not the pixels

## Problem

The relay decides "something arrived" by comparing strings scraped off the inbox
DOM: the conversation's name and its preview line, plus an age token (`2h`) used
to guess that a generic preview ("Mary sent an attachment.") belongs to a fresh
message. That signal is fake in three separate ways:

1. **The preview repeats.** Instagram says `X sent an attachment.` for every
   photo, post, reel and story. The same string means "new message" and "the
   same message as an hour ago", so the relay cannot tell them apart and invents
   an age-reset heuristic that fires at random.
2. **The list is virtual and unstable.** Rows are re-rendered mid-scroll; a
   scrape can catch a row whose first line is `Active 7m ago` instead of a name
   (this is where the `Active` topic came from), or a preview mid-transition.
3. **Opening by name is a guess.** `OPEN_JS` matched on
   `first.startsWith(want) || want.startsWith(first)`, so `nika` could land on
   `nika and Giorgos Papadakis`. The messages that come back are then another
   conversation's history — old messages delivered today.

Symptom the user reports: many irrelevant messages, mostly in one topic, and
individual chats replaying things from months ago.

## Technical Plan

Instagram's web DM page is a React app that fetches everything it renders from
`POST /api/graphql`. Two operations cover the whole relay:

- `PolarisDirectInboxQuery` — every thread with its `id`, `last_activity_timestamp_ms`,
  `users[]` (username + fbid), and the last message's `id`, `timestamp_ms`,
  `content_type` and text.
- `IGDThreadDetailQuery` — one thread's last 20 messages with real
  `timestamp_ms`, `sender_fbid`, `text_body`, and for shared posts a
  `content.xma.target_url` holding the actual permalink.

So the relay becomes:

- **Freshness** = `thread.id` + last message `id`. An id never repeats; a
  preview string does.
- **Which messages** = everything with `timestamp_ms` greater than the stored
  watermark for that thread. No overlap heuristics, no tail guessing.
- **Identity** = the thread id from the JSON, which is also the topic mapping
  key. Renames in either app stop mattering.
- **Content** = `text_body`, the xma title, and `target_url`. The post permalink
  the DOM only ever gave us as the author's profile is now available directly.

Replay mechanics: the page's own POST body is captured once (`page.on("request")`),
cached in `meta` as `ig_gql`, and replayed through `page.evaluate(fetch)` with only
the `variables` parameter swapped. `doc_id` rotates every few weeks, so a replay
that fails refreshes the template from one navigation and retries once.

`IGDThreadDetailQuery` replay needs no navigation, so **the relay stops marking
conversations as read** — the read-receipt cost that justified "only look when
the preview changes" disappears.

## Alternatives

- **Keep scraping, fix the heuristics.** Already attempted twice (age reset,
  first-sight = newest bubble). Each fix needs another heuristic because the DOM
  does not expose message ids at all. Rejected: the information is simply not
  there.
- **The mobile API** (`i.instagram.com/api/v1/direct_v2/inbox/`). It has the same
  data, but it needs a different session (app credentials, device ids) and is the
  endpoint Instagram polices hardest. The web GraphQL endpoint is the one the
  user's own browser calls all day.
- **Read responses instead of replaying requests** (`page.on("response")` +
  `response.text()`). Sync Playwright makes body reads inside event handlers
  fragile; replaying a captured body gives the same JSON on demand, with
  pagination under our control.
- **Push updates** (`iris` MQTT subscription, `useIGDSystemFolderUnreadThreadCountQuery`).
  Real-time and cheap, but it is a websocket protocol with its own reconnect
  logic. Not worth it while a 45s poll costs one HTTP call.

## Detailed Implementation

`app/igd.py` (new):

- `Direct(provider, conn)` with `threads()` and `messages(thread_id)`.
- `_template(name, capture_path)` → cached body from `meta["ig_gql"]`, captured
  by `provider.capture()` when missing or stale.
- `_call(name, path, **variables)` → replace the `variables` parameter, replay,
  parse; on `errors`, refresh the template once.
- `threads()` → `[{id, name, group, users, viewer, last_id, last_ts, last_text}]`
  sorted newest first.
- `messages(thread_id)` → `[{id, ts, mine, sender, text, url}]`, oldest first,
  with the content-type mapping for media and shares.
- Pruning is not this module's business: it returns what Instagram returned.

`app/browser.py`:

- `graphql(body)` — one `page.evaluate` POST, returns the response text.
- `capture(path, name)` — `net()` internals, one name.

`app/relay.py`:

- `plan`/`fresh`/`_generic`/`GENERIC`/`OURS` deleted. Replaced by
  `diff(state, threads)` which returns the threads whose last message id differs
  from the stored one and is younger than the cutoff.
- `relay_once` asks `Direct.messages()` for those threads only, sends each
  message newer than the watermark as its own Telegram message, then moves the
  watermark.
- First sight of a thread (no watermark) sends only the newest message, and only
  if it is younger than `IG_RELAY_CATCHUP` hours (default 6). A thread that
  reappears after a week of silence must not dump a week of history.
- Topic mapping keyed by Instagram thread id (`ig_threads.ig_id`), so a rename
  does not orphan a topic; the display name fills the title on creation.

Tests: the JSON is turned into rows in `igd.py`, so the relay tests feed
fabricated thread/message dicts and assert exactly one Telegram message per
Instagram message, no old messages on first sight, watermarks advancing, and the
post permalink appended under the text.

## Reactions (added after the JSON rewrite)

A reaction creates no message, so it cannot be a trigger: nothing in the inbox
changes when someone hearts something. It is also the one operation with no
documented surface, so the mutation was learned by watching the page do it.

`IGDirectReactionSendMutation` takes
`{"input": {emoji, item_id, message_id, reaction_status, thread_id}}`, where
`reaction_status` is `"created"` or `"deleted"`. That is the whole feature:
one POST, exact emoji, any message id — including old ones.

The mutation never fires on a page load, so its template cannot be captured the
way the two queries are. `_capture_reaction` presses the button instead: hover
the newest bubble, click "React to message", click the first emoji tile, watch
the request, then replay it with `reaction_status: "deleted"` so capturing a
template never leaves a heart behind. This only runs when the cached `doc_id`
is missing or has been rotated.

Telegram side: the long poll now also asks for `message_reaction`; each one is
queued in `ig_reacts`, and `relay_once` writes `(chat, tg_msg_id) -> (ig_id,
ig_msg_id)` into `ig_sent_map` as it sends. A worker drains the queue. A
reaction on a message the relay never sent (backfill blocks, anything typed in
the group) has no map entry and is dropped.

Not done: Instagram -> Telegram reactions. They would have to be diffed out of
each thread read, and a thread that gets no new message is never read.
