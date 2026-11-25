# 00sgram v2 — QA review

Role: QA. Instance `http://192.168.1.72:8091`, deployed bytes verified identical to
`app/static/*` (sha256 of all six files). WebKit 390×844 / 844×390 / 1280×800, one fresh
device per context. Nothing was liked, reacted to, followed, unfollowed or session-finished;
write endpoints were exercised only through the app's own gated paths (open row, open story).

**Verdict: FAIL — 1 blocker, 3 majors, 5 minors.** The automated gates are green and the
contract is almost entirely honoured; the blocker is that at 390×844 the player's playlist
opens by default and the story picture gets **0 px** (post picture 116 px, contract 558).

## Suite output

| command | result |
|---|---|
| `~/venvs/00sgram/bin/python -m pytest tests -q` | `144 passed in 3.64s` |
| `node tests/player_check.mjs` | `75 ok`, `0 FAIL`, `all ok` |
| `node tests/secondary_check.mjs` | `48 ok`, `0 FAIL`, `all ok` |

## Contract table (engineering §1, statement by statement)

| id | statement (short) | verified? | proof |
|---|---|---|---|
| F1 | `lang=el`, `#topbar[hidden]`, `#app`, `#statusbar`, one module script, no inline script/style | yes | DOM: `lang="el"`, inline `<script>`=0, `<style>`=0, `/static/app.js` only; `#/login` → `topbar.hidden===true` |
| F2 | shell paints chrome once; no view paints chrome | yes | `grep wtitle\|menubar\|statusbar app/static/views.js` → 0 hits |
| F3 | chrome 26/44/28·742; 22/28/22·314; 1200×760 centred, 30/28/30·668 | yes | measured 26/44/742 · 22/28/314 · 1200×760@(40,20), 30/28/668 |
| F4 | content is the only scroller; chrome never scrolls | yes | `/accounts` 390: `scrollTop` 0→500, title/menu/status `top` 2/28/814 unchanged; `scrollWidth==clientWidth`; document not scrollable |
| F5 | 3 menus open on press, stay until item/Esc/outside, arrows move, greyed item keeps place + prints reason | yes | Προβολή: `aria-disabled=true` on prev/top with reasons `Είναι η πρώτη σελίδα.`/`Είσαι ήδη στην αρχή.` printed to `[data-status]`, menu stays open; Esc and outside click close and clear; ArrowDown → `refresh→prev` |
| F6 | `#/` and every unknown hash resolve to `#/feed` | **violated (minor)** | `#/` → `history.replaceState` → `#/feed`; `#/nonsense` renders the bulletin but the hash stays `#/nonsense` |
| B1 | `ul.files > li.post`, 10/page, row is `a href="#/post/<pk>"`, no media in row DOM | yes | 10 rows; `[src*="/api/media/post"]`=0; `[data-sentinel]`=0; href `#/post/4028919478410405411` |
| B2 | 56px, `12px minmax(0,1fr) 84px 46px`, gap 8, pad 0 4px, rule `#a0a0a0`, cell4 Βίντεο/Φωτό | yes | computed `grid-template-columns: 12px 1004px 84px 46px`, `column-gap:8px`, `padding:0 4px`, `border-bottom 1px rgb(160,160,160)`, height 56, kinds `Βίντεο,Βίντεο,Βίντεο,Φωτό` |
| B3 | unseen filled `#000080` 8×8 + bold; seen 1px `#808080` outline + regular + `is-seen` | yes | unseen `8×8 rgb(0,0,128)`, weight 700; after open → `is-seen`, `background rgba(0,0,0,0)`, `border 1px rgb(128,128,128)`, weight 400 |
| B4 | `14 Νοε 21:14`, `χθες 21:14`, `tabular-nums` | yes | rows `13 Νοε 15:01`; player header `χθες 12:49`; `font-variant-numeric: tabular-nums` on `.when` |
| B5 | 10/page, `Σελίδα n από m`, 44px Προηγούμενη/Επόμενη, disabled with reason at ends | yes | 44/44 px buttons, `Σελίδα 1 από 5`; last page next disabled + menu reason `Είναι η τελευταία σελίδα.`; `Σελίδα n` (unknown total) not reachable in this data |
| B6 | `m = ceil(item_count/10)`, never shrinks | yes | 41 items → `Σελίδα 1 από 5`; frozen `state.session.item_count`; no shrink across paging |
| B7 | divider above first unseen on resume, scrolled once, none when nothing unseen | yes | after opening row 1 and reloading: divider at child index 2 (above row 2), text `40 νέα από την τελευταία φορά`; page 1 all-unseen → no divider |
| B8 | last page = end block: `Αυτά είναι όλα.`, count line, `Πάνω`/`Παλαιότερα…`/`Νέα συνεδρία`, nothing after it requests | **violated (major, #4)** | block verified verbatim + 3 buttons; 3 s idle → 0 XHR; but reload at the end renders page 1 and fires 1 `/api/feed` |
| B9 | `Παλαιότερα…` appends `Από το αρχείο`, ends `Τέλος αρχείου.`/`Δεν υπάρχουν παλαιότερα αποθηκευμένα.` | partial | one `/api/older` request, heading + `Δεν υπάρχουν παλαιότερα αποθηκευμένα.`, 0 further XHR; row list unverified (archive empty) |
| B10 | no auto-start except `#/feed`; conflict/empty/failed/frozen each a panel with deck sentence + one action | **violated (major, #3)** | `POST /api/sessions` only on `#/feed`; 409 → `Υπάρχει ανοιχτή συνεδρία αλλού.` + Συνέχισε εδώ/Άφησέ την; `/api/feed` 500 → `Δεν φόρτωσε.` + `Δοκιμή ξανά` (retry works); **`/api/settings` 500 → panel prints `boom` twice**; dead network → `Load failed` |
| P1 | `#/post/<pk>` opens over the mounted bulletin; close restores rows and scroll | yes (online) | `data-mode="post"`, root `position:absolute` inside `.content`; close → 10 rows, `scrollTop` unchanged, hash `#/feed`; offline → defect #2 |
| P2 | one `openViewer`/`paintSegment`/`paintVideo`/`paintTray`/`paintLinks`/`advance` | yes | `grep -c` each function in views.js → 1 |
| P3 | playlist = page's posts, 44px rows, name + date | yes | 10 rows, each 44px, `brookeraboutou 12 Νοε 19:30` |
| P4 | one play control labelled `Αναπαραγωγή`; nothing starts until pressed; no transport on a photo | yes | `[data-act=pp]` count 1 on video, 0 controls on photo row; after 10 s `paused===true`, `currentTime===0`; press → plays, press → pauses |
| P5 | `data-seek`, `data-act="mute"`, `m:ss / m:ss` tabular, mute survives segment + reload via `MUTE_KEY` | yes | `type=range 0..1000 aria-label Θέση βίντεο`; `0:00 / 1:06`; unmute → `Ήχος ανοιχτός`, `localStorage 00sgram.muted="0"`, still open after reload and after tray segment switch |
| P6 | header: name, `n από m` story-mode only, Λίστα hidden ≥701, Κλείσιμο | yes | `[data-count]` `1 από 5` story / `""` post; tray button `display:none` at 844 and 1280, `block` at 390 |
| P7 | details: caption, `Τραβήχτηκε …, 19:30.`, Instagram link, `Μου αρέσει` checkbox — never on a row | yes | `like_total_in_doc=1`, `like_in_any_row=0`; link `target=_blank rel=noopener noreferrer` |
| P8 | reactions disclosure: no emoji until pressed, confirm, no request before `Ναι, στείλ' το` | yes | emoji count 0 → 5 after press; `Σίγουρα; Θα σταλεί στη …`; POST count 0 on confirm card; rendered separately |
| P9 | labels selectable text + separate `Άνοιγμα` per URL; panel opens with details shut | yes | `<span class="lbl">` (no enclosing anchor), `<a class="openlink">Άνοιγμα</a>`, `details.hidden===true` while links open |
| S1 | `ul.acc` with `νέες αναρτήσεις: n`, `νέες ιστορίες: n από m`, `Δες τις ιστορίες`, `Σίγα`/`Ξαναμίλα`, `Κλείσε εκείνη τη συνεδρία` | yes (copy defect #6) | `dynastyathens`: `νέες αναρτήσεις: 3 νέες ιστορίες: 3 από 4 …`; press → `#/stories`, player opens `dynastyathens 1 από 4` |
| S2 | archive = same paged list, 2 tabs, `Άνοιγμα` + `Σημείωση ως αδιάβαστο`, no append | yes | 19 rows, per row `Άνοιγμα`/`Σημείωση ως αδιάβαστο`, tabs Αναρτήσεις/Ιστορίες, no sentinel, no `unsee` pressed |
| S3 | setup = 4-tab sheet, `story_auto_advance_accounts` gone/unread | yes | 4 tabs / 4 panels; no auto-advance field or string |
| S4 | every unprompted message one status line, at most once per session | yes | all ~20 `H.status(` call sites are press handlers or the failure of one; no timer/observer/`timeupdate` caller |
| T1 | `pytest -q` green incl. rewritten `test_ui.py`, new `test_copy.py` | yes | 144 passed |
| T2 | `onclick`, `javascript:`, `data-car`, `.carousel`, `.dots`, `.ring`, `watchPlayback`, `autoAdvance`, `story_auto_advance_accounts`, `.toast` in no shipped file | yes | `grep` over `app/static/*` → no match (exit 1) |
| T3 | exactly one `data-act="like"`, in the details panel, never in a row builder | yes | `views.js:679` only; `rowHTML` body contains no `like` |

## Defects

| # | severity | area | reproduction | expected | actual | file:line |
|---|---|---|---|---|---|---|
| 1 | **blocker** | player ≤700 | 390×844, `#/stories`, press the first `Δες τις ιστορίες` | picture fills the stage (558 of 742, design §4 table) | playlist row is open on mount (206–177 px); stage `0 px` in story mode, `116 px` in post mode; picture invisible until `Λίστα` is pressed once (then 514/558) | `views.js:578`, `style.css:285` (tray in an `auto` track), `style.css:308`; at ≤700 no `[hidden]` override exists, so mounting the tray `hidden` fixes it |
| 2 | major | offline post route | load `#/feed`, abort `**/api/**`, press any row | P1: player opens over the mounted bulletin | `#app` is replaced by an error banner; rows 0, player never opens; bulletin is gone | `app.js:181` (`loadBase()` before the `/post/` branch), `app.js:206` |
| 3 | major | failure panel copy | route `**/api/settings` → 500 `{"error":{"code":"boom"}}`, load `#/feed`; or abort `**/api/**` and load `#/feed` | B10: the deck's Greek sentence + one action | panel prints the machine code twice (`boom`/`boom`) or the English browser error (`Load failed`); only `Δοκιμή ξανά` is Greek | `app.js:206-211` |
| 4 | major | end block / resume | page to `Σελίδα 5 από 5` (end block visible), reload | end block renders, no `/api/feed` XHR (engineering §6 step 6, acceptance item) | `Σελίδα 1 από 5`, no end block, 1 `/api/feed`; with `RESUME_MAX=3` the block is unreachable on reload for any feed over 3 pages, even fully seen | `views.js:86,216-259` (`resumeWalk` cap), `views.js:398` |
| 5 | minor | routing | open `#/nonsense` | F6: resolves to `#/feed` | bulletin renders, hash stays `#/nonsense` | `app.js:178` |
| 6 | minor | story counts copy | `#/accounts` row for `@anti.nou` (tray `media_count=1`, `segments_unseen=0`); `#/stories` playlist for any `known:false` ring | `νέες ιστορίες: 0 από 1`; `είδες n από m` | row says `δεν έχει ιστορίες`; playlist sub says `Φορτώνω…` forever with nothing loading | `views.js:1106-1109`, `views.js:658` |
| 7 | minor | paging failure | load `#/feed`, abort `/api/**`, press `Επόμενη` | a visible failure with a retry control | status line `Δεν φόρτωσε.` only, no retry control (pressing `Επόμενη` again does retry) | `views.js:322-324` |
| 8 | minor | dead surface | — | no unfollow path anywhere | `POST /api/accounts/{pk}/unfollow` exists and calls `provider.unfollow`, reachable from no UI; `last_rendered_pk` is written and read by nobody in the client; stale comment claims resume lands on it | `main.py:639`, `views.js:460`, `app.js:5` |
| 9 | minor | player geometry ≥701 | 1280×800, open a video post; 844×390 likewise | §4 table: childbar 24, header 44, stage 528, transport 72 | 20 / 40 / 564 / 44 (landscape matches its table) | `style.css:394-402` |

## State invariants

| invariant | measured |
|---|---|
| seen survives reload, one PATCH | open → `PATCH /api/sessions/41` + `POST /api/posts/seen`; reopen same row → PATCH only; reload → row `is-seen` |
| Επόμενη then Προηγούμενη | forward 1 `/api/feed`, back **0** `/api/feed`, `Σελίδα 2 από 5`→`Σελίδα 1 από 5` |
| reload at the end | **not met**: page 1, no end block, 1 `/api/feed` (defect #4); idle 3 s after the block → 0 XHR |
| mute | `Ήχος ανοιχτός`, `aria-pressed=false`, `localStorage "0"` after reload and after a segment switch |
| no autoplay | video post, 10 s untouched: `paused===true`, `currentTime===0`; idle story 12 s: `1 από 4`→`1 από 4` |
| story progress per account | A `1 από 4` → `2 από 4`; close; B opens at `1 από 2` |
| console health | 11 routes × 3 sizes: 0 uncaught exceptions, 0 5xx; only the expected two `401` (pre-login paint) and one `404` (`/api/sessions/current`) |

## Zero-write audit

| path | reachable from | confirmation? | verdict |
|---|---|---|---|
| `POST/DELETE /api/posts/{pk}/like` | post player → `Στοιχεία` → `Μου αρέσει` checkbox (`views.js:697`) | no — one tap after opening the panel | **sanctioned by P7** (reversible, refusals revert + `Δεν αποθηκεύτηκε· γύρισε πίσω.`); never in a row |
| `POST /api/stories/{pk}/react` | story player → `Αντιδράσεις` → emoji → `Ναι, στείλ' το` | yes — 3 presses, named confirm | pass |
| `POST /api/accounts/{pk}/unfollow` | nothing (no UI string, no call) | n/a | unreachable; delete or gate before any UI grows |
| `POST /api/accounts/{pk}/mute` | People row `Σίγα`/`Ξαναμίλα` | no | local settings write, not Instagram |
| `POST /api/sessions/{id}/finish` | People `Κλείσε εκείνη τη συνεδρία` | no | local session, contract S1; not pressed by QA |
| `POST /api/posts/seen`, `/api/stories/seen`, `/api/stories/{pk}/done`, `/api/posts/{pk}/unsee`, `PATCH /api/sessions/{id}` | open row, open story, archive `Σημείωση ως αδιάβαστο` | no | local read-state |
| `PUT /api/settings`, `POST /api/sessions`, `/api/sync`, `/logout`, `/login` | settings save, `Νέα συνεδρία`, `Έλεγχος τώρα`, `Έξοδος`, login card | no | local / read-only sync |

## Not covered

- Like and reaction **happy path** — forbidden to press; only the gate (0 POST before confirm) and payload wiring were read.
- Empty-feed panel and frozen-sync panel — the live account has 51 unseen posts and a healthy sync, so those states cannot be produced without a new session or a faked store.
- Archive rows with real data — the stored archive is empty, so B9/S2 list rendering is unverified (only their empty states).
- Cold story fetch (`POST /api/stories/{pk}/fetch` + 500 ms poll) — every ring opened had cached segments.
- 401 mid-session (expired cookie → login redirect) and the 409 takeover action (`Συνέχισε εδώ` was not pressed).
- Reduced-motion, screen reader traversal, and long-caption stress.

↳ qa (head: build) — done: docs/designs/00sgram-v2/review-qa.md (1 blocker, 3 majors)

## Second pass (after the fix deploy)

Method: `http://192.168.1.72:8091` (sha256 of all six `app/static/*` still equal to the repo) plus a
local `PROVIDER=mock` instance on `127.0.0.1:8099` serving the **same** static bytes and a seeded
store. The owner's unseen pool was down to **1 post** (the first pass's paging plus this pass's
open-row checks consumed it), so paging, the end block, the archive row and the photo stage were
reproduced on seeded data; everything account-specific (stories list, like gate, geometry on real
media) was measured live, at 390×844 / 1280×800 / 844×390 WebKit, `has_touch` on.

**Verdict: fail** — 34/34 graded fixes PASS, 0 FAIL, 0 UNVERIFIED, but this pass introduced one
regression on the `#/post/<pk>` deep link (Regressions, first bullet).

| id | verdict | evidence |
|---|---|---|
| F1 | PASS | 390×844 stage **558** video / **630** photo (`[data-transport]` display:none); media box == stage box, `inside:true`; 1280×800 **528**, `object-fit:contain`, 320×568 clip paints 297×528 letterboxed; 844×390 **206**; `[data-tray]` display **none** on mount at 390 |
| F2 | PASS | live `#/stories` idle 4 s, 390 and 1280: 36 rows, `Φορτώνω` matches **0**, every `.sub` matches `^(Νέα\|είδες n από m)$` (36/36 `Νέα`) |
| F3 | PASS | live: control is `<button>Μου αρέσει</button>` inside `[data-details]`, in no row; press → **0** `/api/posts/*/like` (only `POST /api/posts/seen` from the open); confirm `Σίγουρα; Θα αρέσει στη {name}.` (author sentence read on the mock player) + `Ναι, στείλ' το`/`Άκυρο`; confirm never pressed |
| F4 | PASS | page 3 (`Σελίδα 3 από 4`) → Αρχείο→`Πρόσφατα` → **`Σελίδα 1 από 4`**, 10 rows |
| F5 | PASS | conn cell writes exactly `Συνδέομαι…`, `Συνδέθηκα.`; **1** `GET /api/feed?session=1&limit=10`; 10 rows re-rendered; page kept |
| F6 | PASS | archive row: count 1→1, `is-seen`→false, `.sub` `διαβασμένο`→`νέο`, marker transparent→`rgb(0,0,128)`, status `Σημειώθηκε ως αδιάβαστο.`, **0** `/api/feed`, 1 unsee POST |
| F7 | PASS | `#/history` → ✕ → `#/feed` + bulletin; ✕ again → status `Είσαι ήδη στην αρχή.`, hash unchanged |
| F8 | PASS | 8 routes at 390: `#statusbar` never empty, `[data-conn]` `display:flex` on all, `Έτοιμο` present |
| F9 | PASS | 12 rows, 7 say `δεν έχει ιστορίες`, **7/7** `[data-act=stories]` disabled with `data-reason` = same words, 0 enabled without a ring |
| F10 | PASS | `appearance:none` computed on `[data-seek]` in a live player, 24px row, `seekOverlapMedia:false`; thumb `border-radius:0` read from `style.css:367` (WebKit exposes no pseudo computed style — rule read, not rendered) |
| F11 | PASS | `.shead [data-act=close]` = **66×44** at 390, 1280×800, 844×390; `.childbar [data-act=close]` kept at 61.9×20 |
| F12 | PASS | story left 10 s untouched: `1 από 1` before/after, **0** `/api/stories/seen` on close; press `Το είδα` → exactly **1** `POST /api/stories/seen`, `1 από 1` unchanged, status `Σημειώθηκε.` |
| F13 | PASS | abort `**/api/**` on a loaded bulletin, press a row: `.stories-viewer` mounts, 10 rows still in `#app`; Κλείσιμο → `#/feed`, 10 rows. Deep-link half is the regression below |
| F14 | PASS | 500 on `/api/settings` → `Δεν φόρτωσε.` + `Δοκιμή ξανά`, **1** retry, `/[A-Za-z]{3,}/` matches **0**; abort `**/api/**` → `Δεν υπάρχει σύνδεση.` + 1 retry, 0 ASCII words |
| F15 | PASS | session spent (`item_count 34`, `remaining 0`), last page `Σελίδα 4 από 4` + end block, no `.pager`; reload → **0** `/api/feed` (settings, sessions/current, status only), `Σελίδα 4 από 4`, terminal block renders |
| M1 | PASS | last page: `.pager` absent, block `Αυτά είναι όλα.` + count line + `Πάνω`/`Παλαιότερα…`/`Νέα συνεδρία`; page 1 keeps the pager |
| M2 | PASS | tabs `Τύποι, Συγχρονισμός, Λογαριασμός, Χώρος`; `aria-selected=true` on Τύποι; only `[data-panel=types]` visible |
| M3 | PASS | `.login` is `login sheet stack`, 1px `rgb(128,128,128)` frame on `rgb(192,192,192)`; `h1.screen` 15px/700 |
| M4 | PASS | `[data-act=links]` shown, `aria-disabled=true`, `data-reason=δεν έχει πάνω της τίποτα`; press leaves the panel hidden and empty |
| M5 | PASS | `.hist .row` is an `<a>`, 1px `rgb(255,255,255)` raised border + inset `-1px -1px rgb(128,128,128)`/`1px 1px rgb(223,223,223)`, identical to the sibling `unsee` button, both 44px |
| M6 | PASS | post mode `[data-count]` = `1 από 10`, story mode `1 από 1`, `[data-nav]` hidden in post mode |
| M7 | PASS | doc `12 + 8 + 194 + 8 + 84 + 8 + 46 = 360`; measured `ul.files` 370 − 2px border − 8px padding = row **360**, height 56; CSS `12px minmax(0,1fr) 84px 46px`, gap 8, padding 0 4px |
| M8 | PASS | `#/nonsense` → `#/feed` with the bulletin and 10 rows |
| M9 | PASS | abort then `Επόμενη` → banner `Δεν φόρτωσε.` + exactly 1 `Δοκιμή ξανά`; press → `Σελίδα 2 από 4`, 10 rows, banner gone |
| M10 | PASS | 1280×800 stage **528** (childbar 24 / head 44 / transport 72 — portrait numbers); 844×390 stage **206** (20/44/44); landscape block gated `(min-width:701px) and (max-height:520px)` |
| M11 | PASS | `app.js:1-8` no longer claims resume lands on `last_rendered_pk`; the write stays `views.js:498`, the client reads it nowhere (1 grep hit, the write) |
| M12 | PASS | `engineering.md:393` "No view may grow a path to unfollow"; `unfollow` in `app/static/*` = 1 hit, a comment (`views.js:1189`) |
| copy: back10 | PASS | `str.js:62` `−10 δευτ.`, transport button measured `−10 δευτ.`; `−10 δ` 0 hits in `app/`, `tests/`, deck |
| copy: fwd10 | PASS | `str.js:63` `+10 δευτ.`, measured in `.svideo`; `+10 δ` 0 hits |
| copy: unmute | PASS | `str.js:109` `Άνοιξε τον ήχο`, rendered at `views.js:1211` when `a.muted` (live account has 0 muted, so the label was not emitted this run); `Ξαναμίλα` 0 hits |
| copy: conflict | PASS | `str.js:54` `Το πρόγραμμα είναι ανοιχτό σε άλλη συσκευή.`, render sites `views.js:200,1664`; old sentence 0 hits |
| copy: today | PASS | `str.js:10` `Πρόσφατα`; h1 and menu item measured `Πρόσφατα`; `Σημερινά` 0 hits |
| copy: kind | PASS | `str.js:33` `Τύπος`; bulletin column header measured `Τύπος`; `Είδος` 0 hits |
| copy: alreadyTop | PASS | `str.js:132` `Είσαι ήδη στην αρχή.`, emitted by ✕ on `#/feed` (F7), and by the menu `top` reason |

**Regressions** (the important section):

- **`#/post/<pk>` deep link or a reload while a post is open now closes onto an empty bulletin.**
  Measured: `goto APP#/post/<pk>` → player opens (`count 1 από 1`), `ul.files li.post` = **0** behind
  it; Κλείσιμο → `#/feed`, rows **0**, `#app` text only `Πρόσφατα`, **0** `/api/feed`, no end block
  and no message — a dead screen that needs a menu press to escape. Cause: `app.js:197-204` mounts a
  stub `[data-bulletin]`, so `views.post` takes `mounted === true` and never calls `feed()`; before
  this fix the deep link fell through to `feed(el)` and had rows underneath. The code comment calls
  the empty shell deliberate (offline close); online it costs the rows. One line in `route()` on
  `#/feed` (`if (!el.querySelector("ul.files li.post")) views.feed(el)`) closes it.
- Nothing else from the first pass broke, re-measured: bulletin row **360×56** with the 12/84/46
  grid, B7 resume divider at child index 2 (`33 νέα από την τελευταία φορά`, row 1 `is-seen`), no
  autoplay (8 s: `paused:true`, `currentTime 0`, one play control), open→close keeps the 10 rows and
  the scroll.
- Unchanged, outside F15's stated scope: with `session.remaining > 0` a reload at the last page
  still lands on page 1 with 1 `/api/feed` (measured: remaining 33 → `Σελίδα 1 από 4`, 1 request).
- Reload at the end of a **spent** session renders the empty-state block (`Τίποτα καινούργιο από την Τρίτη.`) rather than the pre-reload `Αυτά είναι όλα.` + count line; the design makes that panel the page when nothing is unseen — noted, not scored.

**Last pass's defects**: blocker #1 (stage 0/116 at ≤700) **closed** — 558/630. Major #2 (offline
press wiped the bulletin) **closed** — player over 10 rows, close returns. Major #3 (`boom` /
`Load failed` in failure panels) **closed** — Greek sentences only, one action. Major #4 (end block
unreachable on reload) **closed** for a spent session — 0 `/api/feed`, `Σελίδα n από n`.

**Gate output**

| command | result |
|---|---|
| `~/venvs/00sgram/bin/python -m pytest tests -q` | `144 passed in 3.48s` |
| `node tests/player_check.mjs` | `83 ok`, `0 FAIL`, `all ok` |
| `node tests/secondary_check.mjs` | `74 ok`, `0 FAIL`, `all ok` |

**Not covered**

- Like and reaction happy paths — forbidden to press; only the gate, the confirm copy and the payload wiring were read.
- 409 takeover (`Συνέχισε εδώ`), frozen-sync and empty-feed panels — not producible on the live account without a second device.
- Owner-data paging geometry and the archive's live rows — live pool was 1 post and the stored archive is empty.
- Cold story fetch with its 500 ms poll (every ring had cached segments), reduced motion, screen-reader traversal.
- M12 is a rule about the future: a grep cannot prove no view ever grows a path to `unfollow`.

↳ qa (head: build) — done: review-qa.md second pass (34 pass, 0 fail on graded fixes, 0 unverified, 1 new regression — verdict fail)
