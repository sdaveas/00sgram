"""The browser provider, tested through a fake page.

No playwright, no network: `_call` only needs an object with `evaluate()` and a
context with `cookies()`, which is exactly the seam worth pinning down — the URL
it builds, the method it uses, and how it reports the two failure shapes that
matter (a challenge, and a login wall that answers 200 with HTML).
"""
from __future__ import annotations

import json

import pytest

from app.browser import CHALLENGE_MSG, NOT_LOGGED_IN, BrowserProvider
from app.config import Config
from app.provider import ProviderError, SessionExpired


class FakePage:
    def __init__(self, status=200, body=None, final=None, raw=None):
        self.status, self.body, self.raw = status, body, raw
        self.final = final or "https://www.instagram.com/"
        self.url = self.final
        self.calls: list[tuple[str, str]] = []
        self.gotos: list[str] = []
        self.clicks: list[tuple[int, int]] = []
        self.liked = False
        self.heart_missing_until = 0
        self.state_reads = 0
        self.preload = []
        self.mouse = FakeMouse(self)

    def evaluate(self, js, args=None):
        if "aria-label=\"Like\"" in js:          # the like-state script
            self.state_reads += 1
            if self.heart_missing_until and self.state_reads <= self.heart_missing_until:
                return None
            return {"label": "Unlike" if self.liked else "Like", "point": [10, 20]}
        if args is None:                          # a page-preload read
            return self.preload
        url, method, _body = args
        self.calls.append((url, method))
        text = self.raw if self.raw is not None else json.dumps(self.body or {})
        return [self.status, self.final, text]

    def goto(self, url, **_):
        self.gotos.append(url)
        self.url = url

    def wait_for_timeout(self, _ms):
        return None


class FakeMouse:
    def __init__(self, page):
        self.page = page

    def click(self, x, y):
        self.page.clicks.append((round(x), round(y)))
        self.page.liked = not self.page.liked


class FakeHeart:
    """`page.evaluate(_LIKE_STATE)` for a page whose heart is (or is not) there."""

    def __init__(self, page):
        self.page = page


class FakeCtx:
    def __init__(self, cookies):
        self._cookies = cookies

    def cookies(self):
        return self._cookies


class FakeConn:
    """Just enough for the permalink lookup."""

    def __init__(self, row=None):
        self.row = row

    def execute(self, _sql, _params):
        row = self.row
        return type("Cursor", (), {"fetchone": lambda self: row})()


def like_provider(page, **over):
    p = provider(page)
    p.conn = FakeConn({"code": "DfzvKLOEdYL", "permalink": None, **over})
    return p


def provider(page, uid="40660464"):
    cfg = Config.from_env({"DATA_DIR": "/tmp/bp", "PROVIDER": "browser",
                           "API_TOKEN": "t", "APP_PASSWORD": "p", "APP_SECRET": "s" * 32})
    p = BrowserProvider(cfg)
    p._page = page                                    # bypasses launch entirely
    p._ctx = FakeCtx([{"name": "ds_user_id", "value": uid}])
    return p


TIMELINE = {"feed_items": [{"media_or_ad": {
    "pk": "1", "code": "abc", "media_type": 1, "taken_at": 1_700_000_000,
    "user": {"pk": "42", "username": "u"},
    "image_versions2": {"candidates": [{"url": "https://scontent.cdninstagram.com/x.jpg"}]}}}],
    "next_max_id": "NEXT", "more_available": True}


def test_the_feed_is_read_off_the_home_page_preload():
    """The REST timeline answers with the login HTML now; the page ships its own."""
    page = FakePage()
    page.preload = [TIMELINE["feed_items"][0]["media_or_ad"]]
    result = provider(page).timeline_page(None)
    assert [i.pk for i in result.items] == ["1"]
    # One page only: there is no cursor to ask for.
    assert not result.more_available
    assert page.gotos and page.gotos[0].endswith("instagram.com/")


def test_a_cursor_returns_nothing_instead_of_refetching_the_same_page():
    page = FakePage()
    page.preload = [TIMELINE["feed_items"][0]["media_or_ad"]]
    result = provider(page).timeline_page("CURSOR=")
    assert result.items == [] and not result.more_available
    assert page.gotos == []


def test_a_challenge_redirect_names_the_security_check():
    page = FakePage(status=200, body={}, final="https://www.instagram.com/challenge/?next=/")
    with pytest.raises(SessionExpired) as err:
        provider(page).story_tray()
    assert str(err.value) == CHALLENGE_MSG


def test_401_and_an_html_login_wall_both_mean_not_logged_in():
    with pytest.raises(SessionExpired):
        provider(FakePage(status=401)).story_tray()
    # A login wall answers 200 with HTML, which must not become a JSON traceback.
    with pytest.raises(SessionExpired) as err:
        provider(FakePage(status=200, raw="<html>login</html>")).story_tray()
    assert str(err.value).startswith(NOT_LOGGED_IN)


def test_other_errors_surface_as_provider_errors():
    with pytest.raises(ProviderError) as err:
        provider(FakePage(status=429)).story_tray()
    assert "429" in str(err.value)


def test_a_lock_from_a_previous_container_does_not_block_the_launch(tmp_path):
    """Container hostnames change on every deploy, so Chromium's own lock is
    stale by definition here. Leaving it means a 180 s launch timeout."""
    from app.browser import clear_stale_lock

    profile = tmp_path / "browser-profile"
    profile.mkdir()
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        (profile / name).write_text("someone-else")
    (profile / "Default").mkdir()
    assert sorted(clear_stale_lock(str(profile))) == [
        "SingletonCookie", "SingletonLock", "SingletonSocket"]
    assert (profile / "Default").is_dir()
    assert clear_stale_lock(str(profile)) == []          # idempotent


def test_every_call_lands_on_one_thread_even_from_another_one():
    """A like is served by a FastAPI worker thread while sync runs on its own.
    Playwright's sync API refuses to switch threads, so the proxy must pin it."""
    import threading

    from app.browser import ThreadProxy

    seen, lock = [], threading.Lock()

    class Target:
        def whoami(self, tag):
            with lock:
                seen.append((tag, threading.get_ident()))
            return tag

        def boom(self):
            raise ValueError("nope")

    proxy = ThreadProxy(Target)
    threads = [threading.Thread(target=lambda i=i: proxy.whoami(i)) for i in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(tag for tag, _ in seen) == [0, 1, 2, 3]
    assert len({ident for _, ident in seen}) == 1
    assert threading.get_ident() not in {ident for _, ident in seen}
    with pytest.raises(ValueError):
        proxy.boom()


def test_like_opens_the_post_and_clicks_the_real_heart():
    """The HTTP like routes are dead for web, so the write is the click."""
    page = FakePage()
    like_provider(page).like("4031773498854725131")
    assert page.gotos == ["https://www.instagram.com/p/DfzvKLOEdYL/"]
    assert page.clicks == [(10, 20)]
    assert page.liked is True


def test_liking_something_already_liked_does_not_click_again():
    page = FakePage()
    page.liked = True
    like_provider(page).like("1")
    assert page.clicks == []                       # idempotent, no double tap


def test_unlike_clicks_only_when_the_heart_is_filled():
    page = FakePage()
    page.liked = True
    like_provider(page).unlike("1")
    assert page.clicks == [(10, 20)] and page.liked is False
    page.clicks.clear()
    like_provider(page).unlike("1")                # already empty: nothing to do
    assert page.clicks == []


def test_a_missing_heart_is_an_error_not_a_silent_success(monkeypatch):
    monkeypatch.setattr("app.browser.time.sleep", lambda _s: None)
    page = FakePage()
    page.heart_missing_until = 10_000              # page never hydrates
    with pytest.raises(ProviderError) as err:
        like_provider(page).like("1")
    assert "no like button" in str(err.value)


def test_a_like_that_does_not_stick_is_reported(monkeypatch):
    monkeypatch.setattr("app.browser.time.sleep", lambda _s: None)
    page = FakePage()
    p = like_provider(page)
    p.like_timeout = 0
    page.mouse.click = lambda x, y: None           # click does nothing
    with pytest.raises(ProviderError) as err:
        p.like("1")
    assert "did not register" in str(err.value)


def test_a_post_without_a_permalink_cannot_be_liked():
    p = like_provider(FakePage(), code=None)
    with pytest.raises(ProviderError):
        p.like("1")


# ------------------------------------------------------------ story stickers


def test_story_links_read_every_sticker_shape():
    from app.browser import _story_links

    links = _story_links({
        "story_bloks_stickers": [{"bloks_sticker": {"sticker_data": {"ig_mention": {
            "username": "elena.fdm", "full_name": "Elena"}}}}],
        "story_link_stickers": [{"story_link": {
            "url": "https://l.instagram.com/?u=https%3A%2F%2Fyoutube.com%2Flive%2Fx"
                   "&e=AUC"}}],
        "story_hashtags": [{"hashtag": {"name": "athens"}}],
        "story_locations": [{"location": {"pk": "123", "name": "Athens",
                                          "address": "Greece"}}],
        "story_music_stickers": [{"music_asset_info": {
            "title": "Theme", "display_artist": "The Rembrandts"}}],
    })
    kinds = [l["kind"] for l in links]
    assert kinds == ["profile", "url", "hashtag", "place", "music"]
    by = {l["kind"]: l for l in links}
    assert by["profile"]["label"] == "elena.fdm" and by["profile"]["detail"] == "Elena"
    # Outbound links arrive wrapped; the user must get the real destination.
    assert by["url"]["url"] == "https://youtube.com/live/x"
    assert by["hashtag"]["label"] == "#athens"
    assert by["place"]["url"].endswith("/explore/locations/123/")
    assert by["music"]["detail"] == "The Rembrandts"


def test_story_links_drop_duplicates_and_empty_labels():
    from app.browser import _story_links

    links = _story_links({
        "story_mentions": [{"user": {"username": "a", "full_name": "A"}},
                           {"user": {"username": "a"}}],
        "story_bloks_stickers": [{"bloks_sticker": {"sticker_data": {"ig_mention": {
            "username": "a"}}}}],
        "story_hashtags": [{"hashtag": {}}],
    })
    assert [l["label"] for l in links] == ["a"]


def test_story_links_survive_a_story_with_no_stickers():
    from app.browser import _story_links

    assert _story_links({}) == []


# ------------------------------------------------------------- unfollow


class FastClock:
    """Every read of the clock moves it a second: the polling loops end now."""

    def __init__(self):
        self.now = 1_000_000.0

    def time(self):
        self.now += 1.0
        return self.now

    def sleep(self, secs):
        self.now += secs


class FollowPage:
    """A profile page whose header button flips Following -> Follow on click."""

    def __init__(self, state="Following", confirm=True):
        self.state, self.confirm = state, confirm
        self.url = "https://www.instagram.com/someone/"
        self.gotos: list[str] = []
        self.clicks: list[tuple[int, int]] = []
        self.waits = 0
        self.dialog_open = False

    def goto(self, url, **_):
        self.gotos.append(url)
        self.url = url

    def wait_for_timeout(self, _ms):
        return None

    def wait_for_timeout(self, _ms):
        self.waits += 1

    def evaluate(self, js, args=None):
        from app.browser import _FOLLOW_BUTTON, _FOLLOW_STATE, _UNFOLLOW_CONFIRM

        if js == _FOLLOW_BUTTON:
            return [10, 20] if self.state in ("Following", "Requested") else None
        if js == _UNFOLLOW_CONFIRM:
            return [30, 40] if self.confirm and self.dialog_open else None
        if js == _FOLLOW_STATE:
            return self.state
        raise AssertionError(f"unexpected script: {js[:40]}")


def follow_provider(page):
    p = provider(page)
    p.conn = FakeConn(None)
    return p


def test_unfollow_clicks_following_then_the_confirm(monkeypatch):
    monkeypatch.setattr("app.browser.time", FastClock())
    page = FollowPage()
    def click(_self, x, y):
        page.clicks.append((x, y))
        if page.dialog_open:
            page.state = "Follow"                # the dialog's button writes
            page.dialog_open = False
        else:
            page.dialog_open = True              # the header opens the dialog

    page.mouse = type("M", (), {"click": click})()

    follow_provider(page).unfollow("42")
    assert page.clicks == [(10, 20), (30, 40)]
    assert page.state == "Follow"


def test_unfollow_does_not_click_a_stranger(monkeypatch):
    monkeypatch.setattr("app.browser.time", FastClock())
    page = FollowPage(state="Follow")
    p = follow_provider(page)
    p.like_timeout = 0
    with pytest.raises(ProviderError) as err:
        p.unfollow("42")
    assert "Following button" in str(err.value)
    assert page.clicks == []


def test_unfollow_without_a_confirm_dialog_is_an_error(monkeypatch):
    monkeypatch.setattr("app.browser.time", FastClock())
    page = FollowPage(confirm=False)
    page.mouse = type("M", (), {"click": lambda _self, x, y: page.clicks.append((x, y))})()
    with pytest.raises(ProviderError) as err:
        follow_provider(page).unfollow("42")
    assert "dialog" in str(err.value)
    assert len(page.clicks) == 1                 # the Following click, none blind


# ------------------------------------------------------------------ two pages


class FakePages:
    """A context whose tabs are URL-keyed, and which counts new tabs."""

    def __init__(self, urls):
        self.pages = [FakePage(final=u) for u in urls]
        self.created = 0

    def new_page(self):
        self.created += 1
        page = FakePage(final="about:blank")
        self.pages.append(page)
        return page


def test_page_for_gives_whatsapp_its_own_tab(monkeypatch):
    """The Instagram relay holds `_page`; the WhatsApp one asks for its own and
    must get a different tab, or one navigation would move the other."""
    from app.browser import WA

    cfg = Config.from_env({"DATA_DIR": "/tmp/bp", "PROVIDER": "browser",
                           "API_TOKEN": "t", "APP_PASSWORD": "p",
                           "APP_SECRET": "s" * 32})
    p = BrowserProvider(cfg)
    insta = FakePage(final="https://www.instagram.com/")
    p._page = insta
    p._ctx = FakePages(["https://www.instagram.com/"])
    p._ctx.pages = [insta]

    wa = p.page_for(WA)

    assert wa is not insta and p._page is insta
    assert p.page_for(WA) is wa                       # cached, not a tab per call
    assert p._ctx.created == 1
    p.close()
    assert p._pages == {}                             # a reconnect starts clean


def test_wa_page_navigates_only_its_own_tab(monkeypatch):
    from app.browser import WA

    cfg = Config.from_env({"DATA_DIR": "/tmp/bp", "PROVIDER": "browser",
                           "API_TOKEN": "t", "APP_PASSWORD": "p",
                           "APP_SECRET": "s" * 32})
    p = BrowserProvider(cfg)
    insta = FakePage(final="https://www.instagram.com/")
    p._page = insta
    p._ctx = FakePages([])
    p._ctx.pages = [insta]

    page = p.wa_page()

    assert page.url.startswith(WA) and insta.gotos == []
