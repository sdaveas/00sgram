"""Direct messages, read out of Instagram's own inbox page.

Instagram retired the REST path this would have used — `direct_v2/inbox`
answers 404 to the logged-in browser — and the GraphQL query that replaced it
carries a `doc_id` that changes with every web release. So this module does what
a person does: it opens the inbox and reads the words on it. The class names are
obfuscated and worthless; the text is not, and that is what every query here
returns.

Two rules hold the shape:

- **The list is free, the thread is not.** Rendering the inbox changes nothing
  on Instagram; opening a conversation marks it read. So `INBOX_JS` is asked
  whenever someone looks, and `OPEN_JS` only when they press a row.
- **Open by name, learn the id afterwards.** A row carries no thread id the DOM
  keeps (no `__reactProps` hit, no `href="/direct/t/…"`), so the adapter clicks
  the row whose first line is the name and reads the id from `location.href`.
"""
from __future__ import annotations

import re
from datetime import date

# Rows are `[role="button"]` divs in the list column. The chrome above them
# (profile, note, send-message) has no age token, which is what tells them apart.
INBOX_JS = """() => {
  const TIME = /(^|\\s)\\d+[smhdw](\\s|$)|\\b\\d{1,2}:\\d{2}\\b|\\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\\b/;
  const out = [];
  for (const el of document.querySelectorAll('[role="button"]')) {
    const r = el.getBoundingClientRect();
    if (r.width < 200 || r.height < 40 || r.height > 180) continue;
    const text = el.innerText || '';
    if (!TIME.test(text)) continue;
    const lines = text.split('\\n').map(s => s.trim()).filter(Boolean);
    if (lines.length < 2) continue;
    out.push({lines, unread: /(^|\\n)Unread(\\n|$)/.test(text)
              || /\\d+ new messages?/.test(text)});
  }
  return out.slice(0, 40);
}"""

# The row whose first line is this name. A click is the only way in: the row is
# a div with handlers, not a link.
OPEN_JS = """name => {
  const want = (name || '').trim();
  for (const el of document.querySelectorAll('[role="button"]')) {
    const r = el.getBoundingClientRect();
    if (r.width < 200 || r.height < 40) continue;
    const first = (el.innerText || '').split('\\n').map(s => s.trim()).find(Boolean);
    // A row may carry a badge or an emoji next to the name; the inbox list is
    // what produced `want`, so one being a prefix of the other is the same row.
    if (first && (first === want || first.startsWith(want) || want.startsWith(first))) {
      el.click(); return true;
    }
  }
  return false;
}"""

# The list is virtual: only the rows in view are in the DOM, and a conversation
# that has been quiet for a while is simply not there. Scrolling it is the only
# way to reach one by name.
SCROLL_JS = """dy => {
  for (const el of document.querySelectorAll('div')) {
    const st = getComputedStyle(el);
    if (!/(auto|scroll)/.test(st.overflowY)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 250 || r.height < 200 || r.x > innerWidth * 0.5) continue;
    el.scrollTop += dy;
    return true;
  }
  return false;
}"""

PROBE_JS = """() => {
  let box = null, area = 0;
  for (const el of document.querySelectorAll('div')) {
    const st = getComputedStyle(el);
    if (!/(auto|scroll)/.test(st.overflowY)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 300 || r.height < 200 || r.x < innerWidth * 0.35) continue;
    if (r.width * r.height > area) { area = r.width * r.height; box = el; }
  }
  if (!box) return {anchors: [], leaves: []};
  const bx = box.getBoundingClientRect().x, by = box.getBoundingClientRect().y;
  const leaves = [...box.querySelectorAll('div, span')]
    .filter(el => !el.querySelector('div, span') && (el.innerText || '').trim())
    .map(el => {
      const r = el.getBoundingClientRect();
      return {t: el.innerText.trim().slice(0, 40), x: Math.round(r.x - bx),
              y: Math.round(r.y - by), w: Math.round(r.width), h: Math.round(r.height)};
    });
  return {leaves, anchors: [...box.querySelectorAll('a[href]')].map(a => {
    const r = a.getBoundingClientRect();
    return {href: a.getAttribute('href'), w: Math.round(r.width),
            h: Math.round(r.height), y: Math.round(r.y), x: Math.round(r.x),
            bx: Math.round(box.getBoundingClientRect().x),
            text: (a.innerText || '').trim().slice(0, 30)};
  })};
}"""

# The conversation sits in the right-hand scroll box; the list on the left is
# scrollable too, so the pick is "widest box right of the middle".
THREAD_JS = """() => {
  let box = null, area = 0;
  for (const el of document.querySelectorAll('div')) {
    const st = getComputedStyle(el);
    if (!/(auto|scroll)/.test(st.overflowY)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 300 || r.height < 200 || r.x < innerWidth * 0.35) continue;
    if (r.width * r.height > area) { area = r.width * r.height; box = el; }
  }
  return {url: location.href,
          lines: box ? (box.innerText || '').split('\\n') : []};
}"""

# The transcript, one entry per message and *whose* it is. Instagram draws our
# own bubbles on the right and theirs on the left and keeps no author field, so
# a bubble is placed by which edge it hugs: the left gutter is theirs, the right
# gutter is ours. The leaf-only rule keeps the wrapper divs out — the copy of a
# text inside three nested divs is still one message.
THREAD_ROWS_JS = """() => {
  let box = null, area = 0;
  for (const el of document.querySelectorAll('div')) {
    const st = getComputedStyle(el);
    if (!/(auto|scroll)/.test(st.overflowY)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 300 || r.height < 200 || r.x < innerWidth * 0.35) continue;
    if (r.width * r.height > area) { area = r.width * r.height; box = el; }
  }
  if (!box) return {url: location.href, rows: []};
  const br = box.getBoundingClientRect();
  const alias = h => (h || '').split('?')[0].replace(/\/+$/, '').split('/').pop();
  // A group writes the speaker's name above each bubble, in the avatar column
  // and smaller than the words: 11px tall against the bubble's 20, and narrow.
  // A date separator is 11px too, but it spans the width of the list.
  const label = r => r.h <= 13 && r.w < 200 && r.x - br.x < 120;

  const leaves = [...box.querySelectorAll('div, span')]
    .filter(el => !el.querySelector('div, span') && (el.innerText || '').trim())
    .map(el => {
      const r = el.getBoundingClientRect();
      return {text: el.innerText.trim(), r,
              x: Math.round(r.x), w: Math.round(r.width), h: Math.round(r.height)};
    })
    .filter(x => !(x.r.width < 20 && x.r.height < 20))   // a reaction, not a message
    .sort((a, b) => a.r.y - b.r.y);

  // Avatars are the square anchors; their href is the sender's handle, which is
  // the only thing on the page that names a speaker unambiguously.
  const faces = [...box.querySelectorAll('a[href]')]
    .map(a => ({h: a.getAttribute('href'), r: a.getBoundingClientRect()}))
    .filter(x => x.h && x.r.width <= 34 && x.r.height <= 34)
    .map(x => ({who: alias(x.h), y: x.r.y + x.r.height / 2}));
  const face = r => {
    const y = r.y + r.height / 2;
    let best = null;
    for (const f of faces) {
      if (!best || Math.abs(f.y - y) < Math.abs(best.y - y)) best = f;
    }
    return best && Math.abs(best.y - y) <= 400 ? best.who : null;
  };

  const out = [], group = leaves.some(x => label(x));
  let speaker = null;
  for (const el of leaves) {
    if (label(el)) {
      // The label names the speaker of the bubbles under it; its own href is
      // the display name ("nika"), the avatar's is the handle ("nikapro").
      speaker = face(el.r) || speaker;
      continue;
    }
    const r = el.r, text = el.text;
    if (!text) continue;
    const left = r.x - br.x, right = br.right - r.right;
    // Which of a row's anchors is "the" link is not a question the DOM
    // answers: a shared post hides its shortcode on a 28px thumbnail, the same
    // size as an avatar, and a shared profile *is* its handle. So every anchor
    // near the bubble travels and the reader picks; clean_rows drops the ones
    // that recur across the whole conversation (an avatar, a pinned profile).
    // ponytail: an avatar on a single bubble still leaks through; the only way
    // to tell it from a post thumbnail is the page's React state, not the DOM.
    const y0 = r.y + r.height / 2;
    const hrefs = [...box.querySelectorAll('a[href]')]
      .map(a => ({h: a.getAttribute('href'), r2: a.getBoundingClientRect()}))
      .filter(x => x.h && !/^\/direct\//.test(x.h))
      .map(x => ({h: x.h, y: x.r2.y + x.r2.height / 2}))
      .filter(x => Math.abs(x.y - y0) <= 250)             // another message's card
      // A post reads `/shortcode` with no trailing slash; a profile reads
      // `/handle/`. The post is what the sender meant, so it comes first.
      .sort((a, b) => (a.h.endsWith('/') - b.h.endsWith('/'))
                   || (Math.abs(a.y - y0) - Math.abs(b.y - y0)))
      .map(x => x.h)
      .filter((h, i, all) => all.indexOf(h) === i)
      .slice(0, 4);
    out.push({text, mine: right < left, hrefs, who: speaker, group,
              x: Math.round(r.x), w: Math.round(r.width), h: Math.round(r.height)});
  }
  // A group's bubbles sit next to their sender's avatar, so the avatar's href
  // is a face and not a link anyone meant to share. In a direct chat there is
  // no such coupling and every anchor may be the thing that was sent.
  return {url: location.href, rows: out,
          faces: group ? [...new Set(faces.map(f => f.who))] : []};
}"""


_TIME = re.compile(r"(^\s*\d+[smhdw]\s*$)|(\b\d{1,2}:\d{2}\b)|"
                   r"(\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b)")
_ACTIVE = re.compile(r"\bActive\b")
_DAY = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4},\s*\d{1,2}:\d{2}$")
# The line Instagram draws where the unread part of a thread begins.
_UNREAD = re.compile(r"^(New messages|Νέα μηνύματα|Unread messages)$", re.I)
# A group chat's row does not start with its name: the activity line does, and
# the name shares the message line — `Active` / `monday five You: τεστ`.
_STATUS = re.compile(r"^(Active|Online|Typing.*)$")
_GROUP_LINE = re.compile(r"^(.*?)\s+(You:|You sent|εσύ:)", re.I)

_AGE = re.compile(r"(\d+)\s*(m|h|d|w|y)\b")
_ABS = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})")

# The inbox writes an age, not a date: "2h", "14w", "Active 3m ago".
_UNIT_WEEKS = {"m": 1 / 10080, "h": 1 / 168, "d": 1 / 7, "w": 1, "y": 52}


def age_weeks(when: str, today: date | None = None) -> float | None:
    """How old a conversation is, from the list's own `when` string.

    Nothing means unknown, not zero: a missing age must never be read as
    "recent". `None` is the only safe answer there.
    """
    s = (when or "").strip()
    if not s:
        return None
    abs_match = _ABS.match(s)
    if abs_match:
        day, month, year = (int(x) for x in abs_match.groups())
        year += 2000 if year < 100 else 0
        try:
            then = date(year, month, day)
        except ValueError:
            return None
        return max(0.0, ((today or date.today()) - then).days / 7)
    hit = _AGE.search(s)
    if not hit:
        return 0.0                     # "Active" / "now"
    return int(hit.group(1)) * _UNIT_WEEKS[hit.group(2)]


def clean_inbox(raw: list) -> list[dict]:
    """`[{name, preview, when, unread}]` out of the rows the page handed back.

    A row reads `name / preview / · / 2h`, or `name / Active 3h ago` when the
    other side has not written yet. The age is the last line that looks like
    one; the preview is whatever sits between the name and it.
    """
    out: list[dict] = []
    for row in raw or []:
        lines = [ln for ln in (row.get("lines") or [])
                 if ln and ln not in ("·", "\u00a0")]
        if not lines:
            continue
        name = lines[0]
        when = ""
        rest = lines[1:]
        for i in range(len(rest) - 1, -1, -1):
            if _TIME.search(rest[i]) or _ACTIVE.search(rest[i]):
                when = rest[i]
                rest = rest[:i] + rest[i + 1:]
                break
        rest = [ln for ln in rest if ln not in ("Unread",)]
        if _STATUS.match(name) and rest:
            # A group leads with "Active", then `monday five g.papadakis__: 1213`:
            # the name and the sender share one line, and the sender is the
            # token before the colon.
            head, sep, tail = rest[0].partition(":")
            words = head.split()
            if sep and len(words) >= 2 and re.fullmatch(r"[\w.]+", words[-1]):
                name = " ".join(words[:-1])
                rest[0] = f"{words[-1]}:{tail}"
        out.append({"name": name, "preview": " ".join(rest).strip(),
                    "when": when, "unread": bool(row.get("unread"))})
    # The same conversation can be in the DOM twice (the list and a hint).
    seen, unique = set(), []
    for row in out:
        if row["name"] in seen:
            continue
        seen.add(row["name"])
        unique.append(row)
    return unique


def _abs_link(href: str) -> str:
    """An Instagram path as a URL you can tap; anything else is dropped.

    Shared posts appear as a bare shortcode (`/cjd1884`), profiles as
    `/handle/`, and the anchor around a bubble points back into `/direct/`.
    """
    href = (href or "").strip()
    if not href or "/direct/" in href or href.startswith("#"):
        return ""
    if href.startswith("//"):
        href = f"https:{href}"
    elif href.startswith("/"):
        href = f"https://www.instagram.com{href}"
    if "instagram.com/" not in href:
        return ""
    path = href.split("instagram.com/", 1)[1]
    if not path or path.startswith("direct/"):
        return ""
    return href if path.endswith("/") else f"{href}/"


def clean_rows(raw: dict, limit: int = 400) -> list[dict]:
    """`[{text, mine, hrefs}]` out of THREAD_ROWS_JS: the transcript with authors.

    Day separators ("27/07/2025, 13:24", "Yesterday 14:32") are furniture, not
    messages; consecutive duplicates are one bubble seen through more than one
    element. The `hrefs` are every link near the bubble, and a link that turns
    up across the whole conversation (an avatar, a pinned profile) is furniture
    too — it is dropped, because a link on *every* message says nothing about
    any one of them.
    """
    faces = {f.lower() for f in (raw or {}).get("faces") or []}
    out: list[dict] = []
    for row in (raw or {}).get("rows") or []:
        text = " ".join((row.get("text") or "").split())
        if not text or _DAY.search(text) or _UNREAD.match(text):
            continue
        if _TIME.search(text) and len(text) < 24:
            continue
        hrefs = [h for h in (_abs_link(x) for x in row.get("hrefs") or []) if h]
        mine = bool(row.get("mine"))
        group = bool(row.get("group"))
        # Only a group says who is speaking: in a one-to-one chat the speaker is
        # obvious, and a stray name above the bubble is a card's label.
        who = (row.get("who") or "").strip().lstrip("@")
        if who and group and not mine:
            text = f"{who}: {text}"
        # A group's avatars are not links; drop them whether or not the row is
        # ours, because the speaker is already written out.
        if faces:
            hrefs = [h for h in hrefs
                     if h.rstrip("/").split("/")[-1].lower() not in faces]
        # A post card labels its author above the caption, and the caption opens
        # with the same handle glued on. Neither is something anyone said.
        aliases = {h.rstrip("/").split("/")[-1].lower() for h in hrefs}
        low = text.lower()
        # A bare shortcode (`/cjd1884`) is a post and a `/handle/` is a profile:
        # a collab post is several handles pointing at one shortcode and those
        # deserve keeping. Only a label with nothing but profiles behind it is
        # furniture.
        post_like = any(not (x or "").split("?")[0].rstrip().endswith("/")
                        for x in row.get("hrefs") or [])
        if hrefs and low in aliases and not post_like:
            continue
        for alias in aliases:
            if len(alias) > 2 and low.startswith(alias + " "):
                text = text[len(alias):].lstrip()
                break
        if out and out[-1]["text"] == text and out[-1]["mine"] == mine:
            continue
        # One card, several handles: a collab post renders each author as its
        # own line and they all point at the same post. Handles are single words
        # — a sentence that happens to repeat a link is a message, not a card.
        # ponytail: "one word" is the whole test; if a real card ever carries a
        # caption it will split in two lines instead of merging wrongly.
        if (out and out[-1]["mine"] == mine and not group and " " not in text
                and " " not in out[-1]["text"]
                and set(hrefs) & set(out[-1]["hrefs"])):
            out[-1]["text"] = f"{out[-1]['text']} · {text}"
            out[-1]["hrefs"] += [h for h in hrefs if h not in out[-1]["hrefs"]]
            continue
        out.append({"text": text, "mine": mine, "hrefs": hrefs})

    counts: dict[str, int] = {}
    for row in out:
        for href in set(row["hrefs"]):
            counts[href] = counts.get(href, 0) + 1
    for row in out:
        row["hrefs"] = [h for h in row["hrefs"] if counts[h] <= 3][:4]
    return out[-limit:]


def clean_thread(raw: dict) -> dict:
    """`{thread_id, lines}` — the transcript as the page renders it.

    Blank lines, non-breaking spaces and the `·` separators are the page's
    furniture, not the conversation, so they are dropped. Nothing else is
    interpreted: a line is shown where it was found, in the order found.
    """
    url = (raw or {}).get("url") or ""
    match = re.search(r"/direct/t/(\d+)", url)
    lines = [ln.replace("\u00a0", " ").strip()
             for ln in ((raw or {}).get("lines") or [])]
    lines = [ln for ln in lines if ln and ln != "·"]
    return {"thread_id": match.group(1) if match else None,
            "lines": lines[:400], "url": url}
