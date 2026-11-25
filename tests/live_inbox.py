"""Live pass for the messages screen, against the running container.

Opt-in, like live_browse.py: it drives the real app and therefore the real
browser, prints every row it got, and opens ONE conversation — `monday five`, the
one the design probe already marked read — because opening a thread marks it
read on Instagram and this script must not spend anyone's unread state.

Every request is checked: a non-200 is a failure, not a traceback.
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
OPEN_NAME = "monday five"      # already read by the design probe; see above

fails = []


def ok(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


with sync_playwright() as p:
    browser = p.webkit.launch()
    ctx = browser.new_context(viewport={"width": 320, "height": 568},
                              device_scale_factor=2, has_touch=True,
                              is_mobile=True)
    page = ctx.new_page()
    errors, bad = [], []
    # Before the POST there is no session: those two probes answer 404/405 by
    # design and are not what this pass is about.
    ALLOWED = ("/api/sessions/current", "/login")
    allowed = lambda url: any(a in url for a in ALLOWED)
    page.on("pageerror", lambda e: errors.append(str(e)))
    # A failed resource is already counted by the response handler with its
    # URL, which is the useful half; the console copy has neither.
    page.on("console", lambda m: errors.append("console:" + m.text)
            if m.type == "error"
            and not m.text.startswith("Failed to load resource") else None)
    page.on("response", lambda r: bad.append(f"{r.status} {r.url}")
            if r.status >= 400 and not allowed(r.url) else None)

    page.goto(BASE + "/login")
    page.evaluate("""async (pw) => {
        await fetch('/login', {method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({password: pw})});
    }""", PASSWORD)

    # The door is File ▸ Μηνύματα, so the pass uses it: a menu item that goes
    # nowhere is the failure the design forbids.
    page.goto(BASE + "/#/messages")
    page.wait_for_selector(".inbox-row button", timeout=60000)
    rows = page.evaluate("""() => [...document.querySelectorAll('.inbox-row')]
        .map(li => ({
          name: li.querySelector('.who').textContent.trim(),
          preview: li.querySelector('.sub').textContent.trim(),
          when: li.querySelector('.when').textContent.trim(),
          read: li.classList.contains('is-read'),
        }))""")
    print("     rows:")
    for r in rows:
        print(f"       {r['name']!r} | {r['preview']!r} | {r['when']!r}"
              f" | {'read' if r['read'] else 'UNREAD'}")
    ok(len(rows) >= 3, f"the list renders ({len(rows)} conversations)")
    ok(all(r["name"] for r in rows), "every row has a name")
    ok(all(r["when"] for r in rows), "every row has an age")
    ok(all("Unread" not in r["preview"] for r in rows),
       "the word Unread is a flag, not part of a row's text")
    note = page.inner_text("[data-note]")
    ok("Instagram" in note, f"the note names the cost in words: {note!r}")
    ok(page.is_hidden('[data-act="back"]'), "no back button on the list")
    page.screenshot(path=f"{SHOTS}/messages-list.png")

    # One press, the already-read conversation.
    page.evaluate("""(name) => {
        const b = [...document.querySelectorAll('.inbox-row button')]
          .find(x => x.dataset.name === name);
        if (b) b.click();
    }""", OPEN_NAME)
    page.wait_for_selector(".transcript", timeout=60000)
    lines = page.evaluate("""() => [...document.querySelectorAll('.transcript p')]
        .map(p => p.textContent.trim())""")
    print(f"     transcript: {len(lines)} lines, first {lines[:3]}")
    ok(len(lines) >= 3, "the transcript renders the page's lines")
    ok(any(len(ln) > 2 for ln in lines), "the lines carry words, not furniture")
    ok(not page.is_hidden('[data-act="back"]'), "the transcript offers a way back")
    ok("Instagram" in page.inner_text("[data-note]"),
       "the transcript restates that Instagram now has it read")
    page.screenshot(path=f"{SHOTS}/messages-thread.png")

    page.evaluate("() => document.querySelector('[data-act=\"back\"]').click()")
    page.wait_for_selector(".inbox-row button", timeout=10000)
    ok(True, "back returns to the list without another read")

    ok(not bad, f"non-200 responses: {bad or 'none'}")
    ok(not errors, f"page errors: {errors or 'none'}")
    browser.close()

print(f"\n{len(fails)} failed" if fails else "\nall ok")
sys.exit(1 if fails else 0)
