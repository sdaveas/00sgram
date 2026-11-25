"""The seam. Everything above it (store, sync, API) is provider-agnostic.

`timeline_page` is the one method whose production implementation does not go
through instagrapi's Client: the mobile cursor is broken, so `instagram.py`
calls the web host directly (§Data source). Callers still see a `Page`.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from .dtos import AccountDTO, Page, PostDTO, StoryDTO, TrayEntry


class ProviderError(Exception):
    """Anything the provider could not do. Retry policy lives in sync.py."""


class SessionExpired(ProviderError):
    """Instagram rejected the session. Needs a human to paste a new cookie."""


@runtime_checkable
class Provider(Protocol):
    def connect(self) -> None: ...

    def following(self) -> tuple[list[AccountDTO], bool]:
        """Accounts, and whether the list is complete (pagination finished)."""

    def timeline_page(self, max_id: str | None) -> Page: ...

    # Read-only: how a link pasted in a chat becomes a card.
    def post_by_code(self, code: str) -> PostDTO | None: ...

    def story_tray(self) -> list[TrayEntry]: ...

    def user_stories(self, account_pk: str) -> list[StoryDTO]: ...

    def media_stream(self, url: str, byte_range: str | None) -> Iterator[bytes]: ...

    # Writes. The only part of this interface that changes state on Instagram,
    # so every one of them is idempotent and retried by nobody.
    def like(self, pk: str) -> None: ...

    def unlike(self, pk: str) -> None: ...

    def react_to_story(self, story_pk: str, emoji: str) -> None: ...


def get_provider(config, conn=None) -> Provider:
    """Factory. Imports lazily so `PROVIDER=mock` never needs instagrapi.

    `conn` is how the real provider resolves a cookie pasted in Settings
    (DB beats env), and where it persists device identity.
    """
    if config.provider == "mock":
        from .mock import MockProvider

        return MockProvider()
    if config.provider == "browser":
        from .browser import BrowserProvider, ThreadProxy

        # Behind a proxy because the browser is thread-affine: see ThreadProxy.
        return ThreadProxy(lambda: BrowserProvider(config, conn))
    if config.provider == "instagrapi":
        from .instagram import InstagrapiProvider

        return InstagrapiProvider(config, conn)
    raise ValueError(f"unknown provider {config.provider!r}")
