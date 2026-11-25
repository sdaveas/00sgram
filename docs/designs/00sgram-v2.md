# 00sgram v2 — design

Role: design. Input: `designs/00sgram-v2/brief.md`, `product-owner.md`, `design-interview.md`, and the v1 code.
This is the build contract: where it is silent engineering may choose; where it says "chosen:" the call is made.

## Problem

Nikos is 58, a retired mechanic outside Thessaloniki, with a kitchen laptop and a phone in his jacket. He reads
Greek; English he guesses at, and guessing on a screen that can send things is how he sent a heart by accident.
He trusts three things he has used for twenty years: a window with a title bar, a list of files with names and
dates, and a media player with a play button and a bar. He wants his daughter's posts, in order, big enough to
see, and to be told when he is finished.

v1 is shaped like a phone app: a tray of avatar rings, a card stack that appends forever behind a sentinel, a
link strip for navigation, four stat cards for a home screen, a bare heart in the row header. Each was rejected
by the PO by name — the ring is a deadline, the sentinel is "a rope with no end", the heart is the accident, the
cards are a shop window. A CSS reskin cannot reach any of them: the fault is the shape, not the paint.

"A program from 2000" is a position, not a costume: **the screen does not change unless he changes it** (no
autoplay, no auto-advance, no infinite append); **every control says what it does, in Greek, in words** (no
icon-only buttons, no grey 11px labels); **every screen has an edge he can reach** (a page number, an end
block, a close box, a way back). The bevels exist to make those three rules legible, not to be nostalgic.

The contract a reskin may not break: the feed is finite and says so; resume is server-side and opens at the
first unseen post behind "4 νέα από την τελευταία φορά"; story progress is independent per account with no
auto-jump; "Το είδα" marks seen and no countdown exists; the viewer always shows the person, "2 από 5", and a
way to any other person; stickers stay readable without leaving the picture; mute survives segments and
reloads; no writes to Instagram; one container, vanilla ES modules, no build step, no new dependencies.

## Technical Plan

### The shell

One window, always. At ≤700px wide it fills the viewport (the phone *is* the program); above that it is a
1200×760 window centred on a `#008080` desktop. No route paints its own chrome: `shell.js` paints the frame
once, the content area swaps.

| viewport | window | title bar | menu bar | content | status bar |
|---|---|---|---|---|---|
| 390×844 | viewport, 2px border | 26 | 44 | 742 | 28 |
| 844×390 | viewport, 2px border | 22 | 28 | 314 | 22 |
| 1280×800 | 1200×760, centred | 30 | 28 | 668 | 30 |

`box-sizing:border-box` including the 2px frame; content heights are exact remainders (840−98, 386−72, 756−88).
Chrome is a fixed grid and never scrolls; the content area owns the only scrollbar.

**Title bar** — `#000080`, white bold 12px. Left: `00sgram — τα νέα`, ellipsised. Right: three 18×16px
raised boxes, 1px gap, 2px from the edge — minimise, maximise, close; glyphs are inline SVG 8×8, 1px stroke.
Minimise collapses the window to title + status bar over the desktop, restoring on a title-bar click. Maximise
toggles to the full desktop, **disabled at ≤700px** ("Το παράθυρο είναι ήδη όλο η οθόνη."). Close goes to the program's
home (`#/feed`) from any route, and at home it is `aria-disabled` with the status bar's
"Είσαι ήδη στην αρχή." — a close box that cannot close the tab is a lie.

**Menu bar** — `#c0c0c0`, 1px `#808080` bottom rule, three 12px text buttons. Opens on click and stays
until an item, Esc or an outside click; arrows move, Enter activates; items 44px at ≤700px, 22px above. An
unavailable item is **greyed, never hidden**, keeps its place, is `aria-disabled="true"`, and while the menu is
open the status bar prints its reason.

- **Αρχείο** — `Πρόσφατα` (`#/feed` page 1); `Ιστορίες…` (`#/stories`); `Άνθρωποι…` (`#/accounts`);
  `Αρχείο αναρτήσεων…` (`#/history`, disabled with "Δεν υπάρχει αποθηκευμένο αρχείο." when status
  reports none); `Ρυθμίσεις…` (`#/settings`); `Έξοδος` (`POST /logout` → `#/login`, disabled with "Δεν
  είσαι συνδεδεμένος.").
- **Προβολή** — `Ανανέωση` (re-fetch the screen, keep position); `Προηγούμενη σελίδα` / `Επόμενη
  σελίδα` (same actions as the list footer; disabled at the ends with "Είναι η πρώτη σελίδα." / "Είναι
  η τελευταία σελίδα.", and on pageless screens with "Αυτή η οθόνη δεν έχει σελίδες."); `Στην αρχή`
  (scroll content to 0, disabled when already there).
- **Βοήθεια** — `Πώς δουλεύει` (`#/help`, static Greek, no API); `Κατάσταση σύνδεσης` (`#/sync`);
  `Σχετικά με το 00sgram` (`#/about`: version, "Δεν στέλνει τίποτα στο Instagram.").

**Content area** — 8px padding, one screen at a time, `overflow-y:auto`, `overscroll-behavior:contain`,
never horizontal. A screen is a 24px title row (`h1` at 15px bold, not a display heading) plus a body.

**Status bar** — three sunken 1px cells: message (1fr, ellipsised, `aria-live="polite"`), page and connection
(auto, hidden <701px — the list footer states the page). One line, Greek, set only by `H.status()`; nothing else
in the app may speak unprompted.

### Bulletin (`#/feed`)

A paged list of files, newest first. Rows are `<li class="post">` inside `<ul class="files">` — the class is
load-bearing: `watchVisibility` in `app.js` marks `.post` seen and toggles `is-seen`.

Row anatomy at 390px — 370 content, minus 2px list border and 8px row padding = 360 in the row:
`grid-template-columns:12px minmax(0,1fr) 84px 46px; column-gap:8px` (12 + 8 + 194 + 8 + 84 + 8 + 46 = 360),
`height:56px`, `padding:0 4px`, `border-bottom:1px solid #a0a0a0`, `min-height:44px`.

- Cell 1, 12px: the seen marker, an 8×8px square. Unseen — filled `#000080`, name bold; seen — 1px
  `#808080` outline, name regular. Never red, never a shape that fills.
- Cell 2: line 1 the author display name, 15px, ellipsised with the full text in `title` and the row's
  `aria-label`; line 2 at 13px `#404040` — the caption's first ~40 characters, or `Βίντεο · 0:41`, or `3
  φωτογραφίες`.
- Cell 3, 84px: date, 13px `tabular-nums`, `Intl.DateTimeFormat("el-GR")` — `14 Νοε 21:14`; `χθες 21:14` for
  the last two days.
- Cell 4, 46px: the kind as a word — `Βίντεο` or `Φωτό`. A triangle is an icon and an icon is a guess; a play
  button belongs on the film, not the row.

A 24px column-header row (`Όνομα` · `Πότε` · `Τύπος`, aligned to cells 2–4, 12px `#404040`) sits under the
screen title and scrolls away with the list.

**The divider.** Above the first unseen post — the post named by the session's `around_pk` /
`last_rendered_pk` on resume — a 32px row with a 1px `#808080` rule through it and a centred `4 νέα από την
τελευταία φορά`. It is the scroll anchor, not the post: he sees the line first and the post under it. Nothing
unseen, no divider, list opens at page 1.

**Paging.** Ten rows per page. A 32px footer holds `Σελίδα 1 από 2` centred between `Προηγούμενη` and
`Επόμενη` (44px, disabled per the menu rules). Total pages come from `consumed + remaining_in_session` in
`/api/feed` — chosen: no new endpoint; an unknown count prints `Σελίδα 1` rather than guessing. Back-paging
reuses cursors already in `state.feed`, so a page is never fetched twice. **No sentinel and no scroll-to-load
here**: this list cannot grow by itself.

**The end block** replaces the footer on the last page: sunken panel, 8px padding, 1px `#808080` inset
border, `Αυτά είναι όλα.` (15px bold), `12 αναρτήσεις, από τις 9 Νοεμβρίου.` (13px), then `Πάνω` and
`Παλαιότερα…` at 44px. Terminal: after it renders the screen issues no request, and reloading at the end shows
the same block.

**Older history is opt-in by one press.** `Παλαιότερα…` appends a second paged list headed `Από το
αρχείο`, reading `/api/older` with the existing `cursor`/`limit`, ending in `Τέλος αρχείου.` or `Δεν υπάρχουν
παλαιότερα αποθηκευμένα.`.

**Empty and conflict states.** Nothing unseen: the end block *is* the page — `Τίποτα καινούργιο από την
Τρίτη.` + `Τελευταίος έλεγχος: χθες 21:14.` + `Έλεγχος τώρα` (`POST /api/sync`). No session: `#/feed` starts one
once (chosen: entering the bulletin is the act); on `session_conflict` the same panel reads `Υπάρχει ανοιχτή
συνεδρία αλλού.` with `Συνέχισε εδώ` (`take_over`) and `Άφησέ την`. Fetch failed: `Δεν φόρτωσε.` + `Δοκιμή
ξανά`.

### Player (one component, two modes)

A full-content child window with its own title bar (`Αναπαραγωγή — Μαρία`, close box), used for a post opened
from the bulletin and for a story segment. Same root and the same `stories-viewer` class (pinned by
`test_ui.py`, and it carries `touch-action:none`, `overscroll-behavior:none`, `100dvh`); the mode is
`data-mode="post" | "story"`.

Geometry — portrait (390): child title 24, header 44, black stage flexible, transport 72 (seek 24 + buttons 48),
details toggle 44 → stage 558 (a photo has no transport, so its stage is 630). Landscape (844×390): child title 20,
header 44 — **corrected from 40**: a 44px `Κλείσιμο` cannot live in a 40px bar, and the 44px touch target outranks
the 4px — transport 44, permanent 200px playlist column on the left → stage 206. The playlist and the details panel
join or replace the stage; nothing overlays the picture except the stickers panel.

**Reused by name, no second implementation:**

- `openViewer(rings, start, onDone)` — root markup, focus, the pushed history entry and `popstate`,
  `loadAccount` / `coldFetch` and its 500ms/10s poll stay as they are. It gains a fourth argument
  `opts = {mode}`; `rings` is the people list in story mode and the page's posts in post mode.
- `paintSegment()` — one segment, or one resource of a post in post mode (no seen marking); same
  fallback element, `story-ph`. A post with more than one resource is an **album**: the nav row
  (`[data-nav]`) appears with `Προηγούμενο / φωτό 2 από 6 / Επόμενο`, and the two buttons step
  through the pictures before they leave the post for its neighbour. `paintTray()` names the size
  (`12 Νοε 18:38 · 6 φωτογραφίες`), so the bulletin row and the player never disagree.
- `paintVideo(seg, ph)` — the transport: same `<video>`, `data-seek` range, `data-act="mute"`, `mm:ss /
  mm:ss` in `tabular-nums`, `rememberMute()`. Relabelled in words: `−10 δευτ.`, `Αναπαραγωγή` /
  `Παύση`, `+10 δευτ.`, `Ήχος κλειστός` / `Άνοιξε τον ήχο`. A film waits; nothing autoplays.
- `paintTray()` — the playlist. Story mode: one 44px row per person, name + `είδες 2 από 5`, current row
  `#000080` on white. Post mode: one row per post on the current page, name + time. A press loads it and
  returns to the stage.
- `paintLinks()` — the stickers panel, `Τι έχει πάνω της`, grouped `Πρόσωπα / Μουσική / Σύνδεσμοι /
  Ετικέτες / Μέρη`. One change: the label is plain selectable text, and where a URL exists a separate
  44px `Άνοιγμα` button carries it, so nothing opens because a row was read.
- `advance(dir)` — movement inside one account, never across.
- `completeAccount()` — the end card: `Τέλος των ιστοριών της Μαρίας.` / `3 από 3.` / `Επόμενη: Κώστας
  (2)` as a **button**, `Κλείσιμο`, and the remaining people with counts. `autoAdvance()` is deleted and
  always false.

**Stage** — `#000` fill, media `object-fit:contain`, `max-width/height:100%`. Portrait images are full
content width. A tap on the picture does nothing (deleted: v1's tap-to-toggle and the 40px account swipe);
movement is buttons only.

**Header** (44px) — name, `2 από 5` in tabular numerals, `Λίστα` (toggles the playlist; hidden at ≥700px
where it is permanent) and `✕ Κλείσιμο` (44px, back to the list at the row he left). Account arrows are gone:
accounts are chosen from the playlist, deliberately.

**Details panel** — a 44px `Στοιχεία` row under the transport; open, it is a sunken panel, max-height
40%, scrolling, and the one place in the app that can write anything. Post mode: the caption (16px,
selectable, never clamped), `Τραβήχτηκε 14 Νοεμβρίου, 21:14.`, `Άνοιγμα στο Instagram` as its own button, and
the **like checkbox** `Μου αρέσει` (44px hit, no count, `POST`/`DELETE /api/posts/{pk}/like`, self-reverting
with a status-bar message). Story mode: the segment time, the `Αντιδράσεις` disclosure, and the stickers
reachable with this panel shut.

**Αντιδράσεις** is one 44px disclosure. Closed, the emoji row is not in the DOM. Open, five 44px buttons
appear; a press swaps them for `Σίγουρα; Θα σταλεί στη Μαρία.` + `Ναι, στείλ' το` / `Άκυρο`. Already reacted:
`Αντέδρασες` as text.

### People, Archive, Setup

Secondary and cheap: same frame, same list idiom, no new components.

- **People** (`#/accounts`) — `<ul class="acc">` rows, 56px: name, `νέες αναρτήσεις: 2`, `νέες ιστορίες:
  2 από 5`, marker as on the bulletin. Two actions: `Δες τις ιστορίες` (into the player at that person,
  reusing `storyJump`) and `Σίγα` / `Άνοιξε τον ήχο`. `finish-lock` stays, relabelled `Κλείσε εκείνη τη
  συνεδρία`.
- **Archive** (`#/history`) — the same paged list, tabs `Αναρτήσεις` / `Ιστορίες`, each row `Άνοιγμα` and
  `Σημείωση ως αδιάβαστο` (existing `/unsee`). No append.
- **Setup** (`#/settings`, `#/sync`) — a property sheet with four tabs: `Τύποι`, `Συγχρονισμός`,
  `Λογαριασμός` (session cookie, `Αποσύνδεση`), `Χώρος` (storage, backups, last sync).
  `story_auto_advance_accounts` is removed from the form and the setting is ignored: it contradicts the
  contract. This is the owner's maintenance dialog, not a preference screen; Nikos never needs it
  (chosen).

### Network down / provider busy

Every screen renders what the server already has and says so once; no spinner stands in for content.

| screen | provider busy / frozen | network down |
|---|---|---|
| Bulletin | rows render; `Ο συγχρονισμός είναι σταματημένος μέχρι τις 18:30.` | `Δεν υπάρχει σύνδεση. Δείχνω ό,τι είχα.`; page nav works from cache |
| Player | cached segments play; a cold fetch shows `Δεν κατέβηκε. Δοκιμή ξανά;` | `Η εικόνα δεν κατέβηκε.` / `Το βίντεο δεν άνοιξε.`; transport stays |
| People | list renders, counts are last known and dated | `Δεν υπάρχει σύνδεση. Δείχνω ό,τι είχα.` |
| Archive | paged reads still work | rows render; `Δεν φόρτωσε.` replaces the footer |
| Setup | status shows the error verbatim (`Ο συγχρονισμός απέτυχε.`) | `Δεν υπάρχει σύνδεση.`; actions disabled with reasons |

The two unprompted messages S9 allows — no connection, sync failed — appear once per session, in the status bar,
never modal.

### Visual spec

```css
--desktop:#008080; --face:#c0c0c0; --face-hi:#dfdfdf; --hi:#ffffff;
--lo:#808080; --dark:#404040; --line:#a0a0a0; --field:#ffffff;
--title:#000080; --text:#000000; --muted:#404040; --disabled:#808080;
--sel:#000080; --sel-text:#ffffff; --link:#0000ee; --ok:#006000; --danger:#a40000;
```

Raised: `border:1px solid; border-color:#fff #404040 #404040 #fff; box-shadow:inset -1px -1px 0
#808080, inset 1px 1px 0 #dfdfdf`. Sunken (fields, list body, status cells, end block): the reverse
pair, `#808080 #fff #fff #808080` with `inset 1px 1px 0 #404040, inset -1px -1px 0 #dfdfdf`. Selected: `#000080`
background, `#fff` text. Radius 0 everywhere. Spacing unit 4px — every margin and padding is a multiple of it.
Type stack: `Tahoma, Verdana, "DejaVu Sans", "Noto Sans", Roboto, "Segoe UI", sans-serif`; chrome 12px, list and
body 15px, captions 16px, `line-height:1.35`, tabular numerals on every changing number. One appearance: the
`prefers-color-scheme` block and both dark tokens are deleted.

**Pressed** — bevel flips to sunken, label moves 1px right and 1px down, no transition. **Disabled** —
face background, `#808080` text with a 1px `#fff` text-shadow bottom-right, cursor default, no hover change.
**Focus** — `outline:1px dotted #000; outline-offset:-3px` on `:focus-visible`, plus a 3px `#000080` left bar on
the focused row.

Do not: gradients on text or chrome; `border-radius` over 4px; emoji as icons (glyphs are inline SVG; emoji
appear only as reaction *content*); animation longer than 120ms; drop shadows, glow, blur, translucency; hover
colour on list rows (a 2000 list selects, it does not highlight).

### Copy deck

One word per action everywhere. Data — names, captions, places, handles — is never translated.

| Ελληνικά | English | Where |
|---|---|---|
| `00sgram — τα νέα` | 00sgram — the news | title bar |
| `Αρχείο` `Προβολή` `Βοήθεια` | File · View · Help | menu bar |
| `Πρόσφατα` `Ιστορίες…` `Άνθρωποι…` `Αρχείο αναρτήσεων…` `Ρυθμίσεις…` `Έξοδος` | Recent, Stories, People, Post archive, Settings, Log out | Αρχείο |
| `Ανανέωση` `Προηγούμενη σελίδα` `Επόμενη σελίδα` `Στην αρχή` | Refresh, Previous page, Next page, To the top | Προβολή |
| `Πώς δουλεύει` `Κατάσταση σύνδεσης` `Σχετικά με το 00sgram` | How it works, Connection status, About | Βοήθεια |
| `Έτοιμο` `Συνδέομαι…` `Συνδέθηκα.` `Συνδέθηκα — 6 νέα` `Ο συγχρονισμός είναι σταματημένος μέχρι τις 18:30.` `Δεν υπάρχει σύνδεση.` | Ready, Connecting…, Connected (refresh), Connected — 6 new, sync stopped until 18:30, no connection | status bar |
| `Δεν υπάρχει σύνδεση. Δείχνω ό,τι είχα.` `Ο συγχρονισμός απέτυχε. Δείχνω το τελευταίο καλό αντίγραφο.` | No connection / sync failed; showing what I had / the last good copy | status bar, once each |
| `Όνομα` `Πότε` `Τύπος` `Βίντεο` `Φωτό` `3 φωτογραφίες` `0:41` `νέο` `διαβασμένο` | Name, When, Kind, Video, Photo, 3 photos, 0:41, new, read | column heads, rows |
| `4 νέα από την τελευταία φορά` `Σελίδα 1 από 2` `Προηγούμενη` `Επόμενη` | 4 new since last time, page 1 of 2, previous, next | divider, list footer |
| `Αυτά είναι όλα.` `12 αναρτήσεις, από τις 9 Νοεμβρίου.` | That's all. 12 posts, from 9 November. | end block |
| `Πάνω` `Παλαιότερα…` `Από το αρχείο` `Τέλος αρχείου.` | Up, Older…, From the archive, End of archive. | end block, older list |
| `Τίποτα καινούργιο από την Τρίτη.` `Τελευταίος έλεγχος: χθες 21:14.` `Έλεγχος τώρα` | Nothing new since Tuesday. Last check: yesterday 21:14. Check now | empty state |
| `Το πρόγραμμα είναι ανοιχτό σε άλλη συσκευή.` `Συνέχισε εδώ` `Άφησέ την` | The program is open on another device. Continue here, Leave it | conflict |
| `Δεν φόρτωσε.` `Δεν υπάρχει σύνδεση.` `Δοκιμή ξανά` | It didn't load / no connection. Try again | every failed fetch, one action |
| `Αναπαραγωγή` `Παύση` `−10 δευτ.` `+10 δευτ.` `Ήχος κλειστός` `Ήχος ανοιχτός` `0:12 / 1:40` `Λίστα` `Στοιχεία` | Play, Pause, −10 s, +10 s, sound off/on, 0:12 / 1:40, List, Details | transport, player |
| `Κλείσιμο` `2 από 5` `είδες 2 από 5` `Το είδα` `Προηγούμενο` `Επόμενο` | Close, 2 of 5, you saw 2 of 5, I saw it, Previous, Next | player, story controls |
| `Τέλος των ιστοριών της Μαρίας.` `3 από 3.` `Επόμενη: Κώστας (2)` | End of Maria's stories. 3 of 3. Next: Kostas (2) | end card |
| `Τι έχει πάνω της` `δεν έχει πάνω της τίποτα` `Πρόσωπα` `Μουσική` `Σύνδεσμοι` `Ετικέτες` `Μέρη` `Άνοιγμα` | What's on it, nothing on it, People, Music, Links, Tags, Places, Open | stickers |
| `Μου αρέσει` `Σου αρέσει.` `Σημειώθηκε.` `Σίγουρα; Θα αρέσει στη Μαρία.` `Αντιδράσεις` `Αντέδρασες` `Σίγουρα; Θα σταλεί στη Μαρία.` `Ναι, στείλ' το` `Άκυρο` | Like, it's liked, marked, Are you sure? Maria will like it. Reactions, You reacted, Are you sure? It goes to Maria. Yes, send it. Cancel | details panel |
| `Τραβήχτηκε 14 Νοεμβρίου, 21:14.` `Άνοιγμα στο Instagram` `Η εικόνα δεν κατέβηκε.` `Το βίντεο δεν άνοιξε.` `Αυτή η ιστορία έληξε.` | Taken 14 November, 21:14. Open on Instagram. The picture didn't download. The video didn't open. This story expired. | post details, stickers, media fallback |
| `νέες αναρτήσεις: 2` `νέες ιστορίες: 2 από 5` `δεν έχει ιστορίες` `Νέα` `Δες τις ιστορίες` `Σίγα` `Άνοιξε τον ήχο` | new posts, new stories, no stories, new, see the stories, mute, open the sound | People |
| `Αναρτήσεις` `Ιστορίες` `Σημείωση ως αδιάβαστο` `Σημειώθηκε ως αδιάβαστο.` `Κλείσε εκείνη τη συνεδρία` | Posts, Stories, Mark unread, Marked unread, Finish that session | Archive |
| `Τύποι` `Συγχρονισμός` `Λογαριασμός` `Χώρος` `Αποθήκευση` `Αποσύνδεση` | Types, Sync, Account, Space, Save, Log out | Setup |
| `Το 00sgram δείχνει τι ανέβασαν οι άνθρωποι που ακολουθείς, με τη σειρά. Δεν στέλνει τίποτα στο Instagram.` | 00sgram shows what the people you follow posted, in order. It sends nothing to Instagram. | About |

### Migration

**Kept, because tests or behaviour depend on it:** the `#topbar` id and its `[hidden]` rule (the player still
hides the chrome through it), `.post` as the row class plus `is-seen` (that is what `watchVisibility` /
`flushSeen` / `bumpRemaining` act on), `updateProgress`, `renderEnd`, `around_pk`, `last_rendered_pk`,
`stories-viewer` on the player root, `story-ph`, `data-seek`, `data-act="mute"`, `storiesViewer`, `storyJump`,
`/api/history/stories`, `/api/sync/runs`, `session_filters_locked`, `finish-lock`, `.acc li`, `.hist > li`,
`min-height:44px`, `.media .fallback[hidden]`, `touch-action:none`, `overscroll-behavior:none`, `100dvh`,
`history.scrollRestoration = "manual"`.

**Deleted from v1, by name:** the ring tray (`.ring`, `.ringbar`, the unseen ring box-shadow) and its "1
segment · not opened" copy; the carousel overlay (`.carousel`, `data-car`) and `.dots`; the row-header like
(`data-act="like"` in `.post header`) and `toggleLike`'s glyph painting; `watchPlayback`'s autoplay observer and
`playRememberingSound`'s autoplay path (videos exist only in the player and only play on a press);
`story_auto_advance_accounts` and `autoAdvance()`; the 40px account swipe and tap-to-toggle on the stage; the
bulletin's sentinel and its `rootMargin` append loop; `.toast` as an unprompted bottom overlay (status bar
instead); the dashboard and its four stat cards (`#/` redirects to `#/feed`); the dark theme; the `onclick` at
`views.js:353`; the row's "open" word-button and its `<details>` summary.

**Like control, recorded honestly.** Brief constraint 1 says no writes to Instagram; v1 ships a like, the
owner asked for it, and the orchestrator's binding answer keeps it. It is the single write path in the UI, it
lives in the details panel, labelled `Μου αρέσει`, never on a row, never a bare heart, never counted, and
`test_ui.py` gains an assertion that no `.post` row contains `[data-act="like"]`.

**`tests/test_ui.py`** (one commit, before visual work): `Start a new session` → `Νέα συνεδρία`; new markers
`#statusbar`, `.files`, `--face: #c0c0c0`, `data-mode="post"`, `Σελίδα`; `assert "onclick" not in views_js`; and
the like-not-in-a-row enumeration. Nothing else in the file changes — the kept list above is the checklist.

### Wireframes

```
bulletin 390x844                     player 390x844 (portrait)
┌──────────────────────────────┐     ┌──────────────────────────────┐
│ 00sgram — τα νέα    _ □ ✕    │ 26  │ 00sgram — τα νέα    _ □ ✕    │ 26
├──────────────────────────────┤     ├──────────────────────────────┤
│ Αρχείο Προβολή Βοήθεια       │ 44  │ Αρχείο Προβολή Βοήθεια       │ 44
├──────────────────────────────┤     ├──────────────────────────────┤
│ Όνομα      Πότε       Τύπος  │ 24  │ ┌ Αναπαραγωγή — Μαρία    ✕ ┐ │ 24
│ ▪ Μαρία  14 Νοε 21:14 Βίντεο │ 56  │  Μαρία · χθες 21:14  [Λίστα] │ 44
│   Βίντεο · 0:41 · νέο        │     │ ┌──────────────────────────┐ │
│ □ Κώστας 14 Νοε 18:02 Φωτό   │ 56  │ │       ( picture )        │ │558
├──────────────────────────────┤     │ │                          │ │
│ ── 4 νέα από την τελευταία ──│ 32  │ └──────────────────────────┘ │
│ ▪ Μαρία  12 Νοε 20:11 Βίντεο │ 56  │ ▓▓▓▓▓░░░░░░░░░░ 0:12 / 1:40 │ 24
│ □ Ελένη  12 Νοε 07:05 Φωτό   │ 56  │ [−10 δ][Αναπαραγωγή][+10 δ]  │ 48
│        … rows 3–10 …         │     │ [ Ήχος κλειστός ]            │
│ ┌──────────────────────────┐ │     │ Στοιχεία ▾                   │ 44
│ │ Αυτά είναι όλα.          │ │ 96  └──────────────────────────────┘
│ │ 12 αναρτήσεις, από τις 9 │ │
│ │ Νοεμβρίου.               │ │     player 844x390 (landscape)
│ │ [Πάνω] [Παλαιότερα…]     │ │     ┌──────────────────────────────────────────────────┐
│ └──────────────────────────┘ │     │ 00sgram — τα νέα                      _ □ ✕      │ 22
├──────────────────────────────┤ 28  ├──────────────────────────────────────────────────┤
│ Έτοιμο                       │     │ Αρχείο Προβολή Βοήθεια                           │ 28
└──────────────────────────────┘     ├──────────────────────────────────────────────────┤
                                     │ ┌ Αναπαραγωγή — Μαρία                       ✕ ┐ │ 20
bulletin 1280x800 (content area)     │ │ Μαρία · χθες 21:14                          │ 40
┌──────────────────────────────────┐ │ ├─────────────┬────────────────────────────────┤
│ 00sgram — τα νέα      _ □ ✕      │ │ │ Μαρία  2/5  │      ( picture )               │
├──────────────────────────────────┤ │ │ Κώστας 2/2  │                                │
│ Αρχείο Προβολή Βοήθεια           │ │ │ Ελένη  1/3  │ ▓▓▓▓░ 0:12/1:40 [▶][−10][+10]  │ 44
├──────────────────────────────────┤ │ └─────────────┴────────────────────────────────┘
│ Όνομα          Πότε       Τύπος  │ │ ├──────────────────────────────────────────────────┤
│ ▪ Μαρία      14 Νοε 21:14 Βίντεο │ │ │ Έτοιμο                                           │ 22
│ □ Κώστας     14 Νοε 18:02 Φωτό   │ │ └──────────────────────────────────────────────────┘
├──────────────────────────────────┤ │
│ Αυτά είναι όλα. [Πάνω][Παλαιότερα…]│
├──────────────────────────────────┤ │
│ Έτοιμο          Σελίδα 1 από 2   │ │
└──────────────────────────────────┘ │
```

## Alternatives

**(a) A pure CSS reskin of v1's layout** — keep the card feed, the tray, the link strip, the row-header like;
restyle them grey with bevels. Rejected: it leaves every failure the PO described intact. Bevels add no page
number, no divider, no end block, no `Το είδα`, and a grey skin on a sentinel is still a rope with no end — and
it passes the existing tests, which is the trap. Right for a retro screenshot, or if the DOM were list-shaped.

**(b) A full Winamp-style skinnable player** — theme files under `app/static/skins/`, a picker, per-skin
palettes and fonts. Rejected: no build step or asset pipeline, CSP forbids remote assets, no new dependencies,
a skin is a second language (one appearance, by PO decision), and skins make the chrome unreadable at 390px,
where the transport is already four 44px buttons. Right with a real static-asset pipeline — the palette
variables above are the seam.

**(c) The phone's native `<video controls>`** — rejected: Android's overlay is −15s / play / +15s sitting on
the picture forever (the reason v1 wrote its own strip), labels arrive in the device language, there is no
`mm:ss / mm:ss`, no remembered mute, and iOS adds a fullscreen escape. Right if the transport must be free and
platform-localised — which never happens on Android.

**(d) Keep the avatar-ring tray instead of a playlist** — fits v1, the code exists. Rejected: the ring is the
first thing the PO named ("a horseshoe filling means I'm late"), it encodes progress as a shape instead of words,
and it has no room for `είδες 2 από 5`. A playlist row is a line of text with a name and a count — the bulletin's
idiom. Right if the tray had to fit above a feed in 60px, which is the situation this version leaves.

**(f) Whole screen: the Fullscreen API on the player, with a covering fallback** — a 44px drawn glyph
(`[data-act="full"]`, next to `Λίστα` and `Κλείσιμο`) asks the browser for `requestFullscreen()` on the player
root, so the picture fills the display and the transport and the nav stay usable. Rejected: fullscreening the
`<video>` alone (native chrome, no transport for photos), and a second fullscreen view (a second player to keep
in sync). Where the API is missing or refuses — older iOS Safari, some WebKit builds — the same button adds
`.is-max` to the root: `position: fixed; inset: 0`, and `html.is-max` stops the page behind from scrolling. So
the button never hides itself and never fails; only the browser's own address bar remains, which CSS cannot
take away.

**(e) Tabs instead of a menu bar** (`Πρόσφατα | Ιστορίες | Άνθρωποι | Αρχείο`) — rejected: a tab strip is the
touch idiom, it costs 44px of every screen at 390×844, and it cannot show a greyed action with a reason; a menu
can. Right if the program grows past six screens — then the menu grows submenus, not tabs.

## Detailed Implementation

Frontend only. No new endpoints: paging uses `/api/feed`'s `cursor` and `remaining_in_session`, older history
uses `/api/older`, the player uses `/api/posts/{pk}`, `/api/stories`, `/api/stories/{pk}` and the existing
`seen`/`react`/`done`/`fetch` verbs, Setup uses `/api/settings` and `/api/status`. One new file:
`app/static/shell.js`. Steps 4–13 all touch `app/static/views.js`; where a step also touches `app.js` or
`index.html` it says so. Each step is one commit with the check named.

1. **Tests first.** `tests/test_ui.py`: `Start a new session` → `Νέα συνεδρία`, new markers, `assert "onclick"
   not in views_js`. Run `pytest tests/test_ui.py -q` — fails on the new markers, which is the point.
2. **`shell.js` + frame.** Strings table, `paintShell()`, menu open/close/activate, `status()` / `page()` cells;
   `index.html` gets `lang="el"` and the title/menu/status markup inside `#topbar`; `app.js` imports it and
   passes `str`/`status` through `init()`. Observable: every route renders inside the frame at all three viewports.
3. **`style.css` foundation.** Tokens, bevel utilities, chrome heights, pressed/disabled/focus rules;
   delete the dark theme and the `#topbar` nav rules. Observable: chrome heights match the table at
   390×844, 844×390, 1280×800 and `#topbar[hidden]` still hides it.
4. **Bulletin as a list.** Rewrite `feed()`: `<ul class="files">`, 56px rows, column heads, `.post`
   retained, `is-seen` still toggles, dates via a new `H.elWhen`. Observable: ten rows, zero media
   elements in the DOM (so no autoplay by construction), no sentinel, no `data-car`.
5. **Paging + status.** Ten per page, `Σελίδα n από m` footer, cursor cache, `updateProgress` writes the
   status bar. Observable: twelve posts → two pages, `Επόμενη` disabled on the last, Back leaves the
   screen intact.
6. **Divider, end block, older opt-in.** `renderEnd` restyled into the terminal panel, `around_pk` scrolls
   the divider into view, `Παλαιότερα…` mounts the older paged list beneath. Observable: resume opens at
   the divider; reload at the end shows the same block and issues no request.
7. **Player opens from a row.** Row click → `#/post/{pk}`; `post(pk)` renders `openViewer(…,
   {mode:"post"})` instead of the v1 single-post page. Observable: one press opens a full-window picture;
   `Κλείσιμο` / Esc return to the same row, no reload.
8. **Player shell and transport.** Child title bar, header, playlist, stage, relabelled `paintVideo`, details
   toggle; delete the swipe, the tap-to-play and the autoplay path. Observable: exactly one play control per
   video and none on a photo, `0:12 / 1:40`, mute remembered across reload, `data-seek` still present.
9. **Story mode.** `paintTray` as people rows with `είδες n από m`, the end card with all counts,
   `autoAdvance()` deleted. Observable: a 60s idle test changes nothing; the last segment leads to the
   card, not to Kostas's first.
10. **Details panel.** Caption, date, external link, like checkbox, `Αντιδράσεις` disclosure with confirm.
    Observable: no row contains `[data-act="like"]`; emoji buttons are absent until the disclosure opens;
    no request until `Ναι, στείλ' το`.
11. **Stickers panel.** `paintLinks` labels as text, `Άνοιγμα` carries the href, panel reachable with
    details shut. Observable: a URL is readable and does not open by being read.
12. **Secondary screens.** People, Archive, Setup onto the list and property-sheet idiom, Greek strings,
    auto-advance field removed. Observable: every string on those routes appears in the copy deck.
13. **Delete.** Dashboard, `#/` redirect, `#/help`, `#/about`, login as a small window, `.toast` → status
    bar. Observable: no route renders a stat card; `#/` lands on the bulletin.
14. **Full pass.** `pytest -q` (138 + new), then the manual matrix — 390×844, 844×390, 1280×800, every
    route, network removed and sync paused.

**Risks.**

1. **Layout at short viewports** — the player's fixed rows are 104 of 314px at 844×390; one added row crushes
   the stage. Check: the manual 844×390 pass with playlist *and* details open, plus a CSS assertion that the
   player uses `grid-template-rows:auto auto minmax(0,1fr) auto`, so the stage is the only flexible row.
2. **CSP** — inline handlers, inline `<style>`, `javascript:` hrefs and remote fonts fail silently. Check:
   `assert "onclick" not in views_js` and `assert "<script>" not in index`, plus a console pass with zero CSP
   violations on each route.
3. **Tests pinning markup** — `test_ui.py` asserts literals in `views.js` and `style.css`, so renaming a class
   breaks a test that looks unrelated. Check: `pytest tests/test_ui.py -q` in every CSS/JS commit (step 1 makes
   the new set the contract), with the kept list in Migration as the checklist.
