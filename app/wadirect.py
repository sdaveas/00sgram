"""WhatsApp Web as a DOM, and nothing else.

Selectors live here and only here. The module talks to a `hands` object — the
browser provider, or a fake in tests — with seven calls: `wa_eval`, `wa_click`,
`wa_move`, `wa_type`, `wa_press`, `wa_wait`, `wa_screenshot`. Every one of them
is a separate round trip because Playwright's sync API belongs to one thread.

What the DOM can and cannot answer (probed live, 2026-11-23):

- A conversation has **no id**, anywhere. The name is the only handle.
- Opening a conversation is the only way to read it, and it marks it read.
- A message does have an id: `data-id` on the bubble, also spelled
  `data-testid="conv-msg-<id>"`. It survives a reload, so dedup is exact.
- Direction is an `aria-label` ending in `:` — `You:` for ours — which is the
  same signal that names a group's author.
- A reaction is a hover, a click on `reaction-entry-point`, and a click on an
  `img[alt="<emoji>"]` inside the quick bar.
"""
from __future__ import annotations

import contextlib
import re

WA = "https://web.whatsapp.com"
SIX = ("👍", "❤️", "😂", "😮", "😢", "🙏")

# Icon names are WhatsApp's own; the labels are ours, in the same words the
# Instagram relay uses. Anything unrecognised still gets a label, so a new icon
# is a wrong word rather than a silent missing message.
ICONS = (
    ("photo", "[φωτογραφία]"), ("image", "[φωτογραφία]"),
    ("video", "[βίντεο]"), ("audio", "[φωνητικό]"), ("ptt", "[φωνητικό]"),
    ("mic", "[φωνητικό]"), ("sticker", "[sticker]"),
    ("document", "[έγγραφο]"), ("doc", "[έγγραφο]"),
    ("gif", "[gif]"), ("location", "[τοποθεσία]"), ("poll", "[δημοσκόπηση]"),
    ("contact", "[επαφή]"), ("vcard", "[επαφή]"),
)

# Telegram sends the heart without the variation selector; WhatsApp's image needs
# it. One alias, because a dropped ❤ would look like a bug in the relay.
ALIAS = {"❤": "❤️"}

_FOLD = re.compile(r"\s+")


def fold(text: str) -> str:
    """Whitespace and newlines to single spaces: the self chat's title carries a
    newline before `(You)`, and a name is a database key here."""
    return _FOLD.sub(" ", (text or "")).strip()


def key(name: str) -> str:
    """The conversation key. `(You)` is part of it: it is what the list says."""
    return fold(name)


def bare(name: str) -> str:
    """The name without the self-chat suffix — what the chat header shows."""
    return fold(name).replace(" (You)", "")


def canon(emoji: str) -> str:
    """The form WhatsApp's quick bar actually shows."""
    emoji = (emoji or "").strip()
    return ALIAS.get(emoji, emoji)


def label_for(icons: list[str]) -> str:
    for icon in icons or []:
        low = (icon or "").lower()
        for needle, label in ICONS:
            if needle in low:
                return label
    return "[μέσο]"


# --------------------------------------------------------------------- scripts

_CHATS = """() => {
  const pane = document.querySelector('#pane-side');
  if (!pane) return null;
  const fold = s => (s || '').replace(/\\s+/g, ' ').trim();
  const q = (r, s) => { const e = r.querySelector(s); return e ? (e.innerText || '') : ''; };
  const out = [];
  for (const r of pane.querySelectorAll('[data-testid^="list-item-"][role="row"]')) {
    const name = fold(q(r, '[data-testid="cell-frame-title"]'));
    if (!name) continue;
    const b = r.getBoundingClientRect();
    out.push({name,
      preview: fold(q(r, '[data-testid="cell-frame-secondary"]')).slice(0, 300),
      ts: fold(q(r, '[data-testid="chat-list-timestamp"]')),
      unread: fold(q(r, '[data-testid="icon-unread-count"]')),
      self: !!r.querySelector('[data-testid="message-yourself-row"]')
            || name.endsWith('(You)'),
      x: Math.round(b.x + b.width / 2), y: Math.round(b.y + b.height / 2),
      top: Math.round(b.top), bottom: Math.round(b.bottom)});
  }
  return out;
}"""

_HEADER = """() => {
  const main = document.querySelector('#main');
  if (!main) return null;
  const t = main.querySelector('[data-testid="conversation-info-header-chat-title"]');
  return t ? (t.innerText || '').trim() : null;
}"""

# One row of the open conversation: id, direction, author, text, and the icons
# that say what it is when it has no text.
_MESSAGES = """() => {
  const main = document.querySelector('#main');
  const panel = main && main.querySelector('[data-testid="conversation-panel-messages"]');
  if (!panel) return null;
  const fold = s => (s || '').replace(/\\s+/g, ' ').trim();
  const out = [];
  for (const row of panel.querySelectorAll('[role="row"]')) {
    const bubble = row.querySelector('[data-id]');
    if (!bubble) continue;
    const id = bubble.getAttribute('data-id');
    if (!id) continue;
    const labels = [...row.querySelectorAll('[aria-label]')]
      .map(e => (e.getAttribute('aria-label') || '').trim())
      .filter(l => l);
    const who = labels.find(l => l.endsWith(':'));
    const icons = [...bubble.querySelectorAll('[data-icon]')]
      .map(e => e.getAttribute('data-icon') || '').filter(Boolean);
    const sel = bubble.querySelector('.selectable-text');
    out.push({
      id,
      text: fold(sel ? sel.innerText : ''),
      mine: (who ? /^you:?$/i.test(who) : false) || icons.includes('tail-out'),
      sender: who && !/^you:?$/i.test(who) ? who.replace(/:$/, '') : '',
      icons,
    });
  }
  return out;
}"""

_COMPOSER = """() => {
  const box = document.querySelector(
    '[data-testid="conversation-compose-box-input"]');
  if (!box) return null;
  const b = box.getBoundingClientRect();
  return {x: Math.round(b.x + b.width / 2), y: Math.round(b.y + b.height / 2)};
}"""

# A bubble may be scrolled out of the virtualised panel: bring it to the middle
# before hovering, or the hover lands on nothing.
_BUBBLE = """(id) => {
  const el = [...document.querySelectorAll('#main [data-id]')]
    .find(e => e.getAttribute('data-id') === id);
  if (!el) return null;
  el.scrollIntoView({block: 'center'});
  const b = el.getBoundingClientRect();
  return {x: Math.round(b.x + b.width / 2), y: Math.round(b.top + 12),
          w: Math.round(b.width), h: Math.round(b.height)};
}"""

_ENTRY = """() => {
  const e = document.querySelector('[data-testid="reaction-entry-point"]');
  if (!e) return null;
  const b = e.getBoundingClientRect();
  if (!b.width) return null;
  return {x: Math.round(b.x + b.width / 2), y: Math.round(b.y + b.height / 2)};
}"""

# The quick bar is a horizontal run of emoji images. Found by shape and by the
# six known alts, never by position: WhatsApp moves it depending on which side
# of the screen the bubble sits.
_BAR = """(emoji) => {
  const six = %s;
  const tiles = [...document.querySelectorAll('img[alt]')]
    .filter(i => six.includes(i.getAttribute('alt')))
    .map(i => ({i, b: i.getBoundingClientRect()}))
    .filter(t => t.b.width > 8 && t.b.height > 8);
  if (!tiles.length) return null;
  const bands = {};
  for (const t of tiles) {
    const k = Math.round(t.b.y / 12);
    (bands[k] = bands[k] || []).push(t);
  }
  let bar = [];
  for (const k in bands) if (bands[k].length > bar.length) bar = bands[k];
  const hit = bar.find(t => t.i.getAttribute('alt') === emoji);
  if (!hit) return null;
  return {x: Math.round(hit.b.x + hit.b.width / 2),
          y: Math.round(hit.b.y + hit.b.height / 2)};
}""" % (list(SIX),)

# The emoji already under a bubble, outside the message text (a text emoji is an
# image too, so `selectable-text` has to be excluded).
_PILL = """(id) => {
  const el = [...document.querySelectorAll('#main [data-id]')]
    .find(e => e.getAttribute('data-id') === id);
  if (!el) return '';
  const row = el.closest('[role="row"]') || el;
  const six = %s;
  const img = [...row.querySelectorAll('img[alt]')]
    .find(i => !i.closest('.selectable-text')
            && six.includes(i.getAttribute('alt')));
  return img ? (img.getAttribute('alt') || '') : '';
}""" % (list(SIX),)

_HAS = """([id, emoji]) => {
  const el = [...document.querySelectorAll('#main [data-id]')]
    .find(e => e.getAttribute('data-id') === id);
  if (!el) return false;
  const row = el.closest('[role="row"]') || el;
  return [...row.querySelectorAll('[aria-label]')].some(e =>
    !e.closest('.selectable-text') &&
    (e.getAttribute('aria-label') || '').includes(emoji));
}"""

_QR = """() => {
  const c = document.querySelector('canvas') || document.querySelector('[data-ref]');
  return !!c;
}"""


class Wa:
    """`chats`, `open`, `messages`, `send`, `react`, `qr` — for the relay."""

    def __init__(self, hands) -> None:
        self.h = hands

    def _guard(self):
        """One borrow for a whole operation, not one per click.

        Borrowing per call is not enough: `open()` is a click plus a header
        poll, and another daemon's `open()` in between would leave `messages()`
        reading a different conversation — and posting it into the wrong topic.
        The hands object supplies the lock (an RLock, because `send` calls
        `open`); a fake in tests supplies nothing.
        """
        return getattr(self.h, "wa_lock", None) or contextlib.nullcontext()

    # -------------------------------------------------------------- readiness

    def chats(self) -> list[dict] | None:
        """The mounted list rows, or None when the list is not on screen (still
        loading, or logged out and showing a QR)."""
        with self._guard():
            return self.h.wa_eval(_CHATS)

    def ready(self, tries: int = 15, step: int = 1000) -> list[dict] | None:
        """The list, waiting for it. Bounded: a QR screen never becomes a list."""
        for _ in range(max(1, tries)):
            rows = self.chats()
            if rows:
                return rows
            self.h.wa_wait(step)
        return self.chats()

    def qr(self, path: str) -> bool:
        """A PNG of whatever the page shows, so an operator can scan the code."""
        with self._guard():
            self.h.wa_eval("() => 1")      # forces the page to exist and navigate
            self.h.wa_wait(3000)
            self.h.wa_screenshot(path)
            return bool(self.h.wa_eval(_QR))

    # ------------------------------------------------------------------ chats

    def find(self, name: str, preview: str = "") -> dict | None:
        """The row for a conversation, or None when the name is not unique.

        The name *is* the state key (there is no chat id), so two rows sharing
        one name cannot have separate marks and would post each other's messages
        into one topic. The preview cannot fix that, so a duplicate is skipped
        rather than guessed at. Opening the wrong row is also a read receipt on
        a stranger.
        """
        rows = [r for r in (self.chats() or []) if r["name"] == key(name)]
        return rows[0] if len(rows) == 1 else None

    def open(self, name: str, preview: str = "") -> bool:
        """Click the conversation and prove it opened, by its own header.

        A wrong click is a read receipt on someone else's chat, so this returns
        False instead of guessing: a message that waited is better than a message
        in the wrong topic.
        """
        with self._guard():
            row = self.find(name, preview)
            if row is None:
                return False
            want = bare(name)
            for attempt in (1, 2):
                if attempt == 2:
                    row = self.find(name, preview)
                    if row is None:
                        return False
                self.h.wa_click(row["x"], row["y"])
                if self._wait_header(want, tries=12):
                    return True
            return False

    def _wait_header(self, want: str, tries: int = 10) -> bool:
        for _ in range(max(1, tries)):
            got = self.h.wa_eval(_HEADER)
            if got and fold(got) == want:
                return True
            self.h.wa_wait(500)
        return False

    # --------------------------------------------------------------- messages

    def messages(self) -> list[dict] | None:
        """The open conversation's messages, in DOM order. None if no panel."""
        with self._guard():
            rows = self.h.wa_eval(_MESSAGES)
        if rows is None:
            return None
        for row in rows:
            if not row.get("text"):
                row["text"] = label_for(row.get("icons") or [])
        return rows

    # ------------------------------------------------------------------ writes

    def send(self, name: str, text: str, preview: str = "") -> str:
        """Type into the conversation and press Enter; return the new id, or "".

        No API exists, so the proof is the transcript's own last id: unchanged
        means the send did not land, and the caller must not claim otherwise.
        """
        line = fold(text)
        if not line:
            return ""
        with self._guard():
            return self._send(name, preview, line)

    def _send(self, name: str, preview: str, line: str) -> str:
        if not self.open(name, preview):
            return ""
        box = self.h.wa_eval(_COMPOSER)
        if not box:
            return ""
        before = self.last_id()
        self.h.wa_click(box["x"], box["y"])
        self.h.wa_type(line)
        self.h.wa_press("Enter")
        self.h.wa_wait(1500)
        after = self.last_id()
        return after if after and after != before else ""

    def last_id(self) -> str:
        rows = self.messages() or []
        return rows[-1]["id"] if rows else ""

    def react(self, name: str, msg_id: str, emoji: str = "❤") -> bool:
        """Put `emoji` under one message. An empty emoji takes ours back.

        Only the six quick reactions exist as clickable images; anything else is
        refused here rather than clicked and hoped for.
        """
        emoji = canon(emoji)
        if emoji and emoji not in SIX:
            raise ValueError(f"{emoji!r} is not one of the six quick reactions")
        removing = not emoji
        with self._guard():
            return self._react(name, msg_id, emoji, removing)

    def _react(self, name: str, msg_id: str, emoji: str,
               removing: bool) -> bool:
        if not self.open(name):
            return False
        spot = self.h.wa_eval(_BUBBLE, msg_id)
        if not spot:
            return False
        self.h.wa_move(spot["x"], spot["y"])
        self.h.wa_wait(600)
        entry = self.h.wa_eval(_ENTRY)
        if not entry:
            return False
        self.h.wa_click(entry["x"], entry["y"])
        self.h.wa_wait(700)
        if removing:
            emoji = self.h.wa_eval(_PILL, msg_id) or ""
            if not emoji:
                return True                    # nothing of ours to take back
        tile = self.h.wa_eval(_BAR, emoji)
        if not tile:
            return False
        self.h.wa_click(tile["x"], tile["y"])
        self.h.wa_wait(1000)
        # Adding is proven by the emoji being there; removing by it being gone.
        present = bool(self.h.wa_eval(_HAS, [msg_id, emoji]))
        return not present if removing else present
