# Millennial browse mode — design

Requirements: `docs/requirements/millennial-browse-mode.md`. This document may cite
them and may not silently change them. Four amendments were made *in the
requirements* after goldfish round 1 and are marked there:

- **R13** reads `/api/older`, not `/api/history` — history lists the posts just
  swiped, so its first page would append nothing;
- **R11 was amended on the owner's request:** sound is remembered, through the
  player's own `00sgram.muted`, and R11 now reads that way. The old text said
  "per video, nothing is remembered"; a run of videos needed one press each, and
  the browser's refusal is handled by falling back to muted and saying so.
- **R11**'s original shape — autoplay always muted, nothing remembered —
- **R12/R13** say «Παλαιότερα…», the wording the deck already ships;
- **R15** orders the exit as "remember, then navigate, replacing the entry".

## Problem

The program's only appearance is a 2000 desktop window: title bar, menu bar, status
bar, a paged bulletin of rows, and a player modal with a tray and a transport. One
post costs a row, an open, a close. A millennial user reads none of that as a feed.

What has to exist: a second appearance for the same account, same session, same
unseen set, same seam that writes seen — one card per screen (an unseen post, or an
account's unseen stories on the album axis, see `stories-in-browse.md`), swipe up for
the next older card, swipe right for the post's other pictures, no chrome, and a hard end at
the last unseen post with one button that reaches back into older posts.

The v2 contract must survive untouched: finite session, independent story progress,
seen written on open, no autoplay in the player or in stories, no writes to
Instagram. Albums already exist in v2 (nav row `Προηγούμενο / φωτό 2 από 6 /
Επόμενο`); this mode gives them a second axis instead of a row of buttons.

## Technical Plan

### Two modes, one program

| | windowed (existing) | browse (new) |
|---|---|---|
| route | `#/feed`, `#/stories`, … | `#/browse` |
| frame | title bar + menu bar + status bar | none |
| content | paged bulletin, 10 rows a page | one card filling the screen |
| reading order | rows, then a modal player | cards, then album pictures inside the card |
| end | terminal block under the last page | end block on the move after the last unseen post |

The mode is a route, not a theme: `#/browse` is a real hash, linkable, and the
windowed screens keep working while it exists. `localStorage["00sgram.mode"]` is
`"browse"` or `"windows"` (absent = windowed), read and written through the same
two-line `try/catch` the player uses for its mute key (`views.js:29–34`): a browser
with storage blocked throws `SecurityError` inside the router, which would take the
whole app down instead of falling back to the window.

**The `/browse` mount writes `"browse"`, and `leave()` writes `"windows"` before it
navigates.** Mounting is the choice: a pasted link, a remembered visit and a menu
press all end up in the same place, so the preference cannot disagree with the
screen. R16 was amended to say so. Consequences, stated once:

- While the preference is `"browse"`, `#/` and `#/feed` redirect to `#/browse` —
  home means "this device's appearance". Existing code that returns to `#/feed`
  (`views.post`'s close, the unknown-hash fallback) is therefore seen through the
  device's choice, which is the intent.
- `leave()` writes the preference, then calls `navigate("/feed", { replace: true })`
  (`replaceState` plus `route()` under the covers). Replacing means Back cannot
  re-enter the stream and silently undo the choice.
- Every other hash (`#/stories`, `#/settings`, `#/post/<pk>`, …) is never rewritten
  and renders with the full frame, whatever the preference says.
- The two places that used to paint `#/feed` behind the router's back — the
  unknown-hash fallback (`app.js:215`) and `views.post`'s close (`views.js:511`) —
  become `navigate("/feed", { replace: true })`. Otherwise closing a post on a
  browse-remembered device shows the windowed bulletin while storage says browse,
  and the next reload jumps.

The frame costs **118px** of a 390×844 screen: 26 title + 44 menu + 28 status + 16
content padding + 4 window border (2px on each edge). That is the whole argument for
the mode.

### Files

| File | Change |
|---|---|
| `app/static/browse.js` | **new**, ~300 lines: the stream, its gestures, its two sources and its error card |
| `app/static/str.js` | **2 new keys** — `browse` and `browseDone`. Reused: `older`, `noOlder`, `failed`, `retry`, `loading`, `of`, `photoN`, `muteOff`, `muteOn`, `imgFailed`, `vidFailed`, `windowed` |
| `app/static/style.css` | one `.browse` section at the end (~110 lines); `html.mode-browse` hides `#topbar` and `#statusbar` and stops page scrolling |
| `app/static/app.js` | `cleanup()` before every await, `#/browse` branch with a **dynamic** import, mode redirect, `navigate(path, {replace})` |
| `app/static/shell.js` | one menu item in `Προβολή` and one entry in `ROUTES` |
| `app/static/views.js` | **one word**: `export` on `beginSession` (see "no session") |
| `tests/browse_check.mjs` | **new** node harness, mirroring `tests/player_check.mjs` |
| `tests/test_ui.py` | `browse.js` in `SHIPPED` and in the uncached loop; a route/menu/no-chrome row |
| `tests/test_copy.py` | `browse.js` in the Greek scan and in the `STR.` usage scan; the two new values in `DECK` |
| `README.md` | a section for the mode, and a caveat on the existing "autoplay is muted" line |
| `docs/phase-status.md` | four note rows under its existing `When | Stage | Note` table |

Nothing else changes. The bulletin, the player, the album nav and the mute
preference are untouched.

### Module seam

`browse.js` copies the seam `views.js` already uses: it exports `init(helpers)` and
`browse(el)`.

```js
// app.js
const browseView = await import("/static/browse.js");   // only on this route
browseView.init({ state, api, ApiError, esc, when, navigate, markSeenLocally,
                  loadBase, beginSession });
```

That is a subset of the bag `views.init` receives, and the shell painters are
deliberately absent: a chrome-less screen has no status bar to paint, and its
failures are painted in the error card instead of a one-line status. The dynamic
import keeps `browse.js` out of the startup graph of every other route, so the
rollback claim at the end is true.

`browse(el)` builds the stage inside `#app` and returns a cleanup function;
`app.js` stores it in `cleanup`, and `route()` calls `cleanup(); cleanup = null` so a
teardown cannot run twice on the `/login` or `/post/*` branches.

The cleanup is not cosmetic. The stage registers a capture-phase `keydown` on
`document` and pointer/wheel handlers on the stage. It sets `S.closed = true`,
removes every listener **by the same reference** (the player's `finish()` is the
model, `views.js:1192`), pauses any video, removes its `src` and calls `load()`. A
second mount that skipped any of this would leave two keydown handlers, and one
`ArrowUp` would advance two cards and write two seen marks.

The `/browse` branch runs **before** the shared
`await loadBase()` and calls `H.loadBase()` itself (or `beginSession()` when there
is no session), because the frame must be gone before the network call, not after. **`route()` calls `cleanup?.()` as its first
statement**, before any `await`: today it is called after `loadBase()` and not at
all on the `/post/*` branch, which would leave a playing `<video>` on screen while
the next screen loads. The cleanup pauses the video, removes its `src` and calls
`load()` so a detached element cannot keep decoding.

### Data: two sources, one list

One array `S.items`, newest → oldest, one index `S.i`, one picture index `S.photo`.

```js
const S = {
  items: [], i: 0, photo: 0,      // the stream and its place in it
  total: 0,                       // unseen posts in this session at mount
  added: 0,                       // cards appended from /api/older
  unseen: { cursor: null, more: true, busy: false, failed: false },
  tail: null,                     // last tail_cursor /api/feed reported
  older:  { cursor: null, fetched: false, next_cursor: null,
            busy: false, failed: false },
  end: false,                     // the end block is on screen
  error: false,                   // the error card is on screen
  retry: null,                    // the operation the error card retries
  sound: false,                   // this card; seeded from 00sgram.muted
  closed: false,
};
```

**Session membership is not "unseen".** `store._membership` keeps posts whose
`seen_at >= session.started_at`, because the bulletin must re-show a page the user
already opened. So `/api/feed` returns posts that are already seen. The stream
**drops those on arrival**: `items.filter(it => !it.seen &&
!H.state.feed.seenLocal.has(it.pk))` — R2 and R12 are about
unseen posts, and re-showing earlier reading as "new" is the defect this program
exists to remove.

A page that is entirely seen is not an error: the loop asks for another page **only
after** an unproductive one and stops the moment a page yields an unseen card (the
10-page cap is a ceiling on consecutive empty pages, not a batch size). If the cap is
reached with nothing to show, the stream paints a loading card (`loading`) and the
next vertical move continues. Nothing paints a broken-image card for a post that does
not exist.

**Unseen pages** — `GET /api/feed?session=<id>&limit=10[&cursor=…]`. Keep
`next_cursor` and the response's `tail_cursor` (the key of the last row, whether or
not another page follows). A page is fetched when the user is two cards from the
loaded end (`S.i >= S.items.length - 2`), never on a timer and never ahead of the
run. `next_cursor: null` means the snapshot is exhausted: "stop buffering after the
last unseen" needs no extra rule, because the session is finite by construction.

**Older batches** — `GET /api/older?limit=10[&cursor=…]`, seeded with `S.tail` on
the first press. Only when the user presses «Παλαιότερα…»: it is the continuation
seam the bulletin uses (`views.js:352–375`), it applies the mute/following filters,
and by construction it cannot return a post at or above the tail. The field is
`next_cursor` (`main.py:420`), exactly as the bulletin reads it elsewhere; `null`
means nothing older exists.

**Counter** — `S.total` is `state.session.remaining` after `H.loadBase()` (no
second request; `loadBase` already reads `/api/sessions/current`), i.e. how many
unseen posts this session still has. It never moves while the user swipes. The
overlay reads `of(S.i + 1, S.total + S.added)`: only an explicitly requested older
batch grows the denominator.

**No session** — if `state.session` is null on mount, the stream calls the exported
`beginSession()` (POST with `take_over`, `state.feed = blankFeed()`, `loadBase()`)
and proceeds. Calling it rather than copying it matters: a session finished in
another tab leaves `state.feed` holding the old pages, and the bulletin would then
render them under the new session id.

### Card model

A card reads exactly what the bulletin already reads:

```js
const it  = S.items[S.i];
const res = it?.resources || [];          // 0 when absent, never 1
const pic = res[Math.min(S.photo, res.length - 1)] || null;  // {type, full, thumb}
```

No resources means `imgFailed`; a `<video>` whose `error` event fires means
`vidFailed`. `pic.type === "video"` paints `<video muted loop playsinline
controls preload="metadata" poster>`; anything else paints `<img src=pic.full>`.

**Amendment 2026-11-17 — the transport is ours.** The first attempt used the
platform's `controls`. Three rounds of live feedback killed it: the bar is drawn
on the video element's bottom edge, which put it behind the description; lifting
the element padded the text, then measured the caption, and the owner still saw
the bar behind the text; on the phone the platform's player is also free to take
the element fullscreen, where our card, its exit control and its description are
simply gone and the bar hides itself mid-playback. Every one of those is a
position or a lifetime we do not own. So the mode draws the transport itself,
copying the bulletin player's shape — `[▶/❚❚] [seek] 0:04 / 0:50 [🔊/🔇]` in a
`.bbar` at the top of the description row, `input[type=range]` over 0..1000
remapped to `currentTime`, `play`/`pause`/`timeupdate` keeping the glyph and its
`aria-label` honest. Glyphs, not words: «Αναπαραγωγή» took a third of the row and
the row is what a thumb has to hit — each button is 40×40 and carries the word in
`aria-label`/`title`.
A film is two grid rows (`.bstage.is-video`), so the transport cannot be covered
by text by construction. One gesture rule came with it: `onUp` now ignores a
press that starts on `[data-act], input, textarea, select`, or dragging the seek
bar would be read as a horizontal swipe and change the picture.

Two layout traps came out of measuring every film at 375×667 and 320×568, both
silent until something was hit-tested:

- A percentage height against a `minmax(0, 1fr)` row is **indefinite**, so a
  `height: 100%` film fell back to its own aspect ratio and a portrait reel grew
  168px past its row — over the transport, which is why `elementFromPoint` on the
  pause button answered `<video>`. The film is now pinned with
  `position: absolute; inset: 0` inside the card.
- `stage.innerHTML = …` used to run **before** `classList.toggle("is-video", …)`,
  so the new card spent one layout pass under the previous card's row template
  and kept the resolved height. The class now goes on first.

The mute moved into that transport, so `00sgram.muted` is written by a control
we own again — no `volumechange` guessing about which change was the reader's.
`res.length > 1` is what turns on the album counter and the second axis.

### What is this? (R21–R22)

The bar's note is the one control that leaves the machine, and it leaves from
the **server**: `POST /api/recognize/{pk}/{idx}` looks up the post's resource,
takes the bytes the cache already holds (downloading once if the film was never
watched here), decodes twelve seconds of mono PCM with ffmpeg and hands that to
**ShazamIO**, which fingerprints it against Shazam. No key, no signup, no
Spotify login — the reader taps and either gets a track or gets told the film is
not a song they can name.

Four things settle the shape:

- **The page never uploads.** It cannot: a 20 MB reel off a phone over the LAN is
  slower than the question deserves, and the server already has the media. It
  also keeps any future credential out of `str.js`'s neighbourhood.
- **ffmpeg, not the fingerprint core's decoder.** The core raised `aac too
  complex` on a reel's HE-AAC; decoding first costs one subprocess and removes a
  class of "some reels silently fail". The clip is capped at 12 s and 64 MB.
- **A link, not a window.** iOS blocks a scripted `window.open` after an
  `await`, and a real anchor also opens the Spotify app instead of a tab. The
  answer is a line under the transport (`.bheard`, `aria-live="polite"`).
- **The server returns a name, the page builds the search.** Shazam's Spotify
  provider is usually a `spotify:search:` query, not a track id, and a search
  always lands on the song while an id is only there when Shazam has one. So
  `identify()` returns artist and title and the page makes
  `https://open.spotify.com/search/<artist title>`. Beside it, a copy glyph puts
  the same words on the clipboard (`navigator.clipboard`, written inside the
  press's own gesture) and turns into a tick for a moment.

`found: false` is an answer, not an error — a miss, a broken service and a
missing ffmpeg all come back as 200 with a reason, and the bar says one Greek
sentence. ShazamIO speaks an endpoint that is not public: if it changes, the
note says «Δεν το αναγνώρισα.» and nothing else in the program notices.

**"I don't know it" and "not now" are different sentences.** Shazam throttles by
IP after a couple of presses in a minute, so `error: "RateLimited"` is the one
miss that is not about the song: the bar says «Πολλές προσπάθειες —
ξαναδοκίμασε σε N δ.» and counts N down once a second while the note stays
asleep on that same clock, then clears the line and comes back. The countdown
is `aria-live="off"` (a ticking number is not news) and the line is removed
when it ends. The ask is capped at 2 attempts, 4 s of backoff and 20 s overall,
so a refusal is answered in under a second instead of holding the button.

Two more edges, stated so they are not discovered later: a post with no caption
hides `.bcap` (an empty pressable block is a dead target), and a missing
`account.username` falls back to `account.pk`, as the bulletin does
(`views.js:132`).

### Painting

One card element at a time. No carousel, no three-card window, no virtual list.

```
.browse            position: fixed; inset: 0; background: #000;
                   touch-action: pinch-zoom (pan suppressed, zoom allowed)
  .bcard           one media element, object-fit: contain, centered
  .bmeta           bottom gradient, padding respects env(safe-area-inset-bottom):
                   name · when · counter · album counter · caption
  [data-act=exit]  top-right, 44×44 drawn glyph, offset by
                   max(0px, env(safe-area-inset-top)), aria-label windowed
  [data-act=sound] bottom-left text button, only on a video card
  [data-end]       the end block, replaces the card layer
```

The stage fills the **viewport** at every size (`position: fixed; inset: 0`), not
the 1200×760 window: a mode with no chrome owns the screen, and on a desktop the
media letterboxes on black. The safe-area insets are the only concession to the
notch — with `viewport-fit=cover` in `index.html`, the exit control would otherwise
sit under the Dynamic Island, and it is the only way out.

Above the caption sits the album mark row: `marksHTML(photo, n)` emits at most
five `<span class="bmark">`, one `is-on`, windowed on the current picture
(`start = clamp(photo - 2, 0, n - 5)`), and nothing at all for a single-picture
post. It is `aria-hidden` — the counter already says «φωτό 3 από 20» in words.
The class is `bmark`, not `dot`: `dot` is v1's carousel vocabulary and
`test_ui.py` forbids it on purpose.

The caption clamps with `display: -webkit-box; -webkit-box-orient: vertical;
-webkit-line-clamp: 2; overflow: hidden` (the clamp property alone does nothing); a
press under 8px toggles `.is-open` and lifts it. Nothing else is on the glass (R8 is about content; the exit and
sound controls are controls).

Accessibility, in one place: the stage is `role="group"`, `tabindex="-1"`, focused
on mount, with a counter whose text is copied into `aria-live="polite"` (the
counter itself, not the media); every image carries `alt` = account name and place.

### Two axes

One pointer handler on `.browse`: `pointerdown` records the origin (primary pointer
only, and only when no gesture is already tracked), `pointerup` decides,
`pointercancel` clears it — a pinch is explicitly allowed, and a cancelled pointer
that kept its origin would be measured against the next unrelated `pointerup`. A gesture that starts on `[data-act]` is not a swipe — those elements own
their presses. A gesture that starts on the caption is: under 8px it is a tap that
toggles the clamp, beyond 40px it is a swipe. (Excluding the caption outright would
create a dead zone at the bottom of the screen, exactly where a thumb rests.)

Axis is chosen by the dominant delta at a 40px threshold:

| Delta on release | Axis | Result |
|---|---|---|
| `dy <= -40`, `|dy| > |dx|` | vertical | older post (`S.i + 1`) |
| `dy >= 40`, `|dy| > |dx|` | vertical | newer post (`S.i - 1`) |
| `dx >= 40`, `|dx| > |dy|` | horizontal | next picture |
| `dx <= -40`, `|dx| > |dy|` | horizontal | previous picture |

Keyboard is one `onKey` on **`document`** in the capture phase (the stage owns
`tabindex="-1"` and takes focus on mount; the listener does not depend on it), with
`if (e.repeat) return` — holding a key must not walk the stream marking posts seen.
`Space` and `Escape` are handled unconditionally and always `preventDefault()`: a
focused `<button>` otherwise activates on Space, which would be the sound control
pressing itself. The remaining keys carry a target guard
`e.target.closest("[data-act], input, textarea, select")`. `ArrowDown`/`ArrowUp` = older/newer (down is next, like a scroll down — the owner's
correction: the key used to disagree with the wheel), `ArrowRight`/`ArrowLeft` = next/previous picture (a drag is the opposite way: the
deck follows the finger, so swiping left advances — the owner's correction after
the swipe and the gesture disagreed on a real thumb), `Space` = pause/resume, `Escape` = leave. Wheel: `deltaY > 0` = older, `< 0` = newer, throttled to one move per 400ms. The
listener is registered `{ passive: false }` (Chrome and Safari default wheel to
passive, where `preventDefault()` is ignored), and **every** wheel event is
prevented, including the ones the throttle swallows — otherwise `.content`, the
scroller behind the stage (`style.css:108`), moves under the black screen. Handled
keys are prevented the same way.

Bounded at every edge: no picture before the first or after the last (R7); no card
before the newest; past the last unseen post a vertical move opens the end block
instead of a card.

`S.photo` follows the player's rule (`views.js:1001`): moving to an older post
starts at picture 1, moving to a newer post starts at its last picture. There is no
per-post memory, so picture 4 of 6 is reached again by two right-swipes, not
restored — stated here because the alternative is a map nobody asked for.

No drag-follow: the card cuts on release. `touch-action: pinch-zoom` on `.browse`
plus `html.mode-browse, html.mode-browse body { overflow: hidden }` (the mechanism
the fullscreen fallback already uses at `style.css:332`) kills rubber-band and
pull-to-refresh (R19).

A vertical move at the last loaded card while the next page is in flight is
ignored — no spinner, no jump. The prefetch usually answers first; if it failed,
the error card appears instead (below).

### Failures

Three surfaces, one card:

| Where | Behaviour |
|---|---|
| the first `/api/feed` | the error card: `failed` + `retry` |
| a prefetch / the all-seen loop | `unseen.failed = true`; the move that needs the page shows the error card, whose retry re-runs the fetch |
| «Παλαιότερα…» | the end block keeps its button and adds `failed`; the same press retries |

`retry` is the operation that failed (`S.retry`), so one card covers all three.

The restart is driven by the session, not by a status code. `_owned_session`
(`main.py:384–388`) checks existence and device only, so a session finished in
another tab still answers `/api/feed` 200 with its snapshot, and that stale but
stable snapshot is accepted as read. What does happen is `H.loadBase()` coming back
with a null session (finished elsewhere, or none on this device): the stream then
calls `beginSession()`, resets `S.items` and the cursors, and starts again from the
newest unseen. A `409 session_conflict` or a failed POST from that call is caught and
shown in the error card like any other failure — the stream has no session panel and
does not need one.

### Video

Autoplay exists **only here**, and only muted. `autoplay` is deliberate: a
full-bleed feed whose videos wait for a press is the thing this mode exists to
avoid.

- On activation: `v.muted = mutedPref()`, `v.loop = true`, `v.play().catch(...)`.
  The catch is guarded on the card identity (`S.i` and `S.photo` at call time),
  so a rejection landing after a swipe cannot mute the card the user is now on.
- The platform's bar is the only mute (the mode's own `.bsound` was deleted on
  the owner's word: the bar already has one). Unmuting there is a real gesture,
  which is what makes it legal on iOS, and a `volumechange` listener writes
  `00sgram.muted` — but only when the value differs from how the card opened, so
  our own start-up mute and a refused autoplay never erase the preference.
- Leaving the card or the route: `v.pause(); v.currentTime = 0`.

The v2 rule "nothing autoplays" still holds for the player and for stories; the
browse stage is the only caller that plays without a press.

### Seen

On every card paint, once per pk: `if (!it.seen) { it.seen = true;
H.markSeenLocally(pk); }`. `markSeenLocally` already dedupes, queues the POST,
batches it after 2s, flushes on `pagehide`, and decrements the bulletin's remaining
count. The stream writes nothing else: no like, no react, no follow, no Instagram
call (R17).

Because items arrive filtered to `!seen`, a card seen earlier in this session is not
in the stream — and, being above the session tail, it is not reachable through
«Παλαιότερα…» either. That is accepted and stated: the stream is "what is still
unread", the archive screen is where read things are revisited.

### End of the unseen run

`S.items` only ever holds unseen session posts until the user presses
«Παλαιότερα…». When the active card is the last one and `unseen.more === false`, an
upward move sets `S.end = true` and paints the end block instead of a card:

- headline `browseDone` — the unseen run is finished;
- one button `older` («Παλαιότερα…») while `!older.fetched || older.next_cursor !== null`;
- a successful press **closes the end block** (`S.end = false`), appends the batch and
  lands on its first card (`S.i` = index of the first appended item, `S.photo = 0`),
  so the ten fetched cards are what the user sees next, not something behind a
  down-then-up;
- the exit control;
- `noOlder` replaces the button only after a batch came back with `next_cursor: null`
  (`older.fetched === true`). Before the first press there is no way to know, so the
  button is always offered once;
- a downward move returns to the last card.

An empty session (nothing unseen at all) opens directly on the end block, with
`S.tail` null and «Παλαιότερα…» seeded from the newest post — a fifth behavioural
decision, recorded here because R13 assumes the stream has a last post to walk back
from. `#/feed`'s own «Παλαιότερα…» does the same (`views.js:352–375`), so the two
screens agree.

### Router and frame

In `app.js`:

```js
const MODE_KEY = "00sgram.mode";
// Home asks the device for its appearance. Every other hash is explicit.
if ((raw === "/" || raw === "/feed") && modePref() === "browse")
  return navigate("/browse", { replace: true });
```

where `modePref()`/`setMode()` are the guarded accessors. `navigate(path, { replace })`
becomes:

```js
export function navigate(path, opts = {}) {
  const next = `#${path}`;
  if (opts.replace) {
    history.replaceState(null, "", next);
    route();
  } else if (location.hash === next) route();
  else location.hash = path;
}
```

`route()` starts with `cleanup?.()` and
`document.documentElement.classList.remove("mode-browse")`,
before any `await` and before the early-return branches (`/login`, `/post/*`), so a
401 or a deep link cannot leave a hidden status bar and a scroll-locked page behind.
Then, for `hash === "/browse"`: `top.hidden = true`, add the class to `<html>`, and
`cleanup = await browseView.browse(el)` — after the dynamic import and after
hiding the frame, so a slow `loadBase` never flashes the window over the black
stage.

`shell.js` gains `{ id: "browse", label: STR.browse }` in `Προβολή` and
`browse: "/browse"` in `ROUTES`. No other shell change: the menu is gone the moment
the mode is on, and the exit control is the way back.

### Copy

Every string lives in `str.js`, one per line, and nothing else may contain Greek.
Two keys are new:

| key | value | where |
|---|---|---|
| `browse` | `Περιήγηση` | the `Προβολή` menu item |
| `browseDone` | `Τα νέα τελείωσαν.` | the end block's headline |

Reused, not re-added: `older` («Παλαιότερα…»), `noOlder`, `failed`, `retry`,
`loading`, `of(n, m)`, `photoN(n, m)`, `muteOff`, `muteOn`, the placeholders
`imgFailed`/`vidFailed`, and `windowed` («Κανονικό παράθυρο») as the exit glyph's
label — the same word the player's fullscreen toggle uses, because
it is the same idea. No `swipeHint`: an instruction on the glass is exactly the
distraction this mode removes, and R8 forbids it.

## Alternatives

**(a) Vertical scroll-snap instead of a gesture handler.** `scroll-snap-type: y
mandatory` on a list of full-height cards is ~30 lines and gives free momentum and
accessibility. Rejected: a vertical scroller cannot also own a horizontal album
gesture without fighting iOS's scroll arbitration, and snap scrolling happily runs
past the last card, so the hard end (R12) becomes a fight against the browser
rather than a rule in one place. Revisit if the pointer handler proves unreliable
on a real iPhone.

**(b) Bend `openViewer` into a third mode.** The player already handles posts,
albums, video, mute and a tray. Rejected: it is a modal with a 44px header, a nav
row and a transport; a third mode would add branches to the most complex component
in the app, and all three would have to be suppressed — the cheapest path to a mode
that looks like 2000 and behaves like 2009.

**(c) A library (`swiper`, `embla`).** Rejected: CSP allows no remote assets, the
project has no build step, and a 40px threshold plus four branches is smaller than
the integration.

**(d) Keep the window frame and restyle only the content.** Rejected by decision:
the frame costs 118px of a 390×844 screen and the mode exists to remove it.

**(e) `/api/history` as the source for «Παλαιότερα…».** Rejected by review: history
is "posts with `seen_at`", which is precisely the run the user just swiped, so page
one appends nothing after dedupe; `/api/older` is a keyset walk from the session's
tail and cannot overlap. It also carries the mute filter, which history does not.

**(f) Mark seen after a dwell (the `VIEW_THRESHOLD_MS` watcher).** Rejected: v2
deliberately removed the countdown because a timer that writes state behind the
user's back is the thing the first user asked to stop. A card that is on the glass
is seen; a card never shown is not. Fast swiping marks fast, which is honest.

**(g) A "for you" stream that keeps going after the unseen run.** Rejected: it is
the exact defect the requirements name. The stream is the session's unseen posts
plus explicitly requested older pages.

**(h) Remember the sound choice across cards.** ~~Rejected~~ **Accepted
2026-11-17**: the preference is the player's own `00sgram.muted`, and the
browser's refusal is handled by starting muted, saying so, and keeping the
preference for the next press. The original objection stands only for the first
card after a reload, where the control tells the truth. Rejected-shape: a browser only allows
unmuted playback inside a gesture, so a remembered "sound on" would either start
every later video silently (a lie in the label) or force a failed `play()` per
card. The control unmutes what is on the glass.

**(i) A sticky, per-device `S.i`.** Rejected: the list is recomputed on reload, and
a restored index can point past the end or into a different list. A reload starts at
the newest unseen; posts already swiped in the previous visit are not reachable from
the stream (they sit above the tail), which is the documented behaviour and the
reason the archive screen still exists.

## Detailed Implementation

Ordered so every step is checkable on its own.

**P1 — the mode exists.** `browse.js` skeleton (`init`, `browse`, mount, cleanup),
router branch + redirect + `cleanup()`-first, the class on `<html>`, exit control +
`Escape` + `leave()`, the two strings, `.browse` CSS shell, and the first unseen
card painted with media, name, time and counter. *Done when:* `#/browse` at 390×844
shows a black screen with the newest unseen post, `#topbar` and `#statusbar` have no
box, the exit control lands on `#/feed`, a reload of `#/feed` *before* exiting
returns to `#/browse`, and a reload *after* exiting stays on `#/feed`. *Evidence:*
`node tests/browse_check.mjs` (P1 block) plus one screenshot.

**P2 — two axes.** Pointer, wheel and keyboard handling with the tap/control rules,
`preventDefault()` on handled input; `S.photo` clamping; prefetch at
`items.length - 2`; video autoplay/pause/rewind and the per-video sound control;
`touch-action`/`overflow` lock; safe-area insets. *Done when:* swipe up advances to
the older post, swipe right steps the album, both stop at their edges, and a video
plays muted on activation and rewinds when left. *Evidence:* node assertions plus a
scripted Playwright drag on the live app.

**P3 — the end and the failures.** End block, «Παλαιότερα…» batches from
`/api/older`, terminal line only after a fetched batch comes back empty, the error
card with `retry`, and the dead-session restart. *Done when:* the move after the
last unseen post shows the end block, one press appends exactly 10 older posts, an
exhausted stream offers nothing, and a failed fetch shows words and recovers.
*Evidence:* node assertions with a two-page feed stub, a one-page older stub and a
throwing stub, plus one live press.

**P4 — the contract.** `test_copy.py` and `test_ui.py` rows, a README section and
the autoplay caveat, the evidence rows in `docs/phase-status.md`, three-viewport
screenshots, and a full live pass (login → browse → 3 cards → album → end → older →
exit). *Done when:* `pytest -q` is green, the three node harnesses are green
(`player_check.mjs`, `secondary_check.mjs`, `browse_check.mjs`), and the live pass is
recorded. *Evidence:* the commands, pasted.

Rollback: `#/browse` is additive and lazily imported, so removing the route, the
menu item and `browse.js` returns the program to v2 exactly; nothing else in the
startup graph changes.

## Scroll, not a step (supersedes «Two axes» and the gesture layer)

The deck used to be a pointer machine: `pointerdown`/`pointerup`, a 40px swipe
threshold, a wheel with a 400ms cooldown, one card in the DOM at a time. It worked
and it felt wrong. A phone is a scroller, and the tell was that the deck answered a
slow drag by doing nothing at all.

So the deck is now a native scroller:

- **`.bstage`** is `overflow-y: auto`, `scroll-snap-type: y mandatory`. One
  `.bslide` per card, `height: 100%`, `scroll-snap-align: start`,
  `scroll-snap-stop: always` — one card per screen, and a fling cannot skip one.
- **The album** is the same rule turned sideways: `.bpics` is an `x mandatory` snap
  strip inside the card, one `.bpic` per picture. `touch-action: pan-y` on the deck
  and `pan-x` on the strip, so the two axes never fight.
- **The position is read, never written by a gesture.** `Math.round(scrollTop /
  clientHeight)` is the index; the album index is the same sum on `scrollLeft`.
  `scrollTo` is only used by the keys and by «Παλαιότερα…».
- **Activation happens on settle** — `scrollend` where it exists, a 150ms quiet
  timer where it does not — once per index: play the film, report the post seen,
  fetch a pending story, print the picture counter, prefetch the next page.
- **All cards live in the DOM**, appended, so a prefetch landing does not rebuild
  the card that is on the glass. Films are `preload="none"` and get their `src` on
  activation: ten reels must not pull ten films to show one.
- **Deleted**: `SWIPE`, `TAP`, `WHEEL_MS`, `onDown`/`onUp`/`onCancel`/`onWheel`,
  `move()`/`step()`, `paint()` and `.bstage.is-video`. The transport moved into the
  picture cell it belongs to, so nothing is re-bound when the album moves.

The end of the unseen run is now the last slide rather than a mode: the deck stops
there, and «Παλαιότερα…» is the only control on it. Scrolling into it is also how
the next page is asked for, which deleted the "ignore a move while a page is in
flight" branch along with the move.

`tests/browse_check.mjs` follows: a fake DOM that can parse HTML, hold children and
answer for `scrollTop`, so "which card is on the glass" is a real question and not
whatever string was painted last.
