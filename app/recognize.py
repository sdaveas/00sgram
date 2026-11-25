"""What is this film playing? Shazam's fingerprinting, no account, no token.

The film arrives as bytes, ffmpeg turns it into twelve seconds of mono PCM, and
ShazamIO sends the signature to Shazam. The answer is a name — artist and title —
and that is all this module returns: the page turns it into a Spotify search, so
the program never needs to know how Spotify identifies a track and never holds a
Spotify login.

ponytail: ShazamIO speaks Shazam's mobile endpoint, which is not a public API.
If it starts answering differently, the button says "did not recognise it" and
the rest of the transport is untouched; the upgrade path is a paid fingerprinting
service behind the same `identify()` shape.
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path

CLIP_SECONDS = 12
TIMEOUT = 30
# How long a press may wait for an answer. ShazamIO's own default is twenty
# retries with up to 60 s of backoff on 429/5xx — a button is not allowed to sit
# behind that, so the client it builds is told so and the whole ask is capped.
WAIT = 20.0
# Nothing is uploaded, but ffmpeg still gets a whole file on disk; a reel is a
# few MB and one 858 MB cache entry once proved this needs a ceiling.
MAX_CLIP = 64_000_000


def to_wav(clip: bytes) -> bytes | None:
    """ffmpeg, because the fingerprint core decodes only some AAC profiles — a
    reel's HE-AAC made it raise `aac too complex` rather than guess."""
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "in", Path(tmp) / "out.wav"
        src.write_bytes(clip)
        try:
            subprocess.run(
                ["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(src),
                 "-t", str(CLIP_SECONDS), "-ac", "1", "-ar", "44100",
                 "-f", "wav", str(dst)],
                check=True, timeout=TIMEOUT)
        except (OSError, subprocess.SubprocessError):
            return None
        return dst.read_bytes() if dst.is_file() else None


def _shazam(wav: bytes) -> dict:
    from aiohttp_retry import ExponentialRetry
    from shazamio import Shazam
    from shazamio.client import HTTPClient

    async def ask():
        # Two attempts, four seconds of backoff at most: Shazam throttles by IP
        # when it feels hammered, and the honest answer then is "not now", not a
        # minute of silence.
        client = HTTPClient(retry_options=ExponentialRetry(
            attempts=2, max_timeout=4, statuses={429, 500, 502, 503, 504}))
        async with Shazam(http_client=client) as shazam:
            return await asyncio.wait_for(shazam.recognize(wav), timeout=WAIT)

    return asyncio.run(ask())


def identify(clip: bytes) -> dict:
    """`{found, artist, title}` or `{found: False, error}`.

    Never raises: "I don't know this song" is an answer, and a missing ffmpeg or
    a quiet reel must not become a 500 in a feed."""
    if shutil.which("ffmpeg") is None:
        return {"found": False, "error": "ffmpeg missing"}
    wav = to_wav(clip)
    if not wav:
        return {"found": False, "error": "undecodable"}
    try:
        out = _shazam(wav)
    except (TimeoutError, asyncio.TimeoutError):
        return {"found": False, "error": "timeout"}
    except Exception as exc:  # noqa: BLE001 — see the module docstring
        return {"found": False, "error": type(exc).__name__}
    track = out.get("track") or {}
    title = track.get("title")
    if not title:
        return {"found": False}
    return {"found": True, "artist": track.get("subtitle") or "", "title": title}
