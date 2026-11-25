"""Фоновые задачи: оплаты, автопродление и напоминания (список от ProxyZen), отметка у ProxyZen."""
from __future__ import annotations

import asyncio
import html
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from .api import ApiError
from .db import now
from .i18n import t
from .money import fmt
from .shop import Shop, ShopError, flag

log = logging.getLogger("tasks")


async def send(bot: Bot, shop: Shop, uid: int, text: str) -> bool:
    try:
        await bot.send_message(uid, text, disable_web_page_preview=True)
        return True
    except TelegramForbiddenError:
        await shop.db.run("UPDATE users SET blocked_bot=1 WHERE id=?", uid)
    except Exception as e:
        log.warning("send to %s failed: %s", uid, e)
    return False


async def loop(name: str, every: int, fn, *args) -> None:
    await asyncio.sleep(5)
    while True:
        try:
            await fn(*args)
        except ApiError as e:
            if e.code != "no_key":
                log.warning("%s: %s %s", name, e.code, e.message)
        except Exception:
            log.exception("%s failed", name)
        await asyncio.sleep(every)


async def payments(bot: Bot, shop: Shop) -> None:
    for row in await shop.check_invoices():
        user = await shop.db.user(row["user_id"])
        await send(bot, shop, row["user_id"], t(user["lang"], "paid", amount=fmt(row["amount"]), balance=fmt(user["balance"])))


def plist(proxies: list[dict]) -> str:
    return "\n".join(f"{flag(p['country'])} <code>{p['host']}:{p['http_port']}</code>" for p in proxies[:20])


async def due(bot: Bot, shop: Shop) -> None:
    """ProxyZen говорит, что пора: автопродлить (списываем с баланса здесь) и кого предупредить."""
    api = await shop.api()
    if not api.key:
        return
    d = await api.due()
    for item in d.get("renew", []):
        uid, days, ids = int(item["customer"]), int(item["days"]), [int(i) for i in item["ids"]]
        user = await shop.db.user(uid)
        if not user:
            await api.notified(ids, "auto_off")
            continue
        try:
            total = await shop.renew(uid, ids, days, user["lang"])
            await send(bot, shop, uid, t(user["lang"], "auto_ok", n=len(ids), days=days, total=fmt(total)))
        except ShopError as e:
            await api.notified(ids, "auto_off")   # не получилось — выключаем, чтобы не пытаться бесконечно
            detail = fmt(int(e.detail)) if e.detail.isdigit() else e.detail
            await send(bot, shop, uid, t(user["lang"], "auto_fail", n=len(ids), reason=t(user["lang"], f"e_{e.code}", detail=detail)))
    for kind, key in (("soon", "soon"), ("expired", "expired_note")):
        for item in d.get(kind, []):
            uid = int(item["customer"])
            user = await shop.db.user(uid)
            proxies = item["proxies"]
            if user:
                kw = {"hours": 24} if kind == "soon" else {"until": proxies[0].get("renewable_until", "")[:16].replace("T", " ") + " UTC"}
                await send(bot, shop, uid, t(user["lang"], key, list=plist(proxies), **kw))
            await api.notified([int(p["id"]) for p in proxies], kind)


async def ping(bot: Bot, shop: Shop) -> None:
    """Отметка у ProxyZen (версия, бот, пользователи) + предупреждение админам о низком балансе ProxyZen."""
    api = await shop.api()
    if not api.key:
        return
    me = await bot.me()
    res = await api.ping(me.username or "", await shop.db.val("SELECT COUNT(*) FROM users"))
    shop.notice = str(res.get("notice") or "")
    shop.latest_version = str(res.get("latest_version") or "")
    cfg = await api.config()
    threshold = float(cfg.get("low_balance_alert") or 0)
    balance = float(cfg.get("balance") or 0)
    last = int(await shop.db.setting("low_alert_at") or 0)
    if threshold and balance < threshold and now() - last > 12 * 3600:
        await shop.db.set_setting("low_alert_at", str(now()))
        for admin in shop.admin_ids:
            await send(bot, shop, admin, f"⚠️ Баланс ProxyZen: <b>${html.escape(str(cfg.get('balance')))}</b> — пополните, иначе клиенты не смогут купить прокси.\n"
                                         f"Your ProxyZen balance is low — top up at https://proxyzen.net/cabinet")


def start(bot: Bot, shop: Shop) -> list[asyncio.Task]:
    return [
        asyncio.create_task(loop("payments", 20, payments, bot, shop)),
        asyncio.create_task(loop("due", 600, due, bot, shop)),
        asyncio.create_task(loop("ping", 3 * 3600, ping, bot, shop)),
    ]
