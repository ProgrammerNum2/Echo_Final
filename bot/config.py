from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .languages import normalize


class ConfigError(Exception):
    pass


def _load_dotenv(path: str = ".env") -> None:
    p = Path(path)
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = _env(name)
        if value:
            return value
    return default


def _int(name: str, default: int, minimum: int = 1) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from None
    if value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}")
    return value


@dataclass(frozen=True)
class Config:
    bot_token: str
    owner_username: str
    owner_display_name: str
    owner_language: str
    db_path: str
    providers: list[str]
    gemini_api_key: str
    gemini_model: str
    deepl_api_key: str
    deepl_api_base: str
    openai_api_key: str
    openai_base_url: str
    openai_model: str
    max_chars: int
    invite_ttl_hours: int
    send_rate: int
    rate_limit_messages: int
    rate_limit_window: int
    log_level: str


def load_config() -> Config:
    _load_dotenv()

    token = _first_env("TELEGRAM_BOT_TOKEN", "BOT_TOKEN")
    if not token:
        raise ConfigError("TELEGRAM_BOT_TOKEN is not set (get one from @BotFather)")

    owner = _env("OWNER_USERNAME").lstrip("@").casefold()
    if not owner:
        raise ConfigError("OWNER_USERNAME is not set (your Telegram @username)")

    owner_name = " ".join(_env("OWNER_DISPLAY_NAME", "Admin").split())
    if not 1 <= len(owner_name) <= 32:
        raise ConfigError("OWNER_DISPLAY_NAME must be 1-32 characters")

    owner_lang = normalize(_env("OWNER_LANGUAGE", "English"))
    if owner_lang is None:
        raise ConfigError("OWNER_LANGUAGE is not a valid language name")

    providers = [p.strip().casefold() for p in _env("PROVIDERS", "gemini").split(",") if p.strip()]
    # Accept the shorter name commonly used in .env files.
    providers = ["openai_compat" if p == "openai" else p for p in providers]
    if not providers:
        raise ConfigError("PROVIDERS is empty")
    allowed = {"gemini", "deepl", "openai_compat"}
    unknown = [p for p in providers if p not in allowed]
    if unknown:
        raise ConfigError(f"Unknown provider(s): {', '.join(unknown)}")

    gemini_key = _env("GEMINI_API_KEY")
    deepl_key = _env("DEEPL_API_KEY")
    openai_key = _first_env("OPENAI_COMPAT_API_KEY", "OPENAI_API_KEY")

    if "gemini" in providers and not gemini_key:
        raise ConfigError("GEMINI_API_KEY is required because gemini is in PROVIDERS")
    if "deepl" in providers and not deepl_key:
        raise ConfigError("DEEPL_API_KEY is required because deepl is in PROVIDERS")
    if "openai_compat" in providers and not openai_key:
        raise ConfigError("OPENAI_COMPAT_API_KEY is required because openai_compat is in PROVIDERS")

    return Config(
        bot_token=token,
        owner_username=owner,
        owner_display_name=owner_name,
        owner_language=owner_lang,
        db_path=_env("DB_PATH", "data/bot.db"),
        providers=providers,
        gemini_api_key=gemini_key,
        gemini_model=_env("GEMINI_MODEL", "gemini-3.5-flash-lite"),
        deepl_api_key=deepl_key,
        deepl_api_base=_env("DEEPL_API_BASE", "https://api-free.deepl.com"),
        openai_api_key=openai_key,
        openai_base_url=_first_env("OPENAI_COMPAT_BASE_URL", "OPENAI_BASE_URL", default="https://api.openai.com/v1").rstrip("/"),
        openai_model=_first_env("OPENAI_COMPAT_MODEL", "OPENAI_MODEL", default="gpt-5-mini"),
        max_chars=_int("MAX_MESSAGE_CHARS", 3500),
        invite_ttl_hours=_int("INVITE_TTL_HOURS", 72),
        send_rate=_int("SEND_RATE_PER_SEC", 20),
        rate_limit_messages=_int("RATE_LIMIT_MESSAGES", 20),
        rate_limit_window=_int("RATE_LIMIT_WINDOW_SEC", 60),
        log_level=_env("LOG_LEVEL", "INFO").upper(),
    )
