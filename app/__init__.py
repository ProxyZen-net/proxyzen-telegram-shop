"""ProxyZen Telegram Shop — готовый магазин прокси на API ProxyZen (https://proxyzen.net)."""
from pathlib import Path

__version__ = (Path(__file__).resolve().parent.parent / "VERSION").read_text().strip()
