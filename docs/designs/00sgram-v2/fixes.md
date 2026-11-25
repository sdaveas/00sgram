# 00sgram v2 — fix list after the review stage

Merged from `review-ui.md`, `review-ux.md`, `review-qa.md`. Ordered by what must
land before ship. Each item names the file and the check that proves it.

## Blockers

**F1. The player's picture is a thumbnail (390×844) and a sliver at 1280.**
`style.css:285` `grid-template-rows` uses `auto` for the tray, so the tray takes
442px on mount even though `Λίστα` says collapsed; `.stray{max-height:40%}`
shrinks the element but not the track; `.sstage{overflow:hidden}` plus
`max-height:100%` never resolves, so a 386×686 video paints over its own seek
bar and clock. Measured: stage 116px vs spec 558.
Fix: the tray track is `minmax(0,0)` when `[data-tray][hidden]` and
`minmax(0,40%)` when open, at ≤700; hide the tray on mount at ≤700 (the `Λίστα`
button is the only way in); give `.sstage` a definite height (`min-height:0`,
`height:100%` on the media) so `object-fit:contain` resolves.
Check: at 390×844 the stage is 558±2, the video's painted box never overlaps
`[data-seek]`, and at 1280×800 the stage is 528±2 with the 720×1280 clip
letterboxed inside it.

**F2. Every story row says `Φορτώνω…` forever.** `/api/stories` returns
`known:false` for 36 rings; `ringSaw()` returns null and the fallback is the
loading word (`views.js:511`, `:658`). A loading word for a state that will not
resolve reads as a broken download.
Fix: `known:false` prints a settled word (new `STR.unseenRing`: `Νέα`, no
ellipsis). The loading word stays for the fetch in flight only.
Check: `#/stories` after 3s idle shows no `Φορτώνω`; every row matches
`/^(Νέα|είδες \d+ από \d+)$/`.

**F3. The like is one tap with no confirm.** `Στοιχεία` ends in a 368×44
`Μου αρέσει` checkbox that PATCHes on change (`views.js:678-681`). It is the
last one-tap write to another person, and the reaction panel already solved this
problem better.
Decision: the like borrows the reaction pattern — pressing it swaps the row for
`Σίγουρα; Θα αρέσει στη {name}.` + `Ναι, στείλ' το` / `Άκυρο`; no request before
the confirm. Same shape, same strings, one implementation.
Check: no `change` handler on `[data-act="like"]`; zero `/like` requests until
the confirm is pressed (stubbed `H.api` in `tests/player_check.mjs`).

## Majors

**F4. `Σημερινά` leaves the reader on page 3.** `shell.js:13,265-267` routes to
`/feed` without resetting `state.feed.page` (`views.js:216-224`). Fix: entering
`#/feed` from the menu starts at page 1. Check: from page 3, `Αρχείο → Σημερινά`
lands on `Σελίδα 1 από n`.

**F5. `Ανανέωση` changes nothing and says nothing.** `shell.js:273-279`. Fix:
re-fetch page 1, keep the page if it still exists, and write `Συνδέομαι…` then
`Συνδέθηκα.` in the status cell. Check: two status writes and one `/api/feed`
request, rows re-rendered.

**F6. `Σημείωση ως αδιάβαστο` makes the row vanish.** `views.js:1222` then a
refetch at `:405-419`. Fix: after marking, do not refetch the bulletin; the row
stays where it is with the unseen marker, and the status cell says
`Σημειώθηκε ως αδιάβαστο.`. Check: row count unchanged, marker hollow→filled,
zero `/api/feed` requests.

**F7. The close box is browser Back.** `shell.js:130-131`. Measured: `✕` at
`#/feed` page 3 went to the previous `#/feed`. Fix: `✕` goes to `#/feed` (the
program's home) and, when already on `#/feed`, is `aria-disabled` with reason
`alreadyTop` instead of doing nothing.
Check: from any route, `✕` → `#/feed`; on `#/feed`, the button reports a reason
in the status cell.

**F8. The status bar is a blank box at ≤700.** Both auto cells are
`display:none` and the message cell is empty at rest. Fix: keep `[data-conn]`
visible at ≤700 so the bar always carries one word. Check: `#statusbar` text is
non-empty on every route at 390 wide.

**F9. `Δες τις ιστορίες` is enabled for people with no stories.**
`views.js:1119`, `:1160-1163`. Fix: `disabled` + `data-reason="δεν έχει
ιστορίες"` when no ring with stories exists for that pk. Check: 10/10 sampled
rows with `δεν έχει ιστορίες` carry a disabled action.

**F10. The seek is the operating system's slider.** No bevel, round thumb
(`style.css:336-338`). Fix: `-webkit-appearance:none`, sunken 1px track, square
beveled thumb, 8px tall track inside the 24px row; `data-seek` unchanged.
Check: computed `appearance:none`, thumb radius 0.

**F11. The header has no 44px close.** Only a 61.9×20 box in the child bar
(`views.js:570-577`). Fix: add `Κλείσιμο` to `.shead` at 44px, keep the child
bar box. Check: `[data-act="close"]` in `.shead` measures ≥44×44 at all sizes.

**F12. Story seen-marking is indistinguishable from advancing.** `markSeen`
fires when a segment is painted (`views.js:818`), so `Το είδα` and `Επόμενο` are
the same action. Fix: painting no longer marks; `Το είδα` marks and stays, then
`Επόμενο` advances. Status cell reports `Σημειώθηκε.` on the mark. Check: open a
segment, wait, close — nothing is marked; press `Το είδα` — one PATCH, no
advance.

## Copy (also touches `test_copy.py` and the design's deck)

| key | now | becomes | why |
|---|---|---|---|
| `back10` | `−10 δ` | `−10 δευτ.` | `δ` is nobody's abbreviation |
| `fwd10` | `+10 δ` | `+10 δευτ.` | ditto |
| `unmute` | `Ξαναμίλα` | `Άνοιξε τον ήχο` | "speak again" is about a person |
| `conflict` | `Υπάρχει ανοιχτή συνεδρία αλλού.` | `Το πρόγραμμα είναι ανοιχτό σε άλλη συσκευή.` | συνεδρία is programmer Greek |
| `today` | `Σημερινά` | `Πρόσφατα` | the newest row is not today |
| `kind` | `Είδος` | `Τύπος` | Windows Greek for a file column |
| `alreadyTop` | — | `Είσαι ήδη στην αρχή.` | used by F7, must be in the deck |

**F13. Offline, pressing a bulletin row wipes the bulletin.** `app.js:181` runs
`loadBase()` before the `/post/` branch, so an aborted `/api/**` replaces `#app`
with a banner and the player never opens. Fix: the `/post/` branch must not
require base data — the player fetches its own post. If `#app` is empty (direct
load of `#/post/<pk>`), mount the bulletin shell first, then the player over it.
Check: with `/api/**` aborted, pressing a row still opens the player and
`Κλείσιμο` returns to the rows.

**F14. Failure panels print machine tokens.** A 500 on `/api/settings` prints
`boom` twice; a dead network prints `Load failed` (`app.js:206-211`). Fix: map
the failure to the deck's sentence (`Δεν φόρτωσε.` / `Δεν υπάρχει σύνδεση.`),
never the raw code or the browser's English, and keep exactly one action
(`Δοκιμή ξανά`). Check: with a 500 and with an abort, no panel text matches
`/[A-Za-z]{3,}/` except `Δοκιμή ξανά`'s own Greek.

**F15. Reload at the end of the feed renders page 1.** `views.js:86,216-259`
caps resume at `RESUME_MAX=3` pages, so the end block is unreachable on reload
for any feed longer than three pages, and one `/api/feed` fires. Fix: when the
open session has consumed its whole `item_count`, render the end block straight
away with no `/api/feed`. Check: page to the last page, reload — end block, zero
`/api/feed` requests, `Σελίδα n από n` unchanged.

## Minors

- **M1** Pager and end block both render on the last page; the design says the
  block replaces the footer. Omit the `.pager` row when `last`.
- **M2** Settings tabs are in the wrong order and the wrong one is selected
  (`Τύποι` first, per the design).
- **M3** `#/login` paints unframed and with a 30px display heading. Paint the
  frame, use `.screen` for the `h1`.
- **M4** `Τι έχει πάνω της` is removed when a post has no sticker links. Render
  it `aria-disabled` with `δεν έχει πάνω της τίποτα` instead.
- **M5** `#/history` `Άνοιγμα` is an unboxed link next to a beveled button.
  Give `.hist .row` the raised treatment.
- **M6** The post player prints no `n από m`. Add the playlist position to
  `.shead` in post mode (`3 από 10`), stories already have it.
- **M7** The design's bulletin arithmetic (`12+8+204+…=370`) omits the 2px border
  and 8px padding; the implementation is right. Correct the doc, not the code.
- **M8** An unknown hash renders the bulletin but keeps its own hash (`#/nonsense`).
  `history.replaceState` it to `#/feed`.
- **M9** A paging failure prints one status line and offers no retry control.
  Give the banner the `Δοκιμή ξανά` button the first-page failure already has.
- **M10** The player's chrome at ≥701 uses the landscape numbers: childbar 20,
  header 40, transport 44, stage 564 (spec 24/44/72/528). Gate the landscape
  block on `(min-width:701px) and (max-height:520px)`, as the frame already does.
- **M11** `last_rendered_pk` is written by the client and read by nobody, and the
  comment at `app.js:5` still claims resume lands on it. Fix the comment; keep the
  write (the server uses it).
- **M12** `POST /api/accounts/{pk}/unfollow` is reachable from no UI. Leave it,
  but note in the engineering doc that no view may grow a path to it.

## Accepted, not fixed

- **A1. `Σίγα` and `Κλείσε εκείνη τη συνεδρία` stay one tap.** Both are local
  state, reversed by one press, and reach no other person.
- **A2. Story reactions stay two-step.** Already disclosure → emoji → confirm.
