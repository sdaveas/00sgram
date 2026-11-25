# 00sgram v2 — UI review (final verification)

Verdict: **pass with fixes** — the frame, the bulletin and the control states are on spec; the player is broken at 390×844 and five contract details are wrong. **1 blocker, 6 majors, 7 minors.** Every row was measured in the DOM on the live instance (`http://192.168.1.72:8091`, WebKit, logged in via `POST /login`); no write control was pressed.

## Defects

| # | sev | screen | size | what is wrong | measured vs spec | file:line | required fix |
|---|---|---|---|---|---|---|---|
| 1 | **blocker** | player `#/post/<pk>` | 390×844 | The playlist sits in the grid flow and is **open on mount** (`[data-tray]` has no `hidden`, and `Λίστα` says `aria-expanded="false"`). Its `auto` track sizes to all ten rows, so the stage is squeezed to a thumbnail and a 265px grey band is left empty | tray track **442px** (item 176.8px), stage **116px** vs spec **558**; photo post stage 188px | `style.css:285`, `style.css:307-310`, `views.js:578`, `views.js:1075-1077` | at ≤700 keep `[data-tray]` hidden until `Λίστα` is pressed, and bound the track (`minmax(0,40%)`) so the stage takes the remainder |
| 2 | major | status bar, every route | ≤700 | Page **and** connection cells are `display:none` and the message cell is empty at rest, so the bar paints as one blank sunken box | `#statusbar` text `['','','Έτοιμο']`, conn cell `display:none`, 386×28 all blank; all three spec wireframes show `Έτοιμο` in the bar at 390 | `style.css:145`, `shell.js:94` | only the page cell is "hidden <701px" (`00sgram-v2.md:73`); keep `[data-conn]` visible at ≤700, or mirror `Έτοιμο` into `[data-status]` |
| 3 | major | `#/stories` | all 3 | Every row's sub-line is the *loading* word and nothing is loading: `/api/stories` returns `known:false` for all 36 rings, `ringSaw()` → null, and the fallback is `STR.loading()` | 36/36 rows read `Φορτώνω…` after 2.6s idle, zero requests in flight; row 53px | `views.js:511` (same bug in `paintTray`, `views.js:658`) | a settled string for "not fetched yet" (new `STR` key); never the loading word for a state that will not resolve |
| 4 | major | `#/accounts` | all 3 | `Δες τις ιστορίες` is enabled on rows whose own sub-line says `δεν έχει ιστορίες`; pressing it navigates to `#/stories` and only prints `δεν έχει ιστορίες` | 10/10 sampled rows: sub `δεν έχει ιστορίες`, button `disabled: null`, 44px | `views.js:1119`, `views.js:1160-1163` | `disabled` + `data-reason` when no ring with stories exists for that pk |
| 5 | major | player | 1280×800 | The 1200×760 window gets the *landscape* player chrome, not the 1280 row of the geometry table | childbar **20** (spec 24), header **40** (44), transport **44** (72), stage **564** (528); transport collapses to one line | `style.css:394,401,415` vs `00sgram-v2.md:378-380` | gate the landscape player block on `(min-width:701px) and (max-height:520px)`, as the frame already does (`style.css:134`) |
| 6 | major | player | all 3 | The spec's 44px `✕ Κλείσιμο` is missing from the header; the only close is a 20px button in the 24px child bar | `.childbar button` **61.9×20**; `.shead` controls: `Λίστα` only | `views.js:570-577`, `style.css:293` vs `00sgram-v2.md:161-163` | add the 44px `Κλείσιμο` to `.shead` (or raise the child-bar control to 44px and amend the design) |
| 7 | major | player transport | all 3 | The seek is a native OS slider — no bevel, round thumb (radius ≫ 4), only `accent-color` set | computed `appearance:auto`, no background, `box-shadow:none`, `border:0`; thumb is WebKit's | `style.css:336-338` vs `00sgram-v2.md:229` ("no `border-radius` over 4px") | `-webkit-appearance:none`, sunken 1px track, square beveled thumb; keep `data-seek` |
| 8 | minor | feed, last page | all 3 | The pager and the end block both render; the design says the block *replaces* the footer | page 4: `.pager` present (`Σελίδα 4 από 4`) **and** `Αυτά είναι όλα. 37 αναρτήσεις…` (99.8px) below it | `views.js:294`, `views.js:303` | omit the `.pager` `<li>` when `last` |
| 9 | minor | `#/settings` | all 3 | Tab order and default differ from the design | order `Λογαριασμός, Τύποι, Συγχρονισμός, Χώρος`, `Λογαριασμός` selected; spec `Τύποι, Συγχρονισμός, Λογαριασμός, Χώρος` | `views.js:1479-1482` vs `00sgram-v2.md:186-187` | reorder `TABS`, default to `types` |
| 10 | minor | `#/login` | all 3 | Unframed (no title bar, no menu bar) and the heading is a display heading | `#topbar.hidden = true`; `h1` **30px** vs "`h1` at 15px bold, not a display heading" | `views.js:61`, `shell.js` login branch vs `00sgram-v2.md:34,71` | paint the frame on `#/login` and use `.screen` on the `h1`. Note engineering D1 sanctions hiding `#topbar` here; the design does not |
| 11 | minor | copy | all 3 | A Greek string outside the deck is printed in the status bar | `alreadyTop: "Είσαι ήδη στην αρχή."` (for `Στην αρχή`), absent from `00sgram-v2.md:236-262` and engineering §5 | `str.js:125` | add it to the deck or reuse listed wording |
| 12 | minor | player | all 3 | `Τι έχει πάνω της` is removed when the post has no sticker links, so the panel is unreachable rather than empty | `hidden = !links.length`; measured 0×0 on 9/10 sampled posts | `views.js:758` vs `00sgram-v2.md:165-170` | render the toggle disabled with a reason, or record in the design that a stickerless post has no panel |
| 13 | minor | `#/history` | all 3 | `Άνοιγμα` is an unboxed 44px link next to a beveled button on the same row | `.files.hist .row` has no border/box-shadow, 44px tall | `style.css:214` vs the raised rule at `216-219` | give `.hist .row` the raised treatment |
| 14 | minor | bulletin | 390 | Column 2 is 10px narrower than the design's arithmetic | **194px** vs "12+8+204+8+84+8+46 = 370"; the formula omits the 2px list border and 8px row padding (368−8−12−84−46−24 = 194) | `00sgram-v2.md:82-83`, `engineering.md:321` | correct the design's arithmetic — the implementation matches the CSS spec; no code change |

## What is right (do not regress)

- **Frame geometry is exact** at all three viewports: 26+44 / 742 / 28, 22+28 / 314 / 22, and a 1200×760 window at (40,20) with 30+28 / 668 / 30 inside a 2px bevel.
- **The bulletin is the design's list**: ten 56px rows, `12px … 84px 46px` grid with 8px gaps and 4px padding, 8×8 navy marker, `13 Νοε 16:11` in tabular numerals, `Βίντεο`/`Φωτό` as words, hollow marker + regular name under `is-seen`, 44px pager with `Σελίδα n από m`, no media element in the DOM.
- **One appearance holds**: zero `border-radius` over 4px anywhere, no gradient, and **zero** painted colours outside the token set on all ten routes at three sizes; title bar `#000080` / white 12px bold, desktop `#008080`.
- **Control states are on spec**: `aria-disabled` menu items keep their place and print their reason in the status bar with the menu still open; pressed flips the bevel (`style.css:41-45`); the keyboard focus ring is `dotted 1px #000` at offset −3 **plus** the 3px navy left bar on a row.
- **Chrome and menus are sized right**: window buttons 18×16 with SVG glyphs and `Μεγέθυνση` `aria-disabled` at ≤700, menu items 44px at 390 / 22px at 1280, and no horizontal overflow at any size (`scrollWidth == clientWidth`).

## Screenshots

```
/tmp/v2-phone-feed.png            /tmp/v2-land-feed.png            /tmp/v2-desk-feed.png
/tmp/v2-phone-feed-last.png       /tmp/v2-desk-feed-last.png
/tmp/v2-phone-player-video.png    /tmp/v2-land-player-video.png    /tmp/v2-desk-player-video.png
/tmp/v2-phone-player-photo.png    /tmp/v2-land-player-photo.png    /tmp/v2-desk-player-photo.png
/tmp/v2-phone-player-video-details.png  /tmp/v2-land-player-video-details.png  /tmp/v2-desk-player-video-details.png
/tmp/v2-phone-player-photo-details.png  /tmp/v2-land-player-photo-details.png  /tmp/v2-desk-player-photo-details.png
/tmp/v2-phone-stories.png         /tmp/v2-land-stories.png         /tmp/v2-desk-stories.png
/tmp/v2-phone-accounts.png        /tmp/v2-land-accounts.png        /tmp/v2-desk-accounts.png
/tmp/v2-phone-history.png         /tmp/v2-land-history.png         /tmp/v2-desk-history.png
/tmp/v2-phone-settings.png        /tmp/v2-land-settings.png        /tmp/v2-desk-settings.png
/tmp/v2-phone-sync.png            /tmp/v2-land-sync.png            /tmp/v2-desk-sync.png
/tmp/v2-phone-help.png            /tmp/v2-land-help.png            /tmp/v2-desk-help.png
/tmp/v2-phone-about.png           /tmp/v2-land-about.png           /tmp/v2-desk-about.png
/tmp/v2-phone-login.png           /tmp/v2-land-login.png           /tmp/v2-desk-login.png
```
(`/tmp/{phone,land,desk}-player*.png` are older one-shot captures from the supplied `/tmp/matrix.py`; the `v2-` set above is the one this review measured. `/tmp/ui_measure.json` holds the raw numbers.)

## Not reviewed

- **Stickers panel content / `Άνοιγμα`** — every sampled post had no sticker links, so the panel (and D12) could not be opened.
- **Story mode of the player** (`2 από 5`, `Το είδα`, end card, `Αντιδράσεις` confirm) — `Ναι, στείλ' το` is a write; the playlist sub-line there is the same code path as D3 (`views.js:658`).
- **Pressed state as a screenshot** — WebKit `:active` cannot be driven from Playwright; read from the authored rule and a border/shadow flip only.
- **The like checkbox** — read only (`data-act="like"` in the details panel, 44px label); never pressed, so `Δεν αποθηκεύτηκε· γύρισε πίσω.` is unverified.
- **`Σημείωση ως αδιάβαστο`, `Αποθήκευση`, `Αποσύνδεση`, `Έλεγχος τώρα`, `Νέα συνεδρία`** — all writes, not pressed.
- **Offline / frozen-sync states** — no network control on the instance, so the two unprompted messages were not reproduced.
- **B6 "m never shrinks"** — page counts differ per browser context (`από 6`, `από 5`, `από 4`) because each context starts its own server session; that is session state, not measured here.
- **`#/sync` run table beyond first paint** and the `#/history` `Ιστορίες` tab contents.

↳ ui (head: build) — done: docs/designs/00sgram-v2/review-ui.md (1 blocker, 6 majors, 7 minors)
