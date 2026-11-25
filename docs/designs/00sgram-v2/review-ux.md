# 00sgram v2 — UX review (Nikos, 58)

Walked the deployed app at 390×844 and 1280×800 with Playwright/WebKit, login by
`fetch('/login')`, viewing only — no like, no reaction, no follow, no finish-lock.
Persona and contract are fixed; this is execution only.

## Verdict

**pass with fixes — 3 blockers, 10 stops.** The bulletin, the end block, the story
end card and the sticker panel are genuinely his. The player is broken at both
viewports, the stories list never says a number, and one tap still likes.

## Story table

| story | met? | evidence |
|---|---|---|
| S1 order, one at a time | met | `#/feed`: `.files > li.post` = 10, single column, grid `12px 1fr 84px 46px`, no h-scroll at 390/1280; DOM author order = `/api/feed` order; `aria-label="nevecat, 13 Νοε 16:11, Βίντεο"` matches the visible cells |
| S2 picture big enough | partly | `#/feed` → row 3 (`Φωτό`): `Στοιχεία` open ⇒ stage `386×320`, `img` `386×386` `object-fit:contain` in `overflow:hidden` ⇒ **bottom 66px cut**; nothing drawn on the picture itself; caption 16px, unclamped, selectable |
| S3 a film that waits | partly | open a `Βίντεο` row: `video.paused === true`, `muted === true`, one `Αναπαραγωγή`, `0:00 / 0:34`, photo has zero transport elements; mute toggled → reload → still `Ήχος ανοιχτός`. But stage `116px` at 390, video `386×686` painted **over** the seek bar and clock |
| S4 the end says it's the end | met | 4× `Επόμενη` → state block `Αυτά είναι όλα. / 37 αναρτήσεις, από τις 3 Νοεμβρίου. / Πάνω · Παλαιότερα… · Νέα συνεδρία`; `page-next.disabled === true`; reload at the end → same block, no request |
| S5 come back to where I was | partly | open rows 0–4, reload → `li.divider` = `26 νέα από την τελευταία φορά`, `Σελίδα 1 από 4`. First open of the day: boundary is row 0 ⇒ **no line at all**; scroll lands at 0, not on the line |
| S6 stories, one person at a time | met | `#/stories` → `Δες τις ιστορίες`: head `sofiavasilopoulou97 / χθες 22:49 / 1 από 2`; `Προηγούμενο` disabled at 1; `Επόμενο` ×2 → end card `Τέλος των ιστοριών της kalales.editor. / 4 από 4. / Επόμενη: sofiavasilopoulou97 (2)` + 35 names with counts, never the next account's first segment; `Λίστα` opens the people list |
| S7 marking seen is my job | partly | 61s idle in a segment: `.shead` and `.sstage` byte-identical, nothing marked. But `markSeen` fires when a segment is *painted* (`views.js:818`), so `Το είδα` and `Επόμενο` are the same action; the tray shows no `είδες n από m` |
| S8 stickers stay readable | partly | `Τι έχει πάνω της`: `Πρόσωπα / elena.fdm / Elena_Fdm / Άνοιγμα` + `Μουσική / I'll Be There for You (Theme From "Friends") / The Rembrandts`; label is text, `Άνοιγμα` is a separate anchor, nothing navigates on read. Rows are 15px (contract says ≥16) and the URL is behind `Άνοιγμα`, never printed |
| S9 never asked for anything | not met | no like on a row, no reaction without disclosure+confirm, no counts, no badges; but `Μου αρέσει` is a `368×44` checkbox one tap from a real like, and People carries `Σίγα` (mutes a person) and `Κλείσε εκείνη τη συνεδρία`, both one tap, no confirm |

## Where he stops

Worst first. Route, tap path, what he sees, what he expects.

1. **The film is drawn over its own controls.** `#/post/{pk}` (any `Βίντεο`),
   row press → player. Stage `386×320`…`116px` while `video` is `386×686`;
   `[data-seek]` and `0:00 / 0:34` are painted **on top of the frame**, the bottom
   third of the picture is clipped. At 1280×800 the stage is `996×564` and the
   video `720×1280`. He expects a DVD player: picture in its box, bar underneath.
   `app/static/style.css:285,307-308,320-323` (rows `auto … 1fr`, `.stray{max-height:40%}`,
   `.sstage{overflow:hidden}` + `max-height:100%` never resolving), `views.js:557-591`.
2. **Every person in the story list says `Φορτώνω…`.** `#/stories`, and `Λίστα` in
   any player: 36 rows, each `name / Φορτώνω… / Δες τις ιστορίες`; the end card
   prints the real counts for the same people (`sofiavasilopoulou97 (2)`). He waits
   for a download that is not happening, and cannot see `είδες 2 από 5`.
   `views.js:657-658` (`ringSaw` → `STR.loading()`), `views.js:1106-1116`.
3. **One tap likes his daughter's photo.** `#/post/{pk}` → `Στοιχεία`: the panel ends
   in a full-width `Μου αρέσει` checkbox (`368×44`), no confirm, `POST /api/posts/{pk}/like`
   on change. He opened `Στοιχεία` to read a caption. `views.js:678-681,693-706`.
4. **`Σημερινά` leaves him on page 3.** `#/feed` page 3 → `Αρχείο` → `Σημερινά` →
   still `Σελίδα 3 από 4`. The menu item promises the top of today. `shell.js:13,265-267`,
   `views.js:216-224` (never resets `f.page`).
5. **`Ανανέωση` is a silent no-op.** `#/feed` → `Προβολή` → `Ανανέωση`: same hash,
   same rows, status cell blank, no `Συνδέομαι… / Συνδέθηκα`. A press that changes
   nothing and says nothing is the "is it me or the program?" moment. `shell.js:273-279`.
6. **`Σημείωση ως αδιάβαστο` makes the post vanish.** `#/history` → `Σημείωση ως
   αδιάβαστο` → `Σημερινά`: the row he just marked is not on the page, the list
   refetched, nothing says where it went. `views.js:1222`, `views.js:405-419`.
7. **The close box is browser Back.** Any screen → title-bar `✕`: `history.back()`,
   so he lands on whatever he saw before (measured `✕` at `#/feed` → the previous
   `#/feed` page). "The close box means close." `shell.js:130-131`.
8. **Nothing on the phone says what is new.** `#/feed` at 390: `[data-status]` is a
   378px empty cell, `[data-page]`/`[data-conn]` are `0×0`; the only "new" signal is
   an 8×8 filled square and a bold name. `style.css:113-140`, `shell.js:44-60,94`.
9. **`Το είδα` and `Επόμενο` do the same thing.** `#/stories`: `Το είδα` marks (already
   marked on paint) then advances; `Επόμενο` advances. Two buttons, one verb →
   he presses the one that feels safer and can never tell if it counted. `views.js:1085,818,1016-1024`.
10. **`Κλείσε εκείνη τη συνεδρία` sits on every People row.** `#/people` →
    `Άνθρωποι…`: one tap, no confirm, ends the session that holds his place.
    `views.js:1121,1165-1176`.

## The four questions

**Can a single tap send something to another human by accident?** Yes. `Στοιχεία`
ends in a 368×44 `Μου αρέσει` checkbox with no confirm; People carries `Σίγα` and
`Κλείσε εκείνη τη συνεδρία`, one tap each. Reactions are the only safe write
(disclosure → emoji → `Σίγουρα; Θα σταλεί στη Μαρία.`), and that is the pattern the
like should have borrowed.

**Does the app move without him?** No. 61s idle in a story changed nothing; every
`<video>` is `paused && muted` at open; `ended` does not advance; no countdown, no
ring, no auto-jump. The one press that moves him unexpectedly is `✕`, which is Back.

**Can he always tell where he is?** In the bulletin yes — `Σελίδα 1 από 6` in the
footer, `Επόμενη` greyed on the last page, then `Αυτά είναι όλα.`. In the player
**no**: stories say `1 από 2`, but a post player says nothing (no `3 από 10`), and
on the phone the status bar is blank, so the page number only exists at the bottom.

**Is every word his?** Mostly, and the 2000 words (`Αρχείο`, `Προβολή`, `Σελίδα 1
από 6`, `Αυτά είναι όλα.`) are exactly right. The leaks are developer Greek and
abbreviations, not translationese — see below.

## Copy findings

| worst, verbatim | what he would say | `str.js` key |
|---|---|---|
| `−10 δ` / `+10 δ` | `−10 δευτ.` / `+10 δευτ.` — "δ" is nobody's abbreviation for δευτερόλεπτα | `back10`, `fwd10` |
| `Ξαναμίλα` | `Άνοιξε τον ήχο` — "speak again" is a verb about a person, not a speaker | `unmute` |
| `Υπάρχει ανοιχτή συνεδρία αλλού.` | `Το πρόγραμμα είναι ανοιχτό σε άλλη συσκευή.` — συνεδρία is programmer vocabulary | `conflict` (and `newSession`, `finishLock`) |

Also: `Σημερινά` heads a list whose newest row is 10 November — `Νέα` or `Πρόσφατα`
(`today`); `Φορτώνω…` printed as a permanent subtitle (`loading`); `Είδος` where
Windows Greek says `Τύπος` (`kind`); `νέο` only exists in the archive, never on the
bulletin row it describes.

## What is right

- The bulletin is a list of files: name, date, kind, a marker, and a bottom edge.
  Ten rows, one page number, `Επόμενη` that greys out — the shape he asked for.
- The end block, and `Νέα συνεδρία` in it: `Αυτά είναι όλα. 37 αναρτήσεις, από τις
  3 Νοεμβρίου.` is the sentence he was missing for years.
- The story end card names the person, the count and the next three people, and
  waits — nothing advances on its own, verified over 61 seconds.
- `Τι έχει πάνω της` keeps the picture on screen and the sticker as text, with
  `Άνοιγμα` as a separate press. Nothing opens because it was read.
- Mute is remembered across reload, `0:00 / 0:34` is written out, and the photo
  player has no transport at all.

↳ ux (head: build) — done: docs/designs/00sgram-v2/review-ux.md (3 blockers, 10 stops)
