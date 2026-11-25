"""Админка (/admin): статистика, цены, рассылка, настройки, платёжные системы, пользователи, ProxyZen.
Доступ — только Telegram ID из ADMIN_IDS (.env)."""
from __future__ import annotations

import asyncio
import html
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import __version__
from ..api import SITE, ApiError, ProxyZen
from ..db import now
from ..money import fmt, parse_amount, to_cents
from ..payments import PaymentError
from ..shop import Shop
from .user import MENU_TEXTS, date

router = Router(name="admin")
log = logging.getLogger("admin")

A = {
    "ru": {
        "menu": "🛠 <b>Админка «{shop}»</b>\nВерсия скрипта {ver}{notice}",
        "stats": "📊 Статистика", "prices": "💲 Цены", "bc": "📣 Рассылка", "settings": "⚙️ Настройки", "pay": "💳 Платёжные системы",
        "users": "👥 Пользователи", "pz": "🔌 ProxyZen", "back": "‹ Назад", "cancel": "Отмена",
        "no_key": "⚠️ Сначала укажите API-ключ ProxyZen: ⚙️ Настройки → Ключ ProxyZen.",
        "stats_text": ("📊 <b>Статистика</b>\n\n<b>Пользователи</b>\nВсего: {users} · покупали: {buyers}\nНовых: сегодня {u1} · 7 дн. {u7} · 30 дн. {u30}\nЗаблокировали бота: {blocked}\n\n"
                       "<b>Продажи</b> (выручка / закупка у ProxyZen / <b>прибыль</b>)\nСегодня: {s_today}\n7 дней: {s_week}\n30 дней: {s_month}\nВсего: {s_all}\n"
                       "Заказов: {orders} · продлений: {renews} · IP продано: {ips}\nТрафик (резидентские/мобильные): {t_orders} покупок · {t_gb} ГБ\nАктивных прокси у клиентов: {active}\n\n"
                       "<b>Пополнения</b>\nСегодня {t1} · 7 дн. {t7} · 30 дн. {t30} · всего {t}\nНа балансах клиентов: {held}\n\n"
                       "<b>Топ стран (30 дн.)</b>\n{top}\n\nБаланс ProxyZen: <b>{pz}</b>"),
        "prices_type": "💲 <b>Цены</b>\n\nВыберите тип прокси:",
        "prices_list": ("💲 <b>Цены {type}</b> — за 1 IP\n\nЗакупка у ProxyZen → ваша цена (прибыль).\n"
                        "Без своей цены работает базовая наценка <b>{markup}%</b>.\n\n{rows}\n\nНажмите на срок, чтобы задать свою цену."),
        "price_row": "{days} дн.: ${cost} → <b>${price}</b> (+${profit}){mark}",
        "mark_fixed": " · своя", "mark_below": " · ⚠️ ваша цена ниже закупки, продаётся по наценке",
        "markup_btn": "Базовая наценка: {markup}%",
        "ask_price": ("{type} · {days} дн.\nЗакупка у ProxyZen: <b>${cost}</b>\nСейчас клиенты платят: <b>${price}</b>\n\n"
                      "Отправьте свою цену за 1 IP (минимум <b>${min}</b>) или «-», чтобы вернуть цену по наценке."),
        "price_saved": "✅ {type} · {days} дн.: <b>${price}</b>, прибыль ${profit} с IP.", "price_reset": "✅ Цена по наценке: ${price}.",
        "price_low": "\n⚠️ Прибыль меньше 5% — проверьте, что цена указана верно.",
        "price_below": "❌ Цена ниже закупки (${cost}) — вы продавали бы в убыток. Минимум: ${min}.",
        "ask_markup": "Базовая наценка {type} в % к закупке (например 30). Действует на сроки без своей цены:",
        "traffic_view": ("💲 <b>{type}</b> — за 1 ГБ\n\nЗакупка у ProxyZen: ${cost}\nЦена клиентам: <b>${price}</b> (+${profit} с ГБ){mark}\n"
                         "Базовая наценка: <b>{markup}%</b>\n\nСвоя цена заменяет наценку. Ниже закупки поставить нельзя."),
        "traffic_off": "Резидентские и мобильные сейчас не продаются на ProxyZen.",
        "b_own_price": "Своя цена за ГБ", "b_reset_price": "Вернуть цену по наценке",
        "ask_traffic_price": "{type}\nЗакупка у ProxyZen: <b>${cost}</b> за ГБ\nСейчас клиенты платят: <b>${price}</b>\n\nОтправьте свою цену за 1 ГБ (минимум <b>${min}</b>) или «-», чтобы вернуть цену по наценке.",
        "bc_ask": "Отправьте сообщение для рассылки — текст, фото, видео, GIF или файл с подписью. Форматирование сохранится.",
        "bc_button": "Добавить кнопку? Отправьте <code>Текст кнопки | https://ссылка</code> или нажмите «Без кнопки».",
        "bc_no_btn": "Без кнопки", "bc_bad_btn": "Формат: <code>Текст | https://ссылка</code>",
        "bc_preview": "👆 Так увидят пользователи. Получателей: <b>{n}</b>. Отправить?", "bc_send": "🚀 Отправить",
        "bc_started": "Рассылка запущена…", "bc_progress": "Рассылка: {done}/{total}…",
        "bc_done": "✅ Рассылка завершена\nДоставлено: {ok}\nЗаблокировали бота: {blocked}\nОшибок: {fail}",
        "settings_text": ("⚙️ <b>Настройки</b>\n\nНазвание: <b>{name}</b>\nПриветствие: {welcome}\nКартинка /start: {photo}\nПоддержка: {support}\n"
                          "Ключ ProxyZen: {api}\nМин. пополнение: {min_topup}\nРеферальный бонус: {ref}% от пополнений приглашённых\n"
                          "Предупреждать, если баланс ProxyZen ниже: ${low}\nТехработы: {maint}"),
        "set": "задано", "not_set": "не задано", "yes": "вкл.", "no": "выкл.",
        "b_name": "Название", "b_welcome": "Приветствие", "b_start_photo": "Картинка /start", "b_support": "Поддержка", "b_api_key": "Ключ ProxyZen",
        "b_min_topup": "Мин. пополнение", "b_ref_percent": "Реф. бонус %", "b_low_balance_alert": "Порог баланса", "b_maintenance": "Техработы",
        "ask_name": "Отправьте название магазина:", "ask_welcome": "Текст приветствия для /start (можно с форматированием). «-» — стандартный текст.",
        "ask_start_photo": "Отправьте картинку для /start. «-» — убрать.", "ask_support": "Отправьте @username поддержки (или ссылку t.me/…):",
        "ask_api_key": "Отправьте API-ключ ProxyZen ({site}/cabinet → API). Сообщение с ключом удалю.",
        "ask_min_topup": "Минимальная сумма пополнения в $ (например 5):", "ask_ref_percent": "Реферальный бонус — % от пополнений приглашённых (0 — выключить, максимум 50):",
        "ask_low_balance_alert": "Предупреждать, если баланс ProxyZen ниже, $ (например 10):",
        "saved": "✅ Сохранено", "bad_value": "Неверное значение, попробуйте ещё раз.",
        "key_ok": "✅ Ключ ProxyZen работает. Баланс: ${balance}", "key_bad": "❌ Ключ не подошёл: {err}",
        "pay_text": "💳 <b>Платёжные системы</b>\n\nКлиенты увидят все подключённые. Свою платёжку можно добавить по шаблону app/payments/_template.py.\n\n{rows}",
        "pay_on": "✅ подключена", "pay_off": "не подключена",
        "pay_field": "{provider}: {label}\nОтправьте значение. Сообщение удалю.",
        "pay_ok": "✅ {provider} подключена: {name}", "pay_bad": "❌ {provider}: {err}",
        "users_ask": "Отправьте Telegram ID или @username пользователя:", "user_none": "Пользователь не найден.",
        "user_card": "👤 <b>{name}</b> {username}\nID: <code>{id}</code> · язык {lang}\nБаланс: <b>{balance}</b>\nПополнено: {topped} · потрачено: {spent}\nАктивных прокси: {active}\nС {since} · был {seen}\nСтатус: {status}",
        "u_add": "➕ Начислить", "u_sub": "➖ Списать", "u_ban": "🚫 Заблокировать", "u_unban": "✅ Разблокировать", "u_msg": "✉️ Написать",
        "u_banned": "заблокирован", "u_ok": "активен", "ask_amount": "Сумма в $:", "ask_msg": "Сообщение пользователю:",
        "sent": "Отправлено", "not_sent": "Не доставлено (пользователь заблокировал бота?)",
        "pz_text": "🔌 <b>ProxyZen</b>\n\nКлюч: {key}\nБаланс аккаунта: <b>{balance}</b>\nВерсия скрипта: {ver} · последняя: {latest}\n{notice}\n\nПополнить баланс и ключи: {site}/cabinet",
    },
    "en": {
        "menu": "🛠 <b>“{shop}” admin</b>\nScript version {ver}{notice}",
        "stats": "📊 Statistics", "prices": "💲 Prices", "bc": "📣 Broadcast", "settings": "⚙️ Settings", "pay": "💳 Payment methods",
        "users": "👥 Users", "pz": "🔌 ProxyZen", "back": "‹ Back", "cancel": "Cancel",
        "no_key": "⚠️ Set your ProxyZen API key first: ⚙️ Settings → ProxyZen key.",
        "stats_text": ("📊 <b>Statistics</b>\n\n<b>Users</b>\nTotal: {users} · buyers: {buyers}\nNew: today {u1} · 7d {u7} · 30d {u30}\nBlocked the bot: {blocked}\n\n"
                       "<b>Sales</b> (revenue / ProxyZen cost / <b>profit</b>)\nToday: {s_today}\n7 days: {s_week}\n30 days: {s_month}\nAll time: {s_all}\n"
                       "Orders: {orders} · renewals: {renews} · IPs sold: {ips}\nTraffic (residential/mobile): {t_orders} purchases · {t_gb} GB\nActive customer proxies: {active}\n\n"
                       "<b>Top-ups</b>\nToday {t1} · 7d {t7} · 30d {t30} · total {t}\nCustomer balances: {held}\n\n"
                       "<b>Top countries (30d)</b>\n{top}\n\nProxyZen balance: <b>{pz}</b>"),
        "prices_type": "💲 <b>Prices</b>\n\nChoose the proxy type:",
        "prices_list": ("💲 <b>{type} prices</b> — per IP\n\nProxyZen cost → your price (profit).\n"
                        "Periods without your own price use the base markup <b>{markup}%</b>.\n\n{rows}\n\nTap a period to set your own price."),
        "price_row": "{days} d: ${cost} → <b>${price}</b> (+${profit}){mark}",
        "mark_fixed": " · custom", "mark_below": " · ⚠️ your price is below cost, selling at markup",
        "markup_btn": "Base markup: {markup}%",
        "ask_price": ("{type} · {days} days\nProxyZen cost: <b>${cost}</b>\nCustomers pay now: <b>${price}</b>\n\n"
                      "Send your price per IP (minimum <b>${min}</b>) or “-” to return to the markup price."),
        "price_saved": "✅ {type} · {days} days: <b>${price}</b>, profit ${profit} per IP.", "price_reset": "✅ Markup price: ${price}.",
        "price_low": "\n⚠️ Profit is below 5% — double-check the price.",
        "price_below": "❌ The price is below cost (${cost}) — you'd sell at a loss. Minimum: ${min}.",
        "ask_markup": "Base {type} markup, % over cost (e.g. 30). Applies to periods without your own price:",
        "traffic_view": ("💲 <b>{type}</b> — per 1 GB\n\nProxyZen cost: ${cost}\nCustomer price: <b>${price}</b> (+${profit} per GB){mark}\n"
                         "Base markup: <b>{markup}%</b>\n\nYour own price replaces the markup. It can't be below cost."),
        "traffic_off": "Residential and mobile proxies aren't on sale at ProxyZen right now.",
        "b_own_price": "Own price per GB", "b_reset_price": "Back to markup price",
        "ask_traffic_price": "{type}\nProxyZen cost: <b>${cost}</b> per GB\nCustomers pay now: <b>${price}</b>\n\nSend your price per 1 GB (minimum <b>${min}</b>) or “-” to return to the markup price.",
        "bc_ask": "Send the broadcast message — text, photo, video, GIF or a file with a caption. Formatting is kept.",
        "bc_button": "Add a button? Send <code>Button text | https://link</code> or tap “No button”.",
        "bc_no_btn": "No button", "bc_bad_btn": "Format: <code>Text | https://link</code>",
        "bc_preview": "👆 This is what users will see. Recipients: <b>{n}</b>. Send?", "bc_send": "🚀 Send",
        "bc_started": "Broadcast started…", "bc_progress": "Broadcast: {done}/{total}…",
        "bc_done": "✅ Broadcast finished\nDelivered: {ok}\nBlocked the bot: {blocked}\nErrors: {fail}",
        "settings_text": ("⚙️ <b>Settings</b>\n\nShop name: <b>{name}</b>\nWelcome: {welcome}\n/start image: {photo}\nSupport: {support}\n"
                          "ProxyZen key: {api}\nMin top-up: {min_topup}\nReferral bonus: {ref}% of invited users' top-ups\n"
                          "Alert when ProxyZen balance below: ${low}\nMaintenance: {maint}"),
        "set": "set", "not_set": "not set", "yes": "on", "no": "off",
        "b_name": "Shop name", "b_welcome": "Welcome text", "b_start_photo": "/start image", "b_support": "Support", "b_api_key": "ProxyZen key",
        "b_min_topup": "Min top-up", "b_ref_percent": "Referral %", "b_low_balance_alert": "Balance alert", "b_maintenance": "Maintenance",
        "ask_name": "Send the shop name:", "ask_welcome": "Send the /start welcome text (formatting allowed). “-” — default text.",
        "ask_start_photo": "Send an image for /start. “-” — remove.", "ask_support": "Send the support @username (or a t.me/… link):",
        "ask_api_key": "Send your ProxyZen API key ({site}/cabinet → API). I'll delete the message.",
        "ask_min_topup": "Minimum top-up in $ (e.g. 5):", "ask_ref_percent": "Referral bonus — % of invited users' top-ups (0 — off, max 50):",
        "ask_low_balance_alert": "Alert when the ProxyZen balance drops below, $ (e.g. 10):",
        "saved": "✅ Saved", "bad_value": "Invalid value, please try again.",
        "key_ok": "✅ ProxyZen key works. Balance: ${balance}", "key_bad": "❌ Key rejected: {err}",
        "pay_text": "💳 <b>Payment methods</b>\n\nCustomers see all connected methods. Add your own using app/payments/_template.py.\n\n{rows}",
        "pay_on": "✅ connected", "pay_off": "not connected",
        "pay_field": "{provider}: {label}\nSend the value. I'll delete the message.",
        "pay_ok": "✅ {provider} connected: {name}", "pay_bad": "❌ {provider}: {err}",
        "users_ask": "Send the user's Telegram ID or @username:", "user_none": "User not found.",
        "user_card": "👤 <b>{name}</b> {username}\nID: <code>{id}</code> · lang {lang}\nBalance: <b>{balance}</b>\nTopped up: {topped} · spent: {spent}\nActive proxies: {active}\nSince {since} · last seen {seen}\nStatus: {status}",
        "u_add": "➕ Add", "u_sub": "➖ Deduct", "u_ban": "🚫 Ban", "u_unban": "✅ Unban", "u_msg": "✉️ Message",
        "u_banned": "banned", "u_ok": "active", "ask_amount": "Amount in $:", "ask_msg": "Message for the user:",
        "sent": "Sent", "not_sent": "Not delivered (user blocked the bot?)",
        "pz_text": "🔌 <b>ProxyZen</b>\n\nKey: {key}\nAccount balance: <b>{balance}</b>\nScript version: {ver} · latest: {latest}\n{notice}\n\nTop up and keys: {site}/cabinet",
    },
}

TYPE_NAME = {"ipv4": "IPv4", "ipv6": "IPv6", "residential": "🏠 Residential", "mobile": "📱 Mobile"}
TYPE_NAME_RU = {"residential": "🏠 Резидентские", "mobile": "📱 Мобильные"}


def tname(lang: str, type_: str) -> str:
    return TYPE_NAME_RU.get(type_, TYPE_NAME[type_]) if lang == "ru" else TYPE_NAME[type_]


def a(lang: str, key: str, **kw) -> str:
    s = A.get(lang, A["en"]).get(key) or A["en"][key]
    return s.format(**kw) if kw else s


class Adm(StatesGroup):
    bc_message = State()
    bc_button = State()
    setting = State()
    photo = State()
    price = State()
    traffic_price = State()
    markup = State()
    pay_field = State()
    user_search = State()
    user_amount = State()
    user_message = State()


def setup(admin_ids: frozenset[int]) -> Router:
    router.message.filter(F.from_user.id.in_(admin_ids))
    router.callback_query.filter(F.from_user.id.in_(admin_ids))
    return router


def menu_kb(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for key, cb in (("stats", "ad:stats"), ("prices", "ad:pr"), ("bc", "ad:bc"), ("settings", "ad:set"), ("pay", "ad:pay"), ("users", "ad:users"), ("pz", "ad:pz")):
        kb.button(text=a(lang, key), callback_data=cb)
    kb.adjust(2, 2, 2, 1)
    return kb.as_markup()


def back_kb(lang: str, to: str = "ad:menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=a(lang, "back"), callback_data=to)]])


async def show(event: Message | CallbackQuery, text: str, kb: InlineKeyboardMarkup | None = None) -> None:
    if isinstance(event, CallbackQuery):
        await event.answer()
        try:
            await event.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
            return
        except Exception:
            pass
        await event.message.answer(text, reply_markup=kb, disable_web_page_preview=True)
    else:
        await event.answer(text, reply_markup=kb, disable_web_page_preview=True)


@router.message(Command("admin"))
@router.callback_query(F.data == "ad:menu")
async def admin_menu(event: Message | CallbackQuery, shop: Shop, lang: str, state: FSMContext) -> None:
    await state.clear()
    notice = f"\n\n📢 {html.escape(shop.notice)}" if shop.notice else ""
    if not (await shop.api()).key:
        notice += "\n\n" + a(lang, "no_key")
    await show(event, a(lang, "menu", shop=html.escape((await shop.config()).get("name") or "Proxy Shop"), ver=__version__, notice=notice), menu_kb(lang))


# ---------- статистика ----------
@router.callback_query(F.data == "ad:stats")
async def stats(call: CallbackQuery, shop: Shop, lang: str) -> None:
    db = shop.db
    t0 = now()
    day, week, month = t0 - 86400, t0 - 7 * 86400, t0 - 30 * 86400
    try:
        s = await (await shop.api()).stats()
    except ApiError as e:
        s = None
        log.warning("stats: %s", e.code)

    def line(p: dict | None) -> str:
        return f"${p['revenue']} / ${p['cost']} / <b>${p['profit']}</b>" if p else "—"

    paid = "SELECT COALESCE(SUM(amount),0) FROM invoices WHERE status='paid'"
    text = a(lang, "stats_text",
             users=await db.val("SELECT COUNT(*) FROM users"), buyers=s["buyers"] if s else "—",
             u1=await db.val("SELECT COUNT(*) FROM users WHERE created_at>=?", day),
             u7=await db.val("SELECT COUNT(*) FROM users WHERE created_at>=?", week),
             u30=await db.val("SELECT COUNT(*) FROM users WHERE created_at>=?", month),
             blocked=await db.val("SELECT COUNT(*) FROM users WHERE blocked_bot=1"),
             s_today=line(s and s["today"]), s_week=line(s and s["week"]), s_month=line(s and s["month"]), s_all=line(s and s["all"]),
             orders=s["all"]["orders"] if s else "—", renews=s["all"]["renewals"] if s else "—", ips=s["all"]["ips"] if s else "—",
             t_orders=s["all"].get("traffic_orders", 0) if s else "—", t_gb=s["all"].get("traffic_gb", 0) if s else "—",
             active=s["active_proxies"] if s else "—",
             t1=fmt(await db.val(paid + " AND paid_at>=?", day)), t7=fmt(await db.val(paid + " AND paid_at>=?", week)),
             t30=fmt(await db.val(paid + " AND paid_at>=?", month)), t=fmt(await db.val(paid)),
             held=fmt(await db.val("SELECT COALESCE(SUM(balance),0) FROM users")),
             top="\n".join(f"{r['country']}: {r['ips']} IP" for r in (s["top_countries"] if s else [])) or "—",
             pz=f"${s['balance']}" if s else "—")
    await show(call, text, back_kb(lang))


# ---------- цены ----------
@router.callback_query(F.data == "ad:pr")
async def prices_menu(call: CallbackQuery, lang: str, state: FSMContext) -> None:
    await state.clear()
    kb = InlineKeyboardBuilder()
    kb.button(text="IPv4", callback_data="ad:pr:ipv4")
    kb.button(text="IPv6", callback_data="ad:pr:ipv6")
    kb.button(text=tname(lang, "residential"), callback_data="ad:pt:residential")
    kb.button(text=tname(lang, "mobile"), callback_data="ad:pt:mobile")
    kb.button(text=a(lang, "back"), callback_data="ad:menu")
    kb.adjust(2, 2, 1)
    await show(call, a(lang, "prices_type"), kb.as_markup())


async def prices_view(shop: Shop, lang: str, type_: str) -> tuple[str, InlineKeyboardMarkup]:
    table = await (await shop.api()).price_table()
    rows = table["data"].get(type_, [])
    lines = [a(lang, "price_row", days=r["days"], cost=r["cost"], price=r["price"], profit=r["profit"],
               mark=a(lang, "mark_below") if r["below_cost"] else (a(lang, "mark_fixed") if r["fixed"] else "")) for r in rows]
    kb = InlineKeyboardBuilder()
    for r in rows:
        kb.button(text=f"{r['days']} · ${r['price']}", callback_data=f"ad:pp:{type_}:{r['days']}")
    kb.adjust(3)
    kb.row(InlineKeyboardButton(text=a(lang, "markup_btn", markup=f"{float(table['markup'][type_]):g}"), callback_data=f"ad:pm:{type_}"))
    kb.row(InlineKeyboardButton(text=a(lang, "back"), callback_data="ad:pr"))
    text = a(lang, "prices_list", type=TYPE_NAME[type_], markup=f"{float(table['markup'][type_]):g}", rows="\n".join(lines) or "—")
    return text, kb.as_markup()


@router.callback_query(F.data.regexp(r"^ad:pr:(ipv4|ipv6)$"))
async def prices_type(call: CallbackQuery, shop: Shop, lang: str, state: FSMContext) -> None:
    await state.clear()
    try:
        text, kb = await prices_view(shop, lang, call.data.split(":")[2])
    except ApiError:
        await show(call, a(lang, "no_key"), back_kb(lang))
        return
    await show(call, text, kb)


@router.callback_query(F.data.startswith("ad:pp:"))
async def ask_price(call: CallbackQuery, shop: Shop, lang: str, state: FSMContext) -> None:
    _, _, type_, days = call.data.split(":")
    rows = (await (await shop.api()).price_table())["data"].get(type_, [])
    r = next((x for x in rows if x["days"] == int(days)), None)
    if not r:
        await call.answer()
        return
    minimum = f"{(to_cents(r['cost']) + 1) / 100:.2f}"
    await state.set_state(Adm.price)
    await state.update_data(type=type_, days=int(days))
    await call.answer()
    await call.message.answer(a(lang, "ask_price", type=TYPE_NAME[type_], days=days, cost=r["cost"], price=r["price"], min=minimum),
                              reply_markup=back_kb(lang, f"ad:pr:{type_}"))


@router.message(Adm.price, F.text, ~F.text.in_(MENU_TEXTS))
async def got_price(message: Message, shop: Shop, lang: str, state: FSMContext) -> None:
    data = await state.get_data()
    raw = message.text.strip()
    price = None
    if raw != "-":
        cents = parse_amount(raw)
        if cents is None:
            await message.answer(a(lang, "bad_value"))
            return
        price = f"{cents / 100:.2f}"
    try:
        res = await (await shop.api()).set_price(data["type"], data["days"], price)
    except ApiError as e:
        if e.code == "below_cost":
            await message.answer(a(lang, "price_below", cost=e.data.get("cost", "?"), min=e.data.get("min_price", "?")))
            return
        await message.answer(f"❌ {html.escape(e.message)}")
        return
    await state.clear()
    shop.forget("periods")
    note = a(lang, "price_saved", type=TYPE_NAME[data["type"]], days=data["days"], price=res["price"], profit=res["profit"]) if price \
        else a(lang, "price_reset", price=res["price"])
    if res.get("warning") == "low_margin":
        note += a(lang, "price_low")
    text, kb = await prices_view(shop, lang, data["type"])
    await message.answer(note + "\n\n" + text, reply_markup=kb)


# ---------- цены за ГБ (резидентские / мобильные) ----------
async def traffic_view(shop: Shop, lang: str, type_: str) -> tuple[str, InlineKeyboardMarkup]:
    info = await (await shop.api()).traffic()
    r = next((x for x in info.get("data", []) if x["type"] == type_), None)
    if not r:
        return a(lang, "traffic_off"), back_kb(lang, "ad:pr")
    mark = a(lang, "mark_below") if r["below_cost"] else (a(lang, "mark_fixed") if r["fixed"] else "")
    text = a(lang, "traffic_view", type=tname(lang, type_), cost=r["cost"], price=r["price"], profit=r["profit"], mark=mark,
             markup=f"{float(r['markup']):g}")
    kb = InlineKeyboardBuilder()
    kb.button(text=a(lang, "b_own_price"), callback_data=f"ad:ptp:{type_}")
    kb.button(text=a(lang, "markup_btn", markup=f"{float(r['markup']):g}"), callback_data=f"ad:pm:{type_}")
    if r["fixed"] or r["below_cost"]:
        kb.button(text=a(lang, "b_reset_price"), callback_data=f"ad:ptr:{type_}")
    kb.button(text=a(lang, "back"), callback_data="ad:pr")
    kb.adjust(1)
    return text, kb.as_markup()


@router.callback_query(F.data.regexp(r"^ad:pt:(residential|mobile)$"))
async def traffic_prices(call: CallbackQuery, shop: Shop, lang: str, state: FSMContext) -> None:
    await state.clear()
    try:
        text, kb = await traffic_view(shop, lang, call.data.split(":")[2])
    except ApiError:
        await show(call, a(lang, "no_key"), back_kb(lang))
        return
    await show(call, text, kb)


@router.callback_query(F.data.startswith("ad:ptp:"))
async def ask_traffic_price(call: CallbackQuery, shop: Shop, lang: str, state: FSMContext) -> None:
    type_ = call.data.split(":")[2]
    r = next((x for x in (await (await shop.api()).traffic()).get("data", []) if x["type"] == type_), None)
    await call.answer()
    if not r:
        return
    await state.set_state(Adm.traffic_price)
    await state.update_data(type=type_)
    await call.message.answer(a(lang, "ask_traffic_price", type=tname(lang, type_), cost=r["cost"], price=r["price"],
                                min=f"{(to_cents(r['cost']) + 1) / 100:.2f}"), reply_markup=back_kb(lang, f"ad:pt:{type_}"))


async def _save_traffic_price(shop: Shop, lang: str, type_: str, price: str | None) -> str:
    res = await (await shop.api()).set_traffic_price(type_, price)
    shop.forget("traffic")
    note = a(lang, "price_saved", type=tname(lang, type_), days="1 GB" if lang != "ru" else "1 ГБ", price=res["price"], profit=res["profit"]) \
        if price else a(lang, "price_reset", price=res["price"])
    if res.get("warning") == "low_margin":
        note += a(lang, "price_low")
    return note


@router.message(Adm.traffic_price, F.text, ~F.text.in_(MENU_TEXTS))
async def got_traffic_price(message: Message, shop: Shop, lang: str, state: FSMContext) -> None:
    type_ = (await state.get_data())["type"]
    raw = message.text.strip()
    price = None
    if raw != "-":
        cents = parse_amount(raw)
        if cents is None:
            await message.answer(a(lang, "bad_value"))
            return
        price = f"{cents / 100:.2f}"
    try:
        note = await _save_traffic_price(shop, lang, type_, price)
    except ApiError as e:
        if e.code == "below_cost":
            await message.answer(a(lang, "price_below", cost=e.data.get("cost", "?"), min=e.data.get("min_price", "?")))
            return
        await message.answer(f"❌ {html.escape(e.message)}")
        return
    await state.clear()
    text, kb = await traffic_view(shop, lang, type_)
    await message.answer(note + "\n\n" + text, reply_markup=kb)


@router.callback_query(F.data.startswith("ad:ptr:"))
async def reset_traffic_price(call: CallbackQuery, shop: Shop, lang: str) -> None:
    type_ = call.data.split(":")[2]
    note = await _save_traffic_price(shop, lang, type_, None)
    text, kb = await traffic_view(shop, lang, type_)
    await show(call, note + "\n\n" + text, kb)


@router.callback_query(F.data.startswith("ad:pm:"))
async def ask_markup(call: CallbackQuery, lang: str, state: FSMContext) -> None:
    type_ = call.data.split(":")[2]
    await state.set_state(Adm.markup)
    await state.update_data(type=type_)
    await call.answer()
    back = f"ad:pt:{type_}" if type_ in ("residential", "mobile") else f"ad:pr:{type_}"
    await call.message.answer(a(lang, "ask_markup", type=tname(lang, type_)), reply_markup=back_kb(lang, back))


@router.message(Adm.markup, F.text, ~F.text.in_(MENU_TEXTS))
async def got_markup(message: Message, shop: Shop, lang: str, state: FSMContext) -> None:
    type_ = (await state.get_data())["type"]
    try:
        v = float(message.text.strip().replace(",", ".").replace("%", ""))
        assert 0 <= v <= 1000
    except (ValueError, AssertionError):
        await message.answer(a(lang, "bad_value"))
        return
    await shop.update_config(markup={type_: v})
    await state.clear()
    shop.forget("periods")
    shop.forget("traffic")
    text, kb = await (traffic_view(shop, lang, type_) if type_ in ("residential", "mobile") else prices_view(shop, lang, type_))
    await message.answer(a(lang, "saved") + "\n\n" + text, reply_markup=kb)


# ---------- рассылка ----------
@router.callback_query(F.data == "ad:bc")
async def bc_start(call: CallbackQuery, lang: str, state: FSMContext) -> None:
    await state.set_state(Adm.bc_message)
    await call.answer()
    await call.message.answer(a(lang, "bc_ask"), reply_markup=back_kb(lang))


@router.message(Adm.bc_message)
async def bc_got_message(message: Message, lang: str, state: FSMContext) -> None:
    await state.update_data(bc_chat=message.chat.id, bc_msg=message.message_id)
    await state.set_state(Adm.bc_button)
    kb = InlineKeyboardBuilder()
    kb.button(text=a(lang, "bc_no_btn"), callback_data="ad:bc:nobtn")
    await message.answer(a(lang, "bc_button"), reply_markup=kb.as_markup())


def parse_button(text: str) -> InlineKeyboardMarkup | None:
    if "|" not in text:
        return None
    label, url = (x.strip() for x in text.split("|", 1))
    if not label or not url.startswith(("https://", "http://", "tg://")):
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label[:64], url=url)]])


@router.message(Adm.bc_button, F.text, ~F.text.in_(MENU_TEXTS))
async def bc_got_button(message: Message, shop: Shop, lang: str, state: FSMContext, bot: Bot) -> None:
    markup = parse_button(message.text)
    if not markup:
        await message.answer(a(lang, "bc_bad_btn"))
        return
    await state.update_data(bc_button=message.text)
    await bc_preview(message, shop, lang, state, bot, markup)


@router.callback_query(Adm.bc_button, F.data == "ad:bc:nobtn")
async def bc_no_button(call: CallbackQuery, shop: Shop, lang: str, state: FSMContext, bot: Bot) -> None:
    await call.answer()
    await state.update_data(bc_button=None)
    await bc_preview(call.message, shop, lang, state, bot, None)


async def bc_preview(msg: Message, shop: Shop, lang: str, state: FSMContext, bot: Bot, markup) -> None:
    data = await state.get_data()
    await bot.copy_message(msg.chat.id, data["bc_chat"], data["bc_msg"], reply_markup=markup)
    n = await shop.db.val("SELECT COUNT(*) FROM users WHERE banned=0 AND blocked_bot=0")
    kb = InlineKeyboardBuilder()
    kb.button(text=a(lang, "bc_send"), callback_data="ad:bc:go")
    kb.button(text=a(lang, "cancel"), callback_data="ad:menu")
    await msg.answer(a(lang, "bc_preview", n=n), reply_markup=kb.as_markup())


@router.callback_query(Adm.bc_button, F.data == "ad:bc:go")
async def bc_go(call: CallbackQuery, shop: Shop, lang: str, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    await state.clear()
    await call.answer()
    status = await call.message.edit_text(a(lang, "bc_started"))
    markup = parse_button(data["bc_button"]) if data.get("bc_button") else None
    asyncio.create_task(run_broadcast(bot, shop, lang, status, data["bc_chat"], data["bc_msg"], markup))


async def run_broadcast(bot: Bot, shop: Shop, lang: str, status: Message, from_chat: int, msg_id: int, markup) -> None:
    ids = [r["id"] for r in await shop.db.all("SELECT id FROM users WHERE banned=0 AND blocked_bot=0 ORDER BY id")]
    ok = blocked = fail = 0
    for i, uid in enumerate(ids, 1):
        for _ in range(3):
            try:
                await bot.copy_message(uid, from_chat, msg_id, reply_markup=markup)
                ok += 1
                break
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
            except TelegramForbiddenError:
                blocked += 1
                await shop.db.run("UPDATE users SET blocked_bot=1 WHERE id=?", uid)
                break
            except Exception as e:
                log.warning("broadcast to %s failed: %s", uid, e)
                fail += 1
                break
        await asyncio.sleep(0.05)   # ~20 сообщений в секунду — в пределах лимитов Telegram
        if i % 200 == 0:
            try:
                await status.edit_text(a(lang, "bc_progress", done=i, total=len(ids)))
            except Exception:
                pass
    await status.edit_text(a(lang, "bc_done", ok=ok, blocked=blocked, fail=fail))


# ---------- настройки ----------
SERVER_FIELDS = ("name", "welcome", "support", "ref_percent", "low_balance_alert")   # хранятся у ProxyZen
LOCAL_FIELDS = ("api_key", "min_topup")                                              # хранятся в боте


async def settings_view(shop: Shop, lang: str) -> tuple[str, InlineKeyboardMarkup]:
    cfg = await shop.config()
    api_set = bool((await shop.db.setting("api_key")) or shop.env_api_key)
    text = a(lang, "settings_text", name=html.escape(cfg.get("name") or "—"), welcome=a(lang, "set" if cfg.get("welcome") else "not_set"),
             photo=a(lang, "set" if await shop.db.setting("start_photo") else "not_set"),
             support=html.escape(cfg.get("support") or a(lang, "not_set")), api=a(lang, "set" if api_set else "not_set"),
             min_topup=fmt(int(await shop.db.setting("min_topup") or 0)), ref=f"{float(cfg.get('ref_percent') or 0):g}",
             low=f"{float(cfg.get('low_balance_alert') or 0):g}", maint=a(lang, "yes" if cfg.get("maintenance") else "no"))
    kb = InlineKeyboardBuilder()
    for key in ("name", "welcome", "start_photo", "support", "api_key", "min_topup", "ref_percent", "low_balance_alert"):
        kb.button(text=a(lang, f"b_{key}"), callback_data=f"ad:s:{key}")
    kb.button(text=a(lang, "b_maintenance") + (" ✓" if cfg.get("maintenance") else ""), callback_data="ad:maint")
    kb.button(text=a(lang, "back"), callback_data="ad:menu")
    kb.adjust(2)
    return text, kb.as_markup()


@router.callback_query(F.data == "ad:set")
async def settings(call: CallbackQuery, shop: Shop, lang: str, state: FSMContext) -> None:
    await state.clear()
    text, kb = await settings_view(shop, lang)
    await show(call, text, kb)


@router.callback_query(F.data == "ad:maint")
async def toggle_maintenance(call: CallbackQuery, shop: Shop, lang: str) -> None:
    try:
        await shop.update_config(maintenance=not (await shop.config()).get("maintenance"))
    except ApiError:
        await call.answer(a(lang, "no_key"), show_alert=True)
        return
    text, kb = await settings_view(shop, lang)
    await show(call, text, kb)


@router.callback_query(F.data.startswith("ad:s:"))
async def ask_setting(call: CallbackQuery, lang: str, state: FSMContext) -> None:
    key = call.data.split(":")[2]
    await call.answer()
    if key == "start_photo":
        await state.set_state(Adm.photo)
    else:
        await state.set_state(Adm.setting)
        await state.update_data(key=key)
    await call.message.answer(a(lang, f"ask_{key}", site=SITE), reply_markup=back_kb(lang, "ad:set"))


@router.message(Adm.photo)
async def got_photo(message: Message, shop: Shop, lang: str, state: FSMContext) -> None:
    if message.text and message.text.strip() == "-":
        await shop.db.set_setting("start_photo", "")
    elif message.photo:
        await shop.db.set_setting("start_photo", message.photo[-1].file_id)
    else:
        await message.answer(a(lang, "bad_value"))
        return
    await state.clear()
    text, kb = await settings_view(shop, lang)
    await message.answer(a(lang, "saved") + "\n\n" + text, reply_markup=kb)


@router.message(Adm.setting, F.text, ~F.text.in_(MENU_TEXTS))
async def got_setting(message: Message, shop: Shop, lang: str, state: FSMContext) -> None:
    key = (await state.get_data()).get("key")
    raw = message.text.strip()
    if key == "api_key":
        try:
            await message.delete()   # не оставляем ключ в переписке
        except Exception:
            pass
        probe = ProxyZen(raw)
        try:
            bal = (await probe.config())["balance"]
        except ApiError as e:
            await message.answer(a(lang, "key_bad", err=html.escape(e.message)))
            return
        finally:
            await probe.close()
        await shop.db.set_setting("api_key", raw)
        await message.answer(a(lang, "key_ok", balance=bal))
    elif key == "min_topup":
        cents = parse_amount(raw)
        if cents is None:
            await message.answer(a(lang, "bad_value"))
            return
        await shop.db.set_setting("min_topup", str(cents))
    elif key in SERVER_FIELDS:
        value: object = raw
        if key == "welcome":
            value = None if raw == "-" else message.html_text
        elif key == "support":
            value = raw.replace("https://t.me/", "").lstrip("@")
        elif key in ("ref_percent", "low_balance_alert"):
            try:
                value = float(raw.replace(",", ".").replace("%", "").replace("$", ""))
            except ValueError:
                await message.answer(a(lang, "bad_value"))
                return
        try:
            await shop.update_config(**{key: value})
        except ApiError as e:
            await message.answer(a(lang, "bad_value") if e.code == "validation_error" else f"❌ {html.escape(e.message)}")
            return
    else:
        await state.clear()
        return
    await state.clear()
    text, kb = await settings_view(shop, lang)
    await message.answer(a(lang, "saved") + "\n\n" + text, reply_markup=kb)


# ---------- платёжные системы ----------
async def pay_view(shop: Shop, lang: str) -> tuple[str, InlineKeyboardMarkup]:
    rows, kb = [], InlineKeyboardBuilder()
    for p in await shop.providers(only_configured=False):
        rows.append(f"<b>{html.escape(p.title)}</b> — {a(lang, 'pay_on' if p.configured() else 'pay_off')}")
        for f in p.fields:
            if f.toggle:
                kb.button(text=f"{p.code}: {f.label}" + (" ✓" if p.s.get(f.key) == "1" else ""), callback_data=f"ad:pt:{p.code}:{f.key}")
            else:
                kb.button(text=f"{p.code}: {f.label.split(' (')[0]}", callback_data=f"ad:pf:{p.code}:{f.key}")
    kb.button(text=a(lang, "back"), callback_data="ad:menu")
    kb.adjust(1)
    return a(lang, "pay_text", rows="\n".join(rows)), kb.as_markup()


@router.callback_query(F.data == "ad:pay")
async def payments(call: CallbackQuery, shop: Shop, lang: str, state: FSMContext) -> None:
    await state.clear()
    text, kb = await pay_view(shop, lang)
    await show(call, text, kb)


@router.callback_query(F.data.startswith("ad:pt:"))
async def pay_toggle(call: CallbackQuery, shop: Shop, lang: str) -> None:
    _, _, code, key = call.data.split(":")
    name = f"pay.{code}.{key}"
    await shop.db.set_setting(name, "0" if (await shop.db.setting(name)) == "1" else "1")
    text, kb = await pay_view(shop, lang)
    await show(call, text, kb)


@router.callback_query(F.data.startswith("ad:pf:"))
async def pay_ask(call: CallbackQuery, shop: Shop, lang: str, state: FSMContext) -> None:
    _, _, code, key = call.data.split(":")
    p = await shop.provider(code)
    field = next(f for f in p.fields if f.key == key)
    await state.set_state(Adm.pay_field)
    await state.update_data(code=code, key=key)
    await call.answer()
    await call.message.answer(a(lang, "pay_field", provider=html.escape(p.title), label=html.escape(field.label)), reply_markup=back_kb(lang, "ad:pay"))


@router.message(Adm.pay_field, F.text, ~F.text.in_(MENU_TEXTS))
async def pay_got(message: Message, shop: Shop, lang: str, state: FSMContext) -> None:
    data = await state.get_data()
    try:
        await message.delete()
    except Exception:
        pass
    name = f"pay.{data['code']}.{data['key']}"
    old = await shop.db.setting(name)
    await shop.db.set_setting(name, message.text.strip())
    p = await shop.provider(data["code"])
    if p.configured():
        try:
            await message.answer(a(lang, "pay_ok", provider=html.escape(p.title), name=html.escape(await p.check_credentials())))
        except PaymentError as e:
            await shop.db.set_setting(name, old)   # неверный ключ не сохраняем
            await message.answer(a(lang, "pay_bad", provider=html.escape(p.title), err=html.escape(str(e))))
            return
    await state.clear()
    text, kb = await pay_view(shop, lang)
    await message.answer(text, reply_markup=kb)


# ---------- пользователи ----------
@router.callback_query(F.data == "ad:users")
async def users_search(call: CallbackQuery, lang: str, state: FSMContext) -> None:
    await state.set_state(Adm.user_search)
    await call.answer()
    await call.message.answer(a(lang, "users_ask"), reply_markup=back_kb(lang))


async def user_card(msg: Message, shop: Shop, lang: str, uid: int) -> None:
    u = await shop.db.user(uid)
    if not u:
        await msg.answer(a(lang, "user_none"))
        return
    try:
        active = len(await shop.proxies(uid))
    except Exception:
        active = "—"
    text = a(lang, "user_card", name=html.escape(u["first_name"] or "—"), username=f"@{u['username']}" if u["username"] else "", id=u["id"],
             lang=u["lang"], balance=fmt(u["balance"]), topped=fmt(u["topped_up"]), spent=fmt(u["spent"]), active=active,
             since=date(u["created_at"])[:10], seen=date(u["last_seen"]), status=a(lang, "u_banned" if u["banned"] else "u_ok"))
    kb = InlineKeyboardBuilder()
    kb.button(text=a(lang, "u_add"), callback_data=f"ad:u:add:{uid}")
    kb.button(text=a(lang, "u_sub"), callback_data=f"ad:u:sub:{uid}")
    kb.button(text=a(lang, "u_unban" if u["banned"] else "u_ban"), callback_data=f"ad:u:ban:{uid}")
    kb.button(text=a(lang, "u_msg"), callback_data=f"ad:u:msg:{uid}")
    kb.button(text=a(lang, "back"), callback_data="ad:menu")
    kb.adjust(2, 2, 1)
    await msg.answer(text, reply_markup=kb.as_markup())


@router.message(Adm.user_search, F.text, ~F.text.in_(MENU_TEXTS))
async def users_found(message: Message, shop: Shop, lang: str, state: FSMContext) -> None:
    u = await shop.db.find_user(message.text)
    await state.clear()
    if not u:
        await message.answer(a(lang, "user_none"), reply_markup=back_kb(lang))
        return
    await user_card(message, shop, lang, u["id"])


@router.callback_query(F.data.startswith("ad:u:"))
async def user_action(call: CallbackQuery, shop: Shop, lang: str, state: FSMContext) -> None:
    _, _, action, uid = call.data.split(":")
    uid = int(uid)
    await call.answer()
    if action == "ban":
        await shop.db.run("UPDATE users SET banned=1-banned WHERE id=?", uid)
        await user_card(call.message, shop, lang, uid)
    elif action in ("add", "sub"):
        await state.set_state(Adm.user_amount)
        await state.update_data(uid=uid, sign=1 if action == "add" else -1)
        await call.message.answer(a(lang, "ask_amount"))
    elif action == "msg":
        await state.set_state(Adm.user_message)
        await state.update_data(uid=uid)
        await call.message.answer(a(lang, "ask_msg"))


@router.message(Adm.user_amount, F.text, ~F.text.in_(MENU_TEXTS))
async def user_amount(message: Message, shop: Shop, lang: str, state: FSMContext) -> None:
    cents = parse_amount(message.text)
    if cents is None:
        await message.answer(a(lang, "bad_value"))
        return
    data = await state.get_data()
    await state.clear()
    try:
        await shop.db.change_balance(data["uid"], data["sign"] * cents, "admin", f"by {message.from_user.id}")
    except Exception as e:
        await message.answer(f"❌ {html.escape(str(e))}")
        return
    await user_card(message, shop, lang, data["uid"])


@router.message(Adm.user_message)
async def user_message(message: Message, lang: str, state: FSMContext, bot: Bot) -> None:
    uid = (await state.get_data())["uid"]
    await state.clear()
    try:
        await bot.copy_message(uid, message.chat.id, message.message_id)
        await message.answer(a(lang, "sent"))
    except Exception:
        await message.answer(a(lang, "not_sent"))


# ---------- ProxyZen ----------
@router.callback_query(F.data == "ad:pz")
async def pz_status(call: CallbackQuery, shop: Shop, lang: str) -> None:
    key, balance = a(lang, "not_set"), "—"
    try:
        cfg = await (await shop.api()).config()
        key, balance = "✅", f"${cfg['balance']}"
    except ApiError as e:
        if e.code != "no_key":
            key = f"❌ {html.escape(e.message)}"
    await show(call, a(lang, "pz_text", key=key, balance=balance, ver=__version__, latest=shop.latest_version or "—",
                       notice=html.escape(shop.notice), site=SITE), back_kb(lang))
