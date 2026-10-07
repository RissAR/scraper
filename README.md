# 🛒 Multi-Platform E-Commerce Scraper & Telegram Bot

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Aiogram 3.x](https://img.shields.io/badge/aiogram-3.x-informational.svg)](https://docs.aiogram.dev/)
[![Docker](https://img.shields.io/badge/Docker-Enabled-brightgreen.svg)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Високопродуктивний асинхронний сервіс для паралельного збору, дедуплікації та аналізу оголошень з **OLX.ua** та **Prom.ua**. Інтерфейс взаємодії реалізовано у вигляді Telegram-бота з підтримкою експорту звітності в Excel.

---

## ⚡ Ключові особливості

- **Висока швидкість (Zero-Headless):** Робота через публічні REST/GraphQL API та швидкий парсинг SSR-верстки (`httpx[http2]`) без використання важких браузерів (Selenium/Playwright).
- **Вбудована дедуплікація:** База даних SQLite (`aiosqlite`) надійно відсікає вже зібрані офери за унікальними складеними ключами.
- **Збалансована видача (Interleaving):** Алгоритм чергування карток товарів у Telegram запобігає домінуванню одного майданчика над іншим у комбінованому режимі.
- **Генерація Excel-звітів:** Формування форматованих таблиць `.xlsx` (`openpyxl`) з автопідбором ширини стовпців та клікабельними лінками.
- **Автономне розгортання:** Готова конфігурація `docker-compose.yml` з персистентним сховищем та підтримкою rootless Podman / Docker.

---

## 🏗 Архітектура системи

[ OLX.ua (GraphQL / REST) ] ──┐
├──► [ Async Engine (httpx) ] ──► [ Pydantic v2 Models ]
[ Prom.ua (SSR HTML)      ] ──┘                                        │
▼
[ Telegram User ] ◄── [ Aiogram 3 Bot ] ◄── [ Exporter (.xlsx) ] ◄── [ SQLite DB (aiosqlite) ]


---

## 🛠 Технологічний стек

- **Core:** Python 3.12, Asyncio, Pydantic v2
- **Scraping:** `httpx` (HTTP/2), `BeautifulSoup4`, `lxml`
- **Bot Framework:** `aiogram 3.x` (FSM, Routers)
- **Database:** SQLite, `aiosqlite`
- **Reporting:** `openpyxl`
- **DevOps:** Docker, Docker Compose, Podman

---

## 🚀 Швидкий старт

### 1. Клонування репозиторію
```bash
git clone [https://github.com/RissAR/scraper.git](https://github.com/RissAR/scraper.git)
cd scraper
2. Налаштування середовища
Створіть файл .env на основі .env.example:

Bash
cp .env.example .env
Задайте параметри:

Фрагмент коду
BOT_TOKEN=ваш_telegram_bot_token
DB_PATH=data/scraped.db
LOG_LEVEL=INFO
3. Запуск через Docker Compose
Bash
docker compose up -d --build
