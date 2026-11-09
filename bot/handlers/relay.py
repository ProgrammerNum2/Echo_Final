from __future__ import annotations
import asyncio, logging
from functools import partial
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message, ReactionTypeEmoji
from ..config import Config
from ..db import Database, User
from ..services.media import detect_media, safe_media_send, _caption_parts, _admin_original
from ..services.relay import SendResult, relay_text
from ..services.rate_limit import RateLimiter
from ..services.serial import SerialRunner
from ..services.tgio import Throttle, make_sender, notify_owner
from ..textutil import esc
from ..translators.router import TranslatorRouter
from ..translators.base import TranslationError
from ..languages import same_language

log=logging.getLogger(__name__)
router=Router(name="relay")

def _sender_ready(message: Message, db: Database) -> User | None:
    return None

@router.message(F.chat.type=="private", F.text, ~F.text.startswith("/"))
async def on_text(message: Message, bot: Bot, db: Database, cfg: Config,
                  translator: TranslatorRouter, runner: SerialRunner, send, limiter: RateLimiter):
    if not message.from_user: return
    if not limiter.allow(message.from_user.id):
        await message.answer("⚠️ Too many messages. Please wait a moment.")
        return
    runner.submit(message.from_user.id, partial(_process_text, message, bot, db, cfg, translator, send))

async def _process_text(message, bot, db, cfg, translator, send):
    user=await db.get_user(message.from_user.id)
    if user is None or not user.active: return
    await db.set_started(user.tg_id, True); await db.touch(user.tg_id)
    text=message.text or ""
    if not text.strip(): return
    if len(text)>cfg.max_chars:
        await message.reply(f"⚠️ Message too long ({len(text)}/{cfg.max_chars} characters).")
        return
    owner_raw=await db.get_setting("owner_id")
    owner_id=int(owner_raw) if owner_raw else None
    admin_view=(await db.get_setting("admin_view","0"))=="1"
    report=await relay_text(sender=user,text=text,db=db,translator=translator,send=send,
                            admin_view=admin_view,owner_id=owner_id)
    if report.translation_failed:
        try: await message.react([ReactionTypeEmoji(emoji="❌")])
        except TelegramAPIError: pass
        await notify_owner(bot,db,"⚠️ Translation failed. Check translator/API settings.")
    elif report.recipients==0:
        await message.reply("ℹ️ Nobody else is connected yet.")
    if report.blocked:
        await notify_owner(bot,db,"⚠️ One or more members blocked the bot and were paused.")

@router.message(F.chat.type=="private", ~F.text)
async def on_media_or_unsupported(message: Message, bot: Bot, db: Database, cfg: Config,
                                   translator: TranslatorRouter, limiter: RateLimiter, throttle: Throttle):
    if not message.from_user: return
    user=await db.get_user(message.from_user.id)
    if user is None or not user.active: return
    if not limiter.allow(user.tg_id):
        await message.answer("⚠️ Too many messages. Please wait a moment.")
        return
    media=detect_media(message)
    if media is None:
        # Unknown/unsupported updates are intentionally ignored.
        return
    await db.set_started(user.tg_id, True); await db.touch(user.tg_id)
    recipients=await db.recipients(user.tg_id)
    if not recipients:
        await message.reply("ℹ️ Nobody else is connected yet.")
        return

    caption=media.caption
    admin_raw=await db.get_setting("owner_id")
    owner_id=int(admin_raw) if admin_raw else None
    admin_view=(await db.get_setting("admin_view","0"))=="1"

    # Voice is deliberately not translated. Preserve its original audio and any caption text.
    translate_caption = bool(caption) and media.kind != "voice"
    translations={}
    if translate_caption:
        targets={}
        for u in recipients:
            if not same_language(u.lang,user.lang):
                targets.setdefault(u.lang.casefold(),u.lang)
        if targets:
            try:
                translations=await translator.translate(caption,user.lang,list(targets.values()))
            except TranslationError:
                await db.bump_stat("translation_errors")
                try: await message.react([ReactionTypeEmoji(emoji="❌")])
                except TelegramAPIError: pass
                await notify_owner(bot,db,"⚠️ Media caption translation failed.")
                return

    for dest in recipients:
        body = caption if media.kind=="voice" else translations.get(dest.lang, caption)
        if not body and media.kind not in {"video_note","sticker"}:
            body=""
        show_original = admin_view and owner_id==dest.tg_id and translate_caption and not same_language(dest.lang,user.lang)

        # For types with captions, prefer one media message with the required display name.
        if media.kind not in {"video_note","sticker"}:
            parts=_caption_parts(user.name, body)
            first=parts[0]
            # Admin view can fit the original in a normal text caption only when short enough.
            if show_original and len(first)+len(caption)+50 <= 1000:
                first=f"{first}\n<blockquote expandable>{esc(caption)}</blockquote>"
            result,_=await safe_media_send(bot,throttle,dest.tg_id,media.kind,media.file_id,first)
            if result is SendResult.BLOCKED:
                await db.set_started(dest.tg_id,False); continue
            if result is not SendResult.OK:
                continue
            # Long captions overflow as text below the media.
            for extra in parts[1:]:
                await send_text_safe(bot,throttle,dest.tg_id,extra)
            if show_original and len(first)+len(caption)+50 > 1000:
                await send_text_safe(bot,throttle,dest.tg_id,
                                     f"<b>{esc(user.name)}</b>\n<blockquote expandable>{esc(caption)}</blockquote>")
        else:
            # Stickers and video notes do not support captions: name immediately before the media.
            r=await send_text_safe(bot,throttle,dest.tg_id,f"<b>{esc(user.name)}</b>")
            if r is SendResult.BLOCKED:
                await db.set_started(dest.tg_id,False); continue
            r,_=await safe_media_send(bot,throttle,dest.tg_id,media.kind,media.file_id)
            if r is SendResult.BLOCKED:
                await db.set_started(dest.tg_id,False)
    await db.bump_stat("media")

async def send_text_safe(bot: Bot, throttle: Throttle, chat_id: int, html: str) -> SendResult:
    sender=make_sender(bot,throttle)
    return await sender(chat_id,html)
