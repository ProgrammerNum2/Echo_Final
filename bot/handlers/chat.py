"""The actual relay: text messages from connected users are translated and fanned out."""
from __future__ import annotations

import logging
from functools import partial

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message, ReactionTypeEmoji

from ..config import Config
from ..db import Database
from ..services.relay import SendFn, relay_text
from ..services.serial import SerialRunner
from ..services.tgio import notify_owner
from ..textutil import esc
from ..translators.router import TranslatorRouter

log = logging.getLogger(__name__)
router = Router(name="chat")


@router.message(F.chat.type == "private", F.text, ~F.text.startswith("/"))
async def on_text(message: Message, bot: Bot, db: Database, cfg: Config,
                  translator: TranslatorRouter, runner: SerialRunner, send: SendFn) -> None:
    if message.from_user is None:
        return
    # Queue per sender so their messages are always delivered in the order they were written.
    runner.submit(message.from_user.id, partial(_process, message, bot, db, cfg, translator, send))


async def _process(message: Message, bot: Bot, db: Database, cfg: Config,
                   translator: TranslatorRouter, send: SendFn) -> None:
    assert message.from_user is not None
    user = await db.get_user(message.from_user.id)
    if user is None or not user.active:
        return  # strangers and disabled users are ignored silently
    if not user.started:
        await db.set_started(user.tg_id, True)  # they can write to us, so we can write to them

    text = message.text or ""
    if not text.strip():
        return
    if len(text) > cfg.max_chars:
        await message.reply(f"⚠️ Message too long ({len(text)}/{cfg.max_chars} characters). Please split it.")
        return

    owner_raw = await db.get_setting("owner_id")
    owner_id = int(owner_raw) if owner_raw else None
    admin_view = (await db.get_setting("admin_view", "0")) == "1"

    report = await relay_text(sender=user, text=text, db=db, translator=translator, send=send,
                              admin_view=admin_view, owner_id=owner_id)

    if report.translation_failed:
        await message.reply("⚠️ Translation is unavailable right now, so your message was NOT delivered. "
                            "Please try again in a moment.")
        await notify_owner(bot, db, "⚠️ Translation failed — all providers returned errors. Check the logs/API key.")
    elif report.recipients == 0:
        await message.reply("ℹ️ Nobody else is connected yet.")
    elif report.delivered == 0:
        await message.reply("⚠️ Couldn't deliver your message to anyone.")
    else:
        try:
            await message.react([ReactionTypeEmoji(emoji="👍")])
        except TelegramAPIError:
            pass  # reactions are only a nicety

    if report.blocked:
        names = ", ".join(f"<b>{esc(u.name)}</b>" for u in report.blocked)
        await notify_owner(bot, db, f"⚠️ Can't deliver to {names}: the bot is blocked. "
                                    "They're paused until they press Start again.")


@router.message(F.chat.type == "private", ~F.text)
async def on_unsupported(message: Message, db: Database) -> None:
    if message.from_user is None:
        return
    user = await db.get_user(message.from_user.id)
    if user is None or not user.active:
        return
    await message.answer("ℹ️ Only text messages are supported for now. "
                         "Photos, videos and voice messages are coming soon.")
