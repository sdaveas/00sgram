# In-app chat (DMs without Telegram)

## Problem

The Messages view shows the Telegram mirror: two tables written by a bot
long-poll. With no bot configured the inbox is empty, and the app cannot answer
a DM at all. Meanwhile the relay already holds everything a chat needs — reading
a mailbox and a thread straight from Instagram's own JSON (`igd.Direct`), and
writing a reply by typing into the real thread (`BrowserProvider.send_dm`).
Those two pieces answer each other; Telegram was only a delivery channel.

## Technical Plan

Make Instagram the source, keep Telegram as an optional mirror.

1. `igd` learns three facts about the last message of each thread (text, kind,
   whether we sent it). Everything else it already returns.
2. A cached list and a local message store: Instagram is asked at most once per
   20 s for the list and once per 8 s per open thread. The store answers the
   rest, so a 6 s UI tick costs SQLite, not a browser.
3. Three routes — `GET /api/chat`, `GET /api/chat/thread?id=`, `POST
   /api/chat/send` — returning exactly the shape `views.js` already renders
   (same field names), so the front end changes four URLs.
4. Send reuses `relay.send_row`'s proven path: thread id → the inbox name →
   `provider.send_dm(name, text)` under `syncer.borrow()` (one browser).
5. Unread comes from a stored watermark per thread; opening a thread moves it.
   No read receipt is sent to Instagram (recorded below).

## Alternatives

- **Shape adapter behind `/api/messages`.** Rejected: two unrelated id spaces
  (Telegram topic ids, Instagram thread ids) behind one field. Whichever source
  wins, the other becomes a bug waiting for a config change.
- **Second tab for native chat.** Rejected: two lists of the same conversations,
  two pollers, and the reader has to know which one is real.
- **Send through a GraphQL mutation** (like `igd.react`). The right shape, but
  the mutation template only exists once the page has fired a send, and nobody
  has captured one. `send_dm` is already exercised by the relay every day.
- **Fetch every thread on every tick.** Rejected: one browser navigation per
  conversation per tick is how the account gets challenged.
- **Mark read on Instagram when a thread opens.** Deferred: it needs the DOM
  path (`provider.thread(name)`, a full navigation), so opening a chat would
  cost seconds and a read receipt — a write — just to clear a dot.

## Detailed Implementation

- `app/igd.py`: `thread_rows` adds `last_text`, `last_kind`, `last_mine`
  (`sender_fbid == viewer`). Additive; the relay ignores it.
- `app/store.py`: tables `ig_msgs(thread_id, id, ts, mine, sender, text, kind,
  url, PRIMARY KEY(thread_id, id))` and `ig_read(thread_id PRIMARY KEY, at)`;
  helpers `save_ig_msgs`, `ig_msgs`, `ig_mark_read`, `ig_read_at`,
  `ig_unread_all`. List cache stays in `meta['ig_chat_list']` with
  stale-on-failure, like `inbox_cache`.
- `app/main.py`: the three routes. Title is the thread title, else the other
  participant's username. `unread` compares the last message with the
  watermark; on the very first list every thread is seeded as read.
- `app/static/views.js`: `/api/messages` → `/api/chat`, thread and send
  likewise. `configured` is always true for Instagram, so the composer is
  always available.
- `tests/test_chat_api.py`: list shape and unread, thread stores and reads
  back, send calls `send_dm` once and returns a bubble-shaped row, empty text
  and unsupported provider refused. `tests/test_ui.py` follows the new URLs.
- The Telegram relay and its routes stay exactly as they are; nothing reads
  `tg_messages` for the UI any more.
