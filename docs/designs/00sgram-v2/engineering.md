# 00sgram v2 — engineering

Role: engineering. Input: `00sgram-v2.md` (the contract), `product-owner.md`, `brief.md`, and the v1 tree as it stands (`views.js` 1795, `app.js` 242, `style.css` 299, `index.html` 27). This is the build spec. "chosen:" means the call is made; "delete" means same commit. Inherited and not negotiable: no new dependencies, no new endpoints, no build step, no `onclick`, no inline `<style>`, CSP `script-src 'self'`, vanilla ES modules, one container.

## 0. Interview with the design team

**Eng.** The frame and the row are buildable. The player is where I have questions, starting with mode.
**Des.** One component, `data-mode="post"|"story"`. Same `stories-viewer` root, same `openViewer`. The mode changes the header, the playlist rows and the absence of seen-marking — not the markup.
**Eng.** "Full-content child window", but `.stories-viewer` is `position:fixed; inset:0; height:100dvh`. Your wireframe shows the app title bar and menu bar still on screen with the player under them.
**Des.** Inside the content area. The chrome is the program; the player is a window in it. `100dvh` stays for the window at ≤700px, where the window *is* the screen. The player is `position:absolute` inside `.content`.
**Eng.** Then `openViewer` stops hiding `#topbar` and stops appending to `document.body`. Accepted; the test that pins `#topbar[hidden]` still passes through the login route. Next: `#/post/<pk>` is a hash route, so the row is an `<a href="#/post/pk">` and the router runs `views.post`. But `openViewer` also pushes a history entry. Which owns Back?
**Des.** The viewer has always owned one entry: Esc pops it, `popstate` finishes. Keep it. In post mode the entry underneath is the hash entry, so popping lands on `#/post/pk` with the bulletin untouched — no reload, same row, by construction.
**Eng.** Almost. After closing, the hash still says `#/post/pk`, so a reload reopens the player and the address bar lies. And a second Back remounts the list and loses the row.
**Des.** On finish, replace the hash with `#/feed` without pushing. Reload gives the bulletin, Back gives `#/feed` again. Conceded — decision 2.
**Eng.** The list is paged. `around_pk` returns the page *containing* the resume row: `store.feed_page` snaps `offset = (newer // limit) * limit`. So we can land on page 3 of 5 with no pages 1–2 in hand; `Προηγούμενη` has nothing to go back to and `Σελίδα n από m` has no honest `n`.
**Des.** The design already says "back-paging reuses cursors already in `state.feed`". That sentence assumes a prefix. Cursors are forward-only; you cannot seek to page 2 directly.
**Eng.** So drop `around_pk` from the request: walk from page 1 with `cursor` until a page holds the seen→unseen boundary, cap at three pages, render that one. Two requests on a bad day, no server change, `Προηγούμενη` always free.
**Des.** Conceded. `around_pk` leaves the request path and the test marker with it. The divider is still the scroll anchor, still above the first unseen row.
**Eng.** Which row is that? `last_rendered_pk` is "the row that owned the middle of the viewport". With seen-on-open, a post he *tapped* never owned the viewport, so the line would never move.
**Des.** The boundary is the first row in the payload with `seen === false`. In an `unseen` session that is exactly "the first one you have not opened". `last_rendered_pk` is still written — on open, not by an observer — so the server's resume record agrees with the line.
**Eng.** Then `watchVisibility` and the `-40%` observer leave the bulletin, and `state.threshold` becomes a setting nothing reads. I keep the function and the literal because the test pins them.
**Des.** Agreed. Seen is written on open only; `flushSeen` still batches and `pagehide` still flushes.

### The one loop

**Finding 1 (Eng.).** The end block is terminal and carries `Πάνω` and `Παλαιότερα…`. Nothing finishes a session and `#/feed` resumes the open one, so after `Αυτά είναι όλα.` a user can never see a post that arrived afterwards. That is the dead end the PO calls fatal.
**Design concedes.** Add `Νέα συνεδρία` as the third button — already the string the Migration section names. `POST /api/sessions` with `take_over` = the current id, then re-mount at page 1.
**Finding 2 (Eng.).** Step 13 deletes `#/help` and `#/about`; the menu bar in the same document requires `Πώς δουλεύει` (`#/help`) and `Σχετικά με το 00sgram` (`#/about`). Both cannot hold.
**Design concedes.** Step 13 deletes the *stub* (`views.stub`) and the dashboard, not those routes. `#/help` and `#/about` are new static screens with no API call, built with the frame in step 2.
**Engineering concedes.** `Στοιχεία` is a 44px row holding two 44px buttons, which at 844×390 eats the stage the design was protecting. Your geometry wins: at ≥701px the sheet buttons move into the 200px playlist column. I add no row.
**Design concedes.** And the third status cell has no content in the copy deck. It is the dial-up line — `Έτοιμο`, `Συνδέομαι…`, `Συνδέθηκα — 6 νέα` — with the two unprompted messages in the first cell.

### Settled decisions

1. **Post mode is an overlay on a live screen.** `views.post` never repaints a mounted bulletin; it paints one only when `#app` holds another screen (deep link, reload, arriving from `/stories`).
2. **The hash settles to `#/feed` on close** via `history.replaceState`. No `hashchange` fires.
3. **Resume walks forward from page 1, capped at `RESUME_MAX = 3`.** No `around_pk`; the marker is dropped from `test_ui.py`. `last_rendered_pk` is still PATCHed, on open.
4. **The divider is above the first row with `seen === false`**, only when a seen row is above it (or it is not page 1). The anchor is `scrollTop` arithmetic, never `scrollIntoView`.
5. **`Νέα συνεδρία` is the end block's third button.** Without it the end is a dead end.
6. **`#/help` and `#/about` stay** (static, no API); `dashboard`, `stub` and the `#/` route are deleted and `#/` resolves to `#/feed`.
7. **Three status cells:** message (live), page, connection. `toast()` is deleted.
8. **The player is absolute inside `.content`**; `100dvh` moves to `#window`, the literal stays.
9. **At ≥701px the sheet toggles live in the playlist column**; at ≤700px in a 44px row. Stage keeps 210.
10. **The pager row is 44px**, not 32 — `min-height:44px` is pinned and the buttons are 44.
11. **Strings live in `app/static/str.js`** — one table imported by views and shell. No import cycle, and "no free-text Greek" becomes a test.
12. **Login keeps three new strings** (`Σύνδεση`, `Κωδικός`, `Λάθος κωδικός.`); the deck has none.
13. **`/api/status` has no archive count**, so `Αρχείο αναρτήσεων…` is never disabled; `Δεν υπάρχει αποθηκευμένο αρχείο.` is the Archive screen's own empty state.
14. **`Δεν αποθηκεύτηκε· γύρισε πίσω.`** is added for a refused like — it is a write, and `Δεν φόρτωσε.` would lie about what failed.

## 1. Contract summary

1. **F1** `index.html` is `lang="el"`, holds `#topbar` (still carrying `[hidden]`), `#app`, `#statusbar`, one `<script type="module" src="/static/app.js">`, and no inline `<script>` or `<style>`.
2. **F2** `shell.js` paints title bar, menu bar and status bar once; no view paints chrome.
3. **F3** At 390×844 chrome is 26+44 top, 28 bottom, content 742; at 844×390, 22+28 / 22 / 314; at 1280×800 a 1200×760 window centred, 30+28 / 30 / 668.
4. **F4** The content area is the only scroll container; chrome never scrolls.
5. **F5** Three menus open on press, stay until item/Esc/outside click, move with arrows; an unavailable item is greyed, keeps its place and prints its reason in the status bar.
6. **F6** `#/` and every unknown hash resolve to `#/feed`.
7. **B1** The bulletin is `<ul class="files">` of `<li class="post">` rows, ten per page, each row an `<a href="#/post/<pk>">`; no media element exists in its DOM.
8. **B2** A row is 56px, `grid-template-columns:12px minmax(0,1fr) 84px 46px`, gap 8, padding 0 4px, rule `#a0a0a0`; cell 4 is the word `Βίντεο` or `Φωτό`.
9. **B3** Unseen rows carry a filled `#000080` 8×8 marker and a bold name; seen rows a 1px `#808080` outline and a regular name, under `is-seen`.
10. **B4** Dates read `14 Νοε 21:14`, or `χθες 21:14` for yesterday, in `tabular-nums`.
11. **B5** Ten rows a page; the footer prints `Σελίδα n από m` (or `Σελίδα n` when the total is unknown) between 44px `Προηγούμενη` and `Επόμενη`, each disabled with a reason at the ends.
12. **B6** `m = ceil(item_count / 10)` from the session snapshot, and it never shrinks.
13. **B7** A divider sits above the first unseen row on resume; nothing unseen means no divider; it is scrolled to the top of the content area once on mount.
14. **B8** The last page is replaced by the end block: `Αυτά είναι όλα.`, the count and month line, then `Πάνω`, `Παλαιότερα…`, `Νέα συνεδρία`. Nothing after it issues a request.
15. **B9** `Παλαιότερα…` appends a list headed `Από το αρχείο` from `/api/older`, ending in `Τέλος αρχείου.` or `Δεν υπάρχουν παλαιότερα αποθηκευμένα.`.
16. **B10** No session auto-start except on entering `#/feed`; conflict, empty, failed fetch and frozen sync each render a panel with the deck's sentence and one action.
17. **P1** `#/post/<pk>` opens the player over the mounted bulletin; the root carries `stories-viewer` and `data-mode="post"`; closing restores the same rows at the same scroll.
18. **P2** One `openViewer(items, start, onDone, {mode})`, one `paintSegment`, `paintVideo`, `paintTray`, `paintLinks`, `advance`. No second viewer.
19. **P3** Post mode's playlist is the current page's posts, one 44px row each, name + date.
20. **P4** A video has exactly one play control, labelled `Αναπαραγωγή`, and it starts nothing until pressed. A photo has no transport element at all.
21. **P5** The seek input carries `data-seek`, mute `data-act="mute"`, the label is `m:ss / m:ss` in tabular numerals, and mute survives segment change and reload through `MUTE_KEY`.
22. **P6** The header shows the name, `2 από 5` in story mode only, `Λίστα` (hidden at ≥701px) and `Κλείσιμο`.
23. **P7** The details panel holds the caption, `Τραβήχτηκε …, 21:14.`, `Άνοιγμα στο Instagram` and the like checkbox `Μου αρέσει` — the only write control, never on a row.
24. **P8** `Αντιδράσεις` is a disclosure: no emoji in the DOM until pressed, then a confirm, and no request before `Ναι, στείλ' το`.
25. **P9** `paintLinks` renders labels as selectable text and a separate `Άνοιγμα` link per URL; the panel opens with the details panel shut.
26. **S1** People is `<ul class="acc">` with `νέες αναρτήσεις: n`, `νέες ιστορίες: n από m`, `Δες τις ιστορίες`, `Σίγα`/`Άνοιξε τον ήχο`, `Κλείσε εκείνη τη συνεδρία`.
27. **S2** Archive is the same paged list with `Αναρτήσεις`/`Ιστορίες` and per-row `Άνοιγμα` and `Σημείωση ως αδιάβαστο` (`POST /api/posts/{pk}/unsee`). No append.
28. **S3** Setup is a four-tab sheet; `story_auto_advance_accounts` is gone from the form and unread.
29. **S4** Every unprompted message is one status-bar line, at most once per session.
30. **T1** `pytest -q` green, including the rewritten `test_ui.py` and the new `test_copy.py`.
31. **T2** `onclick`, `javascript:`, `data-car`, `.carousel`, `.dots`, `.ring`, `watchPlayback`, `autoAdvance`, `story_auto_advance_accounts`, `.toast` appear in no shipped file.
32. **T3** Exactly one `data-act="like"` exists in `views.js`, in the details panel, and no row builder emits it.

## 2. File plan

| file | change | size |
|---|---|---|
| `app/static/str.js` | new. `export const STR = {…}` — every Greek string, one table | ~90 |
| `app/static/shell.js` | new. `paintShell`, `status`, `page`, `conn`, menu + window buttons | ~220 |
| `app/static/index.html` | window skeleton, `lang="el"`, status bar, no nav | 27 → ~40 |
| `app/static/app.js` | import shell; drop toast + keyboard; `/`→`/feed`; `/post` overlay guard; pass `status/page/conn` into `views.init` | 242 → ~200 |
| `app/static/views.js` | rewrite feed, player, post, people, archive, setup; delete dashboard, stub, carousel, media rows, playback watcher | 1795 → ~1500 |
| `app/static/style.css` | tokens, bevels, chrome grid, list and player grids; delete dark theme, cards, rings, toast | 299 → ~620 |
| `tests/test_ui.py` | new markers, no-`onclick`, no-like-in-a-row, no dead tokens | 71 → ~130 |
| `tests/test_copy.py` | new. Greek only in `str.js`; keys used exist; deck strings present | ~70 |
| `/tmp/00s-v1-backup/` | untouched rollback copy of the four v1 files | — |

Untouched: all of `app/*.py`, `tests/test_api.py`, `test_store.py`, `test_sync.py`, `test_media.py`, `test_browser.py`, `test_mcp.py`.

## 3. Seams

### D1 — post mode of the player

```js
export async function post(el, pk)                            // route target, "#/post/<pk>"
function openViewer(items, start, onDone, opts = { mode: "story" })
```

State owned: `viewer` (the handle), nothing else. `post(el, pk)`:

1. `if (!el.querySelector("[data-bulletin]")) await feed(el)` — paint only when `#app` holds another screen or nothing (reload, deep link, arriving from `/stories`).
2. `const items = state.feed.items` (flat, every fetched page). If `pk` is absent, `const one = await H.api("/api/posts/"+pk)` and use `[one]`.
3. `const done = () => { if (location.hash === "#/post/"+pk) history.replaceState(null,"","#/feed"); }`
4. `viewer = openViewer(items, idx, done, { mode: "post" })`.
5. Deep-link case only: set `content.scrollTop` so the `pk` row is at the top before opening.

`app.js` must test `hash.startsWith("/post/")` **before** `cleanup()`, and that branch returns `views.post` without tearing down a mounted bulletin. No `mounted` variable: `el.querySelector("[data-bulletin]")` is the truth, because every other route replaces `el.innerHTML`.

History: the row's anchor makes entry **E1** (`hashchange`, no paint). `openViewer` pushes **E2** (`{storiesViewer:true}`, same URL), unchanged. `Κλείσιμο` / Esc / browser-back → `history.back()` → E1 → `popstate` → `finish()` → `onDone` → `replaceState("#/feed")`. No `hashchange` fires after E1, so the router never re-renders.

**Failure mode:** calling `route()` or `feed()` on close. That re-mounts, resets `.content.scrollTop` to 0 and drops the row he left — the regression `scrollRestoration="manual"` exists to prevent. Second failure: leaving the hash at `#/post/pk`, so a reload reopens a player nobody asked for.

### D2 — seen

```js
export function markSeenLocally(pk)          // app.js, unchanged: dedupe, bumpRemaining(-1), queue, 2s flush
export async function flushSeen()            // unchanged; pagehide + visibilitychange still call it
export function bumpRemaining(delta)         // now ends in views.updateProgress(n) → H.page()
```

- The bulletin calls nothing on scroll. `watchVisibility` is called by neither `feed()` nor `post()`; it stays in `app.js` with `rootMargin` intact because `test_ui.py` pins both literals.
- The only write is the row press: `H.markSeenLocally(pk)` **and** `H.api("/api/sessions/"+id,{method:"PATCH",body:{last_rendered_pk:pk}})`, fire-and-forget, both in `post()` before the viewer opens — so the row behind the overlay already reads `is-seen`.
- `Σημείωση ως αδιάβαστο` (Archive row only): `POST /api/posts/{pk}/unsee`, `seenLocal.delete(pk)`, `item.seen = false`, `bumpRemaining(+1)`, row repaints.
- `state.threshold` stays and is read only by `watchVisibility` (dead in practice). `loadBase` keeps parsing `view_threshold_ms`; do not remove the setting.
- `app.js`'s `document.addEventListener("keydown", …)` block (lines 207–238) is **deleted whole**. Its `m` branch is a second seen path that contradicts this seam, its `←/→` call the deleted `carousel`, its `Escape` navigates to `#/`. The player owns Escape, the shell owns the menu.

**Failure mode:** leaving the 1 s observer in. Ten 56px rows are all "40% in view" at once, so page 1 is marked seen within a second and `consumed` jumps by ten.

### D3 — paging state

```js
state.feed = {
  pages: [],     // [{items: Item[]}]  index 0 = page 1; a fetched prefix, never a hole
  page: 0,       // 0-based index into pages
  cursor: null,  // next_cursor for the page after the last fetched
  end: false,    // next_cursor was null
  endOnly: false, // spent session: the end block is the page, nothing fetched
  loading: false,
  total: 0,      // Number(state.session.item_count), frozen at mount; 0 = unknown
  remaining: 0,  // last remaining_in_session seen
  items: [],     // flat, append-only: every fetched row (playlist + seen lookups)
  seenLocal: new Set(),
  older: null,   // {cursor, end} for the opt-in archive list
};
```

- A session whose `item_count` is fully consumed renders the end block as the only
  page — `endOnly: true`, one empty page, **zero** `/api/feed` requests — and the page
  cell reads `Σελίδα n από n`. A reload at the end of the feed must not walk to page 1.
- `m = Math.ceil(total/10)`, `n = page + 1`. `total` is `state.session.item_count` — `GET /api/sessions/current` returns the row merged with `session_counts`, so the field is `item_count`, **not** `items`, which only `/api/status` has. `consumed + remaining === item_count` always, which is the quantity the design names.
- Footer: `STR.pageOf(n,m)` when `total > 0`, else `STR.pageN(n)`.
- `Προηγούμενη`: `page--`, render `pages[page]` from memory, no request, scroll to top; disabled at 0 with `STR.firstPage`. `Επόμενη`: render `pages[page+1]` if cached, else fetch with `cursor`, push, render; on the last page it is replaced by the end block with `STR.lastPage`.
- Render replaces `<ul class="files">`'s `innerHTML` with that page's rows plus its divider. One page in the DOM, so DOM order is page order.
- The page number lives in `state`, not the URL; browser-back never pages (§D1). The menu's `Προηγούμενη σελίδα` presses the footer's button (§D8).
- A post arriving mid-session is not a member (`store._membership` reserves `first_seen_sync <= snapshot_sync`) and never appears; the end block reports it and `Νέα συνεδρία` starts the next session.

**Failure mode:** indexing pages by `state.feed.items.length`. `items` survives navigation, so page 2 renders rows 1–20 and the footer counts rows, not pages.

### D4 — the divider

```js
const RESUME_MAX = 3;
function dividerIndex(page)   // → index within page.items, or -1
async function resumeWalk()   // fetch until a page holds the boundary, or 3 pages
function scrollToDivider(el)  // exact arithmetic, once
```

- Boundary: `i = page.items.findIndex(it => !it.seen)`. Divider renders when `i > 0`, or `i === 0 && page > 0`; `i === -1` means keep walking. In an `unseen` session `seen === false` is exactly "he has not opened it", and every `/api/feed` item carries `seen`.
- The divider is a sibling `<li class="divider">` inserted between the row above and the row at `i`, text `STR.divider(state.feed.remaining)`. The row under the line is the first one he has not read.
- Walk: `while (pages.length < RESUME_MAX && !end) fetchAndPush()`, stopping at the first page that yields a boundary. No boundary in three pages → render the last fetched page, no divider (deeper than 30 rows; say nothing rather than guess). Walk reaches `end` with nothing unseen → the end block is the page, which is the design's empty state.
- Scroll, after the page is in the DOM: `content.scrollTop = div.getBoundingClientRect().top - content.getBoundingClientRect().top + content.scrollTop - 8`, repeated once in a double `requestAnimationFrame`. `.content` is `position:relative`. `scrollIntoView` is banned here: it can scroll `.content`'s ancestors and re-runs the layout `scrollRestoration` was fighting.
- Resume on page 2 or 3 is the normal case: page `k` renders with the divider at the top, and `pages[0..k-1]` are in memory so `Προηγούμενη` is free.
- Two entries, two results: re-entering `/feed` resets to page 1 (`Πρόσφατα`), while `Ανανέωση` re-fetches page 1 and keeps the current page when it still exists — `views.feed(el, {fresh: true})`, reached through the `refresh` dep wired into `paintShell`.

**Failure mode:** `scrollIntoView({block:"start"})` inside a double rAF *and* `around_pk`. The first scrolls the window too (the shell is taller than 844×390), the second leaves `Προηγούμενη` unreachable.

### D5 — the status bar

```js
export function status(text = "", kind = "")   // kind: "" | "err" | "ok"   → [data-status]
export function page(n, m)                     // m falsy → STR.pageN(n)    → [data-page]
export function conn(text = "")                // dial-up line              → [data-conn]
```

- Owned DOM: `#statusbar > [data-status]`, `[data-page]`, `[data-conn]`. Views reach them through `H.status` / `H.page` / `H.conn`, added to the `views.init` env — the existing pattern, no bus and no import from shell into views. At ≤700 the two auto cells may hide, but `[data-conn]` stays: the bar always carries one word (`Έτοιμο` at rest).
- No timers. A message stays until the next one; `status("")` clears. `kind` adds `.err` (`--danger`) or `.ok` (`--ok`); the words always carry the meaning.
- Callers: any view, from a press or from the completion of a request it started. Never from a timer, never from `timeupdate`, never from an observer.
- `toast()` is deleted from `app.js`, `.toast` from CSS, and its three call sites become `H.status(…, "err")`: `toggleLike`'s catch (which moves to the details panel), the older-list fetch, `react`'s catch.
- `aria-live`: **only** `[data-status]` is `polite`; `aria-live` is removed from `<main id="app">` (it announces whole screens today). The page cell is not live. `role="status"` replaces the toast's.

**Failure mode:** writing progress into the live region. Every open announces "11 left" and the region reserved for two messages becomes noise.

### D6 — transport

DOM in §4. All wiring inside `paintVideo(seg, ph)`:

- `v.muted = mutedPref()` on construction. **No `play()` on load**: `playRememberingSound` becomes `applyMute(v)` (set + `volumechange` → `rememberMute`, 300 ms guard kept).
- `pp` → `v.paused ? v.play().catch(()=>{}) : v.pause()`; label `Αναπαραγωγή`/`Παύση`. `-10`/`+10` → `v.currentTime = clamp(v.currentTime ± 10, 0, dur)`.
- `seek.input` → `v.currentTime = Number(seek.value)/1000*dur`; `paintTime` writes the reverse.
- `timeupdate`, `loadedmetadata`, `durationchange` → `paintTime()`: `${clock(v.currentTime)} / ${clock(dur())}` using the existing `clock()` (`1:40`, not `01:40`), plus `seek.value`; both `tabular-nums`.
- `mute` → flip, `rememberMute`, label, `aria-pressed`. `ended` → repaint `Αναπαραγωγή`. `error` → the `story-ph` fallback with `STR.vidFailed`. Nothing advances.
- Post mode: `markSeen` is not called by paint, `playing` or `error` — the open already did it (§D2), and `/api/stories/seen` must never fire for a post.

`data-seek` and `data-act="mute"` are pinned by `test_ui.py` and keep their exact text.

**Failure mode:** leaving `playRememberingSound`'s `v.play()`. Every video starts on mount, the one behaviour the persona names as fatal.

### D7 — stickers

```html
<aside class="slinks" data-links hidden aria-label="Τι έχει πάνω της">
  <h2>Τι έχει πάνω της</h2>
  <section><h3>Πρόσωπα</h3><ul>
    <li><span class="lbl">@maria</span><small>14 Νοε 21:14</small>
        <a class="openlink" href="…" target="_blank" rel="noopener noreferrer">Άνοιγμα</a></li>
  </ul></section>
</aside>
```

- A row without `l.url` has no `.openlink`; nothing else in a row is clickable.
- `.lbl` is `user-select:text`, `overflow-wrap:anywhere`, never clamped or ellipsised — readability is the hard requirement, density is not.
- Groups in deck order (`Πρόσωπα`, `Μουσική`, `Σύνδεσμοι`, `Ετικέτες`, `Μέρη`); empty groups omitted.
- Reachable with details shut: `Στοιχεία` and `Τι έχει πάνω της` are two independent buttons (`.sheetbtns`) toggling `[data-details]` and `[data-links]`, closing the other; `aria-expanded` on each.
- An anchor rather than `button` + `window.open`: same CSP status, and the browser's own "open in new tab" survives. No JS.

**Failure mode:** leaving `<a href>` on the label, so reading a place name navigates the app away.

### D8 — menu bar

```html
<header id="topbar" hidden>
  <div class="titlebar"><span class="wtitle"></span><div class="winbtns"></div></div>
  <nav class="menubar" data-menubar></nav>
</header>
<main id="app" class="content"></main>
<div id="statusbar"><span data-status aria-live="polite"></span><span data-page></span><span data-conn></span></div>
```

```js
export function paintShell({ navigate, api, refresh })   // idempotent; fills title, menubar, win buttons
```

- Called once from `app.js` before the first `route()`. It builds `<button aria-haspopup="menu" aria-expanded="false">` per group plus a sibling `<div role="menu" hidden>` of `<button role="menuitem">` items, labels from `STR`.
- Open/close: a top button toggles its menu and closes any other; `Escape` closes and refocuses the top button; `pointerdown` outside `.menubar` closes. Inside a menu, `ArrowDown`/`ArrowUp` move focus (wrap), `Home`/`End` jump, `Enter`/`Space` activate (they are buttons), `Escape` closes.
- `data-item` selects a row of one table: `feed stories accounts history settings help sync about` → `navigate("/x")`; `logout` → `api("/logout",{method:"POST"})` then `navigate("/login")`; `refresh` → `deps.refresh()` (the router's `refreshRoute`: on the bulletin it re-fetches page 1 and writes `Συνδέομαι…` then `Συνδέθηκα.` in `[data-conn]`; elsewhere it repaints the route); `prev` / `next` → `document.querySelector('[data-act="page-prev"]').click()` — the menu is a proxy for the on-screen control, so paging state is never duplicated; `top` → `content.scrollTop = 0`.
- Disabled: `aria-disabled="true"` + `data-reason`, **not** the `disabled` attribute (it must stay focusable so arrows can land on it). Activating or focusing a disabled item calls `status(reason)`, and the item is never hidden. Reasons are computed when the menu opens: `prev` mirrors the footer button's `disabled` (or absent → `STR.pageless`), `top` when `scrollTop === 0`, `max` when `matchMedia("(max-width:700px)").matches`.
- Window buttons: minimise toggles `#window[data-min="1"]` (title + status only, restore on a title-bar press); maximise toggles `#window[data-max="1"]`, disabled ≤700px; close is `navigate("/feed")` from any route, and at home it is `aria-disabled` with `status(STR.alreadyTop)` — never `history.back()`, which reopens the page the list came from.

**Failure mode:** a `Shell.onPage = fn` registry views assign into. It outlives its screen, so the second visit to `/feed` leaves two handlers and one stale closure.

### D9 — tests

See §7. One rule: no test asserts an English string the copy deck owns; assert the Greek.

## 4. DOM contract

Load-bearing, never renamed: `.post`, `is-seen`, `stories-viewer`, `.acc li`, `.hist > li`, `story-ph`, `data-seek`, `data-act="mute"`, `#topbar` + `[hidden]`, `.media .fallback[hidden]`, `min-height:44px`, `touch-action:none`, `overscroll-behavior:none`, `100dvh`.

### Shell

```css
:root { --face:#c0c0c0; --hi:#fff; --lo:#808080; --dk:#404040; --desktop:#0f6b6b; --text:#000; --sel:#000080 }
#window { display:grid; grid-template-rows:auto auto minmax(0,1fr) auto; height:100dvh; border:2px solid }
#window[data-min="1"] { grid-template-rows:auto 0 minmax(0,1fr) auto }
#topbar { display:grid; grid-template-rows:26px 44px }     /* 22 / 28 at 844x390 */
.content { overflow-y:auto; min-height:0; position:relative; padding:8px }
#statusbar { display:grid; grid-template-columns:minmax(0,1fr) auto auto; height:28px }
@media (min-width:701px){
  body { background:var(--desktop); display:grid; place-items:center; height:100dvh }
  #window { width:1200px; height:760px } }
@media (max-width:700px){ [data-page], [data-conn] { display:none } }
```

390×844 → `26+44+742+28 = 840` inside the border. 844×390 → `22+28+314+22 = 386`. 1280×800 window → `30+28+668+30 = 756`.

### Bulletin

```html
<section data-bulletin>
  <h1 class="screen">Πρόσφατα</h1>                                <!-- 24px, 15px bold -->
  <div class="colheads"><span>Όνομα</span><span>Πότε</span><span>Τύπος</span></div>
  <ul class="files">
    <li class="post" data-pk="…">
      <a class="row" href="#/post/…" aria-label="Μαρία, 14 Νοε 21:14, Βίντεο">
        <span class="mk" aria-hidden="true"></span>
        <span class="nm"><span class="who">Μαρία</span><span class="sub">Βίντεο · 0:41</span></span>
        <span class="when">14 Νοε 21:14</span><span class="kind">Βίντεο</span></a>
    </li>
    <li class="divider" role="separator"><span>4 νέα από την τελευταία φορά</span></li>
    <li class="pager"><button data-act="page-prev">Προηγούμενη</button>
      <span class="pg">Σελίδα 1 από 2</span>
      <button data-act="page-next">Επόμενη</button></li>
  </ul>
</section>
```

```css
.files { list-style:none; margin:0; padding:0 }
.post, .colheads { display:grid; grid-template-columns:12px minmax(0,1fr) 84px 46px;
                   column-gap:8px; padding:0 4px; align-items:center }
.colheads { height:24px; font-size:12px; color:var(--muted) }
.post { height:56px; min-height:44px; border-bottom:1px solid var(--line) }
.post .row { display:grid; grid-template-columns:subgrid; grid-column:1/-1; height:100%;
             color:inherit; text-decoration:none }
.post .mk { width:8px; height:8px; background:var(--title) }
.post.is-seen .mk { background:none; border:1px solid var(--lo) }
.post .who { font-size:15px; font-weight:bold; overflow:hidden; text-overflow:ellipsis; white-space:nowrap }
.post.is-seen .who { font-weight:normal }
.post .sub, .post .when, .post .kind { font-size:13px; font-variant-numeric:tabular-nums }
.divider { height:32px; display:flex; align-items:center; gap:8px }
.divider::before, .divider::after { content:""; flex:1; height:1px; background:var(--lo) }
.pager { height:44px; display:grid; grid-template-columns:auto 1fr auto; align-items:center }
```

At 390 the 370 usable px are `12 + 8 + 204 + 8 + 84 + 8 + 46 = 370`. `subgrid` keeps cells 2–4 aligned between the head row and the rows; a browser without it repeats the same template on `.row` — identical numbers, no drift.

### Player

```html
<div class="stories-viewer" data-mode="post" role="dialog" aria-label="Αναπαραγωγή">
  <div class="childbar"><span class="ctitle">Αναπαραγωγή — Μαρία</span>
    <button data-act="close">Κλείσιμο</button></div>
  <header class="shead">
    <span class="swho"><strong>Μαρία</strong><span class="small">χθες 21:14</span></span>
    <span class="scount">2 από 5</span>              <!-- story mode only -->
    <button data-act="tray" hidden>Λίστα</button>    <!-- hidden at >=701px -->
    <div class="sheetbtns">
      <button data-act="details" aria-expanded="false">Στοιχεία</button>
      <button data-act="links" aria-expanded="false">Τι έχει πάνω της</button></div>
  </header>
  <aside class="stray" data-tray></aside>
  <div class="sstage" data-stage></div>
  <div class="svideo" data-transport>              <!-- absent for a photo -->
    <button data-act="pp">Αναπαραγωγή</button>
    <button data-act="-10">−10 δ</button><button data-act="+10">+10 δ</button>
    <input type="range" data-seek min="0" max="1000" step="1" value="0" aria-label="Θέση βίντεο">
    <span class="stime" data-time>0:00 / 0:00</span>
    <button data-act="mute" aria-pressed="true">Ήχος κλειστός</button></div>
  <aside class="sdetails" data-details hidden></aside>
  <aside class="slinks" data-links hidden></aside>
</div>
```

```css
.stories-viewer { position:absolute; inset:0; display:grid; background:var(--face); color:var(--text);
  touch-action:none; overscroll-behavior:none; grid-template-columns:minmax(0,1fr);
  grid-template-rows:auto 44px minmax(0,1fr) auto auto;
  grid-template-areas:"childbar" "head" "stage" "transport" "tools" }
.childbar { grid-area:childbar; height:24px; display:flex; justify-content:space-between }
.shead { grid-area:head; display:flex; align-items:center; gap:8px; padding:0 4px }
.sstage { grid-area:stage; background:#000; display:grid; place-items:center; min-height:0; overflow:hidden }
.sstage img, .sstage video { max-width:100%; max-height:100%; object-fit:contain }
.svideo { grid-area:transport; display:grid; height:72px;
          grid-template-columns:1fr 1fr 1fr 1.4fr; grid-template-rows:24px 48px }
.sheetbtns { grid-area:tools; display:grid; grid-template-columns:1fr 1fr; height:44px }
[data-act="pp"]{grid-area:2/2} [data-act="-10"]{grid-area:2/1} [data-act="+10"]{grid-area:2/3}
[data-act="mute"]{grid-area:2/4} [data-seek]{grid-area:1/1/2/4} [data-time]{grid-area:1/4; text-align:right}
@media (min-width:701px){
  .stories-viewer { grid-template-columns:200px minmax(0,1fr); grid-template-rows:auto 44px minmax(0,1fr) 44px;
    grid-template-areas:"childbar childbar" "head head" "tray stage" "tray transport" }
  .stray { grid-area:tray; align-self:start; max-height:calc(100% - 88px); overflow-y:auto }
  .sdetails, .slinks { grid-area:tray; align-self:stretch; overflow-y:auto }
  .sheetbtns { grid-area:tray; align-self:end; height:88px; grid-template-rows:44px 44px }
  .svideo { grid-area:transport; height:44px; grid-template-columns:auto auto auto minmax(0,1fr) auto auto;
            grid-template-rows:44px }
  [data-act="pp"]{grid-area:1/1} [data-act="-10"]{grid-area:1/2} [data-act="+10"]{grid-area:1/3}
  [data-seek]{grid-area:1/4} [data-time]{grid-area:1/5} [data-act="mute"]{grid-area:1/6} }
```

| viewport | childbar | header | stage | transport | tools | total |
|---|---|---|---|---|---|---|
| 390×844 | 24 | 44 | **558** | 72 | 44 | 742 |
| 844×390 | 20 | 44 | **206** | 44 | in column | 314 |
| 1280×800 | 24 | 44 | **528** | 72 | in column | 668 |

Four rows are fixed and `minmax(0,1fr)` is the only flexible one — design risk 1 answered in CSS. At 844×390 the two sheet buttons stack in the bottom 88px of the 200px column, so they cost the stage nothing. The landscape block is gated on `(min-width:701px) and (max-height:520px)`, as the frame already is, so a 1200×760 desktop window gets the portrait numbers (M10); header 44 also at landscape, because the 44px close box in `.shead` does not shrink below its touch target (F11) — the stage pays the 4px (206, not 210). Details open: `max-height:40%` at ≤700, scrolling, sunken; at ≥701 it replaces the playlist in the same cell. `.slinks` at ≤700 is `position:absolute; top:68px; right:0; width:min(320px,82%); max-height:72%; overflow-y:auto` — the only permitted overlay.

### Secondary

People `<ul class="acc">` → `<li data-pk>` + `.pic` + `.who` + `.acts` (`Δες τις ιστορίες`, `Σίγα`/`Άνοιξε τον ήχο`, `Κλείσε εκείνη τη συνεδρία`). Archive `<ul class="files hist">` where each row is a `<li class="post">` with `.row` (`Άνοιγμα`) plus `Σημείωση ως αδιάβαστο`; the v1 `.hist > li` grid rule stays. Setup: `.sheet` with `role="tablist"` and four `role="tab"`/`role="tabpanel"` pairs.

**No view may grow a path to unfollow.** `POST /api/accounts/{pk}/unfollow` is reachable from no screen and
**must stay that way**: the client keeps the endpoint for a future account screen, and the app never removes a
person on its own. Reaching it needs the account's pk from the DB, so any UI path to it is a deliberate design
decision, not a convenience (M12).

## 5. Strings

`app/static/str.js` is the only file containing Greek. `(…)` marks a function. Everything below is verbatim from the deck except `†` (from the design's Technical Plan) and `‡` (decision 12).

| key | Greek | English |
|---|---|---|
| `title` | `00sgram — τα νέα` | 00sgram — the news |
| `file` `view` `help` | `Αρχείο` `Προβολή` `Βοήθεια` | File · View · Help |
| `today` `stories` `people` | `Πρόσφατα` `Ιστορίες…` `Άνθρωποι…` | Recent · Stories · People |
| `archive` `settings` `logout` | `Αρχείο αναρτήσεων…` `Ρυθμίσεις…` `Έξοδος` | Post archive · Settings · Log out |
| `refresh` `prevPage` `nextPage` `toTop` | `Ανανέωση` `Προηγούμενη σελίδα` `Επόμενη σελίδα` `Στην αρχή` | Refresh · Previous page · Next page · To the top |
| `howItWorks` `connStatus` `about` | `Πώς δουλεύει` `Κατάσταση σύνδεσης` `Σχετικά με το 00sgram` | How it works · Connection status · About |
| `ready` `connecting` `reloaded` | `Έτοιμο` `Συνδέομαι…` `Συνδέθηκα.` | Ready · Connecting… · Connected (refresh) |
| `connected` (n) | `Συνδέθηκα — ${n} νέα` | Connected — n new |
| `syncStopped` (t) | `Ο συγχρονισμός είναι σταματημένος μέχρι τις ${t}.` | sync stopped until t |
| `offline` | `Δεν υπάρχει σύνδεση. Δείχνω ό,τι είχα.` | No connection; showing what I had |
| `syncFailed` | `Ο συγχρονισμός απέτυχε. Δείχνω το τελευταίο καλό αντίγραφο.` | sync failed; last good copy |
| `noConnection` | `Δεν υπάρχει σύνδεση.` | No connection |
| `name` `when` `kind` | `Όνομα` `Πότε` `Τύπος` | Name · When · Kind |
| `video` `photo` | `Βίντεο` `Φωτό` | Video · Photo |
| `nPhotos` (n) | `${n} φωτογραφίες` | 3 photos |
| `photoN` (n, m) | `φωτό ${n} από ${m}` | photo 2 of 6 — the album counter on the nav row |
| `fullscreen` | `Πλήρης οθόνη` | whole screen (the header glyph's label) |
| `windowed` | `Κανονικό παράθυρο` | the same glyph, pressed |
| `new` `read` | `νέο` `διαβασμένο` | new · read |
| `divider` (n) | `${n} νέα από την τελευταία φορά` | n new since last time |
| `pageOf` (n,m) | `Σελίδα ${n} από ${m}` | page n of m |
| `pageN` (n) | `Σελίδα ${n}` | page n |
| `prev` `next` | `Προηγούμενη` `Επόμενη` | previous · next |
| `allDone` | `Αυτά είναι όλα.` | That's all. |
| `countLine` (n,d) | `${n} αναρτήσεις, από τις ${d}.` | n posts, from d |
| `up` `older` | `Πάνω` `Παλαιότερα…` | Up · Older… |
| `fromArchive` `endArchive` | `Από το αρχείο` `Τέλος αρχείου.` | From the archive · End of archive |
| `noOlder` | `Δεν υπάρχουν παλαιότερα αποθηκευμένα.` | no older stored posts |
| `nothingNew` (d) | `Τίποτα καινούργιο από την ${d}.` | Nothing new since d |
| `lastCheck` (t) | `Τελευταίος έλεγχος: ${t}.` | Last check: t |
| `checkNow` | `Έλεγχος τώρα` | Check now |
| `conflict` `continueHere` `leaveIt` | `Το πρόγραμμα είναι ανοιχτό σε άλλη συσκευή.` `Συνέχισε εδώ` `Άφησέ την` | open on another device · continue here · leave it |
| `failed` `retry` | `Δεν φόρτωσε.` `Δοκιμή ξανά` | It didn't load · Try again — one action, no code and no browser English |
| `newSession` † | `Νέα συνεδρία` | New session |
| `play` `pause` | `Αναπαραγωγή` `Παύση` | Play · Pause |
| `back10` `fwd10` | `−10 δευτ.` `+10 δευτ.` | −10 s · +10 s |
| `muteOff` `muteOn` | `Ήχος κλειστός` `Ήχος ανοιχτός` | sound off · sound on |
| `seekLabel` | `Θέση βίντεο` | video position |
| `list` `details` `close` | `Λίστα` `Στοιχεία` `Κλείσιμο` | List · Details · Close |
| `of` (n,m) `sawOf` (n,m) | `${n} από ${m}` `είδες ${n} από ${m}` | n of m · you saw n of m |
| `sawIt` `prevSeg` `nextSeg` | `Το είδα` `Προηγούμενο` `Επόμενο` | I saw it · Previous · Next |
| `endAccount` (n) | `Τέλος των ιστοριών της ${n}.` | End of n's stories |
| `ofAll` (n,m) | `${n} από ${m}.` | n of m. |
| `nextPerson` (n,c) | `Επόμενη: ${n} (${c})` | Next: name (count) |
| `childTitle` (n) | `Αναπαραγωγή — ${n}` | Playing — name |
| `stickers` `nothingOn` | `Τι έχει πάνω της` `δεν έχει πάνω της τίποτα` | What's on it · nothing on it |
| `gPeople` `gMusic` `gLinks` `gTags` `gPlaces` | `Πρόσωπα` `Μουσική` `Σύνδεσμοι` `Ετικέτες` `Μέρη` | People · Music · Links · Tags · Places |
| `open` | `Άνοιγμα` | Open |
| `like` `sureLike` (n) `liked` `marked` | `Μου αρέσει` `Σίγουρα; Θα αρέσει στη ${n}.` `Σου αρέσει.` `Σημειώθηκε.` | Like · are you sure · it's liked · marked (one-way: no unlike) |
| `likeFailed` † | `Δεν αποθηκεύτηκε· γύρισε πίσω.` | not saved; reverted |
| `reactions` `reacted` | `Αντιδράσεις` `Αντέδρασες` | Reactions · You reacted |
| `sure` (n) | `Σίγουρα; Θα σταλεί στη ${n}.` | Are you sure? It goes to name |
| `sendIt` `cancel` | `Ναι, στείλ' το` `Άκυρο` | Yes, send it · Cancel |
| `taken` (d,t) | `Τραβήχτηκε ${d}, ${t}.` | Taken d, t |
| `openInstagram` | `Άνοιγμα στο Instagram` | Open on Instagram |
| `imgFailed` `vidFailed` `expired` | `Η εικόνα δεν κατέβηκε.` `Το βίντεο δεν άνοιξε.` `Αυτή η ιστορία έληξε.` | picture · video · expired |
| `coldFailed` | `Δεν κατέβηκε. Δοκιμή ξανά;` | It didn't download. Try again? |
| `newPosts` (n) | `νέες αναρτήσεις: ${n}` | new posts: n |
| `newStories` (n,m) | `νέες ιστορίες: ${n} από ${m}` | new stories: n of m |
| `unseenRing` | `Νέα` | new (ring of unknown freshness — not a loading state) |
| `noStories` `seeStories` | `δεν έχει ιστορίες` `Δες τις ιστορίες` | no stories · see the stories |
| `mute` `unmute` | `Σίγα` `Άνοιξε τον ήχο` | mute · open the sound |
| `finishLock` | `Κλείσε εκείνη τη συνεδρία` | Finish that session |
| `posts` `storyTab` | `Αναρτήσεις` `Ιστορίες` | Posts · Stories |
| `markUnread` `markedUnread` | `Σημείωση ως αδιάβαστο` `Σημειώθηκε ως αδιάβαστο.` | Mark unread · marked unread |
| `tabTypes` `tabSync` `tabAccount` `tabSpace` | `Τύποι` `Συγχρονισμός` `Λογαριασμός` `Χώρος` | Types · Sync · Account · Space |
| `save` `disconnect` | `Αποθήκευση` `Αποσύνδεση` | Save · Log out |
| `aboutText` | `Το 00sgram δείχνει τι ανέβασαν οι άνθρωποι που ακολουθείς, με τη σειρά. Δεν στέλνει τίποτα στο Instagram.` | (About) |
| `firstPage` `lastPage` † | `Είναι η πρώτη σελίδα.` `Είναι η τελευταία σελίδα.` | first · last page |
| `pageless` `alreadyFull` `alreadyTop` † | `Αυτή η οθόνη δεν έχει σελίδες.` `Το παράθυρο είναι ήδη όλο η οθόνη.` `Είσαι ήδη στην αρχή.` | no pages · already full · already at the top (close box at home) |
| `noArchive` † | `Δεν υπάρχει αποθηκευμένο αρχείο.` | no stored archive |
| `loading` (n) | `Φορτώνω…` `Κατεβάζω τις ιστορίες της ${n}…` | loading · fetching stories |
| `signIn` `password` `wrongPassword` ‡ | `Σύνδεση` `Κωδικός` `Λάθος κωδικός.` | Sign in · Password · Wrong password |

Dates: `H.when` (`app.js:145`) and `H.ago` (`app.js:135`) already arrive in `views.init` and are called ~20 times; today they return `toLocaleString()` and `"7d ago"`. Keep both names and reimplement them in `app.js` on top of a `MONTHS` array exported from `str.js`: `when(ts)` → `14 Νοε 21:14`, `χθες 21:14` when the calendar day is yesterday, `""` for a zero ts; `ago = when`, so no call site in `views.js` changes and one date format exists in the app. Chosen: a fixed array, because `Intl`'s `el-GR` month forms differ between WebKit builds and the deck pins the string.

## 6. Step plan for software

Strict order 1 → 14. Steps **2, 3 and 12** are safe to ship alone (✚): after them every route still serves and no test regresses.

| # | task | files | delete first | proof |
|---|---|---|---|---|
| 1 | tests first | `test_ui.py`, `test_copy.py` | — | `pytest tests/test_ui.py tests/test_copy.py -q` fails on the new markers — that is the point |
| 2 ✚ | frame: `str.js`, `shell.js`, new `index.html`, `app.js` wiring | str, shell, index, app, css | `#topbar nav` rules | every route renders in the frame at all three sizes; `#/` lands on `#/feed`; a disabled item prints its reason |
| 3 ✚ | CSS foundation: tokens, bevels, chrome heights, pressed/disabled/focus | css | `prefers-color-scheme` block, `.card`, `.list` | chrome measures 26/44/28, 22/28/22, 30/28/30; `#topbar[hidden]` still hides |
| 4 | bulletin as a list: `feed()`, `rowHTML`, Greek `H.when`/`H.ago`, seen on open | views, app | `postHTML`, `mediaFor`, `bindPosts`, `carousel`, `state.carousels`, sentinel, `watchVisibility` call, pos observer | ten rows, no `/api/media/post` element in the DOM, no `[data-sentinel]` |
| 5 | paging + status: `pages`, `cursor`, footer, `updateProgress` → `H.page` | views, app | `[data-progress]`, `[data-side]`, the keys hint card | 12 posts → `Σελίδα 1 από 2`, `Επόμενη` disabled on 2, `Προηγούμενη` issues no request |
| 6 | divider, end block, older opt-in: `resumeWalk`, `renderEnd`, `Παλαιότερα…` | views | the v1 end-card copy and its Dashboard button | resume opens at the divider; reload at the end renders the block with no `/api/feed` |
| 7 | player opens from a row: `post()`, `opts.mode`, route guard | views, app | v1 `post()` body, its `watchVisibility` call | one press opens a full-content picture; `Κλείσιμο`/Esc/Back return to the same row, `scrollTop` unchanged |
| 8 | player shell + transport: child bar, header, playlist, stage, relabelled `paintVideo` | views, css | swipe and tap-to-play pointer handlers, `playRememberingSound`'s play path, `watchPlayback`, the auto-advance read | one `[data-act="pp"]` per video and none on a photo; `0:12 / 1:40`; mute survives reload; `data-seek` present |
| 9 | story mode: playlist rows with `είδες n από m`, end card, no auto-advance | views | `autoAdvance()` | 60 s idle changes nothing; the last segment leads to the card |
| 10 | details panel: caption, date, external link, like, `Αντιδράσεις` | views | `toggleLike`'s glyph painting | no `.post` row contains `[data-act="like"]`; emoji absent until pressed; no request before `Ναι, στείλ' το` |
| 11 | stickers: labels as text, `Άνοιγμα` as an anchor, independent of details | views | `LINK_GROUPS`' anchor around the label | a URL is readable and does not open by being read; panel opens with details shut |
| 12 ✚ | secondary screens: People, Archive, Setup in Greek | views, css | `accHTML`'s `posts`/`unfollow` buttons, the auto-advance field | every string on those routes exists in `STR`; `test_copy.py` green |
| 13 | delete: dashboard, `stub`, `.toast`, `#/` route, v1 login card | views, app, css | `dashboard`, `routeSame`, `stub`, `toast`, `.toast` | no stat card on any route; `#/` → bulletin; `Δεν αποθηκεύτηκε· γύρισε πίσω.` appears once from a forced like failure |
| 14 | full pass: suite + manual matrix | — | — | `pytest -q` green; the §7 matrix clicked through |

## 7. Test plan

**Must stay green:** `test_api.py`, `test_store.py`, `test_sync.py`, `test_media.py`, `test_browser.py`, and `test_mcp.py` (needs the project venv; it fails to import `mcp.client` in a bare interpreter). The brief's "138" is the venv count — the gate is "the whole suite green", not a number. None of those files changes, because no endpoint changes.

**`test_ui.py`, replaced assertions:**

1. `test_index_is_public_and_uncached` — keep status, `cache-control`, `/static/app.js`; add `lang="el"`, `id="statusbar"`, `/static/shell.js`, `"<style" not in html`.
2. `test_static_js_is_served_uncached` — the tuple gains `shell.js` and `str.js`.
3. `test_static_assets_carry_their_contract` — app.js: `watchVisibility`, `bumpRemaining`, `flushSeen`, `rootMargin`, `views.accounts`, `views.historyView`, `views.sync`, `views.settings`, `history.scrollRestoration = "manual"`. views.js: `updateProgress`, `renderEnd`, `last_rendered_pk`, `stories-viewer`, `data-seek`, `story-ph`, `storiesViewer`, `storyJump`, `/api/history/stories`, `/api/sync/runs`, `session_filters_locked`, `finish-lock`, `data-act="mute"`, plus `data-mode="post"`, `Σελίδα`, `Νέα συνεδρία`, `.files`, `Σημείωση ως αδιάβαστο`, `Άνοιγμα`, `Μου αρέσει`. `around_pk` is **removed** (decision 3) — say so in the docstring so the next reader does not restore it. CSS: `#topbar[hidden]`, `.stories-viewer`, `touch-action: none`, `overscroll-behavior: none`, `100dvh`, `.media .fallback[hidden]`, `.acc li`, `.hist > li`, `min-height: 44px`, plus `--face: #c0c0c0`, `.files`, `#statusbar`, `grid-template-columns: 12px`, `is-seen`.
4. `test_no_dead_vocabulary` (new) — `onclick`, `javascript:` and `<script>` absent from every shipped file; `.toast`, `.ring`, `.carousel`, `.dots`, `prefers-color-scheme`, `data-car`, `watchPlayback`, `autoAdvance`, `story_auto_advance_accounts` absent from css/js.
5. `test_no_row_has_a_like_control` (new) — slice `views.js` from `function rowHTML(` to the next `\nfunction `, assert `"like" not in body`; and `views_js.count('data-act="like"') == 1`.

**`test_copy.py` (new):**

- Parse `str.js`: every `^\s{2}\w+: ` is a key; assert no duplicate keys.
- Assert a 40-entry list of deck strings appears verbatim, including `Σελίδα`, `Αυτά είναι όλα.`, `4 νέα από την τελευταία φορά`, `Μου αρέσει`, `Άνοιγμα στο Instagram`, `Ήχος κλειστός`, `Σημείωση ως αδιάβαστο`, `Κλείσε εκείνη τη συνεδρία`, `Τραβήχτηκε`.
- Strip the table and assert `[\u0370-\u03ff]` matches nothing in `views.js`, `shell.js`, `app.js`, `index.html` — no free-text Greek, comments included.
- Every `STR.<key>` used in `views.js`/`shell.js` exists; every key is used at least once (dead copy is a copy bug).

**Manual WebKit matrix.** Device toolbar, hard reload between sizes. At each: (a) `#/feed` — count ten rows, press `Επόμενη`, then `Προηγούμενη` and confirm no request in the network panel; (b) press a video row — it is paused, press `Αναπαραγωγή`, `+10 δ`, `Ήχος ανοιχτός`, reload and confirm the sound is still on; (c) press `Στοιχεία` and `Τι έχει πάνω της` with the other shut; (d) `Κλείσιμο` and confirm the row you left is still under the pointer and the hash is `#/feed`; (e) `Αρχείο` → open each item, then `Προβολή` on the last page: `Επόμενη σελίδα` is greyed and prints its reason; (f) reload at the end block: it renders with zero XHR for `/api/feed`.
**390×844** — chrome 26/44/28, stage 558, no margin. **844×390** — 22/28/22, playlist column visible, stage 210, sheet buttons inside the column. **1280×800** — 1200×760 window centred on teal, content 668, the page cell visible in the status bar.

## 8. Rollback

`/tmp/00s-v1-backup` holds the four v1 static files (`app.js`, `views.js`, `style.css`, `index.html`). It is the only rollback artifact; no Python changes in this build. Deploy per commit into the running instance (`00sgram-web-1`, host port 8091, static baked at `/app/app/static/`):

1. `pytest -q` — never deploy on red.
2. `docker cp app/static/. 00sgram-web-1:/app/app/static/` — no rebuild, no restart; the mount revalidates every request (`_Revalidating` sets `cache-control: no-cache`).
3. Browser hard reload (`Cmd-Shift-R`) — module URLs are not fingerprinted.
4. Verify: `curl -s localhost:8091/static/str.js | head -3`, then one screen per route.

If a step breaks the instance: (1) `docker cp /tmp/00s-v1-backup/. 00sgram-web-1:/app/app/static/`; (2) hard reload, the v1 bulletin renders; (3) if the step also changed sources, `git checkout -- app/static/index.html app/static/style.css` then repeat 1 — v1 has no `shell.js`/`str.js`, nothing can resurrect them, so the rollback is complete without deleting the new files; (4) the real deploy is `docker compose build && docker compose up -d`, which always wins over copied files and is the only way back after a restart. Do not run it mid-rollback.

↳ engineering (head: build) — done: docs/designs/00sgram-v2/engineering.md
