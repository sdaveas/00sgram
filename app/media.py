"""Media bytes: DB URL -> disk cache or upstream proxy, always with `Range`.

The browser only ever sees `/api/media/...`; upstream URLs stay in SQLite.
`media_stream` attaches the Instagram session, so every URL is host-checked
before any provider call (a tampered `src_url` would otherwise exfiltrate the
session).

`MEDIA_CACHE=1` stores the fetched bytes once and serves from disk. `=0`
proxies per request and writes nothing. `?size=t` resolves to the poster/thumb
URL the DB already has, else the full one — no re-encoding here:
ponytail: bytes are stored exactly as fetched; the 320px sync-time thumbnail is
step 6's job.
"""
from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Iterator
from email.utils import formatdate
from pathlib import Path
from urllib.parse import urlsplit

from fastapi.responses import Response, StreamingResponse

from . import store

ALLOWED_HOSTS = ("cdninstagram.com", "fbcdn.net")
CHUNK = 64 * 1024
IMMUTABLE = "public, max-age=31536000, immutable"
SNIFF = 16

EXT = {"image/jpeg": ".jpg", "video/mp4": ".mp4", "image/png": ".png",
       "image/webp": ".webp", "image/gif": ".gif"}


class RangeNotSatisfiable(Exception):
    pass


def host_allowed(url: str, provider: str) -> bool:
    parts = urlsplit(url)
    if provider == "mock" and parts.scheme == "mock":
        return True
    if parts.scheme != "https":
        return False
    host = (parts.hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)


def content_type(url: str, head: bytes) -> str:
    """Bytes first: CDN URLs are opaque and `mock://` has no suffix at all."""
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if head[:4] == b"GIF8":
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[4:8] == b"ftyp":
        return "video/mp4"
    suffix = Path(urlsplit(url).path).suffix.lower()
    return {".mp4": "video/mp4", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"
            }.get(suffix, "application/octet-stream")


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """None means "serve the whole body". Raises when the range is out of bounds."""
    if not header:
        return None
    unit, _, spec = header.partition("=")
    if unit.strip().lower() != "bytes" or "," in spec:
        return None                      # multi-range: legal to ignore, send the lot
    first, sep, last = spec.strip().partition("-")
    if not sep:
        return None
    try:
        if not first:
            want = int(last)
            if want <= 0:
                raise RangeNotSatisfiable
            start, end = max(0, size - want), size - 1
        else:
            start = int(first)
            end = int(last) if last else size - 1
    except ValueError:
        return None
    if start < 0 or end < start or start >= size:
        raise RangeNotSatisfiable
    return start, min(end, size - 1)


def unavailable() -> Response:
    """Never JSON, never cacheable: an `<img>` is waiting for bytes."""
    return Response(status_code=404, headers={"Cache-Control": "no-store"})


def _base_headers() -> dict[str, str]:
    return {"Accept-Ranges": "bytes"}


def _partial(body: bytes, ctype: str, header: str | None,
             headers: dict[str, str]) -> Response:
    size = len(body)
    try:
        rng = parse_range(header, size)
    except RangeNotSatisfiable:
        return Response(status_code=416,
                        headers={**headers, "Accept-Ranges": "bytes",
                                 "Content-Range": f"bytes */{size}"})
    if rng is None:
        return Response(body, media_type=ctype,
                        headers={**headers, "Content-Length": str(size)})
    start, end = rng
    chunk = body[start:end + 1]
    return Response(chunk, status_code=206, media_type=ctype, headers={
        **headers, "Content-Range": f"bytes {start}-{end}/{size}",
        "Content-Length": str(len(chunk))})


def _slice_path(path: Path, ctype: str, header: str | None,
                headers: dict[str, str]) -> Response:
    size = path.stat().st_size
    try:
        rng = parse_range(header, size)
    except RangeNotSatisfiable:
        return Response(status_code=416,
                        headers={**headers, "Accept-Ranges": "bytes",
                                 "Content-Range": f"bytes */{size}"})
    if rng is None:
        return StreamingResponse(_chunks(path), media_type=ctype,
                                 headers={**headers, "Content-Length": str(size)})
    start, end = rng
    with path.open("rb") as fh:
        fh.seek(start)
        chunk = fh.read(end - start + 1)
    return Response(chunk, status_code=206, media_type=ctype, headers={
        **headers, "Content-Range": f"bytes {start}-{end}/{size}",
        "Content-Length": str(len(chunk))})


def _chunks(path: Path) -> Iterator[bytes]:
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            yield chunk


class MediaStore:
    """One instance per app. Endpoints are sync, so FastAPI already runs them
    in the threadpool — upstream fetches never touch the event loop."""

    def __init__(self, config, conn) -> None:
        self.config = config
        self.conn = conn
        self.root = Path(config.data_dir) / "media"
        self.budget_bytes = config.media_budget_mb * 1024 * 1024
        self._provider = None

    @property
    def provider(self):
        """Lazy: PROJECT=instagrapi must not import the provider to answer a
        404, and a rejected host never gets here at all."""
        if self._provider is None:
            from .provider import get_provider

            self._provider = get_provider(self.config, self.conn)
            self._provider.connect()
        return self._provider

    @provider.setter
    def provider(self, value) -> None:
        self._provider = value

    # ------------------------------------------------------------------ serve

    def serve(self, *, kind: str, pk: str, url: str | None,
              range_header: str | None) -> Response:
        if not url or not host_allowed(url, self.config.provider):
            return unavailable()
        ref = f"{pk}:{hashlib.sha1(url.encode()).hexdigest()[:8]}"

        if self.config.media_cache:
            row = self._cached(kind, ref)
            if row is not None:
                self._touch(row["id"])
                path = Path(row["path"])
                return _slice_path(path, content_type(str(path), _head(path)),
                                   range_header,
                                   {**_base_headers(), **_file_meta(path, ref)})

        data = self._fetch(url)
        if data is None:
            return unavailable()
        ctype = content_type(url, data[:SNIFF])
        headers = {**_base_headers(), "Cache-Control": IMMUTABLE,
                   "ETag": f'"{ref}"'}
        if not self.config.media_cache:
            return _partial(data, ctype, range_header,
                            {**_base_headers(), "Cache-Control": "private, max-age=0"})
        path = self._write(kind, url, data, ctype)
        self._record(kind, ref, path, len(data))
        self.evict()
        return _partial(data, ctype, range_header, headers)

    def bytes_for(self, *, kind: str, pk: str, url: str | None) -> tuple[bytes, str] | None:
        """The whole file, for a caller that is not a browser range request —
        today only the song recogniser. Cached bytes are reused; anything else is
        fetched once and cached the way `serve()` would.

        ponytail: a film that was never watched here is downloaded from the
        provider on the spot. Fine for one press; give it a queue if recognition
        ever becomes a bulk job."""
        if not url or not host_allowed(url, self.config.provider):
            return None
        ref = f"{pk}:{hashlib.sha1(url.encode()).hexdigest()[:8]}"
        if self.config.media_cache:
            row = self._cached(kind, ref)
            if row is not None:
                self._touch(row["id"])
                path = Path(row["path"])
                return path.read_bytes(), content_type(str(path), _head(path))
        data = self._fetch(url)
        if data is None:
            return None
        ctype = content_type(url, data[:SNIFF])
        if self.config.media_cache:
            path = self._write(kind, url, data, ctype)
            self._record(kind, ref, path, len(data))
            self.evict()
        return data, ctype

    # ------------------------------------------------------------------ cache

    def _cached(self, kind: str, ref: str):
        row = self.conn.execute(
            "SELECT id, path FROM media_cache WHERE kind=? AND ref=?",
            (kind, ref)).fetchone()
        if row is None:
            return None
        if not Path(row["path"]).is_file():
            with store.write(self.conn):
                self.conn.execute("DELETE FROM media_cache WHERE id=?", (row["id"],))
            return None
        return row

    def prune(self) -> int:
        """Drop rows whose file is gone.

        The archive asks this table which posts it can still show, so a row
        without bytes is a lie that paints a black card. One stat per row, once
        at boot.
        """
        rows = list(self.conn.execute("SELECT id, path FROM media_cache"))
        dead = [r["id"] for r in rows if not Path(r["path"]).is_file()]
        live = {r["path"] for r in rows if r["id"] not in set(dead)}
        if dead:
            with store.write(self.conn):
                self.conn.executemany("DELETE FROM media_cache WHERE id=?",
                                      [(i,) for i in dead])
        self._sweep_orphans(live)
        return len(dead)

    def _sweep_orphans(self, live: set[str], older_than: int = 3600) -> int:
        """Delete files no row points at.

        A row deleted without its file (or a write whose record failed) leaves
        bytes that no query can ever reach — and they count against the cap from
        underneath, so the budget says one thing and the disk another.
        Fresh files are left alone: a write in flight has bytes before it has a row.
        """
        now = time.time()
        dropped = 0
        for path in self.root.rglob("*"):
            if not path.is_file() or str(path) in live or path.name.endswith(".tmp"):
                continue
            try:
                if now - path.stat().st_mtime < older_than:
                    continue
                path.unlink()
                dropped += 1
            except OSError:
                pass
        return dropped

    def _touch(self, row_id: int) -> None:
        with store.write(self.conn):
            self.conn.execute("UPDATE media_cache SET last_access=? WHERE id=?",
                              (int(time.time()), row_id))

    def _write(self, kind: str, url: str, data: bytes, ctype: str) -> Path:
        folder = self.root / kind
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (hashlib.sha1(url.encode()).hexdigest()
                         + EXT.get(ctype, ".bin"))
        # A unique temporary name per write: two cards asking for the same file
        # at once used to share one `.tmp`, and the loser's rename blew up as a
        # 500 on a picture that was sitting right there.
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        return path

    def _record(self, kind: str, ref: str, path: Path, size: int) -> None:
        now = int(time.time())
        with store.write(self.conn):
            self.conn.execute(
                "INSERT INTO media_cache (kind, ref, path, bytes, last_access)"
                " VALUES (?,?,?,?,?) ON CONFLICT(kind, ref) DO UPDATE SET"
                " path=excluded.path, bytes=excluded.bytes,"
                " last_access=excluded.last_access",
                (kind, ref, str(path), size, now))

    def evict(self) -> int:
        """One LRU across kinds. Oldest `last_access` goes first."""
        rows = list(self.conn.execute(
            "SELECT id, path, bytes FROM media_cache ORDER BY last_access, id"))
        total = sum(int(r["bytes"]) for r in rows)
        dropped = []
        for row in rows:
            if total <= self.budget_bytes:
                break
            total -= int(row["bytes"])
            dropped.append(row)
        if not dropped:
            return 0
        with store.write(self.conn):
            for row in dropped:
                self.conn.execute("DELETE FROM media_cache WHERE id=?", (row["id"],))
        for row in dropped:
            try:
                Path(row["path"]).unlink()
            except OSError:
                pass
        return len(dropped)

    # --------------------------------------------------------------- upstream

    def _fetch(self, url: str) -> bytes | None:
        """ponytail: broad catch on purpose — provider error, missing module and
        a dead session all mean the same thing to an `<img>`: 404."""
        try:
            data = b"".join(self.provider.media_stream(url, None))
        except Exception:
            return None
        return data or None


def _head(path: Path) -> bytes:
    with path.open("rb") as fh:
        return fh.read(SNIFF)


def _file_meta(path: Path, ref: str) -> dict[str, str]:
    stat = path.stat()
    return {"ETag": f'"{ref}-{stat.st_size:x}"',
            "Last-Modified": formatdate(stat.st_mtime, usegmt=True),
            "Cache-Control": IMMUTABLE}
