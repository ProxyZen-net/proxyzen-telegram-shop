"""Мои прокси (данные у ProxyZen): список, карточка, продление одного или всех, автопродление, выгрузка .txt."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..api import ApiError
from ..i18n import t
from ..money import fmt
from ..shop import Shop, ShopError, flag
from .buy import TYPE_NAME
from .traffic import plan_buttons
from .user import btn_texts, date, error_text

router = Router(name="proxies")
PAGE = 10


def status_text(lang: str, p: dict) -> str:
    if p["status"] == "grace":
        return t(lang, "st_grace", until=date(p.get("renewable_until")))
    return t(lang, f"st_{p['status']}") if p["status"] in ("active", "expired", "refunding") else p["status"]


async def load(msg: Message, shop: Shop, uid: int, lang: str) -> list[dict] | None:
    try:
        return await shop.proxies(uid)
    except (ApiError, ShopError):
        await msg.answer(t(lang, "e_shop_unavailable"))
        return None


@router.message(F.text.in_(btn_texts("btn_my")))
async def my_proxies(message: Message, shop: Shop, user, lang: str, state: FSMContext) -> None:
    await state.clear()
    await show_list(message, shop, user, lang, 0, edit=False)


@router.callback_query(F.data.startswith("px:l:"))
async def list_page(call: CallbackQuery, shop: Shop, user, lang: str) -> None:
    await call.answer()
    await show_list(call.message, shop, user, lang, int(call.data.split(":")[2]), edit=True)


async def show_list(msg: Message, shop: Shop, user, lang: str, page: int, edit: bool) -> None:
    rows = await load(msg, shop, user["id"], lang)
    if rows is None:
        return
    plans = await plan_buttons(shop, user["id"], lang)   # резидентские/мобильные — первыми
    if not rows and not plans:
        await msg.answer(t(lang, "my_empty"))
        return
    kb = InlineKeyboardBuilder()
    for text, cb in plans:
        kb.button(text=text, callback_data=cb)
    for p in rows[page * PAGE:(page + 1) * PAGE]:
        mark = "🟡 " if p["status"] == "grace" else ""
        kb.button(text=f"{mark}{flag(p['country'])} {p['host']}:{p['http_port']} · {date(p['expires_at'])[:10]}", callback_data=f"px:o:{p['id']}")
    kb.adjust(1)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="«", callback_data=f"px:l:{page - 1}"))
    if (page + 1) * PAGE < len(rows):
        nav.append(InlineKeyboardButton(text="»", callback_data=f"px:l:{page + 1}"))
    if nav:
        kb.row(*nav)
    if rows:
        kb.row(InlineKeyboardButton(text=t(lang, "btn_renew_all"), callback_data="px:ra"),
               InlineKeyboardButton(text=t(lang, "btn_export"), callback_data="px:e"))
    text = t(lang, "my_list", n=len(rows) + len(plans))
    if edit:
        await msg.edit_text(text, reply_markup=kb.as_markup())
    else:
        await msg.answer(text, reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("px:o:"))
async def card(call: CallbackQuery, shop: Shop, user, lang: str) -> None:
    await call.answer()
    await show_card(call.message, shop, user, lang, int(call.data.split(":")[2]))


async def show_card(msg: Message, shop: Shop, user, lang: str, pid: int) -> None:
    rows = await load(msg, shop, user["id"], lang)
    p = next((r for r in rows or [] if r["id"] == pid), None)
    if not p:
        await msg.answer(t(lang, "e_not_found"))
        return
    vals = dict(host=p["host"], http=p["http_port"], socks=p["socks5_port"], login=p["login"] or "—", password=p["password"] or "—")
    text = t(lang, "px_card", flag=flag(p["country"]), country=p["country"], type=TYPE_NAME.get(p["type"], p["type"]), ip=p.get("ip") or p["host"],
             status=status_text(lang, p), expires=date(p["expires_at"]), auto=t(lang, "on" if p["auto_renew"] else "off"), **vals)
    if p["login"]:
        text += "\n\n" + t(lang, "px_formats", **vals)
    kb = InlineKeyboardBuilder()
    if p["status"] in ("active", "grace"):
        kb.button(text=t(lang, "btn_renew"), callback_data=f"px:r:{pid}")
    if p["status"] == "active":
        kb.button(text=t(lang, "btn_auto_off" if p["auto_renew"] else "btn_auto_on"), callback_data=f"px:a:{pid}:{0 if p['auto_renew'] else 1}")
    kb.button(text=t(lang, "btn_back"), callback_data="px:l:0")
    kb.adjust(1)
    await msg.edit_text(text, reply_markup=kb.as_markup())


# ---------- продление ----------
async def period_keyboard(shop: Shop, uid: int, lang: str, ids: list[int], prefix: str):
    kb = InlineKeyboardBuilder()
    for days, total in await shop.renew_options(uid, ids):
        kb.button(text=t(lang, "period_btn", days=days, price=fmt(total)), callback_data=f"{prefix}:{days}")
    kb.button(text=t(lang, "btn_back"), callback_data="px:l:0")
    kb.adjust(2)
    return kb.as_markup()


@router.callback_query(F.data.regexp(r"^px:r:\d+$"))
async def renew_one(call: CallbackQuery, shop: Shop, user, lang: str) -> None:
    pid = int(call.data.split(":")[2])
    await call.answer()
    try:
        kb = await period_keyboard(shop, user["id"], lang, [pid], f"px:rd:{pid}")
    except ShopError as e:
        await call.message.answer(error_text(lang, e))
        return
    await call.message.edit_text(t(lang, "renew_choose", n=1), reply_markup=kb)


@router.callback_query(F.data == "px:ra")
async def renew_all(call: CallbackQuery, shop: Shop, user, lang: str) -> None:
    await call.answer()
    rows = await load(call.message, shop, user["id"], lang)
    if not rows:
        return
    try:
        kb = await period_keyboard(shop, user["id"], lang, [r["id"] for r in rows], "px:rad")
    except ShopError as e:
        await call.message.answer(error_text(lang, e))
        return
    await call.message.edit_text(t(lang, "renew_choose", n=len(rows)), reply_markup=kb)


async def _do_renew(call: CallbackQuery, shop: Shop, user, lang: str, ids: list[int], days: int) -> None:
    await call.answer()
    try:
        total = await shop.renew(user["id"], ids, days, lang)
    except ShopError as e:
        kb = InlineKeyboardBuilder()
        if e.code == "insufficient_funds":
            kb.button(text=t(lang, "btn_topup"), callback_data="tp")
        await call.message.edit_text(error_text(lang, e), reply_markup=kb.as_markup())
        return
    fresh = await shop.db.user(user["id"])
    await call.message.edit_text(t(lang, "renewed", n=len(ids), days=days, total=fmt(total), balance=fmt(fresh["balance"])))


@router.callback_query(F.data.startswith("px:rd:"))
async def renew_one_do(call: CallbackQuery, shop: Shop, user, lang: str) -> None:
    _, _, pid, days = call.data.split(":")
    await _do_renew(call, shop, user, lang, [int(pid)], int(days))


@router.callback_query(F.data.startswith("px:rad:"))
async def renew_all_do(call: CallbackQuery, shop: Shop, user, lang: str) -> None:
    rows = await load(call.message, shop, user["id"], lang)
    if rows:
        await _do_renew(call, shop, user, lang, [r["id"] for r in rows], int(call.data.split(":")[2]))


# ---------- автопродление и выгрузка ----------
@router.callback_query(F.data.startswith("px:a:"))
async def toggle_auto(call: CallbackQuery, shop: Shop, user, lang: str) -> None:
    _, _, pid, enabled = call.data.split(":")
    try:
        await shop.set_auto_renew(user["id"], int(pid), enabled == "1")
    except ShopError as e:
        await call.answer(error_text(lang, e), show_alert=True)
        return
    await call.answer(t(lang, "auto_set", state=t(lang, "on" if enabled == "1" else "off")), show_alert=True)
    await show_card(call.message, shop, user, lang, int(pid))


@router.callback_query(F.data == "px:e")
async def export(call: CallbackQuery, shop: Shop, user, lang: str) -> None:
    await call.answer()
    rows = await load(call.message, shop, user["id"], lang)
    if not rows:
        return
    body = "\n".join(f"{r['host']}:{r['http_port']}:{r['login']}:{r['password']}" for r in rows if r["login"]) + "\n"
    await call.message.answer_document(BufferedInputFile(body.encode(), filename="proxies.txt"), caption=t(lang, "my_list", n=len(rows)))
