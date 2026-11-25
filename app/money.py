"""Деньги храним в центах (int), цены поставщика — Decimal-строки с 4 знаками."""
from __future__ import annotations

from decimal import ROUND_CEILING, Decimal


def to_cents(value: str | Decimal | float | int) -> int:
    return int((Decimal(str(value)) * 100).to_integral_value(rounding=ROUND_CEILING))


def fmt(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100}.{cents % 100:02d}"


def sell_price_cents(cost_per_ip: str | Decimal, markup_percent: str | Decimal | float | int) -> int:
    """Цена для клиента за 1 IP: цена ProxyZen + наценка, вверх до цента (минимум 1 цент)."""
    price = Decimal(str(cost_per_ip)) * (Decimal(1) + Decimal(str(markup_percent)) / Decimal(100))
    return max(1, int((price * 100).to_integral_value(rounding=ROUND_CEILING)))


def parse_amount(text: str) -> int | None:
    """'10', '10.5', '$10,50' → центы; None если не число."""
    t = text.strip().replace("$", "").replace(",", ".").replace(" ", "")
    try:
        d = Decimal(t)
    except Exception:
        return None
    if d <= 0 or d > 100000:
        return None
    return int((d * 100).to_integral_value())
