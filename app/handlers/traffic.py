"""Резидентские и мобильные прокси (оплата за ГБ): покупка/докупка, карточка с остатком,
сборка строки подключения (страна, регион/город, оператор, один IP на время, HTTP/SOCKS5), смена пароля.
Цены, планы покупателей и списки стран — ProxyZen Shop API; деньги покупателя — здесь, у владельца."""
from __future__ import annotations

import html
import random
import string

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..api import ApiError
from ..i18n import t
from ..money import fmt
from ..shop import Shop, ShopError, flag
from .buy import notify_admins
from .user import MENU_TEXTS, btn_texts, error_text

router = Router(name="traffic")

TYPES = ("residential", "mobile")
ICON = {"residential": "🏠", "mobile": "📱"}
GB_CHOICES = (1, 5, 10, 25, 50, 100)
MAX_GB = 1000
PAGE = 24


class TBuy(StatesGroup):
    gb = State()


def gb_text(v: float) -> str:
    v = float(v)
    return f"{v:.1f}" if v >= 10 else f"{v:.3f}".rstrip("0").rstrip(".")


def name(lang: str, type_: str) -> str:
    return t(lang, f"tr_name_{type_}")


def new_session() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=6))


async def gen_get(state: FSMContext, type_: str) -> dict:
    g = (await state.get_data()).get(f"gen_{type_}") or {}
    return {"country": "", "region": "", "city": "", "asn": "", "label": "", "sticky": False, "minutes": 10,
            "session": new_session(), "proto": "http", **g}


async def gen_set(state: FSMContext, type_: str, **kw) -> dict:
    g = {**await gen_get(state, type_), **kw}
    await state.update_data(**{f"gen_{type_}": g})
    return g


def build_login(plan: dict, g: dict, type_: str) -> str:
    login = plan["username"]
    if g["country"]:
        login += f"-country-{g['country']}"
        if g["asn"]:
            login += f"-asn-{g['asn']}"
        elif type_ == "residential" and g["region"]:
            login += f"-state-{g['region']}"
            if g["city"]:
                login += f"-city-{g['city']}"
    if g["sticky"]:
        login += f"-session-{g['session']}-time-{g['minutes']}"
    return login


async def load_plan(shop: Shop, uid: int, type_: str) -> dict | None:
    try:
        return next((p for p in await shop.traffic_plans(uid) if p["type"] == type_), None)
    except (ApiError, ShopError):
        return None


# ---------- покупка ----------
@router.message(F.text.in_(btn_texts("btn_res") | btn_texts("btn_mob")))
async def open_type(message: Message, shop: Shop, user, lang: str, state: FSMContext) -> None:
    await state.set_state(None)
    type_ = "mobile" if message.text in btn_texts("btn_mob") else "residential"
    await show_buy(message, shop, user, lang, type_, edit=False)


@router.callback_query(F.data.startswith("tr:buy:"))
async def open_type_cb(call: CallbackQuery, shop: Shop, user, lang: str) -> None:
    await call.answer()
    await show_buy(call.message, shop, user, lang, call.data.split(":")[2], edit=True)


async def show_buy(msg: Message, shop: Shop, user, lang: str, type_: str, edit: bool) -> None:
    if (await shop.config()).get("maintenance"):
        await msg.answer(t(lang, "maintenance"))
        return
    price = await shop.traffic_price(type_)
    if price is None:
        await msg.answer(t(lang, "tr_off"))
        return
    plan = await load_plan(shop, user["id"], type_)
    left = t(lang, "tr_left", gb=gb_text(plan["remaining_gb"])) if plan else ""
    kb = InlineKeyboardBuilder()
    for n in GB_CHOICES:
        kb.button(text=t(lang, "tr_gb_btn", n=n, price=fmt(price * n)), callback_data=f"tr:q:{type_}:{n}")
    kb.button(text=t(lang, "qty_custom"), callback_data=f"tr:x:{type_}")
    if plan:
        kb.button(text=t(lang, "btn_tr_my"), callback_data=f"tr:o:{type_}")
    kb.adjust(2, 2, 2, 1, 1)
    text = t(lang, "tr_buy", icon=ICON[type_], name=name(lang, type_), desc=t(lang, f"tr_desc_{type_}"), price=fmt(price), left=left)
    if edit:
        await msg.edit_text(text, reply_markup=kb.as_markup())
    else:
        await msg.answer(text, reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("tr:x:"))
async def ask_gb(call: CallbackQuery, lang: str, state: FSMContext) -> None:
    await state.update_data(tr_type=call.data.split(":")[2])
    await state.set_state(TBuy.gb)
    await call.answer()
    await call.message.answer(t(lang, "tr_send_gb", max=MAX_GB))


@router.message(TBuy.gb, F.text, ~F.text.in_(MENU_TEXTS))
async def got_gb(message: Message, shop: Shop, user, lang: str, state: FSMContext) -> None:
    text = message.text.strip()
    if not text.isdigit() or not 1 <= int(text) <= MAX_GB:
        await message.answer(t(lang, "tr_bad_gb", max=MAX_GB))
        return
    type_ = (await state.get_data()).get("tr_type") or "residential"
    await state.set_state(None)
    await show_confirm(message, shop, user, lang, type_, int(text), edit=False)


@router.callback_query(F.data.startswith("tr:q:"))
async def confirm_cb(call: CallbackQuery, shop: Shop, user, lang: str) -> None:
    _, _, type_, gb = call.data.split(":")
    await call.answer()
    await show_confirm(call.message, shop, user, lang, type_, int(gb), edit=True)


async def show_confirm(msg: Message, shop: Shop, user, lang: str, type_: str, gb: int, edit: bool) -> None:
    price = await shop.traffic_price(type_)
    if price is None:
        await msg.answer(t(lang, "tr_off"))
        return
    total = price * gb
    fresh = await shop.db.user(user["id"])
    kb = InlineKeyboardBuilder()
    if fresh["balance"] >= total:
        kb.button(text=t(lang, "btn_pay", total=fmt(total)), callback_data=f"tr:y:{type_}:{gb}")
    else:
        kb.button(text=t(lang, "btn_topup_need", need=fmt(total - fresh["balance"])), callback_data="tp")
    kb.button(text=t(lang, "btn_back"), callback_data=f"tr:buy:{type_}")
    kb.adjust(1)
    text = t(lang, "tr_confirm", icon=ICON[type_], name=name(lang, type_), gb=gb, price=fmt(price), total=fmt(total), balance=fmt(fresh["balance"]))
    if edit:
        await msg.edit_text(text, reply_markup=kb.as_markup())
    else:
        await msg.answer(text, reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("tr:y:"))
async def do_buy(call: CallbackQuery, shop: Shop, user, lang: str, state: FSMContext) -> None:
    _, _, type_, gb = call.data.split(":")
    await call.answer()
    await call.message.edit_text(t(lang, "buying"))
    try:
        res = await shop.buy_traffic(user["id"], type_, int(gb), lang)
    except ShopError as e:
        await call.message.edit_text(error_text(lang, e))
        if e.code == "shop_unavailable":
            await notify_admins(call.bot, shop, f"⚠️ ProxyZen отказал в покупке трафика: <code>{html.escape(e.detail)}</code>. Проверьте баланс и ключ ProxyZen (/admin).\n"
                                                f"ProxyZen declined a traffic purchase — check your ProxyZen balance and API key.")
        return
    fresh = await shop.db.user(user["id"])
    head = t(lang, "tr_bought", gb=gb, total=fmt(res["total"]), balance=fmt(fresh["balance"]))
    await show_card(call.message, shop, user, lang, type_, state, plan=res["plan"], head=head, edit=True)


# ---------- карточка и строка подключения ----------
@router.callback_query(F.data.startswith("tr:o:"))
async def card_cb(call: CallbackQuery, shop: Shop, user, lang: str, state: FSMContext) -> None:
    await call.answer()
    await show_card(call.message, shop, user, lang, call.data.split(":")[2], state, edit=True)


async def show_card(msg: Message, shop: Shop, user, lang: str, type_: str, state: FSMContext, plan: dict | None = None,
                    head: str = "", edit: bool = True) -> None:
    plan = plan or await load_plan(shop, user["id"], type_)
    if not plan:
        await msg.answer(t(lang, "tr_no_plan"))
        return
    g = await gen_get(state, type_)
    login = build_login(plan, g, type_)
    port = plan["socks5_port"] if g["proto"] == "socks5" else plan["http_port"]
    url = f"{g['proto']}://{login}:{plan['password']}@{plan['host']}:{port}"
    line = f"{plan['host']}:{port}:{login}:{plan['password']}"
    where = f"{flag(g['country'])} {html.escape(g['label'])}" if g["country"] else t(lang, "tr_any_country")
    mode = t(lang, "tr_sticky", min=g["minutes"]) if g["sticky"] else t(lang, "tr_rotating")
    left = float(plan["remaining_gb"])
    text = (head + "\n\n" if head else "") + t(
        lang, "tr_card", icon=ICON[type_], name=name(lang, type_), left=gb_text(left), total=gb_text(plan["total_gb"]),
        empty=t(lang, "tr_empty") if left <= 0 else "", host=plan["host"], http=plan["http_port"], socks=plan["socks5_port"],
        login=html.escape(plan["username"]), password=html.escape(plan["password"]), where=where, mode=mode,
        url=html.escape(url), line=html.escape(line))
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "btn_tr_country"), callback_data=f"tr:pk:{type_}:c:0")
    first = 1
    if g["country"]:
        detail = await shop.traffic_country(type_, g["country"], lang)
        if type_ == "residential" and detail.get("states"):
            kb.button(text=t(lang, "btn_tr_city"), callback_data=f"tr:pk:{type_}:st:0")
            first += 1
        if detail.get("isps"):
            kb.button(text=t(lang, "btn_tr_isp"), callback_data=f"tr:pk:{type_}:isp:0")
            first += 1
    kb.button(text=t(lang, "btn_tr_sticky_on" if g["sticky"] else "btn_tr_sticky_off"), callback_data=f"tr:s:{type_}")
    kb.button(text=t(lang, "btn_tr_proto", proto="SOCKS5" if g["proto"] == "socks5" else "HTTP"), callback_data=f"tr:p:{type_}")
    if g["sticky"]:
        kb.button(text=t(lang, "btn_tr_newip"), callback_data=f"tr:n:{type_}")
    kb.button(text=t(lang, "btn_tr_add"), callback_data=f"tr:buy:{type_}")
    kb.button(text=t(lang, "btn_tr_pass"), callback_data=f"tr:pw:{type_}")
    kb.button(text=t(lang, "btn_back"), callback_data="px:l:0")
    kb.adjust(first, 2, *((1,) if g["sticky"] else ()), 2, 1)
    if edit:
        try:
            await msg.edit_text(text, reply_markup=kb.as_markup(), disable_web_page_preview=True)
            return
        except Exception:
            pass
    await msg.answer(text, reply_markup=kb.as_markup(), disable_web_page_preview=True)


@router.callback_query(F.data.startswith("tr:s:"))
async def toggle_sticky(call: CallbackQuery, shop: Shop, user, lang: str, state: FSMContext) -> None:
    type_ = call.data.split(":")[2]
    g = await gen_get(state, type_)
    await gen_set(state, type_, sticky=not g["sticky"], session=new_session())
    await call.answer()
    await show_card(call.message, shop, user, lang, type_, state)


@router.callback_query(F.data.startswith("tr:n:"))
async def new_ip(call: CallbackQuery, shop: Shop, user, lang: str, state: FSMContext) -> None:
    type_ = call.data.split(":")[2]
    await gen_set(state, type_, session=new_session())
    await call.answer(t(lang, "tr_new_ip_done"))
    await show_card(call.message, shop, user, lang, type_, state)


@router.callback_query(F.data.startswith("tr:p:"))
async def toggle_proto(call: CallbackQuery, shop: Shop, user, lang: str, state: FSMContext) -> None:
    type_ = call.data.split(":")[2]
    g = await gen_get(state, type_)
    await gen_set(state, type_, proto="http" if g["proto"] == "socks5" else "socks5")
    await call.answer()
    await show_card(call.message, shop, user, lang, type_, state)


@router.callback_query(F.data.startswith("tr:pw:"))
async def reset_password(call: CallbackQuery, shop: Shop, user, lang: str, state: FSMContext) -> None:
    type_ = call.data.split(":")[2]
    try:
        plan = await shop.traffic_reset_password(user["id"], type_)
    except ShopError as e:
        await call.answer(error_text(lang, e), show_alert=True)
        return
    await call.answer(t(lang, "tr_pass_changed"), show_alert=True)
    await show_card(call.message, shop, user, lang, type_, state, plan=plan)


# ---------- выбор страны / региона и города / оператора ----------
async def picker_items(shop: Shop, lang: str, type_: str, kind: str, g: dict) -> list[tuple[str, str]]:
    """[(код, подпись)] для списка выбора."""
    if kind == "c":
        return [(c["code"], f"{flag(c['code'])} {c['name']}") for c in await shop.traffic_countries(type_, lang)]
    detail = await shop.traffic_country(type_, g["country"], lang) if g["country"] else {}
    if kind == "st":
        return [(s["code"], s["name"]) for s in detail.get("states", [])]
    if kind == "ci":
        st = next((s for s in detail.get("states", []) if s["code"] == g["region"]), None)
        return [(c["code"], c["name"]) for c in (st or {}).get("cities", [])]
    return [(i["asn"], i["name"]) for i in detail.get("isps", [])]


@router.callback_query(F.data.startswith("tr:pk:"))
async def picker(call: CallbackQuery, shop: Shop, lang: str, state: FSMContext) -> None:
    _, _, type_, kind, page = call.data.split(":")
    await call.answer()
    await render_picker(call.message, shop, lang, state, type_, kind, int(page))


async def render_picker(msg: Message, shop: Shop, lang: str, state: FSMContext, type_: str, kind: str, page: int) -> None:
    g = await gen_get(state, type_)
    try:
        items = await picker_items(shop, lang, type_, kind, g)
    except ApiError:
        await msg.answer(t(lang, "e_shop_unavailable"))
        return
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "tr_any_country" if kind == "c" else "tr_any"), callback_data=f"tr:set:{type_}:{kind}:-")
    for code, label in items[page * PAGE:(page + 1) * PAGE]:
        kb.button(text=label[:40], callback_data=f"tr:set:{type_}:{kind}:{code}"[:64])
    kb.adjust(1, 2)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="«", callback_data=f"tr:pk:{type_}:{kind}:{page - 1}"))
    if (page + 1) * PAGE < len(items):
        nav.append(InlineKeyboardButton(text="»", callback_data=f"tr:pk:{type_}:{kind}:{page + 1}"))
    if nav:
        kb.row(*nav)
    kb.row(InlineKeyboardButton(text=t(lang, "btn_back"), callback_data=f"tr:o:{type_}"))
    title = {"c": "tr_pick_country", "st": "tr_pick_state", "ci": "tr_pick_city", "isp": "tr_pick_isp"}[kind]
    await msg.edit_text(t(lang, title, page=page + 1, pages=max(1, -(-len(items) // PAGE))), reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("tr:set:"))
async def picked(call: CallbackQuery, shop: Shop, user, lang: str, state: FSMContext) -> None:
    _, _, type_, kind, code = call.data.split(":", 4)
    code = "" if code == "-" else code
    g = await gen_get(state, type_)
    if kind == "c":
        label = next((c["name"] for c in await shop.traffic_countries(type_, lang) if c["code"] == code), code)
        g = await gen_set(state, type_, country=code, label=label, region="", city="", asn="")
    elif kind == "st":
        g = await gen_set(state, type_, region=code, city="", asn="")
        if code:   # регион выбран — сразу предложить город
            await call.answer()
            await render_picker(call.message, shop, lang, state, type_, "ci", 0)
            return
    elif kind == "ci":
        g = await gen_set(state, type_, city=code, asn="")
    else:
        g = await gen_set(state, type_, asn=code, region="" if code else g["region"], city="" if code else g["city"])
    await call.answer()
    await show_card(call.message, shop, user, lang, type_, state)


# ---------- для «Мои прокси» ----------
async def plan_buttons(shop: Shop, uid: int, lang: str) -> list[tuple[str, str]]:
    """[(текст кнопки, callback)] планов трафика покупателя — для списка «Мои прокси»."""
    try:
        plans = await shop.traffic_plans(uid)
    except (ApiError, ShopError):
        return []
    return [(t(lang, "tr_plan_btn", icon=ICON.get(p["type"], "•"), name=name(lang, p["type"]), gb=gb_text(p["remaining_gb"])),
             f"tr:o:{p['type']}") for p in plans]

