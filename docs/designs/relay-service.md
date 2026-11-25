# The relay becomes its own service

## Problem

The Telegram relay is welded into the web app. Two consequences that now bite:

1. **One process, two jobs.** The relay borrows the same browser and the same
   event loop as the feed. A crash in either is a crash in both, and turning
   Telegram on means shipping it inside the web image.
2. **Transport in the schema.** `tg_chats` / `tg_messages` sit next to the feed
   tables and the UI reads them directly, so the app's idea of "a conversation"
   is Telegram's idea. That is the mistake the in-app chat work just undid for
   reading; the relay still writes there.

The core is now the only thing that should own the browser, the Instagram
session and the message store. The relay should be a client of that core, the
same way a phone is.

## Technical Plan

Split along the line that already exists: **browser session = core app;
Telegram = a separate process that speaks HTTP.**

1. **Core grows a chat sync.** Nothing fetches thread contents today; the relay
   fetched them one thread at a time as it relayed. A loop walks the chat list
   every minute and fetches only threads whose newest message id changed.
2. **Core grows the API the relay needs.** `GET /api/chat/changes?since=` —
   everything inbound since a cursor, across threads, deduped by message id.
   Plus the three routes the in-app chat already adds (list, thread, send).
3. **The relay becomes `python -m app.relayd`.** Same image, second compose
   service, own volume, no ports. It holds its own SQLite (topic mapping,
   dedupe, outbox) and talks only HTTP to `http://web:8080` with `API_TOKEN`.
4. **The in-process relay is deleted**, not kept behind a flag. Its tests move
   to the service, with a fake API and a fake Bot API.

Topic mapping moves to the relay's database: the core never learns what a
Telegram topic is.

## Alternatives

- **Keep it in-process behind a flag.** No isolation, and the schema stays
  mixed. Used only during cutover (a day), never as the end state.
- **Relay reads the app's SQLite directly (shared volume).** No API to build,
  but the relay then depends on table shapes, on WAL locks across containers,
  and on the volume being on the same host. Rejected: it is the coupling we are
  removing, just quieter.
- **Telegram webhooks instead of long polling.** Needs a public HTTPS endpoint;
  this is a LAN tool with one password.
- **A queue (Redis) between core and relay.** One more moving part for a handful
  of messages a minute; HTTP + a cursor is the queue.
- **Let the relay own the sync loop** (it does today via `relay_once`). Then the
  relay needs the browser — the exact thing we are separating.

## Detailed Implementation

- `app/store.py`: `ig_thread_last(thread_id PRIMARY KEY, last_id TEXT)` to know
  which threads changed, and `ig_changes(conn, since, limit)` over `ig_msgs`
  (`mine=0 AND at >= since`, oldest first).
- `app/chat_sync.py`: `sync_once(provider, conn)` — list → for each thread whose
  `last_id` differs, `igd.Direct.messages()` → `save_ig_msgs` → record
  `last_id`. Runs in the existing scheduler thread every `CHAT_SYNC_INTERVAL`
  (default 60 s), and not at all while sync is paused.
- `app/main.py`: `GET /api/chat/changes?since=<unix>&limit=50` →
  `{messages: [{thread_id, msg_id, at, who, text, kind, links}]}`. No browser
  involved: the store answers.
- `app/relayd.py`: config (`API_URL`, `API_TOKEN`, `TELEGRAM_TOKEN`,
  `TELEGRAM_RELAY_CHAT`, `RELAY_DB`), its own schema (`topics`, `seen`,
  `outbox`), Telegram long poll, and two loops — inbound topic message →
  `POST /api/chat/send`; changes cursor → one Telegram message per conversation
  per batch (reusing `line_for`/`batches` logic, moved, not rewritten).
- `docker-compose.yml`: `relay` service, same image, `command: python -m
  app.relayd`, volume `relay:/data`, `profiles: [relay]`. `TELEGRAM_*` leaves
  the web service's `.env` block.
- Delete `app/relay.py` wiring from `app/asgi.py` (`start_poller`,
  `start_outbox`, `start_reacts`); `app/telegram.py` stays as the Bot API
  client the service imports.
- Tests: `tests/test_chat_changes.py`, `tests/test_relayd.py` (fake API via
  `httpx.MockTransport`, fake Telegram), and the existing `test_relay.py`
  cases re-pointed at the service functions.

Cutover: run the service alongside the in-process relay for one day with
`TELEGRAM_RELAY_INPROC=0` on the web container, watch for duplicate posts
(dedupe hides them but the log shows them), then delete the old path.
