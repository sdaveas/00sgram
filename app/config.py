"""Environment -> Config. Every value is validated here, once, at startup.

Env seeds a setting a single time (INSERT OR IGNORE); after that the `settings`
row is the only source of truth (§Settings precedence). Env is still the source
for process-level things: paths, ports, the session cookie.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

KINDS = ("photo", "video", "carousel", "reel", "igtv")


class ConfigError(ValueError):
    """A required variable is missing or out of range. Never silently defaulted."""


def _int(env: dict[str, str], key: str, default: int, lo: int, hi: int) -> int:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        val = int(raw)
    except ValueError:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from None
    if not lo <= val <= hi:
        raise ConfigError(f"{key} must be {lo}..{hi}, got {val}")
    return val


def _bool(env: dict[str, str], key: str, default: bool) -> bool:
    raw = env.get(key, "").strip().lower()
    if not raw:
        return default
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{key} must be 0 or 1, got {raw!r}")


def _required(env: dict[str, str], key: str) -> str:
    val = env.get(key, "").strip()
    if not val:
        raise ConfigError(f"{key} is required")
    return val


def _types(env: dict[str, str]) -> tuple[str, ...]:
    raw = env.get("TYPES", "").strip() or ",".join(KINDS)
    picked = tuple(t.strip() for t in raw.split(",") if t.strip())
    unknown = set(picked) - set(KINDS)
    if unknown or not picked:
        raise ConfigError(f"TYPES must be a non-empty subset of {KINDS}, got {raw!r}")
    return picked


@dataclass(frozen=True)
class Config:
    data_dir: Path
    backup_dir: Path
    provider: str
    ig_session_cookie: str
    api_token: str
    app_password: str
    app_secret: str
    cookie_secure: bool
    tz: str
    sync_interval: int
    sync_max_pages: int
    backfill_days: int
    backfill_pages: int
    backfill_sleep: int
    view_threshold_ms: int
    media_cache: bool
    media_budget_mb: int
    media_retention_days: int
    types: tuple[str, ...] = field(default=KINDS)
    hide_muted: bool = True
    story_auto_advance_accounts: bool = False
    # PROVIDER=browser: either drive a Chrome that is already running, or own a
    # persistent Chromium profile (the Pi deployment). The profile is the
    # credential, so it never leaves the machine it lives on.
    browser_cdp: str = ""
    browser_profile: Path = Path("")
    browser_headless: bool = True
    # Optional: without it the Telegram surface is simply off, never an error.
    telegram_token: str = ""
    # The group the inbox is mirrored into. Empty: the relay stays off.
    relay_chat: str = ""
    relay_fast: int = 60        # seconds between looks while a chat is active
    relay_slow: int = 600       # and while nothing is happening
    relay_active: int = 900     # how long a new message keeps it fast
    # Two-way: what is typed in a topic is written to Instagram as the account.
    # Off by default; it is the only path that writes to Instagram.
    relay_send: bool = False
    # WhatsApp relay. A separate group on purpose: topics are keyed by the
    # conversation's *name*, and both apps have a "Μαμά". Empty: the relay is off.
    wa_relay_chat: str = ""
    wa_relay_send: bool = False
    wa_relay_fast: int = 20     # seconds between looks while a chat is active
    wa_relay_slow: int = 90     # and while nothing is happening
    # The chat sync loop: seconds between walks of the DM list. 0 turns it off.
    chat_sync_interval: int = 120
    # Opening a conversation to read the shared post behind a preview. That is a
    # read receipt on Instagram, and the only way to relay a link.

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Config":
        env = dict(os.environ if env is None else env)
        data_dir = Path(env.get("DATA_DIR", "/data"))
        backup_dir = Path(env.get("BACKUP_DIR") or data_dir / "backups")
        provider = env.get("PROVIDER", "instagrapi").strip()
        if provider not in ("instagrapi", "browser", "mock"):
            raise ConfigError(
                f"PROVIDER must be instagrapi, browser or mock, got {provider!r}")
        # The cookie is only needed by the real provider, and it may arrive from
        # Settings (meta) after startup: a missing one must not stop the app from
        # booting. `connect()` refuses with a clear message instead.
        cookie = env.get("IG_SESSION_COOKIE", "").strip()
        secret = _required(env, "APP_SECRET")
        if len(secret) < 32:
            raise ConfigError("APP_SECRET must be at least 32 characters")
        return cls(
            data_dir=data_dir,
            backup_dir=backup_dir,
            provider=provider,
            ig_session_cookie=cookie,
            api_token=_required(env, "API_TOKEN"),
            app_password=_required(env, "APP_PASSWORD"),
            app_secret=secret,
            cookie_secure=_bool(env, "COOKIE_SECURE", False),
            tz=env.get("TZ", "Europe/Athens").strip() or "Europe/Athens",
            sync_interval=_int(env, "SYNC_INTERVAL", 1800, 300, 86400),
            sync_max_pages=_int(env, "SYNC_MAX_PAGES", 10, 1, 50),
            backfill_days=_int(env, "BACKFILL_DAYS", 7, 1, 50),
            # A deep history walk: 40 pages is roughly 400 posts for 40 requests.
            backfill_pages=_int(env, "BACKFILL_PAGES", 40, 1, 200),
            # Seconds between pages. Faster than a person scrolls reads as
            # automation; 2 s costs 80 s across a 40-page walk.
            backfill_sleep=_int(env, "BACKFILL_SLEEP", 2, 0, 60),
            view_threshold_ms=_int(env, "VIEW_THRESHOLD_MS", 1000, 0, 10000),
            media_cache=_bool(env, "MEDIA_CACHE", True),
            media_budget_mb=_int(env, "MEDIA_BUDGET_MB", 800, 0, 100_000),
            media_retention_days=_int(env, "MEDIA_RETENTION_DAYS", 30, 1, 3650),
            types=_types(env),
            hide_muted=_bool(env, "HIDE_MUTED", True),
            story_auto_advance_accounts=_bool(env, "STORY_AUTO_ADVANCE", False),
            browser_cdp=env.get("BROWSER_CDP", "").strip(),
            browser_profile=Path(env.get("BROWSER_PROFILE") or data_dir / "browser-profile"),
            browser_headless=_bool(env, "BROWSER_HEADLESS", False),
            telegram_token=env.get("TELEGRAM_TOKEN", "").strip(),
            relay_chat=env.get("TELEGRAM_RELAY_CHAT", "").strip(),
            relay_fast=_int(env, "IG_RELAY_FAST", 60, 15, 3600),
            relay_slow=_int(env, "IG_RELAY_SLOW", 600, 60, 86400),
            relay_active=_int(env, "IG_RELAY_ACTIVE", 900, 0, 86400),
            relay_send=_bool(env, "IG_RELAY_SEND", False),
            wa_relay_chat=env.get("WA_RELAY_CHAT", "").strip(),
            wa_relay_send=_bool(env, "WA_RELAY_SEND", False),
            wa_relay_fast=_int(env, "WA_RELAY_FAST", 20, 5, 3600),
            wa_relay_slow=_int(env, "WA_RELAY_SLOW", 90, 10, 86400),
            chat_sync_interval=_int(env, "CHAT_SYNC_INTERVAL", 120, 0, 86400),
        )

    def seed_values(self) -> dict[str, object]:
        """The five `settings` rows env is allowed to seed, once ever."""
        return {
            "sync_interval": self.sync_interval,
            "view_threshold_ms": self.view_threshold_ms,
            "story_auto_advance_accounts": int(self.story_auto_advance_accounts),
            "types": ",".join(self.types),
            "hide_muted": int(self.hide_muted),
        }
