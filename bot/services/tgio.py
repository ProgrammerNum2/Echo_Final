from __future__ import annotations
import asyncio, logging, time
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from ..db import Database
from .relay import SendFn, SendResult

log = logging.getLogger(__name__)

class Throttle:
    def __init__(self, per_sec: int):
        self._interval = 1.0 / per_sec
        self._next = 0.0
        self._lock = asyncio.Lock()
    async def wait(self):
        async with self._lock:
            now=time.monotonic()
            delay=self._next-now
            if delay>0: await asyncio.sleep(delay)
            self._next=max(now,self._next)+self._interval

def make_sender(bot: Bot, throttle: Throttle) -> SendFn:
    async def send(chat_id: int, html: str) -> SendResult:
        for attempt in range(4):
            await throttle.wait()
            try:
                await bot.send_message(chat_id, html)
                return SendResult.OK
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 0.5)
            except TelegramForbiddenError:
                return SendResult.BLOCKED
            except TelegramBadRequest:
                return SendResult.FAILED
            except TelegramAPIError as e:
                log.warning("Telegram send error to %s (attempt %d): %s", chat_id, attempt+1, e)
                if attempt < 3: await asyncio.sleep(1+attempt)
        return SendResult.FAILED
    return send

async def notify_owner(bot: Bot, db: Database, html: str):
    raw=await db.get_setting("owner_id")
    if raw is None: return
    try: await bot.send_message(int(raw), html)
    except TelegramAPIError as e: log.warning("Owner notification failed: %s",e)
