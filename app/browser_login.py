"""One-time interactive login for `PROVIDER=browser`.

Run it, open a VNC client to the Pi on port 5900, log in to Instagram in the
Chromium window that appears, and close the window when it says it worked. The
login is stored in `BROWSER_PROFILE`, and that directory becomes the credential:
no cookie is copied anywhere, and nothing else ever needs to sign in.

    docker compose run --rm -p 5900:5900 web python -m app.browser_login

Why a whole display for one login: a headless browser announces itself, and the
point of this provider is to look like the browser a person uses.
"""
from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import sys
import time

from .config import Config

DISPLAY = os.environ.get("LOGIN_DISPLAY", ":99")
TIMEOUT_S = 15 * 60

# `ds_user_id` survives a session revocation — Instagram keeps the id and drops
# `sessionid`. Trusting it made this helper announce "logged in" on a profile
# whose next request was a login wall, twice. Ask for real data instead.
_SESSION_CHECK = """async () => {
  const r = await fetch('/api/v1/feed/timeline/', {credentials: 'include',
      headers: {'x-ig-app-id': '936619743392459'}});
  const text = await r.text();
  try {
    const j = JSON.parse(text);
    return {ok: r.status === 200 && Array.isArray(j.feed_items),
            status: r.status, items: (j.feed_items || []).length};
  } catch (e) {
    return {ok: false, status: r.status, items: 0};   // an HTML login wall
  }
}"""


def _start(cmd: list[str]) -> subprocess.Popen:
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def main() -> int:
    for binary in ("Xvfb", "x11vnc"):
        if shutil.which(binary) is None:
            print(f"{binary} is missing — this image needs xvfb and x11vnc", file=sys.stderr)
            return 2
    cfg = Config.from_env()
    profile = str(cfg.browser_profile)
    if not profile:
        print("BROWSER_PROFILE is empty", file=sys.stderr)
        return 2
    os.makedirs(profile, exist_ok=True)

    os.environ["DISPLAY"] = DISPLAY
    xvfb = _start(["Xvfb", DISPLAY, "-screen", "0", "1280x1024x24"])
    time.sleep(1.5)
    password = secrets.token_urlsafe(6)
    vnc = _start(["x11vnc", "-display", DISPLAY, "-rfbport", "5900",
                  "-passwd", password, "-forever", "-shared", "-quiet"])
    print(f"VNC on <this-host>:5900   password: {password}", flush=True)
    print("Log in to Instagram in the window, then wait for 'logged in'.", flush=True)

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            args = ["--no-sandbox", "--disable-blink-features=AutomationControlled"]
            # Only for the "someone else types it for me" path: a driver outside
            # this process needs a TCP endpoint to attach to.
            if os.environ.get("LOGIN_DEBUG_PORT"):
                args.append("--remote-debugging-port=" + os.environ["LOGIN_DEBUG_PORT"])
            ctx = pw.chromium.launch_persistent_context(
                profile, headless=False,
                executable_path=os.environ.get("CHROMIUM_PATH") or None,
                args=args,
                viewport={"width": 1280, "height": 900},
                locale="en-GB", timezone_id="Europe/Athens")
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=60000)
            deadline = time.time() + TIMEOUT_S
            logged_in = False
            while time.time() < deadline:
                try:
                    cookies = ctx.cookies()
                except Exception:                  # noqa: BLE001
                    # An external driver closed the browser gracefully, which is
                    # exactly how the profile gets flushed to disk.
                    print("browser closed externally; cookies were flushed on exit", flush=True)
                    return 0
                uid = next((c["value"] for c in cookies if c["name"] == "ds_user_id"), "")
                live = False
                if uid:
                    try:
                        live = bool(page.evaluate(_SESSION_CHECK).get("ok"))
                    except Exception:          # noqa: BLE001 - mid-navigation
                        live = False
                if uid and live:
                    logged_in = True
                    print(f"logged in as uid {uid}", flush=True)
                    # Chromium keeps cookie writes in memory for a while and only
                    # commits them on a clean shutdown. A killed container (which
                    # is how this used to be stopped) therefore saved a profile
                    # with the pre-login cookies and no sessionid — a login that
                    # silently evaporated.
                    print("saving the profile — the window will close by itself", flush=True)
                    time.sleep(3)
                    ctx.close()
                    print("profile saved; this container can be removed", flush=True)
                    break
                time.sleep(2)
            if not logged_in:
                print("timed out without a login", file=sys.stderr)
                ctx.close()
                return 1
    finally:
        for proc in (vnc, xvfb):
            try:
                proc.terminate()
            except Exception:                      # noqa: BLE001
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
