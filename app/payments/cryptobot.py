"""Crypto Pay API (@CryptoBot): счёт в USD, оплата USDT, TON, BTC и другими монетами из Telegram.
Документация: https://help.send.tg/en/articles/10279948-crypto-pay-api
Токен: @CryptoBot → Crypto Pay → My Apps → Create App → API Token."""
from __future__ import annotations

import httpx

from .base import Field, Invoice, PaymentError, PaymentProvider

TRANSPORT: httpx.AsyncBaseTransport | None = None   # подменяется в тестах


class CryptoBot(PaymentProvider):
    code = "cryptobot"
    title = "CryptoBot (USDT, TON, BTC…)"
    fields = [Field("token", "API Token (@CryptoBot → Crypto Pay → My Apps)"), Field("testnet", "Testnet", secret=False, toggle=True)]

    async def _call(self, method: str, **params):
        base = "https://testnet-pay.crypt.bot/api" if self.s.get("testnet") == "1" else "https://pay.crypt.bot/api"
        async with httpx.AsyncClient(base_url=base, timeout=20, transport=TRANSPORT, headers={"Crypto-Pay-API-Token": self.s.get("token", "")}) as http:
            try:
                r = await http.get(f"/{method}", params={k: v for k, v in params.items() if v is not None})
                data = r.json()
            except (httpx.HTTPError, ValueError) as e:
                raise PaymentError(f"CryptoBot {method}: {e.__class__.__name__}") from e
        if not data.get("ok"):
            err = data.get("error", {})
            raise PaymentError(f"CryptoBot {method}: {err.get('name') if isinstance(err, dict) else err}")
        return data["result"]

    async def check_credentials(self) -> str:
        return str((await self._call("getMe")).get("name", "CryptoBot"))

    async def create(self, amount_cents: int, payload: str, description: str, return_url: str) -> Invoice:
        inv = await self._call("createInvoice", currency_type="fiat", fiat="USD", amount=f"{amount_cents / 100:.2f}",
                               description=description[:1024], payload=payload, expires_in=3600,
                               paid_btn_name="callback", paid_btn_url=return_url)
        url = inv.get("bot_invoice_url") or inv.get("mini_app_invoice_url") or inv.get("web_app_invoice_url")
        return Invoice(str(inv["invoice_id"]), url)

    async def statuses(self, ids: list[str]) -> dict[str, str]:
        res = await self._call("getInvoices", invoice_ids=",".join(ids))
        items = res.get("items", []) if isinstance(res, dict) else res
        out = {}
        for i in items:
            st = i.get("status")
            out[str(i["invoice_id"])] = "paid" if st == "paid" and str(i.get("fiat", "USD")).upper() == "USD" else ("expired" if st == "expired" else "active")
        return out
