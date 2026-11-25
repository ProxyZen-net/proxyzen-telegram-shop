"""Настройки из .env. Всё остальное (название магазина, ключи, наценки) — в /admin, хранится в базе."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: frozenset[int]
    api_key_env: str
    db_path: Path


def load() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token or ":" not in token:
        raise SystemExit("BOT_TOKEN не задан в .env / BOT_TOKEN is missing in .env")
    admins = frozenset(int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.strip().lstrip("-").isdigit())
    if not admins:
        raise SystemExit("ADMIN_IDS не задан в .env / ADMIN_IDS is missing in .env")
    db = Path(os.getenv("DB_PATH", "data/bot.db"))
    if not db.is_absolute():
        db = ROOT / db
    db.parent.mkdir(parents=True, exist_ok=True)
    return Config(token, admins, os.getenv("PROXYZEN_API_KEY", "").strip(), db)
