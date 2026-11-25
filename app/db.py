"""SQLite у владельца магазина: пользователи, балансы, история, счета платёжных систем, локальные настройки.

Каталог, цены, заказы и прокси клиентов хранит ProxyZen (Shop API) — здесь их нет.

Все изменения баланса идут через change_balance() — одна транзакция,
баланс не уходит в минус, каждое движение записано в transactions.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,               -- Telegram user id
    username TEXT,
    first_name TEXT,
    lang TEXT NOT NULL DEFAULT 'en',
    balance INTEGER NOT NULL DEFAULT 0,   -- центы
    spent INTEGER NOT NULL DEFAULT 0,     -- центы, всего потрачено на прокси
    topped_up INTEGER NOT NULL DEFAULT 0, -- центы, всего пополнено
    ref_by INTEGER,
    ref_earned INTEGER NOT NULL DEFAULT 0,
    banned INTEGER NOT NULL DEFAULT 0,
    blocked_bot INTEGER NOT NULL DEFAULT 0, -- пользователь заблокировал бота (рассылка не дошла)
    created_at INTEGER NOT NULL,
    last_seen INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,              -- центы, +/-
    balance_after INTEGER NOT NULL,
    kind TEXT NOT NULL,                   -- topup | purchase | renew | refund | admin | referral
    ref TEXT,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS tx_user ON transactions(user_id);
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    provider TEXT NOT NULL DEFAULT 'cryptobot',
    invoice_id TEXT,                      -- id счёта у платёжной системы
    amount INTEGER NOT NULL,              -- центы
    url TEXT,
    status TEXT NOT NULL DEFAULT 'active',-- active | paid | expired
    created_at INTEGER NOT NULL,
    paid_at INTEGER
);
CREATE INDEX IF NOT EXISTS inv_status ON invoices(status);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""

DEFAULTS = {
    "api_key": "",        # API-ключ ProxyZen
    "start_photo": "",    # file_id картинки для /start (у каждого бота свой)
    "min_topup": "100",   # центы
}


def now() -> int:
    return int(time.time())


class InsufficientFunds(Exception):
    pass


class DB:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self.conn: aiosqlite.Connection | None = None
        self.lock = asyncio.Lock()   # одна запись за раз — баланс не гоняется

    async def open(self) -> None:
        self.conn = await aiosqlite.connect(self.path, isolation_level=None)  # autocommit; транзакции — явно
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA foreign_keys=ON")
        await self.conn.executescript(SCHEMA)
        # обновление с версии 1.x: у счетов появился провайдер платежей
        cols = [r[1] for r in await self.all("PRAGMA table_info(invoices)")]
        if "provider" not in cols:
            await self.conn.execute("ALTER TABLE invoices ADD COLUMN provider TEXT NOT NULL DEFAULT 'cryptobot'")
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    async def one(self, sql: str, *args) -> aiosqlite.Row | None:
        async with self.conn.execute(sql, args) as cur:
            return await cur.fetchone()

    async def all(self, sql: str, *args) -> list[aiosqlite.Row]:
        async with self.conn.execute(sql, args) as cur:
            return list(await cur.fetchall())

    async def val(self, sql: str, *args, default: Any = 0) -> Any:
        row = await self.one(sql, *args)
        return row[0] if row and row[0] is not None else default

    async def run(self, sql: str, *args) -> int:
        async with self.lock:
            cur = await self.conn.execute(sql, args)
            await self.conn.commit()
            return cur.lastrowid

    # ---------- настройки ----------
    async def setting(self, key: str) -> str:
        row = await self.one("SELECT value FROM settings WHERE key=?", key)
        return row["value"] if row and row["value"] is not None else DEFAULTS.get(key, "")

    async def set_setting(self, key: str, value: str) -> None:
        await self.run("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", key, value)

    # ---------- пользователи ----------
    async def touch_user(self, uid: int, username: str | None, first_name: str | None, lang: str, ref_by: int | None = None) -> tuple[aiosqlite.Row, bool]:
        row = await self.one("SELECT * FROM users WHERE id=?", uid)
        if row:
            await self.run("UPDATE users SET username=?, first_name=?, last_seen=?, blocked_bot=0 WHERE id=?", username, first_name, now(), uid)
            return await self.one("SELECT * FROM users WHERE id=?", uid), False
        if ref_by == uid or (ref_by and not await self.one("SELECT 1 FROM users WHERE id=?", ref_by)):
            ref_by = None
        await self.run("INSERT INTO users(id,username,first_name,lang,ref_by,created_at,last_seen) VALUES(?,?,?,?,?,?,?)",
                       uid, username, first_name, lang, ref_by, now(), now())
        return await self.one("SELECT * FROM users WHERE id=?", uid), True

    async def user(self, uid: int) -> aiosqlite.Row | None:
        return await self.one("SELECT * FROM users WHERE id=?", uid)

    async def find_user(self, query: str) -> aiosqlite.Row | None:
        q = query.strip().lstrip("@")
        if q.lstrip("-").isdigit():
            return await self.user(int(q))
        return await self.one("SELECT * FROM users WHERE lower(username)=lower(?)", q)

    async def change_balance(self, uid: int, amount: int, kind: str, ref: str | None = None,
                             spent: int = 0, topped_up: int = 0) -> int:
        """Атомарно изменить баланс. При списании больше остатка — InsufficientFunds. Возвращает новый баланс."""
        async with self.lock:
            await self.conn.execute("BEGIN IMMEDIATE")
            try:
                async with self.conn.execute("SELECT balance FROM users WHERE id=?", (uid,)) as cur:
                    row = await cur.fetchone()
                if row is None:
                    raise KeyError(uid)
                new = row[0] + amount
                if new < 0:
                    raise InsufficientFunds(row[0])
                await self.conn.execute("UPDATE users SET balance=?, spent=spent+?, topped_up=topped_up+? WHERE id=?",
                                        (new, spent, topped_up, uid))
                await self.conn.execute("INSERT INTO transactions(user_id,amount,balance_after,kind,ref,created_at) VALUES(?,?,?,?,?,?)",
                                        (uid, amount, new, kind, ref, now()))
                await self.conn.commit()
                return new
            except BaseException:
                await self.conn.rollback()
                raise

    # ---------- счета ----------
    async def mark_invoice_paid(self, invoice_row_id: int) -> bool:
        """Перевести счёт в paid ровно один раз (защита от двойного зачисления)."""
        async with self.lock:
            cur = await self.conn.execute("UPDATE invoices SET status='paid', paid_at=? WHERE id=? AND status='active'", (now(), invoice_row_id))
            await self.conn.commit()
            return cur.rowcount == 1
