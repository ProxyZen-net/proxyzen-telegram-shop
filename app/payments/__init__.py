"""Подключённые платёжные системы. Свою — добавьте сюда (см. _template.py)."""
from __future__ import annotations

from .base import Field, Invoice, PaymentError, PaymentProvider
from .cryptobot import CryptoBot

PROVIDERS: list[type[PaymentProvider]] = [CryptoBot]

__all__ = ["PROVIDERS", "PaymentProvider", "PaymentError", "Invoice", "Field"]
