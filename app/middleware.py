"""Регистрация пользователя, язык, бан — до любого обработчика."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from .i18n import lang_for, t


class UserMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]], event: TelegramObject, data: dict[str, Any]) -> Any:
        tg_user = data.get("event_from_user")
        chat = data.get("event_chat")
        if tg_user is None or tg_user.is_bot or (chat is not None and chat.type != "private"):
            return None   # магазин работает только в личке
        shop = data["shop"]
        ref = None
        if isinstance(event, Message) and event.text and event.text.startswith("/start "):
            arg = event.text.split(maxsplit=1)[1]
            if arg.startswith("r") and arg[1:].isdigit():
                ref = int(arg[1:])
        user, _ = await shop.db.touch_user(tg_user.id, tg_user.username, tg_user.first_name, lang_for(tg_user.language_code), ref)
        data["user"] = user
        data["lang"] = user["lang"]
        data["is_admin"] = tg_user.id in shop.admin_ids
        if user["banned"] and not data["is_admin"]:
            text = t(user["lang"], "banned")
            if isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
            elif isinstance(event, Message):
                await event.answer(text)
            return None
        return await handler(event, data)
