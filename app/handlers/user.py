"""/start, главное меню, профиль, история, пополнение (любая подключённая платёжка), поддержка."""
from __future__ import annotations

import html
import logging
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, KeyboardButton, Message, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..api import ApiError
from ..i18n import T, t
from ..money import fmt, parse_amount
from ..payments import PaymentError
from ..shop import Shop, ShopError

router = Router(name="user")
log = logging.getLogger("user")

MENU_KEYS = ("btn_ipv4", "btn_ipv6", "btn_res", "btn_mob", "btn_my", "btn_profile", "btn_topup", "btn_support")
MENU_TEXTS = {t(lang, k) for lang in ("ru", "en") for k in MENU_KEYS}


def btn_texts(key: str) -> set[str]:
    return {t("ru", key), t("en", key)}


def main_menu(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(resize_keyboard=True, is_persistent=True, keyboard=[
        [KeyboardButton(text=t(lang, "btn_ipv4")), KeyboardButton(text=t(lang, "btn_ipv6"))],
        [KeyboardButton(text=t(lang, "btn_res")), KeyboardButton(text=t(lang, "btn_mob"))],
        [KeyboardButton(text=t(lang, "btn_my")), KeyboardButton(text=t(lang, "btn_profile"))],
        [KeyboardButton(text=t(lang, "btn_topup")), KeyboardButton(text=t(lang, "btn_support"))],
    ])


def error_text(lang: str, e: ShopError) -> str:
    detail = e.detail
    if e.code in ("insufficient_funds", "min_topup") and detail.lstrip("-").isdigit():
        detail = fmt(int(detail))
    return t(lang, f"e_{e.code}", detail=html.escape(detail)) if f"e_{e.code}" in T["en"] else t(lang, "e_generic")


def date(ts: int | str | None) -> str:
    if not ts:
        return "—"
    if isinstance(ts, str):
        ts = int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d.%m.%Y %H:%M UTC")


class TopUp(StatesGroup):
    amount = State()


# ---------- /start ----------
@router.message(CommandStart())
async def start(message: Message, shop: Shop, lang: str, state: FSMContext) -> None:
    await state.clear()
    cfg = await shop.config()
    welcome = cfg.get("welcome") or t(lang, "welcome_default")
    text = f"<b>{html.escape(cfg.get('name') or 'Proxy Shop')}</b>\n\n{welcome}\n\n<i>{t(lang, 'powered')}</i>"
    photo = await shop.db.setting("start_photo")
    if photo:
        try:
            await message.answer_photo(photo, caption=text[:1024], reply_markup=main_menu(lang))
            return
        except Exception as e:
            log.warning("start photo failed: %s", e)
    await message.answer(text, reply_markup=main_menu(lang), disable_web_page_preview=True)


@router.message(Command("menu"))
@router.callback_query(F.data == "menu")
async def menu(event: Message | CallbackQuery, lang: str, state: FSMContext) -> None:
    await state.clear()
    msg = event.message if isinstance(event, CallbackQuery) else event
    if isinstance(event, CallbackQuery):
        await event.answer()
    await msg.answer(t(lang, "menu_hint"), reply_markup=main_menu(lang))


@router.callback_query(StateFilter("*"), F.data == "cancel")
async def cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.answer()
    await call.message.delete()


# ---------- профиль ----------
@router.message(F.text.in_(btn_texts("btn_profile")))
@router.message(Command("profile"))
async def profile(message: Message, shop: Shop, user, lang: str, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    try:
        active = len(await shop.proxies(user["id"]))
    except (ApiError, ShopError):
        active = "—"
    bought = await shop.db.val("SELECT COUNT(*) FROM transactions WHERE user_id=? AND kind='purchase'", user["id"])
    failed = await shop.db.val("SELECT COUNT(*) FROM transactions WHERE user_id=? AND kind='refund' AND ref NOT LIKE 'renew%'", user["id"])
    text = t(lang, "profile", id=user["id"], balance=fmt(user["balance"]), active=active, orders=max(bought - failed, 0),
             spent=fmt(user["spent"]), since=date(user["created_at"])[:10])
    percent = float((await shop.config()).get("ref_percent") or 0)
    if percent > 0:
        me = await bot.me()
        text += t(lang, "profile_ref", percent=f"{percent:g}", link=f"https://t.me/{me.username}?start=r{user['id']}", earned=fmt(user["ref_earned"]))
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "btn_topup"), callback_data="tp")
    kb.button(text=t(lang, "btn_history"), callback_data="pr:hist")
    kb.button(text=t(lang, "btn_lang"), callback_data="pr:lang")
    kb.adjust(1, 2)
    await message.answer(text, reply_markup=kb.as_markup(), disable_web_page_preview=True)


@router.callback_query(F.data == "pr:lang")
async def switch_lang(call: CallbackQuery, shop: Shop, user) -> None:
    new = "en" if user["lang"] == "ru" else "ru"
    await shop.db.run("UPDATE users SET lang=? WHERE id=?", new, user["id"])
    await call.answer()
    await call.message.answer(t(new, "menu_hint"), reply_markup=main_menu(new))


@router.callback_query(F.data == "pr:hist")
async def history(call: CallbackQuery, shop: Shop, user, lang: str) -> None:
    rows = await shop.db.all("SELECT * FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 15", user["id"])
    await call.answer()
    if not rows:
        await call.message.answer(t(lang, "history_empty"))
        return
    lines = [f"{date(r['created_at'])[:16]} · {t(lang, 'tx_' + r['kind'])} · <b>{'+' if r['amount'] > 0 else ''}{fmt(r['amount'])}</b>" for r in rows]
    await call.message.answer(t(lang, "history", rows="\n".join(lines)))


# ---------- пополнение ----------
TOPUP_AMOUNTS = [500, 1000, 2500, 5000, 10000]


@router.message(F.text.in_(btn_texts("btn_topup")))
@router.callback_query(F.data == "tp")
async def topup(event: Message | CallbackQuery, shop: Shop, lang: str, state: FSMContext) -> None:
    msg = event.message if isinstance(event, CallbackQuery) else event
    if isinstance(event, CallbackQuery):
        await event.answer()
    if not await shop.providers():
        await msg.answer(t(lang, "topup_off"))
        return
    minimum = int(await shop.db.setting("min_topup") or 100)
    kb = InlineKeyboardBuilder()
    for a in [x for x in TOPUP_AMOUNTS if x >= minimum] or [minimum]:
        kb.button(text=fmt(a), callback_data=f"tp:a:{a}")
    kb.adjust(3)
    await state.set_state(TopUp.amount)
    await msg.answer(t(lang, "topup", min=fmt(minimum)), reply_markup=kb.as_markup())


async def _choose_method(msg: Message, shop: Shop, user, lang: str, amount: int, bot: Bot) -> None:
    providers = await shop.providers()
    if len(providers) == 1:
        await _invoice(msg, shop, user, lang, amount, providers[0].code, bot)
        return
    kb = InlineKeyboardBuilder()
    for p in providers:
        kb.button(text=p.title, callback_data=f"tp:p:{p.code}:{amount}")
    kb.adjust(1)
    await msg.answer(t(lang, "choose_method"), reply_markup=kb.as_markup())


async def _invoice(msg: Message, shop: Shop, user, lang: str, amount: int, provider: str, bot: Bot) -> None:
    try:
        me = await bot.me()
        inv = await shop.create_topup(user["id"], amount, provider, me.username)
        title = (await shop.provider(provider)).title
    except ShopError as e:
        await msg.answer(error_text(lang, e))
        return
    except PaymentError as e:
        log.error("invoice failed: %s", e)
        await msg.answer(t(lang, "topup_off"))
        return
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "btn_invoice", amount=fmt(amount)), url=inv["url"])
    kb.button(text=t(lang, "btn_check"), callback_data=f"tp:chk:{inv['id']}")
    kb.adjust(1)
    await msg.answer(t(lang, "invoice", amount=fmt(amount), method=html.escape(title)), reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("tp:a:"))
async def topup_amount(call: CallbackQuery, shop: Shop, user, lang: str, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    await call.answer()
    await _choose_method(call.message, shop, user, lang, int(call.data.split(":")[2]), bot)


@router.callback_query(F.data.startswith("tp:p:"))
async def topup_provider(call: CallbackQuery, shop: Shop, user, lang: str, bot: Bot) -> None:
    _, _, code, amount = call.data.split(":")
    await call.answer()
    await _invoice(call.message, shop, user, lang, int(amount), code, bot)


@router.message(TopUp.amount, F.text, ~F.text.in_(MENU_TEXTS))
async def topup_custom(message: Message, shop: Shop, user, lang: str, state: FSMContext, bot: Bot) -> None:
    minimum = int(await shop.db.setting("min_topup") or 100)
    amount = parse_amount(message.text)
    if amount is None or amount < minimum:
        await message.answer(t(lang, "bad_amount", min=fmt(minimum)))
        return
    await state.clear()
    await _choose_method(message, shop, user, lang, amount, bot)


@router.callback_query(F.data.startswith("tp:chk:"))
async def topup_check(call: CallbackQuery, shop: Shop, user, lang: str) -> None:
    row_id = int(call.data.split(":")[2])
    await shop.check_invoices()
    row = await shop.db.one("SELECT * FROM invoices WHERE id=? AND user_id=?", row_id, user["id"])
    if row and row["status"] == "paid":
        fresh = await shop.db.user(user["id"])
        await call.answer()
        await call.message.edit_text(t(lang, "paid", amount=fmt(row["amount"]), balance=fmt(fresh["balance"])))
    else:
        await call.answer(t(lang, "not_paid_yet"), show_alert=True)


# ---------- поддержка ----------
@router.message(F.text.in_(btn_texts("btn_support")))
@router.message(Command("support"))
async def support(message: Message, shop: Shop, lang: str, state: FSMContext) -> None:
    await state.clear()
    contact = ((await shop.config()).get("support") or "").strip().lstrip("@")
    if not contact:
        await message.answer(t(lang, "support_none"))
        return
    url = contact if contact.startswith("http") else f"https://t.me/{contact}"
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "btn_write"), url=url)
    await message.answer(t(lang, "support"), reply_markup=kb.as_markup())
