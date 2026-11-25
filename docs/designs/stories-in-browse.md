# Stories in the browse deck

## Problem

`/browse` streams unseen **posts**. Stories — the freshest thing Instagram has,
and the thing "new" means to the people this app is for — never appear. Measured
today: 40 accounts with unseen stories, 115 segments, newest segment 16:38,
while the newest post in the store is 12:50. Open the deck and the most recent
thing in the account is missing.

The owner's direction is not "add a story rail": *stories don't differ from posts
in our browse; treat them as regular posts.* One stream, one card element, the
same two axes, the same seen rule.

One measured fact shapes every option: **story segments are only fetched per
account, when an account is opened, and that fetch registers a view on Instagram**
(`docs/designs/distraction-free-instagram-client.md` §Stories, and line 1249 of
the same doc, which rejected sweeping for exactly this reason). The tray gives
`media_ids` and a count but no media URL; `/api/media/story/<pk>` needs a stored
row. So the deck cannot hold a story picture without paying a view — and paying
views ahead of the person is the one thing this app must not do.

## Technical Plan

A story account is **one card whose pictures are its unseen segments**, on the
axis the deck already uses for albums.

- Swipe right and you walk the account's stories in order, with the segment
  marks showing `1 από 5`. Swipe up and you leave the account, exactly as a post.
- This is not a compromise on "regular posts": an album already means "the
  pictures of one thing, in order", and a story *is* an ordered sequence. One
  card per segment would need the same single fetch and then pretend the order
  came from the timestamps.
- The card sits in the post stream by `latest_reel_media` in `taken_at DESC`
  order, so stories are normally the first thing you see.

```
GET  /api/browse/stories              one entry per unseen, unmuted ring:
                                     {account, when, count, pending, resources}
POST /api/stories/<account_pk>/fetch  exists — executor B, answers 202
GET  /api/stories/<account_pk>        exists — the segments once fetched
POST /api/stories/seen                exists — one segment at a time
POST /api/stories/<account_pk>/done   exists — the ring goes quiet
```

- **Lazy by arrival only.** A card whose segments are not stored paints the
  account and «Φορτώνω…», asks for the fetch, and polls the existing endpoint
  until the segments arrive or the fetch fails. Arrival is the moment the person
  is looking at that account, so the view it registers is the one they meant to
  spend. **Nothing is prefetched**: `prefetch()` keeps its meaning for post pages
  and never reaches for a story that is two cards away.
- **Seen, per segment.** Painting a segment POSTs `/api/stories/seen` with that
  pk, once per pk per mount; leaving the card POSTs `/…/done`, so the ring stops
  being "unseen" in the tray. Posts keep `markSeenLocally` and their 2 s flush —
  the two seen paths stay separate because the tables are.
- **The session count stays about posts.** `S.total` is `session.remaining`;
  the card's «X από Y» counts the current card's position among *posts*, so a
  story card does not make the number go backwards or claim a post was read.
- **Hear (Shazam) is off on story cards.** It needs a post pk and a downloaded
  post resource; a story has neither.

### Alternatives, and why not them

- **Sweep stories during a sync cycle.** Cards would be instant and local, but
  every `user_stories` call registers a view: the app would mark 40 accounts'
  stories viewed without anyone looking. Rejected — it is the load-bearing rule
  of the stories design.
- **Cards straight from the tray's `media_ids`.** No media URL exists for an id
  alone, and `/api/media/story/<pk>` needs the row. Rejected.
- **`/api/v1/feed/reels_media/`** answers 500 for web sessions; its GraphQL
  replacement carries a rotating `doc_id`. Rejected for the same reasons as in
  the messages design.
- **A story rail at the top of the deck.** That is Instagram's layout, and the
  whole point of this mode is that there is no second axis of chrome.
- **One card per segment.** Same fetch cost, weaker order, and it would make an
  album (the same shape) behave differently from a story for no reason.

### Deliberately out of scope (v1)

Story links/stickers (the viewer lists them; a card shows the picture and the
transport), story reactions (already a separate write), rings and avatars beyond
the account's face, a "story" badge in the bulletin, and segments of accounts the
session filtered out.

## Detailed Implementation

`app/main.py` — the list, one query, no network:

```python
@app.get("/api/browse/stories")
def browse_stories(session: int, a: Auth = Depends(auth)):
    # rings unseen & unmuted (story_rings already drops muted accounts),
    # resources = stored, live, unseen segments in the deck's picture shape,
    # pending  = no stored segment yet, count from the tray's media_ids.
```

The endpoint never calls the provider: a fetch is the person's, per card.

`app/static/browse.js`

```js
S.stories = {}          // account_pk → {state, items} once fetched
pics(it)                // unchanged: a story item carries `resources`
postOrdinal()           // cards before and including S.i that are not stories
mergeStories(list)      // stable by taken_at DESC; S.i follows the old pk
loadStory(it)           // POST fetch, poll GET, replace resources, repaint
markStorySeen(pk)       // once per pk, POST /api/stories/seen
```

Order: the first post page paints immediately; the story list arrives in
parallel and is merged, and the deck keeps showing the same card it was showing
because `S.i` is recomputed from the painted pk.

Tests

- `tests/test_stories_browse.py` — the list endpoint against the mock provider:
  an unseen ring with a stored segment becomes one resource; an unknown ring is
  `pending` with the tray's count; a seen ring is absent; a muted account is
  absent; the endpoint makes no provider call (asserted by a provider that
  raises).
- `tests/browse_check.mjs` — the deck's merge: story cards are ordered by time,
  the counter ignores them, a pending card asks for one fetch and polls, seen is
  posted once per segment, and `prefetch()` never calls the story path.
- `tests/live_browse.py` — a live assertion on the real container: the deck's
  first card can be a story, tapping it loads the picture, and the tray's unseen
  count drops by that account afterwards.
