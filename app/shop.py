"""Логика магазина поверх ProxyZen Shop API.

Здесь (у владельца): пользователи, балансы, история, счета платёжных систем.
У ProxyZen: каталог, цены (наценка/свои цены владельца), заказы и прокси покупателей, продления, статистика.
Деньги покупателя списываются до заказа и автоматически возвращаются, если ProxyZen отказал.
"""
from __future__ import annotations

import logging
import time
from decimal import Decimal

from .api import ApiError, ProxyZen
from .db import DB, InsufficientFunds, now
from .money import to_cents
from .payments import PROVIDERS, PaymentProvider

log = logging.getLogger("shop")

FLAGS_OFFSET = 127397  # 'A' → 🇦

OWNER_PROBLEMS = {"insufficient_funds", "no_key", "unauthorized", "forbidden", "account_suspended"}


def flag(code: str) -> str:
    code = (code or "").upper()
    return "".join(chr(ord(c) + FLAGS_OFFSET) for c in code) if len(code) == 2 and code.isalpha() else "🏳"


class ShopError(Exception):
    """Ошибка для показа клиенту: code → текст из i18n."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code = code
        self.detail = detail


class Shop:
    def __init__(self, db: DB, admin_ids: frozenset[int], env_api_key: str = ""):
        self.db = db
        self.admin_ids = admin_ids
        self.env_api_key = env_api_key
        self._api: ProxyZen | None = None
        self._api_key_used = ""
        self._cache: dict[str, tuple[float, object]] = {}
        self.notice = ""
        self.latest_version = ""

    # ---------- ProxyZen ----------
    async def api(self) -> ProxyZen:
        key = (await self.db.setting("api_key")) or self.env_api_key
        if self._api is None or key != self._api_key_used:
            if self._api:
                await self._api.close()
            self._api, self._api_key_used = ProxyZen(key), key
            self._cache.clear()
        return self._api

    async def _cached(self, key: str, ttl: int, loader):
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
        value = await loader()
        self._cache[key] = (time.monotonic(), value)
        return value

    def forget(self, prefix: str = "") -> None:
        self._cache = {k: v for k, v in self._cache.items() if prefix and not k.startswith(prefix)}

    async def config(self) -> dict:
        """Настройки магазина у ProxyZen (название, приветствие, поддержка, наценки, реферальный %, техработы)."""
        api = await self.api()
        try:
            return await self._cached("config", 60, api.config)
        except ApiError:
            return {"name": "Proxy Shop", "welcome": None, "support": None, "ref_percent": "0", "maintenance": False,
                    "low_balance_alert": "0", "markup": {}, "balance": None}

    async def update_config(self, **fields) -> dict:
        res = await (await self.api()).update_config(**fields)
        self._cache["config"] = (time.monotonic(), res)
        return res

    # ---------- каталог ----------
    async def countries(self, type_: str, lang: str) -> list[dict]:
        api = await self.api()
        return await self._cached(f"countries:{type_}:{lang}", 60, lambda: api.countries(type_, lang))

    async def periods(self, country: str, type_: str, lang: str) -> dict:
        api = await self.api()
        return await self._cached(f"periods:{country}:{type_}:{lang}", 60, lambda: api.periods(country, type_, lang))

    async def period_price(self, country: str, type_: str, days: int, lang: str) -> int:
        for p in (await self.periods(country, type_, lang))["data"]:
            if int(p["days"]) == days:
                return to_cents(p["price"])
        raise ShopError("invalid_period")

    # ---------- покупка ----------
    async def buy(self, uid: int, country: str, type_: str, days: int, quantity: int, lang: str) -> dict:
        if (await self.config()).get("maintenance") and uid not in self.admin_ids:
            raise ShopError("maintenance")
        if not 1 <= quantity <= 1000:
            raise ShopError("invalid_quantity")
        api = await self.api()
        try:
            q = await api.quote(uid, country, type_, days, quantity)
        except ApiError as e:
            raise self._api_error(e)
        total = to_cents(q["total"])
        ref = f"{type_}:{country}:{days}d×{quantity}"
        try:
            await self.db.change_balance(uid, -total, "purchase", ref, spent=total)
        except InsufficientFunds as e:
            raise ShopError("insufficient_funds", str(total - int(e.args[0])))
        try:
            order = await api.order(uid, country, type_, days, quantity, q["total"], lang)
        except ApiError as e:
            await self.db.change_balance(uid, total, "refund", f"{ref}: {e.code}", spent=-total)   # вернуть деньги покупателю
            log.warning("ProxyZen order failed: %s %s", e.code, e.message)
            self.forget("countries")
            raise self._api_error(e)
        self.forget("countries")
        return {"order_id": order["order_id"], "total": total, "proxies": order["proxies"]}

    @staticmethod
    def _api_error(e: ApiError) -> ShopError:
        if e.code in OWNER_PROBLEMS:
            return ShopError("shop_unavailable", e.code)
        if e.code in ("out_of_stock", "invalid_period", "not_renewable", "not_found", "maintenance", "price_changed"):
            return ShopError(e.code, e.message)
        return ShopError("api_error", e.message)

    # ---------- прокси покупателя ----------
    async def proxies(self, uid: int, status: str = "renewable") -> list[dict]:
        return await (await self.api()).customer_proxies(uid, status)

    async def renew_options(self, uid: int, ids: list[int]) -> list[tuple[int, int]]:
        """[(дней, цена в центах за все выбранные)] — сроки, доступные для всех выбранных прокси."""
        api = await self.api()
        try:
            periods = (await api.renew_quote(uid, ids, 30))["periods"]
            out = []
            for d in periods:
                total = (await api.renew_quote(uid, ids, int(d)))["total"]
                if total is not None:
                    out.append((int(d), to_cents(total)))
            return out
        except ApiError as e:
            raise self._api_error(e)

    async def renew(self, uid: int, ids: list[int], days: int, lang: str) -> int:
        api = await self.api()
        try:
            q = await api.renew_quote(uid, ids, days)
        except ApiError as e:
            raise self._api_error(e)
        if q.get("total") is None:
            raise ShopError("invalid_period")
        total = to_cents(q["total"])
        ref = f"renew {len(ids)}×{days}d"
        try:
            await self.db.change_balance(uid, -total, "renew", ref, spent=total)
        except InsufficientFunds as e:
            raise ShopError("insufficient_funds", str(total - int(e.args[0])))
        try:
            await api.renew(uid, ids, days, q["total"], lang)
        except ApiError as e:
            await self.db.change_balance(uid, total, "refund", f"{ref}: {e.code}", spent=-total)
            raise self._api_error(e)
        return total

    async def set_auto_renew(self, uid: int, proxy_id: int, enabled: bool) -> dict:
        try:
            return await (await self.api()).auto_renew(uid, proxy_id, enabled)
        except ApiError as e:
            raise self._api_error(e)

    # ---------- резидентские и мобильные (за ГБ) ----------
    async def traffic(self) -> dict:
        """Цены за ГБ, хост и порты. {"enabled": bool, "data": [{"type", "price", "cost", ...}]}"""
        api = await self.api()
        try:
            return await self._cached("traffic", 60, api.traffic)
        except ApiError:
            return {"enabled": False, "data": []}

    async def traffic_price(self, type_: str) -> int | None:
        row = next((r for r in (await self.traffic()).get("data", []) if r["type"] == type_), None)
        return to_cents(row["price"]) if row else None

    async def traffic_countries(self, type_: str, lang: str) -> list[dict]:
        api = await self.api()
        return await self._cached(f"tcountries:{type_}:{lang}", 3600, lambda: api.traffic_countries(type_, lang))

    async def traffic_country(self, type_: str, code: str, lang: str) -> dict:
        api = await self.api()
        try:
            return await self._cached(f"tcountry:{type_}:{code}:{lang}", 3600, lambda: api.traffic_country(type_, code, lang))
        except ApiError:
            return {"states": [], "isps": []}

    async def traffic_plans(self, uid: int) -> list[dict]:
        return await (await self.api()).customer_traffic(uid)

    async def buy_traffic(self, uid: int, type_: str, gb: int, lang: str) -> dict:
        if (await self.config()).get("maintenance") and uid not in self.admin_ids:
            raise ShopError("maintenance")
        if not 1 <= gb <= 1000:
            raise ShopError("invalid_quantity")
        self._cache.pop("traffic", None)
        price = await self.traffic_price(type_)
        if price is None:
            raise ShopError("traffic_off")
        total = price * gb
        ref = f"traffic:{type_}:{gb}GB"
        try:
            await self.db.change_balance(uid, -total, "purchase", ref, spent=total)
        except InsufficientFunds as e:
            raise ShopError("insufficient_funds", str(total - int(e.args[0])))
        try:
            res = await (await self.api()).traffic_order(uid, type_, gb, f"{total / 100:.2f}", lang)
        except ApiError as e:
            await self.db.change_balance(uid, total, "refund", f"{ref}: {e.code}", spent=-total)
            log.warning("ProxyZen traffic order failed: %s %s", e.code, e.message)
            raise self._api_error(e)
        return {"total": total, "gb": gb, "plan": res["plan"]}

    async def traffic_reset_password(self, uid: int, type_: str) -> dict:
        try:
            return await (await self.api()).traffic_reset_password(uid, type_)
        except ApiError as e:
            raise self._api_error(e)

    # ---------- платёжные системы ----------
    async def providers(self, only_configured: bool = True) -> list[PaymentProvider]:
        out = []
        for cls in PROVIDERS:
            settings = {f.key: await self.db.setting(f"pay.{cls.code}.{f.key}") for f in cls.fields}
            p = cls(settings)
            if p.configured() or not only_configured:
                out.append(p)
        return out

    async def provider(self, code: str) -> PaymentProvider:
        for p in await self.providers(only_configured=False):
            if p.code == code:
                return p
        raise ShopError("api_error", f"unknown payment provider {code}")

    async def create_topup(self, uid: int, amount: int, provider_code: str, bot_username: str) -> dict:
        minimum = int(await self.db.setting("min_topup") or 100)
        if amount < minimum:
            raise ShopError("min_topup", str(minimum))
        provider = await self.provider(provider_code)
        name = (await self.config()).get("name") or "Proxy Shop"
        row_id = await self.db.run("INSERT INTO invoices(user_id,provider,amount,created_at) VALUES(?,?,?,?)", uid, provider.code, amount, now())
        inv = await provider.create(amount, f"topup:{row_id}", f"{name}: balance top-up", f"https://t.me/{bot_username}")
        await self.db.run("UPDATE invoices SET invoice_id=?, url=? WHERE id=?", inv.id, inv.url, row_id)
        return {"id": row_id, "url": inv.url}

    async def credit_invoice(self, row: dict) -> bool:
        """Зачислить оплаченный счёт (ровно один раз) + реферальный бонус пригласившему."""
        if not await self.db.mark_invoice_paid(row["id"]):
            return False
        await self.db.change_balance(row["user_id"], row["amount"], "topup", f"{row['provider']} #{row['invoice_id']}", topped_up=row["amount"])
        percent = Decimal(str((await self.config()).get("ref_percent") or 0))
        user = await self.db.user(row["user_id"])
        if percent > 0 and user and user["ref_by"]:
            bonus = int(Decimal(row["amount"]) * percent / 100)
            if bonus > 0:
                await self.db.change_balance(user["ref_by"], bonus, "referral", f"from {row['user_id']}")
                await self.db.run("UPDATE users SET ref_earned=ref_earned+? WHERE id=?", bonus, user["ref_by"])
        return True

    async def check_invoices(self) -> list[dict]:
        """Опросить платёжные системы по активным счетам. Возвращает зачисленные."""
        rows = [dict(r) for r in await self.db.all("SELECT * FROM invoices WHERE status='active' AND invoice_id IS NOT NULL AND created_at>?", now() - 7200)]
        credited = []
        by_provider: dict[str, list[dict]] = {}
        for r in rows:
            by_provider.setdefault(r["provider"], []).append(r)
        for code, items in by_provider.items():
            try:
                provider = await self.provider(code)
                statuses = await provider.statuses([r["invoice_id"] for r in items])
            except Exception as e:
                log.warning("payments %s: %s", code, e)
                continue
            for r in items:
                st = statuses.get(r["invoice_id"])
                if st == "paid" and await self.credit_invoice(r):
                    credited.append(r)
                elif st == "expired":
                    await self.db.run("UPDATE invoices SET status='expired' WHERE id=? AND status='active'", r["id"])
        await self.db.run("UPDATE invoices SET status='expired' WHERE status='active' AND created_at<=?", now() - 7200)
        return credited
