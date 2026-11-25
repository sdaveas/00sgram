"""Every film in a run, at small-phone sizes, checked for a usable transport.

Walks the unseen run with the keyboard (the fastest way through a session) and
measures each video card: is the bar there, are the controls inside the screen,
does anything sit on top of them. Leaves the database as it found it — every post
this pass marks seen is unseen again at the end.

    ~/venvs/00sgram/bin/python tests/se_videos.py
"""
import os
import pathlib
import sys
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _env(key, default=""):
    """The .env is the one place the password lives; these passes read it, so a
    change of password never leaves a stale copy in a test file."""
    if os.environ.get(key):
        return os.environ[key]
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return default


BASE = _env("APP_BASE", "http://127.0.0.1:8091")
PASSWORD = _env("APP_PASSWORD")
SHOTS = "/Users/stelios/Projects/stelios/00sgram/docs/shots"

# iPhone SE (2nd/3rd gen) and the original SE, which is narrower still.
SIZES = [(375, 667, "se"), (320, 568, "se-1")]

fails = []


def ok(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


MEASURE = """() => {
  const card = document.querySelector('.bcard');
  const v = card?.querySelector('video');
  const bar = document.querySelector('.bbar');
  if (!v || !bar) return {video: !!v, bar: !!bar};
  const r = card.getBoundingClientRect();
  const b = bar.getBoundingClientRect();
  const m = document.querySelector('.bmeta').getBoundingClientRect();
  const cap = document.querySelector('.bcap');
  const pp = bar.querySelector('[data-act="pp"]');
  const mute = bar.querySelector('[data-act="mute"]');
  const seek = bar.querySelector('input[data-seek]');
  const rr = pp.getBoundingClientRect();
  const hit = document.elementFromPoint(rr.left + rr.width / 2, rr.top + rr.height / 2);
  return {
    video: true, bar: true,
    pk: card.dataset.pk,
    card: [Math.round(r.top), Math.round(r.bottom)],
    barRect: [Math.round(b.top), Math.round(b.bottom), Math.round(b.left), Math.round(b.right)],
    metaBottom: Math.round(m.bottom),
    capTop: cap ? Math.round(cap.getBoundingClientRect().top) : null,
    pp: [Math.round(rr.width), Math.round(rr.height)],
    ppHittable: !!hit && !!hit.closest('[data-act="pp"]'),
    onTop: hit ? (hit.tagName + '.' + (hit.className || '')) : null,
    ppGlyph: !!pp.querySelector('svg'),
    muteGlyph: !!mute.querySelector('svg'),
    label: pp.getAttribute('aria-label'),
    seekW: Math.round(seek.getBoundingClientRect().width),
    vh: Math.round(window.innerHeight), vw: Math.round(window.innerWidth),
    scrollY: Math.round(window.scrollY),
  };
}"""


def walk(page, w, h, tag):
    page.goto(BASE + "/login")
    page.evaluate("""async pw => { await fetch('/login', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({password: pw})}); }""", PASSWORD)
    before = page.evaluate("""async () => (await (await fetch('/api/status',
      {credentials: 'same-origin'})).json()).posts.unseen""")
    seen_before = set(page.evaluate("""async () => {
      const out = []; let cursor = null;
      for (;;) {
        const q = '/api/history?limit=20' + (cursor ? '&cursor=' + cursor : '');
        const b = await (await fetch(q, {credentials: 'same-origin'})).json();
        out.push(...b.items.map(i => i.pk)); cursor = b.next_cursor;
        if (!cursor) return out;
      }
    }"""))
    page.goto(BASE + "/#/browse")
    page.wait_for_selector(".browse .bcard", timeout=20000)

    films = 0
    checked = 0
    shots = 0
    for i in range(160):
        m = page.evaluate(MEASURE)
        if m.get("video") and m.get("bar"):
            films += 1
            if True:                             # every film, not a sample
                checked += 1
                ok(m["pp"][0] >= 40 and m["pp"][1] >= 40,
                   f"{tag} film {films}: the pause target is {m['pp'][0]}x{m['pp'][1]}")
                ok(m["ppHittable"],
                   f"{tag} film {films}: nothing lies on top of the pause button "
                   f"(hit: {m['onTop']})")
                ok(m["ppGlyph"] and m["muteGlyph"], f"{tag} film {films}: controls are glyphs")
                ok(m["label"] in ("Παύση", "Αναπαραγωγή"),
                   f"{tag} film {films}: the glyph keeps its word in the label")
                ok(m["seekW"] >= 60, f"{tag} film {films}: the seek bar has room ({m['seekW']}px)")
                ok(m["barRect"][3] <= m["vw"] and m["barRect"][2] >= 0,
                   f"{tag} film {films}: the bar fits the width")
                ok(m["barRect"][1] <= m["vh"],
                   f"{tag} film {films}: the bar is above the bottom edge")
                ok(m["barRect"][0] >= m["card"][1] - 1,
                   f"{tag} film {films}: the bar starts below the picture")
                ok(m["capTop"] is None or m["capTop"] >= m["barRect"][1],
                   f"{tag} film {films}: the caption is below the bar")
                ok(m["card"][1] - m["card"][0] >= m["vh"] * 0.5,
                   f"{tag} film {films}: the picture keeps over half the screen "
                   f"({m['card'][1] - m['card'][0]} of {m['vh']})")
                if shots < 2:
                    page.screenshot(path=f"{SHOTS}/browse-{tag}-video.png")
                    shots += 1
        if page.evaluate("() => !!document.querySelector('.bend')"):
            break
        page.keyboard.press("ArrowDown")
        page.wait_for_timeout(120)

    ok(checked > 0, f"{tag} a film turned up in the run")
    print(f"     {tag} {w}x{h}: {films} films walked, {checked} measured")

    fresh = set(page.evaluate("""async () => {
      const out = []; let cursor = null;
      for (;;) {
        const q = '/api/history?limit=20' + (cursor ? '&cursor=' + cursor : '');
        const b = await (await fetch(q, {credentials: 'same-origin'})).json();
        out.push(...b.items.map(i => i.pk)); cursor = b.next_cursor;
        if (!cursor) return out;
      }
    }""")) - seen_before
    after = page.evaluate("""async pks => {
      for (const pk of pks) {
        await fetch('/api/posts/' + encodeURIComponent(pk) + '/unsee',
                    {method: 'POST', credentials: 'same-origin'});
      }
      return (await (await fetch('/api/status', {credentials: 'same-origin'})).json()).posts.unseen;
    }""", sorted(fresh))
    ok(after == before, f"{tag} unread restored ({before} -> {after})")


with sync_playwright() as p:
    browser = p.webkit.launch()
    for w, h, tag in SIZES:
        ctx = browser.new_context(viewport={"width": w, "height": h},
                                  is_mobile=True, has_touch=True,
                                  device_scale_factor=2)
        page = ctx.new_page()
        walk(page, w, h, tag)
        ctx.close()
    browser.close()

print("\nFAILED: " + "; ".join(fails) if fails else "\nall ok")
sys.exit(1 if fails else 0)
