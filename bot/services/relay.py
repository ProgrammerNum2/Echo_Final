"""Translation/fan-out core. No message bodies are persisted."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Protocol
from ..db import Database, User
from ..languages import same_language
from ..textutil import chunk, esc
from ..translators.base import TranslationError

TEXT_LIMIT = 3500

class SendResult(Enum):
    OK = "ok"
    BLOCKED = "blocked"
    FAILED = "failed"

SendFn = Callable[[int, str], Awaitable[SendResult]]

class TranslatorLike(Protocol):
    async def translate(self, text: str, source: str, targets: list[str]) -> dict[str,str]: ...

@dataclass
class RelayReport:
    recipients: int = 0
    delivered: int = 0
    blocked: list[User] = field(default_factory=list)
    translation_failed: bool = False

def format_messages(name: str, body: str, original: str | None = None) -> list[str]:
    header = f"<b>{esc(name)}</b>"
    if original is not None and len(header) + len(body) + len(original) + 40 <= TEXT_LIMIT:
        return [f"{header}\n{esc(body)}\n<blockquote expandable>{esc(original)}</blockquote>"]
    parts = chunk(body, TEXT_LIMIT - len(name) - 2)
    return [f"{header}\n{esc(parts[0])}"] + [esc(p) for p in parts[1:]]

async def translate_for_recipients(sender: User, text: str, recipients: list[User], translator: TranslatorLike):
    targets = {}
    for u in recipients:
        if not same_language(u.lang, sender.lang):
            targets.setdefault(u.lang.casefold(), u.lang)
    if not targets:
        return {}, False
    try:
        result = await translator.translate(text, sender.lang, list(targets.values()))
        return {k.casefold(): v for k,v in result.items()}, False
    except TranslationError:
        return {}, True

async def relay_text(*, sender: User, text: str, db: Database, translator: TranslatorLike,
                     send: SendFn, admin_view: bool, owner_id: int | None) -> RelayReport:
    others = await db.recipients(sender.tg_id)
    report = RelayReport(recipients=len(others))
    if not others:
        return report
    translated, failed = await translate_for_recipients(sender, text, others, translator)
    if failed:
        report.translation_failed = True
        await db.bump_stat("translation_errors")
        return report
    async def deliver(u: User):
        body = translated.get(u.lang.casefold(), text)
        original = text if admin_view and owner_id == u.tg_id and not same_language(u.lang, sender.lang) else None
        for part in format_messages(sender.name, body, original):
            res = await send(u.tg_id, part)
            if res is not SendResult.OK:
                return res
        return SendResult.OK
    results = await asyncio.gather(*(deliver(u) for u in others), return_exceptions=True)
    for u,res in zip(others, results):
        if isinstance(res, BaseException):
            continue
        if res is SendResult.OK:
            report.delivered += 1
        elif res is SendResult.BLOCKED:
            report.blocked.append(u)
            await db.set_started(u.tg_id, False)
    if report.delivered:
        await db.bump_stat("messages")
    return report
