<p align="center">
  <img src="https://proxyzen.net/images/icon-192.png" width="88" alt="ProxyZen">
</p>

<h1 align="center">ProxyZen Telegram Shop</h1>

<p align="center">
  A ready-made Telegram bot that sells proxies under <b>your own brand</b> — IPv4, IPv6, residential and mobile.<br>
  Powered by the <a href="https://proxyzen.net/en/api">ProxyZen API</a>. Python 3.9+, no Docker, installs in 5 minutes.
</p>

<p align="center">
  <a href="https://proxyzen.net"><img src="https://img.shields.io/badge/proxies-proxyzen.net-4F46E5" alt="proxyzen.net"></a>
  <img src="https://img.shields.io/badge/python-3.9%2B-3776AB" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/aiogram-3-2CA5E0" alt="aiogram 3">
  <img src="https://img.shields.io/badge/version-2.0.2-success" alt="version">
</p>

**[English](#english) · [Русский](#русский)**

---

## English

### What your customers get
- 🌐 **IPv4 / IPv6** by country and period, delivered instantly in the chat and as a `.txt` file
- 🏠 **Residential** and 📱 **mobile** proxies per GB — country, city and carrier targeting, rotating or sticky IPs
- 📦 **My proxies** — credentials, one-tap renewal, auto-renew, reset password, connection-string builder
- 💰 **Top-ups** via [@CryptoBot](https://t.me/CryptoBot) (USDT, TON, BTC…) — add any other payment method with a small Python class
- 🎁 Referral bonus for inviting friends, English and Russian interface

### What you get as the owner (`/admin`)
- **Prices** — your cost, your price and your profit for every product; set your own price or a markup. Selling below cost is blocked.
- **Statistics** — revenue, cost and profit for today / 7 / 30 days, top countries, users
- **Broadcasts** with images and buttons, **user management** (balance, ban, message)
- Shop name, welcome text and image, support contact, maintenance mode

You pay ProxyZen the wholesale price from your ProxyZen balance; your customers pay you. The difference is your profit.

### Install (Linux, one command)
```bash
bash <(curl -fsSL https://proxyzen.net/bot/install.sh)
```
Update later: `bash <(curl -fsSL https://proxyzen.net/bot/install.sh) --update`

### Manual install (Linux, macOS, Windows)
```bash
git clone <this repository> proxyzen-shop && cd proxyzen-shop
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # BOT_TOKEN, ADMIN_IDS, DEFAULT_LANG
python bot.py
```

### You will need
1. A bot token from [@BotFather](https://t.me/BotFather) and your Telegram ID ([@userinfobot](https://t.me/userinfobot))
2. A ProxyZen account, an API key (dashboard → API) and a funded balance — [sign up](https://proxyzen.net/cabinet/register)
3. A [@CryptoBot](https://t.me/CryptoBot) token (Crypto Pay → My Apps) or your own payment method

### Add your own payment method
Copy `app/payments/_template.py`, implement `create()` and `statuses()`, add the class to `PROVIDERS` in `app/payments/__init__.py`. It appears in `/admin` and for customers.

### Links
- Website: https://proxyzen.net
- API documentation: https://proxyzen.net/en/api
- Support: [@proxyzen_agent](https://t.me/proxyzen_agent)

---

## Русский

Telegram-магазин прокси на API [ProxyZen](https://proxyzen.net): IPv4, IPv6, резидентские и мобильные. Python 3.9+, без Docker.

### Что нужно
- Токен бота от [@BotFather](https://t.me/BotFather)
- Ваш Telegram ID ([@userinfobot](https://t.me/userinfobot))
- API-ключ ProxyZen (кабинет → API) и пополненный баланс ProxyZen
- Токен [@CryptoBot](https://t.me/CryptoBot) (Crypto Pay → My Apps) или своя платёжная система

### Установка
Linux, одной командой (бот запустится как служба `proxyzen-bot`):
```bash
bash <(curl -fsSL https://proxyzen.net/bot/install.sh)
```
Обновление: `bash <(curl -fsSL https://proxyzen.net/bot/install.sh) --update`

Вручную (Linux, macOS, Windows):
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # BOT_TOKEN, ADMIN_IDS, DEFAULT_LANG (en)
python bot.py
```

### Админка (`/admin`)
- **Цены** — закупка ProxyZen, ваша цена и прибыль: IPv4/IPv6 по срокам, резидентские и мобильные за 1 ГБ; своя цена или наценка.
- **Настройки** — название, приветствие и картинка `/start`, поддержка, ключ ProxyZen, мин. пополнение, реферальный %, техработы.
- **Платёжные системы** — ключи CryptoBot и ваших платёжек.
- **Статистика, рассылка, пользователи** (баланс, бан, сообщение).

### Своя платёжная система
Скопируйте `app/payments/_template.py`, реализуйте `create()` и `statuses()`, добавьте класс в `PROVIDERS` в `app/payments/__init__.py`. Платёжка появится в `/admin` и у клиентов.

---

**License:** free to use and modify for running your own shop on ProxyZen. See [LICENSE](LICENSE).
