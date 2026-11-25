"""Deterministic synthetic Instagram. Same seed -> same accounts, posts, stories.

Emits real bytes, not placeholder URLs: JPEGs drawn with Pillow and a tiny MP4
embedded below as base64 (generated once with
`ffmpeg -f lavfi -i color=c=black:s=320x568:d=3:r=10 -b:v 6k -movflags +faststart`).
So the media tests exercise Range, caching and video the same way production does.
"""
from __future__ import annotations

import base64
import hashlib
import io
import random
import time
from collections.abc import Iterator
from dataclasses import replace

from .dtos import AccountDTO, Page, PostDTO, ResourceDTO, StoryDTO, TrayEntry

MP4_B64 = """
AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDEAAASibW9vdgAAAGxtdmhkAAAAAAAAAAAA
AAAAAAAD6AAAC7gAAQAAAQAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAA
AABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAAA810cmFrAAAAXHRraGQAAAADAAAA
AAAAAAAAAAABAAAAAAAAC7gAAAAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAA
AAAAAAAAAABAAAAAAUAAAAI4AAAAAAAkZWR0cwAAABxlbHN0AAAAAAAAAAEAAAu4AAAIAAABAAAA
AANFbWRpYQAAACBtZGhkAAAAAAAAAAAAAAAAAAAoAAAAeABVxAAAAAAALWhkbHIAAAAAAAAAAHZp
ZGUAAAAAAAAAAAAAAABWaWRlb0hhbmRsZXIAAAAC8G1pbmYAAAAUdm1oZAAAAAEAAAAAAAAAAAAA
ACRkaW5mAAAAHGRyZWYAAAAAAAAAAQAAAAx1cmwgAAAAAQAAArBzdGJsAAAAwHN0c2QAAAAAAAAA
AQAAALBhdmMxAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAAUACOABIAAAASAAAAAAAAAABFExhdmM2
My4xLjEwMiBsaWJ4MjY0AAAAAAAAAAAAAAAAGP//AAAANmF2Y0MBZAAV/+EAGmdkABWs2UFASflw
EQAAAwABAAADABQPFi2WAQAFaOvssiz9+PgAAAAAEHBhc3AAAAABAAAAAQAAABRidHJ0AAAAAAAA
F3AAAA4gAAAAGHN0dHMAAAAAAAAAAQAAAB4AAAQAAAAAFHN0c3MAAAAAAAAAAQAAAAEAAAEAY3R0
cwAAAAAAAAAeAAAAAQAACAAAAAABAAAUAAAAAAEAAAgAAAAAAQAAAAAAAAABAAAEAAAAAAEAABQA
AAAAAQAACAAAAAABAAAAAAAAAAEAAAQAAAAAAQAAFAAAAAABAAAIAAAAAAEAAAAAAAAAAQAABAAA
AAABAAAUAAAAAAEAAAgAAAAAAQAAAAAAAAABAAAEAAAAAAEAABQAAAAAAQAACAAAAAABAAAAAAAA
AAEAAAQAAAAAAQAAFAAAAAABAAAIAAAAAAEAAAAAAAAAAQAABAAAAAABAAAUAAAAAAEAAAgAAAAA
AQAAAAAAAAABAAAEAAAAAAEAAAgAAAAAHHN0c2MAAAAAAAAAAQAAAAEAAAAeAAAAAQAAAIxzdHN6
AAAAAAAAAAAAAAAeAAADBAAAABAAAAAQAAAAEAAAABAAAAAWAAAAEgAAABAAAAAQAAAAFgAAABIA
AAAQAAAAEAAAABYAAAASAAAAEAAAABAAAAAWAAAAEgAAABAAAAAQAAAAWAAAABIAAAARAAAAEAAA
ABYAAAARAAAAEAAAABAAAAAWAAAAFHN0Y28AAAAAAAAAAQAABNIAAABhdWR0YQAAAFltZXRhAAAA
AAAAACFoZGxyAAAAAAAAAABtZGlyYXBwbAAAAAAAAAAAAAAAACxpbHN0AAAAJKl0b28AAAAcZGF0
YQAAAAEAAAAATGF2ZjYzLjEuMTAyAAAACGZyZWUAAAVUbWRhdAAAArwGBf//uNxF6b3m2Ui3lizY
INkj7u94MjY0IC0gY29yZSAxNjUgcjMyMjIgYjM1NjA1YSAtIEguMjY0L01QRUctNCBBVkMgY29k
ZWMgLSBDb3B5bGVmdCAyMDAzLTIwMjUgLSBodHRwOi8vd3d3LnZpZGVvbGFuLm9yZy94MjY0Lmh0
bWwgLSBvcHRpb25zOiBjYWJhYz0xIHJlZj0zIGRlYmxvY2s9MTowOjAgYW5hbHlzZT0weDM6MHgx
MTMgbWU9aGV4IHN1Ym1lPTcgcHN5PTEgcHN5X3JkPTEuMDA6MC4wMCBtaXhlZF9yZWY9MSBtZV9y
YW5nZT0xNiBjaHJvbWFfbWU9MSB0cmVsbGlzPTEgOHg4ZGN0PTEgY3FtPTAgZGVhZHpvbmU9MjEs
MTEgZmFzdF9wc2tpcD0xIGNocm9tYV9xcF9vZmZzZXQ9LTIgdGhyZWFkcz0xOCBsb29rYWhlYWRf
dGhyZWFkcz0zIHNsaWNlZF90aHJlYWRzPTAgbnI9MCBkZWNpbWF0ZT0xIGludGVybGFjZWQ9MCBi
bHVyYXlfY29tcGF0PTAgY29uc3RyYWluZWRfaW50cmE9MCBiZnJhbWVzPTMgYl9weXJhbWlkPTIg
Yl9hZGFwdD0xIGJfYmlhcz0wIGRpcmVjdD0xIHdlaWdodGI9MSBvcGVuX2dvcD0wIHdlaWdodHA9
MiBrZXlpbnQ9MjUwIGtleWludF9taW49MTAgc2NlbmVjdXQ9NDAgaW50cmFfcmVmcmVzaD0wIHJj
X2xvb2thaGVhZD00MCByYz1hYnIgbWJ0cmVlPTEgYml0cmF0ZT02IHJhdGV0b2w9MS4wIHFjb21w
PTAuNjAgcXBtaW49MCBxcG1heD02OSBxcHN0ZXA9NCBpcF9yYXRpbz0xLjQwIGFxPTE6MS4wMACA
AAAAQGWIhAAYfyQNzkAAAAMAHMxTOkZKw8AAAAMAAAMAAAMAAAMAAAMAAAMAAAMAAAMAAAMAAAMA
AAMAAAMAAAMAB60AAAAMQZokbEGHAAADABqQAAAADEGeQniDLwAAAwAoIQAAAAwBnmF0QZcAAAMA
KCAAAAAMAZ5jakGXAAADACghAAAAEkGaaEmoQWiZTAgo/wAAAwAUkQAAAA5BnoZFESwYfwAAAwAo
IQAAAAwBnqV0QZcAAAMAKCEAAAAMAZ6nakGHAAADACggAAAAEkGarEmoQWyZTAgg/wAAAwAMWAAA
AA5BnspFFSwUfwAAAwAk4QAAAAwBnul0QWcAAAMAJuAAAAAMAZ7rakFHAAADACTgAAAAEkGa8Emo
QWyZTAhr/wAAAwAHdQAAAA5Bnw5FFSwRfwAAAwAi4QAAAAwBny10QScAAAMAI+EAAAAMAZ8vakEX
AAADACLgAAAAEkGbNEmoQWyZTAhj/wAAAwAGBAAAAA5Bn1JFFSw9/wAAAwAg4QAAAAwBn3F0QQcA
AAMAIeAAAAAMAZ9zakEHAAADACHgAAAAVEGbeEmoQWyZTAiP2gX/Wu360QJtLkXMirx9a+GCYNFg
eaCIbA1pc3WIAB5AB5pGhQyeS5AAAAMAAAMAAAMAAAMAAAMAAAMAAAMAAAMAAAMAAAMD6wAAAA5B
n5ZFFSwl//FCEAACggAAAA0Bn7V0Q1/ygAAAAwLvAAAADAGft2pCXwAAAwAZkQAAABJBm7xJqEFs
mUwJvwAAAwAATMAAAAANQZ/aRRUsVwAAAwAS8QAAAAwBn/l0Rn8AAAMAFbAAAAAMAZ/7akV/AAAD
ABLxAAAAEkGb/UmoQWyZTAm/AAADAABMwQ==
"""

PAGE_SIZE = 3          # production measured ~2.5 posts/page; keep the mock just as thin
ACCOUNTS = 12


def _mock_links(account_pk: str, k: int) -> list[dict]:
    """Enough sticker variety that the viewer's link panel has every group."""
    if k == 0:
        return [{"kind": "profile", "label": f"user{account_pk}", "url": None,
                 "detail": "mentioned"},
                {"kind": "music", "label": "Theme From \"Friends\"", "url": None,
                 "detail": "The Rembrandts"},
                {"kind": "url", "label": "youtube.com/live", "url": "https://youtube.com/live/x",
                 "detail": None},
                {"kind": "hashtag", "label": "#athens", "url": None, "detail": None},
                {"kind": "place", "label": "Athens", "url": None, "detail": "Greece"}]
    if k == 2:
        return [{"kind": "music", "label": "One song", "url": None, "detail": "An artist"}]
    return []


class MockProvider:
    def __init__(self, seed: int = 7, now: int | None = None,
                 page_size: int = PAGE_SIZE, accounts: int = ACCOUNTS) -> None:
        self.seed = seed
        self.now = int(now if now is not None else time.time())
        self.page_size = page_size
        self._rng = random.Random(seed)
        self._mp4: bytes | None = None
        self._story_seen: set[str] = set()
        self.liked: set[str] = set()
        self.reactions: dict[str, str] = {}
        self.unfollowed: set[str] = set()
        self._build(accounts)

    # ---------------------------------------------------------------- fixture

    def _build(self, count: int) -> None:
        rng = self._rng
        names = ["athens", "luben", "souvlaki", "naxos", "reels", "film", "books",
                 "coffee", "hike", "studio", "radio", "kitchen"]
        self.accounts: list[AccountDTO] = []
        self.posts: dict[str, list[PostDTO]] = {}
        for i in range(count):
            pk = str(10_000_000 + i)
            name = f"{names[i % len(names)]}{i}"
            self.accounts.append(AccountDTO(
                pk=pk, username=name, full_name=name.title(),
                pic_url=f"mock://avatar/{pk}", is_following=True,
                muted=i == 5))
            posts: list[PostDTO] = []
            for j in range(rng.randint(3, 6)):
                mt, pt = rng.choice([(1, "feed"), (1, "feed"), (8, "feed"),
                                     (2, "clips"), (2, "igtv")])
                taken = self.now - rng.randint(0, 13 * 86400) - j * 3600
                pkp = f"{pk}{j:03d}"
                kind_n = 2 if mt == 8 else 1
                res = []
                for k in range(kind_n):
                    type_ = "video" if (mt == 2 or k > 0 and rng.random() < 0.5) else "image"
                    res.append(ResourceDTO(
                        idx=k, type=type_,
                        # The path decides the bytes: `mock://video/...` is MP4,
                        # so a resource typed video really is a video.
                        src_url=f"mock://{type_}/{pkp}/{k}",
                        poster_url=f"mock://post/{pkp}/{k}?poster=1",
                        w=1080, h=1080 if k else 1350,
                        duration=12.0 if type_ == "video" else None,
                    ))
                posts.append(PostDTO(
                    pk=pkp, account_pk=pk, media_type=mt, product_type=pt,
                    taken_at=taken, code=f"C{pkp}",
                    caption=f"{name} post {j}", like_count=rng.randint(0, 900),
                    comment_count=rng.randint(0, 40),
                    permalink=f"https://www.instagram.com/p/C{pkp}/",
                    resources=res,
                ))
            self.posts[pk] = sorted(posts, key=lambda p: p.taken_at, reverse=True)

        # Ranked, not chronological: a stable pseudo-shuffle over all posts.
        every = [p for ps in self.posts.values() for p in ps]
        every.sort(key=lambda p: (hashlib.sha1(f"{self.seed}:{p.pk}".encode()).hexdigest(),
                                  -p.taken_at))
        self.feed = every
        self.tray_entries = [
            TrayEntry(account_pk=a.pk, username=a.username,
                      latest_reel_media=self.now - i * 1800,
                      media_count=(i % 4) + 1,
                      media_ids=[f"s{a.pk}{k}" for k in range((i % 4) + 1)],
                      seen=False, expiring_at=self.now + 3600,
                      ring_thumb=f"mock://avatar/{a.pk}")
            for i, a in enumerate(self.accounts[:6])
        ]

    # ---------------------------------------------------------------- protocol

    def connect(self) -> None:
        pass

    def following(self) -> tuple[list[AccountDTO], bool]:
        return list(self.accounts), True

    def timeline_page(self, max_id: str | None) -> Page:
        start = int(max_id) if max_id else 0
        chunk = self.feed[start:start + self.page_size]
        nxt = start + self.page_size
        return Page(items=[_copy(p) for p in chunk],
                    next_max_id=str(nxt) if nxt < len(self.feed) else None,
                    more_available=nxt < len(self.feed))

    def post_by_code(self, code: str) -> PostDTO | None:
        hit = next((p for p in self.feed if p.code == code), None)
        return _copy(hit) if hit is not None else None

    def story_tray(self) -> list[TrayEntry]:
        # Fetching segments marks them seen, exactly like the real API.
        return [replace(e, seen=e.account_pk in self._story_seen)
                for e in self.tray_entries]

    def user_stories(self, account_pk: str) -> list[StoryDTO]:
        self._story_seen.add(account_pk)
        n = next((e.media_count for e in self.tray_entries
                  if e.account_pk == account_pk), None) or 2
        expiring = self.now + 3600
        return [
            StoryDTO(pk=f"s{account_pk}{k}", account_pk=account_pk,
                     media_type=2 if k % 3 == 2 else 1,
                     taken_at=self.now - (n - k) * 900, expiring_at=expiring,
                     src_url=f"mock://story/s{account_pk}{k}",
                     thumb_url=f"mock://story/s{account_pk}{k}?thumb=1",
                     duration=8.0 if k % 3 == 2 else None,
                     links=_mock_links(account_pk, k))
            for k in range(n)
        ]

    def like(self, pk: str) -> None:
        self.liked.add(pk)

    def unlike(self, pk: str) -> None:
        self.liked.discard(pk)

    def unfollow(self, account_pk: str) -> None:
        self.unfollowed.add(account_pk)
        self.accounts = [replace(a, is_following=False) if a.pk == account_pk else a
                         for a in self.accounts]

    def react_to_story(self, story_pk: str, emoji: str) -> None:
        self.reactions[story_pk] = emoji

    def media_stream(self, url: str, byte_range: str | None = None) -> Iterator[bytes]:
        # Same allowlist as production, one host scheme: mock:// and nothing else.
        if not url.startswith("mock://"):
            from .provider import ProviderError

            raise ProviderError(f"mock provider got a non-mock URL: {url[:32]!r}")
        data = self.media_bytes(url)
        if byte_range:
            start, end = _parse_range(byte_range, len(data))
            return iter([data[start:end + 1]])
        return iter([data])

    # ------------------------------------------------------------------ bytes

    def media_bytes(self, url: str) -> bytes:
        if url.startswith("mock://post/") and "poster=" not in url:
            path = url[len("mock://post/"):].rsplit("/", 1)[0]
            return _jpeg(1080, 1350, path)
        if url.startswith("mock://story/"):
            return _jpeg(1080, 1920, url.split("?")[0])
        if url.startswith("mock://avatar/"):
            return _jpeg(256, 256, url.rsplit("/", 1)[-1])
        if url.endswith(".mp4") or "video" in url:
            return self._video()
        return _jpeg(1080, 1080, url)

    def video_bytes(self) -> bytes:
        return self._video()

    def _video(self) -> bytes:
        if self._mp4 is None:
            self._mp4 = base64.b64decode("".join(MP4_B64.split()))
        return self._mp4


def _copy(p: PostDTO) -> PostDTO:
    return PostDTO(
        pk=p.pk, account_pk=p.account_pk, media_type=p.media_type,
        taken_at=p.taken_at, product_type=p.product_type, code=p.code,
        caption=p.caption, like_count=p.like_count,
        comment_count=p.comment_count, permalink=p.permalink,
        resources=[replace(r) for r in p.resources],
    )


def _jpeg(w: int, h: int, seed: str) -> bytes:
    """A picture-shaped placeholder: two seeded colours, a soft disc, no text.

    The stripes this used to draw read as a broken image everywhere the demo is
    seen (README screenshots, a seeded deck on a friend's machine), and a
    gradient costs the same two minutes of code.
    """
    from PIL import Image, ImageDraw

    d = hashlib.sha1(seed.encode()).digest()
    top, bot = (d[0], d[1], d[2]), (d[3], d[4], d[5])
    strip = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        strip.putpixel((0, y), tuple(int(top[i] + (bot[i] - top[i]) * t)
                                     for i in range(3)))
    img = strip.resize((w, h)).convert("RGBA")
    disc = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(disc).ellipse([w * 0.12, h * 0.28, w * 0.88, h * 0.78],
                                 fill=(255, 255, 255, 30))
    img = Image.alpha_composite(img, disc).convert("RGB")
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=80)
    return out.getvalue()


def _parse_range(header: str, size: int) -> tuple[int, int]:
    spec = header.split("=", 1)[1]
    first, _, last = spec.partition("-")
    start = int(first) if first else 0
    end = int(last) if last else size - 1
    return max(0, start), min(size - 1, end)
