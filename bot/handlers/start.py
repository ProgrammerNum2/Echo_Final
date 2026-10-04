from __future__ import annotations
import logging, sqlite3
from aiogram import Bot, F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message
from ..config import Config
from ..db import Database, User
from ..services.tgio import notify_owner
from ..textutil import esc

log=logging.getLogger(__name__)
router=Router(name="start")

@router.message(CommandStart(), F.chat.type=="private")
async def on_start(message: Message, command: CommandObject, bot: Bot, db: Database,
                   cfg: Config):
    tg=message.from_user
    if tg is None: return
    owner_raw=await db.get_setting("owner_id")
    if owner_raw is None and tg.username and tg.username.casefold()==cfg.owner_username:
        await db.set_setting("owner_id",str(tg.id)); owner_raw=str(tg.id)
    if owner_raw is not None and int(owner_raw)==tg.id:
        user=await db.ensure_owner(tg.id,cfg.owner_display_name,cfg.owner_language)
        await message.answer(f"👋 <b>{esc(user.name)}</b>\nOwner access is active. Use /admin.")
        return
    code=(command.args or "").strip()
    existing=await db.get_user(tg.id)
    if code and existing is None:
        try:
            await db.redeem_invite(code,tg.id)
        except sqlite3.IntegrityError:
            await message.answer("⚠️ This invite could not be activated. Ask the owner for a new one.")
            return
        user=await db.get_user(tg.id)
        if user:
            await message.answer(f"✅ Connected as <b>{esc(user.name)}</b>. You do not need to configure anything.")
            await notify_owner(bot,db,f"✅ <b>{esc(user.name)}</b> joined ({esc(user.lang)}).")
        return
    if existing is None:
        await message.answer("This bot is invite-only. Ask the owner for an invite link.")
        return
    if not existing.active:
        return
    if not existing.started:
        await db.set_started(tg.id,True)
        await message.answer(f"✅ Connected as <b>{esc(existing.name)}</b>.")
        await notify_owner(bot,db,f"✅ <b>{esc(existing.name)}</b> pressed Start.")
    else:
        await message.answer("You're already connected.")
