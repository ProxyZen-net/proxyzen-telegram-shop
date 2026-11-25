"""Платёжная система магазина. Чтобы добавить свою — скопируйте _template.py, реализуйте 3 метода
и добавьте класс в PROVIDERS (app/payments/__init__.py). Ключи вводятся в /admin → Платёжные системы."""
from __future__ import annotations

from dataclasses import dataclass


class PaymentError(Exception):
    pass


@dataclass
class Field:
    key: str            # имя настройки, хранится как pay.<code>.<key>
    label: str          # подпись в админке
    secret: bool = True  # секрет: сообщение с ним бот удалит
    toggle: bool = False  # переключатель вкл/выкл вместо текста


@dataclass
class Invoice:
    id: str             # id счёта у платёжной системы
    url: str            # ссылка на оплату для клиента


class PaymentProvider:
    code: str = ""              # латиницей, уникально: cryptobot, mypay…
    title: str = ""             # название на кнопке, например «CryptoBot (USDT, TON, BTC)»
    fields: list[Field] = []

    def __init__(self, settings: dict[str, str]):
        self.s = settings        # pay.<code>.* без префикса

    def configured(self) -> bool:
        """Можно ли принимать оплату (заданы обязательные ключи)."""
        return all(self.s.get(f.key) for f in self.fields if not f.toggle)

    async def check_credentials(self) -> str:
        """Проверить ключи (для админки). Вернуть название аккаунта/приложения или бросить PaymentError."""
        return self.title

    async def create(self, amount_cents: int, payload: str, description: str, return_url: str) -> Invoice:
        """Создать счёт на сумму в USD."""
        raise NotImplementedError

    async def statuses(self, ids: list[str]) -> dict[str, str]:
        """Статусы счетов: {id: 'paid' | 'expired' | 'active'}. Оплаченные зачисляются ровно один раз."""
        raise NotImplementedError
