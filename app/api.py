"""Клиент ProxyZen Shop API (https://proxyzen.net/en/api).

Скрипт работает только вместе с ProxyZen: каталог, цены (наценка и свои цены владельца),
покупки и продления, прокси каждого покупателя, напоминания и статистика продаж — на стороне ProxyZen.
Ключ — из кабинета proxyzen.net → API (вставляется в /admin бота).
"""
from __future__ import annotations

from typing import Any

import httpx

from . import __version__

API_BASE = "https://proxyzen.net/api/v1"
SITE = "https://proxyzen.net"


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 0, data: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.data = data or {}


class ProxyZen:
    def __init__(self, key: str, transport: httpx.AsyncBaseTransport | None = None):
        self.key = (key or "").strip()
        self.http = httpx.AsyncClient(
            base_url=API_BASE, timeout=httpx.Timeout(40, connect=10), transport=transport,
            headers={"Accept": "application/json", "User-Agent": f"ProxyZenShop/{__version__}"},
        )

    async def close(self) -> None:
        await self.http.aclose()

    async def _req(self, method: str, path: str, lang: str = "en", **kw) -> Any:
        if not self.key:
            raise ApiError("no_key", "ProxyZen API key is not set — /admin → Settings")
        params = {**kw.pop("params", {}), "lang": lang}
        try:
            r = await self.http.request(method, path, params=params, headers={"Authorization": f"Bearer {self.key}"}, **kw)
        except httpx.HTTPError as e:
            raise ApiError("network", f"ProxyZen API unreachable: {e.__class__.__name__}") from e
        try:
            data = r.json()
        except ValueError:
            raise ApiError("bad_response", f"ProxyZen API HTTP {r.status_code}", r.status_code)
        if r.status_code >= 400:
            err = data.get("error", {}) if isinstance(data, dict) else {}
            raise ApiError(err.get("code", "error"), err.get("message", f"HTTP {r.status_code}"), r.status_code, err)
        return data

    # --- магазин: настройки и цены ---
    async def config(self) -> dict:
        return await self._req("GET", "/shop")

    async def update_config(self, **fields) -> dict:
        return await self._req("PATCH", "/shop", json=fields)

    async def price_table(self) -> dict:
        return await self._req("GET", "/shop/prices")

    async def set_price(self, type_: str, days: int, price: str | None) -> dict:
        return await self._req("PUT", "/shop/prices", json={"type": type_, "days": days, "price": price})

    # --- каталог ---
    async def countries(self, type_: str, lang: str = "en") -> list[dict]:
        return (await self._req("GET", "/shop/countries", lang, params={"type": type_}))["data"]

    async def periods(self, country: str, type_: str, lang: str = "en") -> dict:
        return await self._req("GET", f"/shop/countries/{country}", lang, params={"type": type_})

    # --- покупки клиентов ---
    async def quote(self, customer: int, country: str, type_: str, days: int, quantity: int) -> dict:
        return await self._req("POST", "/shop/quote", json={"customer": customer, "country": country, "type": type_, "days": days, "quantity": quantity})

    async def order(self, customer: int, country: str, type_: str, days: int, quantity: int, expected_total: str, lang: str = "en") -> dict:
        return await self._req("POST", "/shop/orders", lang, json={"customer": customer, "country": country, "type": type_, "days": days,
                                                                   "quantity": quantity, "expected_total": expected_total})

    async def customer_proxies(self, customer: int, status: str = "renewable") -> list[dict]:
        return (await self._req("GET", f"/shop/customers/{customer}/proxies", params={"status": status}))["data"]

    async def renew_quote(self, customer: int, ids: list[int], days: int) -> dict:
        return await self._req("POST", "/shop/renew/quote", json={"customer": customer, "ids": ids, "days": days})

    async def renew(self, customer: int, ids: list[int], days: int, expected_total: str, lang: str = "en") -> dict:
        return await self._req("POST", "/shop/renew", lang, json={"customer": customer, "ids": ids, "days": days, "expected_total": expected_total})

    async def auto_renew(self, customer: int, proxy_id: int, enabled: bool) -> dict:
        return await self._req("POST", f"/shop/proxies/{proxy_id}/auto-renew", json={"customer": customer, "enabled": enabled})

    # --- фоновые задачи и статистика ---
    async def due(self) -> dict:
        return await self._req("GET", "/shop/due")

    async def notified(self, ids: list[int], kind: str) -> dict:
        return await self._req("POST", "/shop/notified", json={"ids": ids, "kind": kind})

    async def stats(self) -> dict:
        return await self._req("GET", "/shop/stats")

    async def ping(self, bot_username: str, users: int) -> dict:
        return await self._req("POST", "/shop/ping", json={"version": __version__, "bot": bot_username, "users": users})

    # --- резидентские и мобильные прокси (за ГБ) ---
    async def traffic(self) -> dict:
        return await self._req("GET", "/shop/traffic")

    async def set_traffic_price(self, type_: str, price: str | None) -> dict:
        return await self._req("PUT", "/shop/traffic/prices", json={"type": type_, "price": price})

    async def traffic_countries(self, type_: str, lang: str = "en") -> list[dict]:
        return (await self._req("GET", "/shop/traffic/countries", lang, params={"type": type_}))["data"]

    async def traffic_country(self, type_: str, code: str, lang: str = "en") -> dict:
        return await self._req("GET", f"/shop/traffic/countries/{code}", lang, params={"type": type_})

    async def traffic_order(self, customer: int, type_: str, gb: int, expected_total: str, lang: str = "en") -> dict:
        return await self._req("POST", "/shop/traffic/orders", lang, json={"customer": customer, "type": type_, "gb": gb, "expected_total": expected_total})

    async def customer_traffic(self, customer: int) -> list[dict]:
        return (await self._req("GET", f"/shop/customers/{customer}/traffic"))["data"]

    async def traffic_reset_password(self, customer: int, type_: str) -> dict:
        return await self._req("POST", "/shop/traffic/reset-password", json={"customer": customer, "type": type_})
