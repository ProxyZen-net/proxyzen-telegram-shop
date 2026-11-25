"""Шаблон своей платёжной системы. Скопируйте в app/payments/mypay.py, заполните и добавьте в PROVIDERS.

Пример: платёжка с API «создать счёт» и «проверить статус». Вебхуки не нужны — бот сам опрашивает статусы раз в 20 секунд.
"""
from __future__ import annotations

import httpx

from .base import Field, Invoice, PaymentError, PaymentProvider


class MyPay(PaymentProvider):
    code = "mypay"
    title = "Card payment (MyPay)"
    fields = [Field("api_key", "API key"), Field("shop_id", "Shop ID", secret=False)]

    async def create(self, amount_cents: int, payload: str, description: str, return_url: str) -> Invoice:
        async with httpx.AsyncClient(timeout=20) as http:
            r = await http.post("https://api.mypay.example/invoices", headers={"Authorization": f"Bearer {self.s['api_key']}"},
                                json={"shop_id": self.s["shop_id"], "amount": f"{amount_cents / 100:.2f}", "currency": "USD",
                                      "order_id": payload, "description": description, "success_url": return_url})
        if r.status_code >= 400:
            raise PaymentError(f"MyPay: HTTP {r.status_code}")
        data = r.json()
        return Invoice(str(data["id"]), data["pay_url"])

    async def statuses(self, ids: list[str]) -> dict[str, str]:
        out = {}
        async with httpx.AsyncClient(timeout=20) as http:
            for i in ids:
                r = await http.get(f"https://api.mypay.example/invoices/{i}", headers={"Authorization": f"Bearer {self.s['api_key']}"})
                status = r.json().get("status") if r.status_code == 200 else None
                out[i] = {"paid": "paid", "expired": "expired", "canceled": "expired"}.get(status, "active")
        return out
