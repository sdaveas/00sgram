# Messages (DMs), read through the browser

## Problem

The app knows about posts and stories and nothing about direct messages. A
person who lives in this app has to open Instagram to see whether anyone wrote
to them, which is the one errand the app does not cover.

Instagram's DM REST path is gone: `GET /api/v1/direct_v2/inbox/` answers 404 to
the logged-in browser, while timeline, follows and stories still work. What is
left is GraphQL with `doc_id`s that rotate with each web release, and the
rendered inbox itself.

So the question is not "which endpoint" but "how little of the DM surface can we
own". The answer this document takes: **mirror the view, never the API**, and
only the parts that a person could not be surprised by.

Two facts constrain everything below, both measured in the logged-in Chromium
the sync already drives:

- `/direct/inbox/` renders the whole conversation list as text: name, last
  message, age, and an explicit `Unread` line. Reading it does not change
  anything on Instagram.
- Clicking a row opens `/direct/t/<thread id>/` and **marks it read**. There is
  no peek: the same thing happens when the person opens it in Instagram. That
  is a side effect this feature has to say out loud rather than hide.

## Technical Plan

A new provider surface, browser-only, plus a view that renders what it returns.

```
browser.py     inbox()            → [{name, preview, when, unread}]
               thread(name)       → {thread_id, lines: [...], ok}
direct.py      INBOX_JS, THREAD_JS, OPEN_JS   — the DOM queries, as strings
               clean_inbox(raw), clean_thread(raw)  — pure normalisers, testable
main.py        GET /api/inbox
               GET /api/inbox/thread?name=…
views.js       messages(el) + route #/messages + File ▸ Μηνύματα
```

- **Text, not markup.** Every query returns `innerText` lines and rectangle
  sizes. Instagram's classes are obfuscated and change; its wording ("Unread",
  "2 new messages", "Seen by …") is what we already depend on for stories. No
  HTML from Instagram reaches the page.
- **The list is the feature.** Status lives entirely in `inbox()`: the row's
  name, preview, age and unread marker. Opening a thread is opt-in, because it
  costs the person their unread state — the view says so once, in a line under
  the list.
- **Open by name, resolve the id afterwards.** Rows carry no id in the DOM that
  survives React's props removal (measured: no `__reactProps` hit, no
  `href="/direct/t/…"`), so the adapter clicks the row whose first text line
  equals the name, waits, and reads the thread id from `location.href`. The next
  open of the same thread can use the id directly.
- **One page, serialised.** The provider is single-threaded; `inbox()` and
  `thread()` queue behind sync and media like every other call. Each costs a
  navigation plus ~5 s of render, so the list is cached in `meta` and served
  stale-with-a-flag when the browser is busy or Instagram misbehaves.
- **A scrape failure is a sentence.** No stacks in a feed: the endpoint answers
  `{items: [], error: "…"}` and the view says «Δεν φόρτωσαν τα μηνύματα.».

### Alternatives, and why not them

- **GraphQL `IGDInboxQuery` with a discovered `doc_id`.** Faster (one request,
  no render) but the id changes with every release; when it changes, the feature
  dies silently and the token of the day is a string nobody can verify. The DOM
  at least fails the same way every time: the words are not there.
- **Replay `/api/v1/direct_v2/…`.** Measured 404 on this account today. A path
  that Instagram has retired is not a foundation.
- **Read the Relay preloader JSON like the story page.** The inbox page ships no
  thread payload in `script[type="application/json"]` (measured: 0 scripts with
  `thread_id`). The data arrives later, over GraphQL, into the client store.
- **Poll the inbox in the background.** It is one more thing to keep fed, and
  the point of this app is to be quiet. The list is fetched when the view opens.

### Deliberately out of scope (v1)

Sending, reactions, typing state, receipts beyond the `Seen by` line, media
thumbnails, message requests, groups beyond the name they already show, and any
badge pushed into the bulletin. Each is another dependency on a surface that has
no contract; the list alone answers "has anyone written to me?".

## Detailed Implementation

`app/direct.py`

```python
INBOX_JS = """() => { … }"""      # [role=button] rows → [{lines, unread}]
OPEN_JS  = """name => { … }"""    # click the row whose first line is `name`
THREAD_JS = """() => { … }"""     # right-hand scroll box → {url, lines}

def clean_inbox(raw):    # first line = name, a time token = when,
                         # the line between them = preview, "Unread" = flag
def clean_thread(raw):   # thread id from raw["url"], lines with nbsp dropped
```

`app/browser.py`

```python
def inbox(self) -> list[dict]:        # goto /direct/inbox/, wait, INBOX_JS
def thread(self, name: str) -> dict:  # goto inbox, OPEN_JS, wait, THREAD_JS
```

Both raise `SessionExpired` when the page lands on a challenge or a login wall —
the same two sentences the rest of the provider uses.

`app/main.py`

```python
GET /api/inbox                 → {items, fetched_at, stale, error}
GET /api/inbox/thread?name=…   → {thread_id, lines, error}
```

The list is written to `meta["inbox_cache"]` on success and served from it (with
`stale: true`) on failure. The thread is never cached: it is a live view that
has already cost the person their unread state.

`app/static/views.js`

`messages(el)` paints a sheet like the others: a heading, the note about read
state, then rows (name, age, preview, a mark for unread). A row press replaces
the sheet's body with the transcript, one line per text line, monospace-free and
wrapping, plus a way back to the list. `#/messages` is routed like `/sync`, and
`File ▸ Μηνύματα` is the door.

Tests

- `tests/test_direct.py` — normalisers on recorded fixtures: a row with a time,
  a row with `Unread`, a group row, a thread transcript with `Seen by` lines and
  a `nbsp`.
- The endpoint tests use a stub provider, so CI never touches Instagram.
- `tests/live_inbox.py` — opt-in, drives the real browser and prints the list it
  got, so a break shows up as words rather than a timeout.
