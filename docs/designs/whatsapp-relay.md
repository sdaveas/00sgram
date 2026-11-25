# WhatsApp relay

Stage 2 output. Requirements: `docs/requirements/whatsapp-relay.md`. This document
does not change them; where it disagrees, the requirements win and the doc is wrong.

## Problem

The Instagram relay already does the shape of work that is needed here: one Telegram
forum topic per conversation, one Telegram message per incoming message, replies and
reactions travelling back. WhatsApp needs the same thing, and it cannot be the same
code, because WhatsApp Web is not Instagram Web:

| | Instagram | WhatsApp |
|---|---|---|
| freshness | GraphQL last-message id | no API at all; the list row's preview + timestamp |
| message id | in the JSON | `data-id` on the bubble (`conv-msg-<20 hex>`) |
| chat id | `thread.fbid` | none, anywhere; the name is all there is |
| history | one POST per thread, no side effect | must open the chat, which marks it read |
| reaching a thread | GraphQL replay, no navigation | click the list row |
| sending | `send_dm` types + Enter | same idea, different composer |
| reacting | GraphQL mutation, any message id | hover → click → click an emoji image |

So the relay is a DOM adapter plus a loop whose *trigger* is a heuristic but whose
*content* is exact. That distinction is the whole design: the list row only says
"look at this chat"; message ids decide what is new. A false positive costs one read
receipt; a false negative is the only way to lose a message, and it needs two
identical messages in the same displayed minute (see Limitations).

The third constraint is architectural. `browser.py` owns **one page**. The Instagram
sync, the Instagram relay and this relay run at the same time in one process, in
different threads. If this relay navigates "the page", it navigates Instagram's.

## Technical Plan

### 1. `browser.py` — a page per origin

The provider keeps `self._pages: dict[str, Page]` behind one method:

```python
def page_for(self, origin: str) -> Page:
    """One page per origin. Creating the WhatsApp page must never move the
    Instagram one; that is the only reason this exists."""
```

`connect()` keeps its current meaning for Instagram (`_page` = the instagram.com tab,
`goto(WEB)`, cookie check). It is split so that the browser attach step is reusable:
`_attach()` starts Playwright, connects over CDP or launches the profile, and sets
`_ctx`; `connect()` then resolves the Instagram page and checks the cookie. The CDP
path already finds a page by URL; the profile path currently takes `pages[0]` and is
changed to find-by-URL-then-`new_page()`, which is the only behavioural change there
and strictly less fragile.

WhatsApp work goes through seven thin methods on the provider, so every call stays on
the owning thread through `ThreadProxy` (Playwright's sync API is thread-affine — a
direct `page.evaluate` from the relay thread is a greenlet crash):

```python
wa_eval(js, arg=None)      wa_click(x, y)     wa_move(x, y)
wa_type(text)              wa_press(key)      wa_wait(ms)      wa_screenshot(path)
```

`wa_page()` resolves `page_for("https://web.whatsapp.com")` and navigates that page
only if it is not already on that origin. Being logged out is not an exception it
raises: the page is simply missing `#pane-side`, and `wadirect` reports that.

Serialising individual calls is **not** enough, and the first draft of this doc said
it was. One WhatsApp operation is several calls — `open` is a click plus a header
poll, `messages` is another read — so two daemons can interleave and read a
different conversation than the one they were told to open, posting its messages
into the wrong topic and poisoning that topic's id set. And `send` brackets its proof
(`before` … `after`) around a click and a typing burst, so an interleaved `open` by
the reactions daemon would record a stranger's newest id as "ours". The fix is one
lock around a whole operation: `_Hands` (the provider wrapper the relays get) owns a
`threading.RLock`, and `Wa` takes it for the length of each compound method. An RLock
because `send` calls `open`. Per-call borrowing is still what the lock is built on —
`ThreadProxy` remains the thing that keeps Playwright on one thread.

### 2. `app/wadirect.py` — the adapter (selectors only)

Its constructor takes a *hands* object with the seven methods above, so tests pass a
fake and no browser is involved. Only inside `wadirect` are selectors spelled.

```python
class Wa:                       # one per cycle, cheap
    def chats(self) -> list[dict] | None
        # None when the list is absent (still loading, or a QR screen)
        # [{name, preview, ts, unread, self, x, y, top, bottom}]
        # rows: #pane-side [data-testid^="list-item-"][role="row"]
        # name: cell-frame-title, whitespace folded   preview: cell-frame-secondary
        # ts:   chat-list-timestamp                    unread: icon-unread-count
        # self: message-yourself-row present, or a name ending in "(You)"
        # x, y: the row centre, for wa_click; top/bottom: for the header check
    def ready(self, tries=15, step=1000) -> list[dict] | None
        # chats(), waiting for the page; bounded, because a QR never becomes one
    def find(self, name, preview="") -> dict | None
        # None when zero rows match *and* when two do: the name is the state key
    def open(self, name, preview="") -> bool
        # click the row centre, wait for the header to name the chat, retry once
    def messages(self) -> list[dict] | None
        # None = no panel at all; [] is an empty chat
        # [{id, text, mine, sender, icons}] in DOM order, for the open chat
        # bubbles: [data-testid="conversation-panel-messages"] [data-id]
        # mine/sender: the row's first aria-label ending in ":" ("You:" = mine),
        #              falling back to [data-icon="tail-out"]
        # text: .selectable-text; when there is none, icons -> a label
    def send(self, name, text, preview="") -> str
        # open(name), click the composer, type, Enter; returns the new message id,
        # "" when the newest id did not change
    def react(self, name, msg_id, emoji) -> bool   # ValueError if not one of six
        # open(name), scroll the bubble into view, hover it,
        # click [data-testid="reaction-entry-point"], then the emoji tile:
        # the largest same-row group of img[alt] whose alts are the six quick ones
        # add: verified by the emoji being on the bubble; "" removes and is
        #      verified by it being gone (the pill is read first, and is only a
        #      reaction if its alt is one of the six — on a photo the first
        #      img[alt] outside the text is the thumbnail)
    def qr(self, path) -> bool
        # screenshot + whether a canvas/[data-ref] is on screen
```

Direction and sender are read from one place: an outgoing row carries an `aria-label`
of `You:` (observed live), an incoming group row carries the author's. That single
rule also gives the group prefix requirement (R7) without a second selector. It also
means the locale matters: the launch sets `en-GB` and `^you:?$` is matched against
English. A different locale would make every message "incoming"; `en-GB` is a
deployment requirement, not a preference.

R16 says a duplicate name is disambiguated by preview. This design narrows that: a
name with more than one mounted row is skipped, preview or not. Two chats sharing a
name cannot have separate marks (`wa_marks` is keyed by name) or separate topics, so
"disambiguating" would only choose which of the two gets both conversations' messages.
Skipping and logging is the safe reading; the alternative is a data model with a
synthetic key that no requirement asks for.

### 3. `app/warelay.py` — the loop

Not a generic version of `relay.py`. It reuses `relay.line_for` (media labels, link
under text) and `relay.topic_for` is *not* reused — `topic_for` writes `ig_threads`;
`warelay.topic_for` is the same eight lines against `wa_chats`. Copying eight lines
beats a `kind` column, which is the bug this design refuses to create.

```python
def relay_once(tg, conn, chat_id, wa) -> int
    # 1. rows = wa.ready(); None -> raise NotLoggedIn (cycle logs, retries)
    # 2. first run ever (meta wa_relay.primed false): store the visible
    #    (name, preview, ts, unread) rows, post nothing, open nothing, return 0
    # 3. watch = rows with no mark at all, a mark whose `pending` is set (a burst
    #    was cut short), or a (preview, ts, unread) triple that moved
    # 4. for the first MAX_CHATS of those: wa.open(name, preview); rows =
    #    wa.messages(); new = [m for m in rows if m["id"] not in known ids]
    #    - chat never read (no stored ids): post only new[-1]
    #    - otherwise: post every new one, in DOM order
    # 5. each post: topic_for(...) once per chat, tg.send, store wa_sent_map
    # 6. store the ids (last 200), the triple **after** opening (the badge is
    #    cleared now), and `pending` while any unseen message was not settled
def topic_for(tg, conn, chat_id, name, create=True, is_self=False) -> int | None
def start_wa_relay(config, conn, syncer) -> Event
def start_wa_outbox(config, conn, syncer) -> Event
def start_wa_reacts(config, conn, syncer) -> Event
```

The triple is the trigger, and it is deliberately not trusted: it decides *which chats
to open*, never what to send. Two identical previews in the same minute are the known
cost, and it is written down rather than papered over with an age heuristic.

Three ordering rules, each of which is a bug if reversed. **The battery is per cycle,
not per chat**: `MAX_PER_CYCLE` is a budget shared by all `MAX_CHATS` conversations,
or a cycle could post 100 messages. **The mark advances only past what was actually
settled** — the last message that was sent, or deliberately skipped for having no
line. A burst cut by the budget, or a send that hit a stale topic, leaves the rest
unseen and sets `pending`, so the next cycle opens that chat again even though its
list row has not changed; marking the whole tail there is how a relay silently loses
messages. **The mark is written after the send**, so a crash in between reposts one
message on restart. That is the side the design chooses: a duplicate is visible and
harmless, a gap is invisible.

Self chat: `rows` keeps `mine` messages only when the chat is the self chat, and drops
any id the relay itself typed (`wa_sent_map.typed=1`), which is what makes R9 and R10
not fight each other. A *relayed* message is also in `wa_sent_map` (`typed=0`) because
a reaction may target it later; conflating the two meanings would make every
phone-typed message look like an echo.

### 4. `store.py` — four tables, no `kind` column

```sql
wa_chats      (name PK, thread_id, is_self, created_at)
wa_marks      (name PK, ids TEXT /* JSON, last 200 */, preview, ts, unread,
               pending, updated_at)
wa_sent_map   (chat_id, tg_msg_id, name, wa_msg_id, created_at, typed,
               PK(chat_id, tg_msg_id))
wa_reacts     (id, chat_id, tg_msg_id, emoji, at, done, error)
```

`ig_threads` is untouched. `queue_reaction` / `next_reaction` / `finish_reaction` gain
one keyword argument, `table="ig_reacts"`, validated against a two-name whitelist —
the three functions are otherwise identical and duplicating them buys nothing. The
caller that matters is `telegram.ingest`, which is the only place that sees the
reaction *and* the group it was pressed in. It gets the WhatsApp group id as an
argument and files the row in `wa_reacts` when they match, `ig_reacts` otherwise.
Otherwise one relay's worker drains the other's queue and closes every reaction as
"no matching message" — that is the whole of R11/R12 dead, silently. Every other
helper is new and WA-specific (`wa_thread_id`, `wa_name`, `save_wa_thread`, `wa_mark`,
`save_wa_mark`, `map_wa_message`, `wa_message_for`, `wa_message_sent`).

### 5. Telegram cross-talk — one real bug to fix in `relay.py`

Topic ids are per-group and start low, so a WhatsApp topic and an Instagram topic can
both be `5`. `relay.send_row` resolves a `tg_messages` row by `thread_id` alone, and
`ig_threads` might own that number even though the message came from the WhatsApp
group. Two lines: both outboxes filter on their own `chat_id`. This is a bug fix, not
a feature: it also stops random groups with a `thread_id` from being written to
Instagram. It is the only change to `relay.py` and `tests/test_relay.py` gains the
case.

### 6. Wiring

`config.py`: `wa_relay_chat` (`WA_RELAY_CHAT`, empty = off), `wa_relay_send`
(`WA_RELAY_SEND`), `wa_relay_fast` (20 s), `wa_relay_slow` (90 s).
`main.py`: start the three daemons next to the Instagram ones, stop them in the same
shutdown block. Reuse `syncer.borrow()` **per step**, never across a whole cycle: a
cycle of twenty clicks is seconds long, and holding the lock would starve the sync.
The `ThreadProxy` already serialises individual calls, so per-step borrowing is both
safe and enough.

Turning it on, in order:

1. Create a **separate forum group** in Telegram (a Supergroup with Topics on), add
   the bot, and make it an admin with *Manage Topics*.
2. `WA_RELAY_CHAT=-100…` (the group id), `WA_RELAY_SEND=true` when replies from
   Telegram should reach WhatsApp. Empty `WA_RELAY_CHAT` means the relay is off and
   nothing WhatsApp-related starts.
3. Scan once: `curl -H "x-api-token: $API_TOKEN" -H "x-device: cli" \
   -o /tmp/wa.png http://host/api/wa/qr` and open the PNG. `x-wa-qr: 1` means a QR is
   on screen; `0` means already logged in.

Login: `GET /api/wa/qr` (normal auth) renders the WhatsApp page and returns
`image/png`, so the operator can pull it with `curl` from the same machine — no second
process fighting the profile lock. A `--qr <path>` CLI flag exists for the CDP case.

## Alternatives

- **Reuse `relay.py` with a `kind` column.** Rejected, and it is the reason
  `docs/requirements` says "do not make relay.py generic". The two relays key marks
  differently (IG: a timestamp + last id, monotonic; WA: a set of ids, unordered and
  truncated), their topics live in different groups, and a shared table would let one
  relay's cleanup delete the other's state. Eight copied lines are cheaper than one
  conditional per query.
- **A real WhatsApp client** (Baileys / whatsapp-web.js / wppconnect). Technically
  better in every way that matters here: real chat ids (no rename orphans), push
  events (no polling, no preview heuristic), no navigation, no read receipts, media
  access. Rejected for the same reason `ig-relay-json.md` rejected the mobile API: it
  is a re-implementation of an unofficial multi-device protocol, it needs its own Node
  runtime and its own QR handshake per restart, and it is the shape WhatsApp polices
  hardest — the account is the thing at risk, not the request. A logged-in browser
  clicking what a person clicks is the lowest-risk option that still works, and this
  app's whole premise (`browser.py`) is that the browser *is* the client.
- **Detect freshness from the unread badge only.** Cheap and exact-ish, but the self
  chat is never unread (everything in it is you), so acceptance test 1 could not pass.
  The triple keeps self chat in the same code path as everything else.
- **Read every chat every cycle.** No heuristics at all, but it is 22 clicks and 22
  read receipts every 30 seconds. Rejected: it makes the read-receipt cost the
  product.
- **Scroll the virtualised list to see all 22+ chats.** Unnecessary. A chat with a new
  message is by definition at the top — verified live, the self chat jumped from row 10
  to row 0 the moment a message was sent. The mounted rows are the whole search space.
- **Two provider instances, one per origin.** Rejected: the persistent profile has one
  owner, and two `sync_playwright` instances in two threads is a greenlet problem
  dressed as an architecture. `page_for` is ten lines.
- **Ask Telegram for the topic's chat so no filter is needed.** The Bot API cannot
  enumerate forum topics, so the outboxes cannot learn which chat a `thread_id` belongs
  to. Filtering by `chat_id` in the row is the only honest fix.
- **A dedicated Chromium for WhatsApp.** A second profile means a second QR scan and a
  second login to keep alive, for a tab that costs nothing.

## Detailed Implementation

Order of work is the phase table in `docs/phase-status.md`; every phase ends with a
command that fails if it is wrong.

1. **store + config** — the four tables, the helpers, the four config fields, the
   `wa_reacts` table argument. Check: `pytest tests/test_wa_store.py`.
2. **`browser.page_for`** — split `_attach`/`connect`, add `_pages` and the seven `wa_*`
   methods. Check: `tests/test_browser.py` gains a case proving `page_for("wa")` does
   not touch the Instagram page; the 228 existing tests stay green.
3. **`wadirect`** — `chats/open/messages/send/react/qr` against a fake hands object
   built from the live probe's HTML (a `chats()` fixture, a `messages()` fixture with
   one incoming, one outgoing, one photo, one group message). Check:
   `pytest tests/test_wadirect.py`.
4. **`warelay.relay_once`** — the loop, marks, topics, self-chat rule, dedup, no
   backfill. Check: `pytest tests/test_warelay.py` with a fake `Wa` and a fake
   `Telegram`: exactly one TG message per WA message, nothing on the priming cycle,
   only the newest on first sight, a restart posts nothing.
5. **outbox + reacts** — cursor, `chat_id` filter in both outboxes, `wa_reacts` drain,
   the six-emoji gate. Check: `pytest tests/test_warelay.py tests/test_relay.py`.
   A send that cannot be proven (`Wa.send` returns `""`) gets one retry and is then
   dropped with a warning: the cursor must advance or the queue jams on a chat that
   will never open. What proves a send is a *new outgoing* id at the tail of the
   transcript; a concurrent incoming message also changes the tail id, so the check
   is "the last row is an outgoing one we have not seen before" rather than
   "the id changed".
6. **live, self chat only** — start the app with `PROVIDER=browser`,
   `BROWSER_CDP=http://127.0.0.1:9222`, `WA_RELAY_CHAT` = the test group. Evidence:
   a message typed in the self chat appears once in its topic; a reply from the topic
   arrives in the self chat; ❤ from the topic appears under the bubble; restart posts
   nothing twice. Nothing is sent to a real contact — the self chat is the only
   conversation the relay is pointed at until the operator says otherwise. The QR
   route takes the same borrow as everything else; when the account is already
   logged in it returns a screenshot with `x-wa-qr: 0` and the page's chat list,
   which is the operator's "nothing to scan" signal.

### Limitations, stated where the operator will read them

- Rename either side → new topic (no chat id exists to key on).
- Opening a chat marks it read for the other party.
- Two identical messages in the same displayed minute, with no unread badge change,
  can be missed. Fix if it ever bites: open every chat whose list position moved.
- Two conversations with the same name are skipped, not merged (see §2).
- Priming stores no ids, because priming opens nothing. A message that arrives
  between priming and that conversation's first read is therefore only partly
  visible: the first read posts its newest message and treats the older ones as
  history. The window is one cycle, and the alternative — opening all 22 chats to
  seed their ids — spends 22 read receipts to close it.
- Only 👍 ❤️ 😂 😮 😢 🙏 travel back as reactions.
- The relay relays `mine` messages only in the self chat.
- A group message whose author cannot be read is posted bare: it looks like a DM.
  Groups where the author line is missing are a locale/UI change, and the next
  probe should re-check `role="row"`'s first `aria-label` ending in `:`.
- `relay.line_for` truncates at 3500 characters *after* appending the URL, so a very
  long message loses its link. It is Instagram's behaviour and is left alone here;
  fixing it would change that relay's output for no requirement of its own.
- No media, no status, no calls, no WA→TG reactions.
