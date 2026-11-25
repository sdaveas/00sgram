"""Instagram's own JSON -> rows. No DOM, so every field here is exact."""
from __future__ import annotations

import json
import urllib.parse

from app import igd


def inbox_json(*threads) -> dict:
    return {"data": {"get_slide_mailbox_for_iris_subscription": {
        "threads_by_folder": {"edges": [{"node": {"as_ig_direct_thread": t}}
                                        for t in threads]}}}}


def inbox_thread(ig_id="1742", title="Mary Levine", group=False,
                 last_id="mid.3", last_ms=1_700_000_003_000, users=(),
                 last_text=None, last_kind=None, last_sender=None):
    node = {"id": last_id, "timestamp_ms": last_ms}
    if last_text is not None:
        node["text_body"] = last_text
    if last_kind is not None:
        node["content_type"] = last_kind
    if last_sender is not None:
        node["sender_fbid"] = last_sender
    return {"id": ig_id, "thread_title": title, "is_group": group,
            "last_activity_timestamp_ms": last_ms,
            "users": [{"interop_messaging_user_fbid": f,
                       "username": u, "full_name": u} for f, u in users],
            "viewer": {"interop_messaging_user_fbid": "me"},
            "slide_messages": {"edges": [{"node": node}]}}


def thread_json(*messages, users=(("peer", "mary__levine"),), viewer="me") -> dict:
    return {"data": {"get_slide_thread_nullable": {"as_ig_direct_thread": {
        "thread_title": "Mary Levine", "is_group": False,
        "viewer": {"interop_messaging_user_fbid": viewer},
        "users": [{"interop_messaging_user_fbid": f, "username": u,
                   "full_name": u} for f, u in users],
        "slide_messages": {"edges": [{"node": m} for m in messages]}}}}}


def message(mid, text="", ts=1_700_000_000_000, sender="peer", kind="TEXT", xma=None):
    node = {"id": mid, "timestamp_ms": ts, "sender_fbid": sender,
            "content_type": kind, "text_body": text, "content": {}}
    if xma is not None:
        node["content"] = {"xma": xma}
    return node


def test_the_inbox_is_threads_with_ids_and_real_timestamps():
    rows = igd.thread_rows(inbox_json(inbox_thread(users=(("peer", "mary__levine"),))))
    assert rows[0]["id"] == "1742"
    assert rows[0]["name"] == "Mary Levine"
    assert rows[0]["last_id"] == "mid.3"
    assert rows[0]["last_ts"] == 1_700_000_003.0
    assert rows[0]["users"] == {"peer": "mary__levine"}
    assert rows[0]["viewer"] == "me"
    assert rows[0]["group"] is False


def test_the_inbox_row_says_what_the_last_message_was():
    """The list needs a preview and whose it is; the relay never reads these."""
    bare = igd.thread_rows(inbox_json(inbox_thread(users=(("peer", "mary__levine"),))))
    assert (bare[0]["last_text"], bare[0]["last_kind"], bare[0]["last_mine"]) == \
        ("", "", False)

    ours = igd.thread_rows(inbox_json(inbox_thread(
        users=(("peer", "mary__levine"),), last_text="γεια", last_kind="TEXT",
        last_sender="me")))
    assert (ours[0]["last_text"], ours[0]["last_kind"], ours[0]["last_mine"]) == \
        ("γεια", "text", True)

    photo = igd.thread_rows(inbox_json(inbox_thread(
        users=(("peer", "mary__levine"),), last_kind="MEDIA")))
    assert photo[0]["last_text"] == "[φωτογραφία]"


def test_threads_are_newest_activity_first():
    rows = igd.thread_rows(inbox_json(
        inbox_thread("1", "old", last_ms=1_000), inbox_thread("2", "new", last_ms=2_000)))
    assert [r["id"] for r in rows] == ["2", "1"]


def test_a_text_message_is_text_and_its_sender():
    rows = igd.message_rows(thread_json(message("m1", "γεια")))
    assert rows == [{"id": "m1", "reactions": [], "ts": 1_700_000_000.0,
                     "mine": False, "sender": "mary__levine",
                     "text": "γεια", "url": ""}]


def test_our_own_message_is_recognised_by_the_viewer_id():
    rows = igd.message_rows(thread_json(message("m1", "τεστ", sender="me")))
    assert rows[0]["mine"] is True


def test_a_shared_post_carries_its_permalink_without_the_query():
    xma = {"__typename": "SlideMessageStandardXMA",
           "title_text": "kante like",
           "target_url": "https://www.instagram.com/p/Df-PG3ko/?is_sponsored=false"}
    rows = igd.message_rows(thread_json(message("m1", "", kind="MESSAGE_INLINE_SHARE",
                                                xma=xma)))
    assert rows[0]["text"] == "kante like"
    assert rows[0]["url"] == "https://www.instagram.com/p/Df-PG3ko/"


def test_a_photo_says_it_is_a_photo():
    rows = igd.message_rows(thread_json(message("m1", "", kind="MEDIA")))
    assert rows[0]["text"] == "[φωτογραφία]"


def test_a_message_with_nothing_to_show_is_not_a_message():
    xma = {"__typename": "SlideMessagePlaceholderX", "title_text": "Message unavailable"}
    rows = igd.message_rows(thread_json(message("m1", "", kind="MESSAGE_INLINE_SHARE",
                                                xma=xma)))
    assert [r["text"] for r in rows] == ["Message unavailable"]


def test_messages_come_out_oldest_first():
    rows = igd.message_rows(thread_json(message("b", "2", ts=2_000),
                                        message("a", "1", ts=1_000)))
    assert [r["text"] for r in rows] == ["1", "2"]


def test_the_template_keeps_its_parameters_and_swaps_only_the_variables():
    body = urllib.parse.urlencode({
        "doc_id": "123", "fb_dtsg": "tok",
        "variables": json.dumps({"thread_fbid": "1", "__relay_internal__x": False})})
    out = urllib.parse.parse_qs(igd._swap(body, {"thread_fbid": "999"}))
    variables = json.loads(out["variables"][0])
    assert variables == {"thread_fbid": "999", "__relay_internal__x": False}
    assert out["doc_id"] == ["123"] and out["fb_dtsg"] == ["tok"]


def test_a_replay_refreshes_a_rotated_doc_id_once():
    from app import store
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store.init(conn)

    class Page:
        def __init__(self):
            self.captured = 0
            self.calls = 0

        def capture(self, path, name):
            self.captured += 1
            return f"doc_id={self.captured}&variables=%7B%7D"

        def graphql(self, body):
            self.calls += 1
            if "doc_id=1&" in body:
                return json.dumps({"errors": [{"message": "invalid doc_id"}]})
            return json.dumps({"data": {"ok": True}})

    page = Page()
    direct = igd.Direct(page, conn)
    assert direct._call("PolarisDirectInboxQuery", "/direct/inbox/") == {"data": {"ok": True}}
    assert page.calls == 2 and page.captured == 2


def test_a_shared_post_title_loses_its_author_prefix():
    xma = {"title_text": "mary__levine kante like",
           "header_title_text": "mary__levine",
           "target_url": "https://www.instagram.com/p/ABC/"}
    rows = igd.message_rows(thread_json(message("m1", "", kind="MESSAGE_INLINE_SHARE",
                                                xma=xma)))
    assert rows[0]["text"] == "kante like"
