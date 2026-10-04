"""Small SQLite persistence layer. No message bodies are stored."""
from __future__ import annotations

import asyncio
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeVar

T = TypeVar("T")

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    tg_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    lang TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    started INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    last_seen INTEGER
);
CREATE TABLE IF NOT EXISTS invites (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    lang TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    used_by INTEGER,
    revoked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS stats (
    day TEXT PRIMARY KEY,
    messages INTEGER NOT NULL DEFAULT 0,
    media INTEGER NOT NULL DEFAULT 0,
    translation_errors INTEGER NOT NULL DEFAULT 0,
    provider_calls INTEGER NOT NULL DEFAULT 0
);
"""


@dataclass(frozen=True)
class User:
    tg_id: int
    name: str
    lang: str
    active: bool
    started: bool
    created_at: int = 0
    last_seen: int | None = None


@dataclass(frozen=True)
class Invite:
    code: str
    name: str
    lang: str
    created_at: int
    expires_at: int
    used_by: int | None
    revoked: bool


def _user(r: sqlite3.Row | None) -> User | None:
    if r is None:
        return None
    return User(r["tg_id"], r["name"], r["lang"], bool(r["active"]), bool(r["started"]),
                r["created_at"], r["last_seen"])


def _invite(r: sqlite3.Row | None) -> Invite | None:
    if r is None:
        return None
    return Invite(r["code"], r["name"], r["lang"], r["created_at"], r["expires_at"],
                  r["used_by"], bool(r["revoked"]))


class Database:
    def __init__(self, path: str):
        self._path = path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    async def init(self) -> None:
        def _open() -> sqlite3.Connection:
            if self._path != ":memory:":
                Path(self._path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self._path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.executescript(SCHEMA)
            conn.commit()
            return conn
        self._conn = await asyncio.to_thread(_open)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    async def _run(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        def job() -> T:
            with self._lock:
                assert self._conn is not None, "Database.init() was not called"
                try:
                    result = fn(self._conn)
                    self._conn.commit()
                    return result
                except BaseException:
                    self._conn.rollback()
                    raise
        return await asyncio.to_thread(job)

    async def get_setting(self, key: str, default: str | None = None) -> str | None:
        def fn(c):
            r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return r["value"] if r else default
        return await self._run(fn)

    async def set_setting(self, key: str, value: str) -> None:
        await self._run(lambda c: c.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value)))

    async def get_user(self, tg_id: int) -> User | None:
        return await self._run(lambda c: _user(
            c.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()))

    async def list_users(self) -> list[User]:
        return await self._run(lambda c: [
            _user(r) for r in c.execute("SELECT * FROM users ORDER BY name COLLATE NOCASE")])  # type: ignore[misc]

    async def recipients(self, exclude_id: int) -> list[User]:
        return await self._run(lambda c: [
            _user(r) for r in c.execute(
                "SELECT * FROM users WHERE active=1 AND started=1 AND tg_id != ? ORDER BY name COLLATE NOCASE",
                (exclude_id,))])  # type: ignore[misc]

    async def add_user(self, tg_id: int, name: str, lang: str, started: bool = False) -> None:
        await self._run(lambda c: c.execute(
            "INSERT INTO users(tg_id,name,lang,active,started,created_at,last_seen) VALUES(?,?,?,1,?,?,?)",
            (tg_id, name, lang, int(started), int(time.time()), int(time.time()) if started else None)))

    async def ensure_owner(self, tg_id: int, name: str, lang: str) -> User:
        existing = await self.get_user(tg_id)
        if existing:
            if not existing.started:
                await self.set_started(tg_id, True)
            return (await self.get_user(tg_id)) or existing
        try:
            await self.add_user(tg_id, name, lang, started=True)
        except sqlite3.IntegrityError:
            await self.add_user(tg_id, f"{name} (owner)", lang, started=True)
        return (await self.get_user(tg_id))  # type: ignore[return-value]

    async def set_started(self, tg_id: int, started: bool) -> None:
        await self._run(lambda c: c.execute(
            "UPDATE users SET started=?, last_seen=? WHERE tg_id=?",
            (int(started), int(time.time()) if started else None, tg_id)))

    async def touch(self, tg_id: int) -> None:
        await self._run(lambda c: c.execute(
            "UPDATE users SET last_seen=? WHERE tg_id=?", (int(time.time()), tg_id)))

    async def set_active(self, tg_id: int, active: bool) -> None:
        await self._run(lambda c: c.execute(
            "UPDATE users SET active=? WHERE tg_id=?", (int(active), tg_id)))

    async def name_taken(self, name: str) -> bool:
        key = name.casefold()
        def fn(c) -> bool:
            now = int(time.time())
            if any(r["name"].casefold() == key for r in c.execute("SELECT name FROM users")):
                return True
            return any(r["name"].casefold() == key for r in c.execute(
                "SELECT name FROM invites WHERE used_by IS NULL AND revoked=0 AND expires_at>?", (now,)))
        return await self._run(fn)

    async def create_invite(self, name: str, lang: str, ttl_hours: int) -> Invite:
        code = secrets.token_urlsafe(9)
        now = int(time.time())
        expires = now + ttl_hours * 3600
        await self._run(lambda c: c.execute(
            "INSERT INTO invites(code,name,lang,created_at,expires_at) VALUES(?,?,?,?,?)",
            (code, name, lang, now, expires)))
        return Invite(code, name, lang, now, expires, None, False)

    async def list_pending_invites(self) -> list[Invite]:
        now = int(time.time())
        return await self._run(lambda c: [
            _invite(r) for r in c.execute(
                "SELECT * FROM invites WHERE used_by IS NULL AND revoked=0 AND expires_at>? ORDER BY created_at",
                (now,))])  # type: ignore[misc]

    async def revoke_invite(self, code: str) -> bool:
        return await self._run(lambda c: c.execute(
            "UPDATE invites SET revoked=1 WHERE code=? AND used_by IS NULL", (code,)).rowcount == 1)

    async def redeem_invite(self, code: str, tg_id: int) -> Invite | None:
        def fn(c) -> Invite | None:
            now = int(time.time())
            cur = c.execute(
                "UPDATE invites SET used_by=? WHERE code=? AND used_by IS NULL AND revoked=0 AND expires_at>?",
                (tg_id, code, now))
            if cur.rowcount != 1:
                return None
            inv = _invite(c.execute("SELECT * FROM invites WHERE code=?", (code,)).fetchone())
            assert inv is not None
            c.execute(
                "INSERT INTO users(tg_id,name,lang,active,started,created_at,last_seen) VALUES(?,?,?,1,1,?,?)",
                (tg_id, inv.name, inv.lang, now, now))
            return inv
        return await self._run(fn)

    async def bump_stat(self, field: str, amount: int = 1) -> None:
        allowed = {"messages", "media", "translation_errors", "provider_calls"}
        if field not in allowed:
            raise ValueError(field)
        day = time.strftime("%Y-%m-%d", time.gmtime())
        await self._run(lambda c: c.execute(
            f"INSERT INTO stats(day,{field}) VALUES(?,?) ON CONFLICT(day) DO UPDATE SET {field}={field}+excluded.{field}",
            (day, amount)))

    async def stats_today(self) -> tuple[int, int, int, int]:
        day = time.strftime("%Y-%m-%d", time.gmtime())
        def fn(c):
            r = c.execute("SELECT messages,media,translation_errors,provider_calls FROM stats WHERE day=?", (day,)).fetchone()
            return tuple(r) if r else (0, 0, 0, 0)
        return await self._run(fn)
