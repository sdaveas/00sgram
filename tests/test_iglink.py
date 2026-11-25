"""Every shape of Instagram link that reaches Telegram, turned into a code.

Pure functions, so no network and no fixtures: the interesting part is the set
of spellings real senders produce (bare host, tracking query, the
`l.instagram.com/?u=` wrapper on outbound links, the `/share/` form that only a
redirect can resolve) and the refusals, which must not become guesswork.
"""
from __future__ import annotations

from urllib.parse import quote

from app.iglink import links_in, parse, unwrap

REEL = "https://www.instagram.com/reel/DAbCdEf123/"


# --------------------------------------------------------------------- posts


def test_a_post_url_yields_its_code():
    assert parse("https://www.instagram.com/p/CODE/") == {"kind": "post",
                                                          "code": "CODE"}


def test_a_reel_without_a_scheme_is_still_a_reel():
    """Telegram hands over what was typed; the scheme is often dropped."""
    assert parse("instagram.com/reel/CODE") == {"kind": "post", "code": "CODE"}


def test_the_tracking_query_the_share_sheet_adds_is_ignored():
    assert parse("https://www.instagram.com/reel/CODE/"
                 "?utm_source=ig_web_copy_link&igsh=xyz")["code"] == "CODE"


def test_the_tv_spelling_is_the_same_post():
    assert parse("https://www.instagram.com/tv/CODE/")["code"] == "CODE"


def test_the_reels_spelling_is_the_same_post():
    assert parse("https://www.instagram.com/reels/CODE")["code"] == "CODE"


def test_the_l_instagram_wrapper_unwraps_to_the_link_it_hides():
    wrapped = ("https://l.instagram.com/?u="
               + quote("https://www.instagram.com/reel/CODE/", safe="") + "&e=x")
    assert unwrap(wrapped) == "https://www.instagram.com/reel/CODE/"
    assert parse(wrapped)["code"] == "CODE"


def test_a_wrapper_without_a_u_parameter_is_not_a_post():
    assert parse("https://l.instagram.com/?e=abc") is None


# -------------------------------------------------------------- not a post


def test_a_share_link_gives_the_token_and_leaves_resolving_to_the_caller():
    """The token is opaque and short-lived; guessing a code from it would lie."""
    got = parse("https://www.instagram.com/share/reel/TOKEN123/")
    assert (got["kind"], got["token"]) == ("share", "TOKEN123")
    assert "code" not in got


def test_a_story_link_keeps_the_username_and_media_id():
    assert parse("https://www.instagram.com/stories/someone/1234567/") == {
        "kind": "story", "username": "someone", "media_id": "1234567"}


def test_nothing_at_all_is_not_a_post():
    assert parse(None) is None and parse("") is None


def test_a_url_on_another_site_is_not_a_post():
    assert parse("https://example.com/p/x") is None


def test_a_lookalike_host_is_not_instagram():
    """`instagram.com.evil.test` ends with the string but is another domain."""
    assert parse("https://instagram.com.evil.test/p/x") is None


# ------------------------------------------------------------------- links_in


def test_links_keep_their_order_lose_duplicates_and_their_punctuation():
    text = ("see https://www.instagram.com/reel/ABC/, and "
            "https://www.instagram.com/p/XYZ/ (same "
            "https://www.instagram.com/reel/ABC/)")
    assert links_in(text) == ["https://www.instagram.com/reel/ABC/",
                              "https://www.instagram.com/p/XYZ/"]


def test_text_without_a_link_has_no_links():
    assert links_in("nothing to open here") == []


def test_a_missing_message_has_no_links():
    assert links_in(None) == [] and links_in("") == []


def test_a_non_instagram_url_is_ignored():
    assert links_in("https://example.com/p/x and https://instagram.com.evil.test/p/x") == []


def test_a_plain_reel_url_in_a_message_is_found_as_written():
    assert links_in(f"look {REEL}") == [REEL]
