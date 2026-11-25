# 00sgram v2 — brief

Written by the orchestrator (build) from the owner's request, 2026-11-17 night.
Everything below is input, not a decision. The pipeline may change any of it,
but it must not weaken the two constraints marked **hard**.

## Who the owner is

A developer who runs this client against their own Instagram account on a
Raspberry Pi / a Mac. They already use v1 (a distraction-free feed + a story
viewer in Instagram's own idiom). They are not the persona being designed for —
the persona is their imagined "boomer" end user.

## The persona to interview

**Nikos, 58.** Retired mechanic, uses a laptop and an Android phone. Has an
Instagram account because his kids and his old football team post there. He
does not read English comfortably; he reads Greek. He knows three computer
idioms and trusts them: **a window**, **a list of files**, **a media player
with a play button**. He calls the browser "the internet". He has never
understood stories' tap-left/tap-right, has accidentally sent reactions, and
believes the app is "hiding things from him" because the feed never ends.

He wants: to see what his people posted, in order, with a picture big enough
to see, a play button when there is a video, and a clear "that's everything"
at the end. He wants to be able to leave and come back without losing his
place. He does not want to be asked to like, follow, share, or buy anything.
He does not want animation, badges, or a red dot he cannot clear.

## What the owner asked for

- Act as that boomer user: a minimal, uninterrupted experience.
- Stories are videos; a video UI is simpler to use than Instagram's chrome.
- Un-instagram-ify the content: wrap a **familiar media displayer** around it.
- Rediscover a design that is familiar for receiving friends' news.
- Final product should feel like **Instagram built in the 00s**.
- Run the pipeline: product owner → design → engineering → software →
  testing / UI / UX / QA, each interviewing the stage before it, with loops.

## Hard constraints

1. **No writes to Instagram, ever.** No posts, comments, likes, reactions,
   follows, unfollows. Viewing stories is allowed (it registers a view, which
   the owner has already accepted). Nothing may make the account notable.
2. **The design contract of v1 survives** — these are the owner's own
   requirements from the first design, and a new skin must not quietly drop
   them:
   - the feed is **finite** and says so at the end;
   - story progress is **independent per account** (no auto-jumping that
     steals the next account's first segment);
   - there is an **explicit end-of-feed / end-of-stories state**;
   - a story segment is **markable as seen** without a countdown deciding it;
   - the story viewer shows **which person you are in**, their **segment
     counter**, and a way to jump to **any other person with stories**;
   - a story's **stickers** (profiles, songs, links, hashtags, places) are
     readable without leaving the picture;
   - mute/unmute is **remembered** across segments and reloads.

## Environment facts the pipeline must design within

- No build step. Vanilla ES modules served by FastAPI from `app/static/`.
- One container; SQLite; the browser is the Instagram client (not our UI).
- Mobile-first, 390x844 reference viewport; must also be usable at 1280 wide
  and in landscape 844x390.
- CSP is `script-src 'self'` — no inline handlers, no CDNs, no web fonts.
  Any typeface must be a system font stack.
- No new dependencies, no new network calls. The API surface already exists:
  `/api/posts`, `/api/stories`, `/api/stories/{pk}`, `/api/media/*`,
  `/api/accounts`, `/api/settings`, `/api/sessions`.
- 138 tests currently pass; `tests/test_ui.py` asserts parts of the markup.
