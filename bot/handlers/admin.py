from __future__ import annotations
import sqlite3, time
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import BaseFilter, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from ..config import Config
from ..db import Database, User
from ..languages import BUTTON_CODES, LANGUAGES, normalize
from ..textutil import esc
from ..translators.base import TranslationError
from ..translators.router import TranslatorRouter

class OwnerFilter(BaseFilter):
    async def __call__(self,event:Message|CallbackQuery,db:Database)->bool:
        u=event.from_user
        owner=await db.get_setting("owner_id")
        return bool(u and owner and int(owner)==u.id)

class NewUser(StatesGroup):
    waiting_id=State(); waiting_name=State(); waiting_lang=State()
class TestTranslation(StatesGroup):
    waiting_text=State()
class Broadcast(StatesGroup):
    waiting_text=State()

router=Router(name="admin")
router.message.filter(F.chat.type=="private",OwnerFilter())
router.callback_query.filter(OwnerFilter())

def _kb(*rows):
    b=InlineKeyboardBuilder()
    for row in rows:
        for text,data in row: b.button(text=text,callback_data=data)
    b.adjust(*[len(r) for r in rows]); return b.as_markup()
BACK=[("⬅ Menu","adm:menu")]
CANCEL_KB=_kb([("✖ Cancel","adm:menu")])

async def menu_view(db):
    users=await db.list_users()
    connected=sum(1 for u in users if u.active and u.started)
    view=(await db.get_setting("admin_view","0"))=="1"
    providers=await db.get_setting("providers","")
    return (f"🛠 <b>Admin panel</b>\n\nUsers: {connected}/{len(users)} connected\n"
            f"Admin view: {'ON' if view else 'OFF'}\n"
            f"Providers: {esc(providers) or '—'}"), _kb(
        [("👥 Users","adm:users"),("🎫 Invites","adm:invites")],
        [("➕ New invite","adm:new:invite"),("🆔 Add by ID","adm:new:id")],
        [(f"👁 Original view: {'ON' if view else 'OFF'}","adm:view")],
        [("🌐 Translator","adm:translator"),("📊 Stats","adm:stats")],
        [("📣 Broadcast","adm:broadcast")]
    )

async def show(cb,text,kb=None,notice=None):
    await cb.answer(notice)
    if isinstance(cb.message,Message):
        try: await cb.message.edit_text(text,reply_markup=kb)
        except TelegramBadRequest as e:
            if "not modified" not in str(e): raise

async def users_view(db):
    users=await db.list_users(); b=InlineKeyboardBuilder()
    for u in users[:80]:
        icon="🔴" if not u.active else "🟢" if u.started else "⚪"
        b.button(text=f"{icon} {u.name} · {u.lang}",callback_data=f"adm:user:{u.tg_id}")
    b.button(text="⬅ Menu",callback_data="adm:menu"); b.adjust(1)
    return ("👥 <b>Users</b>\n🟢 connected · ⚪ waiting for Start · 🔴 disabled" if users else "No users."),b.as_markup()

async def user_view(db,tg_id):
    u=await db.get_user(tg_id)
    if not u:return None
    owner=await db.get_setting("owner_id")
    status="disabled" if not u.active else "connected" if u.started else "waiting for Start"
    rows=[]
    if owner is None or int(owner)!=tg_id:
        rows.append([("🚫 Disable" if u.active else "✅ Enable",f"adm:toggle:{tg_id}")])
    rows.append([("⬅ Users","adm:users"),("⬅ Menu","adm:menu")])
    return (f"{'🔴' if not u.active else '🟢' if u.started else '⚪'} <b>{esc(u.name)}</b>\n"
            f"Language: {esc(u.lang)}\nTelegram ID: <code>{tg_id}</code>\nStatus: {status}"),_kb(*rows)

async def _link(bot,code=None):
    me=await bot.me(); return f"https://t.me/{me.username}"+(f"?start={code}" if code else "")

def lang_keyboard():
    b=InlineKeyboardBuilder()
    for code in BUTTON_CODES:b.button(text=LANGUAGES[code],callback_data=f"adm:lang:{code}")
    b.button(text="✖ Cancel",callback_data="adm:menu"); b.adjust(3); return b.as_markup()

@router.message(Command("admin"))
async def cmd_admin(message:Message,state:FSMContext,db:Database):
    await state.clear(); text,kb=await menu_view(db); await message.answer(text,reply_markup=kb)

@router.message(Command("cancel"))
async def cmd_cancel(message:Message,state:FSMContext,db:Database):
    await state.clear(); text,kb=await menu_view(db); await message.answer("Cancelled.\n\n"+text,reply_markup=kb)

@router.callback_query(F.data=="adm:menu")
async def cb_menu(cb,state:FSMContext,db:Database):
    await state.clear(); text,kb=await menu_view(db); await show(cb,text,kb)

@router.callback_query(F.data=="adm:view")
async def cb_view(cb,db):
    on=(await db.get_setting("admin_view","0"))!="1"; await db.set_setting("admin_view","1" if on else "0")
    text,kb=await menu_view(db); await show(cb,text,kb,f"Original view {'ON' if on else 'OFF'}")

@router.callback_query(F.data=="adm:users")
async def cb_users(cb,db):
    text,kb=await users_view(db); await show(cb,text,kb)

@router.callback_query(F.data.startswith("adm:user:"))
async def cb_user(cb,db):
    view=await user_view(db,int(cb.data.split(":")[2]))
    if view is None: await cb.answer("User not found",show_alert=True); return
    await show(cb,*view)

@router.callback_query(F.data.startswith("adm:toggle:"))
async def cb_toggle(cb,db):
    tg_id=int(cb.data.split(":")[2]); u=await db.get_user(tg_id); owner=await db.get_setting("owner_id")
    if u is None or (owner and int(owner)==tg_id):
        await cb.answer("Not possible",show_alert=True); return
    await db.set_active(tg_id,not u.active); view=await user_view(db,tg_id); await show(cb,*view,notice="Enabled" if not u.active else "Disabled")

@router.callback_query(F.data=="adm:invites")
async def cb_invites(cb,db,bot):
    invs=await db.list_pending_invites()
    if not invs: await show(cb,"🎫 No pending invites.",_kb(BACK)); return
    now=int(time.time()); lines=["🎫 <b>Pending invites</b>\n"]; b=InlineKeyboardBuilder()
    for inv in invs:
        hours=max(1,(inv.expires_at-now)//3600)
        lines.append(f"• <b>{esc(inv.name)}</b> ({esc(inv.lang)}) — ~{hours} h\n<code>{await _link(bot,inv.code)}</code>")
        b.button(text=f"🗑 Revoke {inv.name}",callback_data=f"adm:revoke:{inv.code}")
    b.button(text="⬅ Menu",callback_data="adm:menu"); b.adjust(1)
    await show(cb,"\n".join(lines),b.as_markup())

@router.callback_query(F.data.startswith("adm:revoke:"))
async def cb_revoke(cb,db,bot):
    ok=await db.revoke_invite(cb.data.split(":",2)[2])
    invs=await db.list_pending_invites()
    if not invs:
        await show(cb,"🎫 No pending invites.",_kb(BACK),"Revoked" if ok else "Already used/revoked")
        return
    now=int(time.time()); lines=["🎫 <b>Pending invites</b>\n"]; b=InlineKeyboardBuilder()
    for inv in invs:
        hours=max(1,(inv.expires_at-now)//3600)
        lines.append(f"• <b>{esc(inv.name)}</b> ({esc(inv.lang)}) — ~{hours} h\n<code>{await _link(bot,inv.code)}</code>")
        b.button(text=f"🗑 Revoke {inv.name}",callback_data=f"adm:revoke:{inv.code}")
    b.button(text="⬅ Menu",callback_data="adm:menu"); b.adjust(1)
    await show(cb,"\n".join(lines),b.as_markup(),"Revoked" if ok else "Already used/revoked")

@router.callback_query(F.data.startswith("adm:new:"))
async def cb_new(cb,state:FSMContext):
    mode=cb.data.split(":")[2]; await state.clear(); await state.update_data(mode=mode)
    if mode=="id":
        await state.set_state(NewUser.waiting_id); await show(cb,"Send the numeric Telegram ID.",CANCEL_KB)
    else:
        await state.set_state(NewUser.waiting_name); await show(cb,"Send the custom display name (1–32 chars).",CANCEL_KB)

@router.message(NewUser.waiting_id,F.text)
async def got_id(message,state,db):
    raw=message.text.strip()
    if not raw.isdigit() or int(raw)<=0: await message.answer("ID must contain digits only."); return
    tg_id=int(raw)
    if await db.get_user(tg_id): await message.answer("That ID is already added."); return
    await state.update_data(tg_id=tg_id); await state.set_state(NewUser.waiting_name)
    await message.answer("Send the custom display name (1–32 chars).")

@router.message(NewUser.waiting_name,F.text)
async def got_name(message,state,db):
    name=" ".join(message.text.split())
    if not 1<=len(name)<=32: await message.answer("Name must be 1–32 characters."); return
    if await db.name_taken(name): await message.answer("That display name is already used."); return
    await state.update_data(name=name); await state.set_state(NewUser.waiting_lang)
    await message.answer(f"Choose <b>{esc(name)}</b>'s language:",reply_markup=lang_keyboard())

async def _finish(state,db,cfg,bot,lang):
    data=await state.get_data(); await state.clear(); name=data["name"]
    if data["mode"]=="invite":
        inv=await db.create_invite(name,lang,cfg.invite_ttl_hours)
        return f"✅ Invite created for <b>{esc(name)}</b> ({esc(lang)}).\n<code>{await _link(bot,inv.code)}</code>"
    try: await db.add_user(data["tg_id"],name,lang,started=False)
    except sqlite3.IntegrityError: return "⚠️ Could not add user; ID/name is already in use."
    return f"✅ Added <b>{esc(name)}</b> ({esc(lang)}). They only need to press Start once."

@router.callback_query(NewUser.waiting_lang,F.data.startswith("adm:lang:"))
async def got_lang_button(cb,state,db,cfg,bot):
    code=cb.data.split(":")[2]
    if code not in LANGUAGES: await cb.answer("Unknown language",show_alert=True); return
    await show(cb,await _finish(state,db,cfg,bot,LANGUAGES[code]),_kb(BACK))

@router.message(NewUser.waiting_lang,F.text)
async def got_lang_text(message,state,db,cfg,bot):
    lang=normalize(message.text)
    if not lang: await message.answer("Type a language name or use the buttons."); return
    await message.answer(await _finish(state,db,cfg,bot,lang),reply_markup=_kb(BACK))

@router.callback_query(F.data=="adm:translator")
async def cb_translator(cb,db,translator:TranslatorRouter):
    configured=", ".join(p.name for p in translator.providers)
    rows=[]
    for p in translator.providers:
        mark="✅ " if p.name==translator.active_name else ""
        rows.append([(f"{mark}{p.name}","adm:provider:"+p.name)])
    rows.append([("🧪 Test","adm:test"),("⬅ Menu","adm:menu")])
    await show(cb,f"🌐 <b>Translator</b>\nActive: <b>{translator.active_name}</b>\nFallback: {esc(configured)}",_kb(*rows))

@router.callback_query(F.data.startswith("adm:provider:"))
async def cb_provider(cb,db,translator:TranslatorRouter):
    name=cb.data.split(":",2)[2]
    if not translator.set_primary(name): await cb.answer("Provider unavailable",show_alert=True); return
    await db.set_setting("active_provider",name)
    await show(cb,f"🌐 Active provider: <b>{esc(name)}</b>\nFallback order: "+esc(",".join(p.name for p in translator.providers)),_kb([("⬅ Translator","adm:translator")]),"Provider selected")

@router.callback_query(F.data=="adm:test")
async def cb_test(cb,state):
    await state.set_state(TestTranslation.waiting_text); await show(cb,"Send a phrase. It will be translated into the owner's language.",CANCEL_KB)

@router.message(TestTranslation.waiting_text,F.text)
async def got_test(message,state,db,translator):
    text=message.text.strip(); await state.clear()
    target=(await db.get_user(message.from_user.id)).lang
    try: out=(await translator.translate(text,"Auto", [target]))[target]
    except TranslationError as e: await message.answer(f"❌ Translation failed: {esc(str(e))[:500]}"); return
    await message.answer(f"<b>{esc(target)}</b>\n{esc(out)}")

@router.callback_query(F.data=="adm:stats")
async def cb_stats(cb,db,translator):
    m,media,err,calls=await db.stats_today()
    await show(cb,f"📊 <b>Today</b>\nMessages: {m}\nMedia: {media}\nTranslation errors: {err}\nProvider calls: {calls}\nActive provider: {esc(translator.active_name)}",_kb([("⬅ Menu","adm:menu")]))

@router.callback_query(F.data=="adm:broadcast")
async def cb_broadcast(cb,state):
    await state.set_state(Broadcast.waiting_text); await show(cb,"Send the announcement text. It will be translated per member.",CANCEL_KB)

@router.message(Broadcast.waiting_text,F.text)
async def got_broadcast(message,state,db,translator,bot,send):
    await state.clear(); users=await db.recipients(message.from_user.id)
    if not users: await message.answer("No connected members."); return
    owner=await db.get_user(message.from_user.id)
    targets={u.lang.casefold():u.lang for u in users if not owner or u.lang.casefold()!=owner.lang.casefold()}
    try: tr=await translator.translate(message.text,owner.lang if owner else "English",list(targets.values()))
    except TranslationError:
        await message.answer("Translation failed."); return
    n=0
    for u in users:
        body=tr.get(u.lang,message.text)
        result=await send(u.tg_id,f"<b>{esc(owner.name if owner else 'Admin')}</b>\n{esc(body)}")
        if result.value=="ok": n+=1
    await message.answer(f"Broadcast delivered to {n} member(s).")
