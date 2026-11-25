"""ProxyZen Telegram Shop — точка входа.

Запуск:  python bot.py        (настройки — в .env, см. README.md)
"""
from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from app import __version__, config, tasks
from app.db import DB
from app.handlers import admin, buy, proxies, traffic, user
from app.middleware import UserMiddleware
from app.shop import Shop


def build(cfg: config.Config, db: DB) -> tuple[Dispatcher, Shop]:
    shop = Shop(db, cfg.admin_ids, cfg.api_key_env)
    dp = Dispatcher(storage=MemoryStorage(), shop=shop)
    dp.message.outer_middleware(UserMiddleware())
    dp.callback_query.outer_middleware(UserMiddleware())
    # админка первой — её шаги ввода важнее общих обработчиков
    dp.include_routers(admin.setup(cfg.admin_ids), user.router, buy.router, traffic.router, proxies.router)
    return dp, shop


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stdout)
    cfg = config.load()
    db = DB(cfg.db_path)
    await db.open()
    bot = Bot(cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
    dp, shop = build(cfg, db)

    me = await bot.me()
    logging.info("ProxyZen Shop %s started as @%s", __version__, me.username)
    for lang in ("ru", "en"):
        await bot.set_my_commands([
            BotCommand(command="start", description="Главное меню" if lang == "ru" else "Main menu"),
            BotCommand(command="profile", description="Профиль" if lang == "ru" else "Profile"),
            BotCommand(command="support", description="Поддержка" if lang == "ru" else "Support"),
        ], language_code=lang)

    background = tasks.start(bot, shop)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        for task in background:
            task.cancel()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as e:
        if isinstance(e, SystemExit) and e.code not in (None, 0):
            print(e.code, file=sys.stderr)
            sys.exit(1)
