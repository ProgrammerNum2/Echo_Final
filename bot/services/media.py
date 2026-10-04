from __future__ import annotations
from dataclasses import dataclass
from typing import Awaitable, Callable
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import Message
from .relay import SendResult
from .tgio import Throttle
from ..textutil import chunk, esc

CAPTION_LIMIT = 1000  # leave room for entities/markup and the display name
MAX_TEXT = 3500

@dataclass(frozen=True)
class MediaKind:
    kind: str
    file_id: str
    caption: str
    original_caption: str

def detect_media(message: Message) -> MediaKind | None:
    cap = message.caption or ""
    if message.photo:
        return MediaKind("photo", message.photo[-1].file_id, cap, cap)
    if message.video:
        return MediaKind("video", message.video.file_id, cap, cap)
    if message.animation:
        return MediaKind("animation", message.animation.file_id, cap, cap)
    if message.audio:
        return MediaKind("audio", message.audio.file_id, cap, cap)
    if message.document:
        return MediaKind("document", message.document.file_id, cap, cap)
    if message.voice:
        return MediaKind("voice", message.voice.file_id, cap, cap)
    if message.video_note:
        return MediaKind("video_note", message.video_note.file_id, "", "")
    if message.sticker:
        return MediaKind("sticker", message.sticker.file_id, "", "")
    return None

def _caption_parts(name: str, body: str) -> list[str]:
    prefix = f"<b>{esc(name)}</b>"
    if not body:
        return [prefix]
    available = max(1, CAPTION_LIMIT - len(prefix) - 1)
    pieces = chunk(body, available)
    return [f"{prefix}\n{esc(p)}" for p in pieces]

def _admin_original(name: str, translated: str, original: str) -> str:
    base = f"<b>{esc(name)}</b>\n{esc(translated)}"
    if len(base) + len(original) + 50 <= MAX_TEXT:
        return f"{base}\n<blockquote expandable>{esc(original)}</blockquote>"
    return f"{base}\n<blockquote expandable>{esc(original)}</blockquote>"

async def safe_media_send(bot: Bot, throttle: Throttle, chat_id: int, kind: str, file_id: str,
                          caption: str | None = None) -> tuple[SendResult, object | None]:
    sender = getattr(bot, f"send_{kind}")
    for attempt in range(4):
        await throttle.wait()
        try:
            kwargs = {"chat_id": chat_id}
            if kind == "video_note":
                result = await sender(video_note=file_id, **kwargs)
            elif kind == "sticker":
                result = await sender(sticker=file_id, **kwargs)
            else:
                result = await sender(**{kind: file_id}, caption=caption, parse_mode="HTML", **kwargs)
            return SendResult.OK, result
        except TelegramRetryAfter as e:
            await __import__("asyncio").sleep(e.retry_after + 0.5)
        except TelegramForbiddenError:
            return SendResult.BLOCKED, None
        except TelegramBadRequest:
            return SendResult.FAILED, None
        except TelegramAPIError:
            if attempt < 3:
                await __import__("asyncio").sleep(1 + attempt)
    return SendResult.FAILED, None
