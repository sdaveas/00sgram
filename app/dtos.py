"""Wire types. No instagrapi object ever escapes `instagram.py`.

Everything here is what the store writes and the API reads, so the fields are
the columns of §Storage and nothing more. `kind_of` is the single place the
five content kinds are decided.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class AccountDTO:
    pk: str
    username: str
    full_name: str | None = None
    pic_url: str | None = None
    is_following: bool = True
    muted: bool = False


@dataclass(slots=True)
class ResourceDTO:
    idx: int
    type: str                      # image | video
    src_url: str | None = None
    poster_url: str | None = None
    w: int | None = None
    h: int | None = None
    duration: float | None = None


@dataclass(slots=True)
class PostDTO:
    pk: str
    account_pk: str
    media_type: int
    taken_at: int
    kind: str = ""                 # filled by kind_of() in __post_init__
    code: str | None = None
    product_type: str | None = None
    caption: str | None = None
    like_count: int | None = None
    comment_count: int | None = None
    permalink: str | None = None
    # Accounts tagged in the picture, collab authors, the place and the song —
    # the same list a story gets from its stickers, in the same shape.
    links: list[dict] | None = None
    resources: list[ResourceDTO] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.kind = kind_of(self.media_type, self.product_type)


@dataclass(slots=True)
class StoryDTO:
    pk: str
    account_pk: str
    media_type: int
    taken_at: int
    expiring_at: int
    src_url: str | None = None
    thumb_url: str | None = None
    duration: float | None = None
    # Stickers the author attached: profiles, music, links, hashtags, places.
    # A list of {"kind", "label", "url"?, "detail"?} — the viewer lists them.
    links: list[dict] | None = None


@dataclass(slots=True)
class TrayEntry:
    account_pk: str
    username: str | None = None
    latest_reel_media: int | None = None
    media_count: int | None = None       # exact segment count, measured present
    media_ids: list[str] = field(default_factory=list)
    seen: bool | None = None
    expiring_at: int | None = None
    ring_thumb: str | None = None


@dataclass(slots=True)
class Page:
    items: list[PostDTO]
    next_max_id: str | None = None
    more_available: bool = False


def kind_of(media_type: int, product_type: str | None = None) -> str:
    """Ordered precedence; the `photo` return is the total fallback.

    Measured: photos carry product_type 'feed', Reels 'clips'. media_type is
    checked before the generic fallback so an unknown product_type can never
    fail the NOT NULL/CHECK constraint in `posts.kind`.
    """
    if product_type == "clips":
        return "reel"
    if product_type == "igtv":
        return "igtv"
    if media_type == 8:
        return "carousel"
    if media_type == 2:
        return "video"
    return "photo"
