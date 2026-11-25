# Millennial browse mode

## Problem — who hurts, and what breaks today

The program has one appearance: a 2000 desktop window (title bar, menu bar, status
bar, bevels, a paged list of rows). That is exactly right for its first user, and
exactly wrong for a millennial who opens the same link: they do not recognise a
paged bulletin as a feed, they do not want a menu bar between them and the media,
and they reach for gestures that do nothing.

What breaks today, concretely:

- Every reading is a list first. Seeing one post costs: read a row, open it, close
  it, find the next row. A familiar feed is one picture per screen.
- A post's extra pictures are behind `Επόμενο` in a nav row, which reads as
  "next post", not "next picture" — the 6-picture posts still feel broken.
- Nothing in the app reacts to a swipe.
- The bulletin's pager (`Σελίδα 1 από 7`) is a workable end, but it invites
  "page 2" before the user has finished page 1.

The second user wants the same content, the same finite session and the same
honest end — in a shape they already know: one post per screen, swipe up for the
next, swipe right for the post's other pictures, nothing else on the glass.

## Requirements

The stream, in the order a user meets it.

1. When the user picks «Περιήγηση» from the `Προβολή` menu, the system shall open
   the browse stream at `#/browse` and hide the title bar, the menu bar and the
   status bar.
2. When the browse stream opens, the system shall show the newest unseen post of
   the current session, filling the screen, with the media on black and nothing
   else besides the overlay described in R8. Posts of the session that are already
   seen (the snapshot keeps them for the bulletin) are not part of the stream.
3. When the user swipes up, presses `ArrowDown`, or scrolls down, the system
   shall move to the older post. The key follows the wheel — down is further
   into the stream — so the two never disagree about direction.
4. When the user swipes down, presses `ArrowUp`, or scrolls up, the system shall
   move to the newer post, without leaving the stream.
5. When the active post has more than one picture and the user swipes **left**
   or presses `ArrowRight`, the system shall show the next picture of that post.
   The deck follows the finger — dragging left brings the next picture in from
   the right — while the arrow keys stay literal, right is next, because a key is
   not a drag.
6. When the user swipes right or presses `ArrowLeft`, the system shall show the
   previous picture of that post.
7. When the user swipes right on the last picture, the system shall do nothing —
   the second axis never leaves the post.
8. While a card is active, the system shall show only: the account name, when it
   was published, `n από m` for the post's place in the stream, `φωτό n από m`
   when the post has more than one picture, and the caption clamped to two lines
   with a press to expand it. When the card is a film, the mode's own transport
   (pause, seek, clock, mute) is part of the card and is not counted as chrome.
9. When a card becomes active, the system shall mark that post seen, once, through
   the existing seen path (`markSeenLocally` + `/api/posts/seen`).
9a. When the active post has more than one picture, the system shall show, next
    to the counter, at most five small marks: one lit for the picture on the
    glass, the others hollow, and the lit mark shall stay mid-window as it slides
    so that "more is to the right" is visible without a row of twenty pips.
10. When the active post is a video, the system shall play it muted, in a loop,
    and stop and rewind it when the card stops being active.
11. When the user presses the mute control in the card's transport, the system
    shall mute or unmute that video and write the same one audio preference the
    player uses (`00sgram.muted`), so every later card opens with it. A change
    the program made itself — the browser refusing unmuted autoplay — shall not
    overwrite that preference.
12. When the active card is the last unseen post of the session, the system shall
    stop fetching posts and shall show the end of the unseen run on the next
    upward swipe: a statement that the new posts are finished, and one button
    «Παλαιότερα…».
13. When the user presses «Παλαιότερα…», the system shall append the next 10 posts
    older than the last one in the stream, from `/api/older` seeded with the
    session's tail cursor (newest first), and shall not fetch anything until the
    user presses again. (§Amended after review: `/api/history` lists what has been
    seen, which is exactly the run just swiped, so its first page would append
    nothing; `/api/older` is the continuation seam the bulletin already uses and
    cannot overlap by construction.)
14. When no older posts remain, the system shall replace «Παλαιότερα…» with
    a terminal line and shall not offer more.
15. When the user presses the exit control or `Escape`, the system shall remember
    that this device prefers the windowed mode and then show the desktop bulletin
    at `#/feed`, replacing the stream's history entry so Back cannot re-enter it.
16. When a device has the browse mode remembered, the system shall open
    `#/browse` instead of `#/feed` on its next visit; and when any device opens
    `#/browse` by hash, the system shall treat that as this device's choice and
    remember it.
17. The system shall not render any like, reaction, comment, follow or unfollow
    control inside the browse stream, and shall not write to Instagram from it.
    The song recogniser's `POST` is the one write-shaped request the stream
    makes, and it writes nothing anywhere: it asks a question and answers it.
18. When the user presses `Space` on a video card, the system shall pause or
    resume it.
20. When the active post is a video, the system shall draw its own transport —
    pause, a seek bar, the clock, mute — from the same markup for every source,
    so a reel, a story and a plain post are not three behaviours. The controls
    shall be drawn as glyphs, with the word for each kept as its accessible
    label, so the bar stays one row on a phone. The platform's
    own controls shall not be used: their bar is positioned and hidden by the
    browser, behind the description and off the glass on a phone. The film and
    the description shall be laid out as two rows, never two layers, so no band
    of text ever covers the transport.
19. When the stream is open, the system shall not scroll, rubber-band or
    pull-to-refresh the page behind it, whether the input is a finger, a wheel or a
    key.

21. When the user presses the note in a film's transport, the system shall send
    that film's audio to the recogniser exactly once per press — never before the
    press and never in the background — and shall answer with the artist and title
    plus a link the reader presses to open the track in Spotify, or say in Greek
    that it did not recognise it. A named track shall carry two controls beside
    it: one that copies the artist and title to the clipboard, and one that opens
    Spotify's own search for those words. No account or key of the reader's shall
    be needed for the answer, and no Spotify login shall be involved: the link is
    a Spotify URL, not a session.
22. When the recogniser cannot answer — an unusual audio profile, a dead service,
    a film with no music — the system shall say so in Greek in the same line and
    shall leave the rest of the transport working. When the service is
    rate-limiting rather than ignorant, the line shall say that instead and name
    the seconds until the note may be pressed again, counting them down, and the
    note shall come back by itself when they run out.

## Out of scope — the things a future session will try to add

- Stories inside the stream. Stories keep the existing player; the browse mode is
  posts only.
- Likes, comments, shares, saves, DMs, follow/unfollow, "for you", trending,
  recommended accounts. The mode is quieter than the desktop one, not louder.
- Drag-follow animation, snap-back rails, haptics, view-transition flourishes.
  The card cuts on release; the only animation is the one native to `<video>`.
- Sound on by default, or a sound preference that resets. The preference is the
  program's own (`00sgram.muted`), so a film in the bulletin and a film here are
  the same choice; the browser's refusal to autoplay sound is the only thing
  that overrides it, and the control shows that.
- Prefetching beyond the current session snapshot, media caching, offline reading.
- A theme picker, a light/dark switch, or a third appearance. Two modes, one
  palette each, chosen on the menu.
- Per-post detail screen, permalink, account pages, search inside the stream.
- Landscape-specific composition beyond centered letterboxing.
- Any change to the session model: what counts as unseen, when a session starts
  and what a new one contains all stay exactly as the v2 design defines them.

## Open unknowns — each with the cheapest experiment that settles it

| Unknown | Cheapest experiment |
|---|---|
| Autoplay on a phone stalls on a slow connection and shows a black rectangle | Open the stream on the Pi's LAN over Wi-Fi, swipe through 10 video posts, count stalls; if more than one, preload the poster instead of the video and start playback on `canplay`. |
| A 40px swipe threshold is either too eager or too lazy on a real thumb | Swipe 20 times on the phone and count wrong turns; adjust the constant in `browse.js` only. |
| The end block is read as "the app is broken" rather than "you are done" | Show it once to the second user, ask what it said; the copy lives in `str.js`. |
| Per-card sound annoys the second user in a run of videos | **Answered 2026-11-17: sound lasts.** The preference is shared with the player; the browser's muted fallback after a reload is accepted and shown by the control. |
