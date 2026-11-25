"""Покупка: тип (IPv4/IPv6) → страна → срок → количество → подтверждение → выдача. Каталог и цены — ProxyZen Shop API."""
from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..api import ApiError
from ..i18n import t
from ..money import fmt, to_cents
from ..shop import Shop, ShopError, flag
from .user import MENU_TEXTS, btn_texts, error_text, main_menu

router = Router(name="buy")
log = logging.getLogger("buy")

PAGE = 24
MAX_QTY = 1000
TYPE_NAME = {"ipv4": "IPv4", "ipv6": "IPv6"}


class Buy(StatesGroup):
    quantity = State()


def proxy_line(p: dict) -> str:
    return f"{p['host']}:{p['http_port']}:{p['login']}:{p['password']}"


async def catalog_or_error(msg: Message, lang: str, coro):
    try:
        return await coro
    except ApiError as e:
        log.error("catalog: %s %s", e.code, e.message)
        await msg.answer(t(lang, "e_shop_unavailable"))
        return None


# ---------- шаг 1: тип → страны ----------
@router.message(F.text.in_(btn_texts("btn_ipv4") | btn_texts("btn_ipv6")))
async def choose_type(message: Message, shop: Shop, lang: str, state: FSMContext) -> None:
    await state.clear()
    type_ = "ipv6" if message.text in btn_texts("btn_ipv6") else "ipv4"
    await show_countries(message, shop, lang, type_, 0, edit=False)


@router.callback_query(F.data.startswith("b:c:"))
async def countries_page(call: CallbackQuery, shop: Shop, lang: str) -> None:
    _, _, type_, page = call.data.split(":")
    await call.answer()
    await show_countries(call.message, shop, lang, type_, int(page), edit=True)


async def show_countries(msg: Message, shop: Shop, lang: str, type_: str, page: int, edit: bool) -> None:
    if (await shop.config()).get("maintenance"):
        await msg.answer(t(lang, "maintenance"))
        return
    rows = await catalog_or_error(msg, lang, shop.countries(type_, lang))
    if rows is None:
        return
    if not rows:
        await msg.answer(t(lang, "no_countries", type=TYPE_NAME[type_]))
        return
    kb = InlineKeyboardBuilder()
    for c in rows[page * PAGE:(page + 1) * PAGE]:
        kb.button(text=f"{flag(c['code'])} {c['name']} ({c['available']})", callback_data=f"b:p:{type_}:{c['code']}")
    kb.adjust(2)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="«", callback_data=f"b:c:{type_}:{page - 1}"))
    if (page + 1) * PAGE < len(rows):
        nav.append(InlineKeyboardButton(text="»", callback_data=f"b:c:{type_}:{page + 1}"))
    if nav:
        kb.row(*nav)
    text = t(lang, "choose_country", type=TYPE_NAME[type_], hint=t(lang, f"type_{type_}"))
    if edit:
        await msg.edit_text(text, reply_markup=kb.as_markup())
    else:
        await msg.answer(text, reply_markup=kb.as_markup())


# ---------- шаг 2: срок ----------
@router.callback_query(F.data.startswith("b:p:"))
async def choose_period(call: CallbackQuery, shop: Shop, lang: str) -> None:
    _, _, type_, country = call.data.split(":")
    await call.answer()
    info = await catalog_or_error(call.message, lang, shop.periods(country, type_, lang))
    if info is None:
        return
    kb = InlineKeyboardBuilder()
    for p in info["data"]:
        kb.button(text=t(lang, "period_btn", days=p["days"], price=fmt(to_cents(p["price"]))), callback_data=f"b:q:{type_}:{country}:{p['days']}")
    kb.button(text=t(lang, "btn_back"), callback_data=f"b:c:{type_}:0")
    kb.adjust(2)
    await call.message.edit_text(t(lang, "choose_period", flag=flag(country), country=html.escape(info["name"]), type=TYPE_NAME[type_]),
                                 reply_markup=kb.as_markup())


# ---------- шаг 3: количество ----------
@router.callback_query(F.data.startswith("b:q:"))
async def choose_qty(call: CallbackQuery, shop: Shop, lang: str, state: FSMContext) -> None:
    _, _, type_, country, days = call.data.split(":")
    await call.answer()
    try:
        price = await shop.period_price(country, type_, int(days), lang)
        name = (await shop.periods(country, type_, lang))["name"]
    except (ShopError, ApiError):
        await call.message.answer(t(lang, "e_invalid_period"))
        return
    kb = InlineKeyboardBuilder()
    for q in (1, 2, 5, 10, 25, 50):
        kb.button(text=str(q), callback_data=f"b:o:{type_}:{country}:{days}:{q}")
    kb.button(text=t(lang, "qty_custom"), callback_data=f"b:x:{type_}:{country}:{days}")
    kb.button(text=t(lang, "btn_back"), callback_data=f"b:p:{type_}:{country}")
    kb.adjust(3, 3, 1, 1)
    await state.update_data(order={"type": type_, "country": country, "days": int(days)})
    await call.message.edit_text(t(lang, "choose_qty", flag=flag(country), country=html.escape(name), type=TYPE_NAME[type_],
                                   days=days, price=fmt(price), max=MAX_QTY), reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("b:x:"))
async def ask_qty(call: CallbackQuery, lang: str, state: FSMContext) -> None:
    _, _, type_, country, days = call.data.split(":")
    await state.update_data(order={"type": type_, "country": country, "days": int(days)})
    await state.set_state(Buy.quantity)
    await call.answer()
    await call.message.answer(t(lang, "send_qty", max=MAX_QTY))


@router.message(Buy.quantity, F.text, ~F.text.in_(MENU_TEXTS))
async def got_qty(message: Message, shop: Shop, user, lang: str, state: FSMContext) -> None:
    text = message.text.strip()
    if not text.isdigit() or not 1 <= int(text) <= MAX_QTY:
        await message.answer(t(lang, "bad_qty", max=MAX_QTY))
        return
    order = (await state.get_data()).get("order") or {}
    await state.clear()
    if not order:
        await message.answer(t(lang, "menu_hint"), reply_markup=main_menu(lang))
        return
    await show_confirm(message, shop, user, lang, order["type"], order["country"], order["days"], int(text), edit=False)


@router.callback_query(F.data.startswith("b:o:"))
async def confirm_cb(call: CallbackQuery, shop: Shop, user, lang: str) -> None:
    _, _, type_, country, days, qty = call.data.split(":")
    await call.answer()
    await show_confirm(call.message, shop, user, lang, type_, country, int(days), int(qty), edit=True)


# ---------- шаг 4: подтверждение ----------
async def show_confirm(msg: Message, shop: Shop, user, lang: str, type_: str, country: str, days: int, qty: int, edit: bool) -> None:
    try:
        price = await shop.period_price(country, type_, days, lang)
        name = (await shop.periods(country, type_, lang))["name"]
    except (ShopError, ApiError):
        await msg.answer(t(lang, "e_invalid_period"))
        return
    total = price * qty
    fresh = await shop.db.user(user["id"])
    kb = InlineKeyboardBuilder()
    if fresh["balance"] >= total:
        kb.button(text=t(lang, "btn_pay", total=fmt(total)), callback_data=f"b:y:{type_}:{country}:{days}:{qty}")
    else:
        kb.button(text=t(lang, "btn_topup_need", need=fmt(total - fresh["balance"])), callback_data="tp")
    kb.button(text=t(lang, "btn_back"), callback_data=f"b:q:{type_}:{country}:{days}")
    kb.adjust(1)
    text = t(lang, "confirm", flag=flag(country), country=html.escape(name), type=TYPE_NAME[type_], days=days, qty=qty,
             price=fmt(price), total=fmt(total), balance=fmt(fresh["balance"]))
    if edit:
        await msg.edit_text(text, reply_markup=kb.as_markup())
    else:
        await msg.answer(text, reply_markup=kb.as_markup())


# ---------- шаг 5: покупка и выдача ----------
@router.callback_query(F.data.startswith("b:y:"))
async def do_buy(call: CallbackQuery, shop: Shop, user, lang: str) -> None:
    _, _, type_, country, days, qty = call.data.split(":")
    await call.answer()
    await call.message.edit_text(t(lang, "buying"))
    try:
        res = await shop.buy(user["id"], country, type_, int(days), int(qty), lang)
    except ShopError as e:
        await call.message.edit_text(error_text(lang, e))
        if e.code == "shop_unavailable":
            await notify_admins(call.bot, shop, f"⚠️ ProxyZen отказал в покупке: <code>{html.escape(e.detail)}</code>. Проверьте баланс и ключ ProxyZen (/admin).\n"
                                                f"ProxyZen declined a purchase — check your ProxyZen balance and API key.")
        return
    fresh = await shop.db.user(user["id"])
    proxies = res["proxies"]
    head = t(lang, "bought", id=res["order_id"], total=fmt(res["total"]), balance=fmt(fresh["balance"]))
    lines = [f"<code>{proxy_line(p)}</code>  SOCKS5:{p['socks5_port']}" for p in proxies[:15]]
    await call.message.edit_text(head + "\n\n" + "\n".join(lines))
    if len(proxies) > 1:   # файл .txt — удобно вставить в софт
        body = "\n".join(proxy_line(p) for p in proxies) + "\n"
        await call.message.answer_document(BufferedInputFile(body.encode(), filename=f"proxies_{res['order_id']}.txt"),
                                           caption=t(lang, "file_caption", id=res["order_id"]))


async def notify_admins(bot, shop: Shop, text: str) -> None:
    for admin in shop.admin_ids:
        try:
            await bot.send_message(admin, text)
        except Exception:
            pass
