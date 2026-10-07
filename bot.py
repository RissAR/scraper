import asyncio
import html
import logging
import os
import time
from pathlib import Path
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from config import settings
from database import DatabaseManager
from exporter import export_items_to_excel
from models import Platform, ProductItem
from olx_scraper import OLXScraper
from prom_scraper import PromScraper

logger = logging.getLogger(__name__)

# FSM стани
class SearchStates(StatesGroup):
    waiting_for_platform = State()
    waiting_for_query = State()


# Ініціалізація компонентів
router = Router()
db_manager = DatabaseManager()
prom_scraper = PromScraper()
olx_scraper = OLXScraper()

# Кеш останніх результатів пошуку для інлайн-експорту: user_id -> list[ProductItem]
user_search_cache: dict[int, list[ProductItem]] = {}


def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Головна клавіатура бота."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 Пошук (Prom + OLX)")],
            [
                KeyboardButton(text="🟠 Пошук тільки OLX"),
                KeyboardButton(text="🟣 Пошук тільки Prom"),
            ],
            [
                KeyboardButton(text="📥 Експорт бази в Excel"),
                KeyboardButton(text="📊 Статистика бази"),
            ],
        ],
        resize_keyboard=True,
    )


# --- Обробка /start та привітання ---
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    welcome_text = (
        "👋 <b>Вітаю в системі збору та моніторингу оголошень!</b>\n\n"
        "Я вмію збирати та аналізувати товари з маркетплейсів <b>Prom.ua</b> та <b>OLX.ua</b>, "
        "зберігати їх у базі SQLite із захистом від дублікатів та формувати звітні таблиці Excel.\n\n"
        "Оберіть дію на клавіатурі нижче:"
    )
    await message.answer(welcome_text, reply_markup=get_main_keyboard())


# --- Сценарій вибору платформи та очікування запиту ---
@router.message(F.text == "🔍 Пошук (Prom + OLX)")
@router.message(Command("search"))
async def search_all_prompt(message: Message, state: FSMContext) -> None:
    await state.update_data(platform="all")
    await state.set_state(SearchStates.waiting_for_query)
    await message.answer(
        "🔍 <b>Пошук по Prom.ua та OLX.ua</b>\nВведіть пошуковий запит (наприклад, <i>зимова куртка</i>):"
    )


@router.message(F.text == "🟠 Пошук тільки OLX")
@router.message(Command("olx"))
async def search_olx_prompt(message: Message, state: FSMContext) -> None:
    await state.update_data(platform="olx")
    await state.set_state(SearchStates.waiting_for_query)
    await message.answer(
        "🟠 <b>Пошук тільки по OLX.ua</b>\nВведіть пошуковий запит (наприклад, <i>зимова куртка</i>):"
    )


@router.message(F.text == "🟣 Пошук тільки Prom")
@router.message(Command("prom"))
async def search_prom_prompt(message: Message, state: FSMContext) -> None:
    await state.update_data(platform="prom")
    await state.set_state(SearchStates.waiting_for_query)
    await message.answer(
        "🟣 <b>Пошук тільки по Prom.ua</b>\nВведіть пошуковий запит (наприклад, <i>зимова куртка</i>):"
    )


# --- Обробка введеного пошукового запиту ---
@router.message(SearchStates.waiting_for_query, F.text)
async def process_search_query(message: Message, state: FSMContext) -> None:
    query = message.text.strip()
    if not query:
        await message.answer("Будь ласка, введіть непорожній текст запиту:")
        return

    data = await state.get_data()
    target_platform = data.get("platform", "all")
    await state.clear()

    status_msg = await message.answer(
        f"⏳ Виконую пошук за запитом '<b>{html.escape(query)}</b>'... Зачекайте."
    )

    found_items: list[ProductItem] = []

    try:
        if target_platform == "olx":
            found_items = await olx_scraper.scrape(query=query, max_pages=1)
        elif target_platform == "prom":
            found_items = await prom_scraper.scrape(query=query, max_pages=1)
        else:
            # Паралельний запуск обох скрейперів
            results = await asyncio.gather(
                olx_scraper.scrape(query=query, max_pages=1),
                prom_scraper.scrape(query=query, max_pages=1),
                return_exceptions=True,
            )
            for res in results:
                if isinstance(res, list):
                    found_items.extend(res)
                elif isinstance(res, Exception):
                    logger.error("Scraper execution error: %s", res)
    except Exception as exc:
        logger.exception("Unexpected error during scraping: %s", exc)
        await status_msg.edit_text(f"❌ Виникла помилка під час скрейпінгу: {html.escape(str(exc))}")
        return

    # Збереження в базу даних батчем
    added, skipped = await db_manager.save_items_batch(found_items)
    total_found = len(found_items)

    # Зберігаємо в кеш користувача для можливого експорту
    user_search_cache[message.from_user.id] = found_items

    # Формування підсумкового звіту
    summary_text = (
        f"✅ <b>Результати пошуку: '{html.escape(query)}'</b>\n\n"
        f"📦 Знайдено всього: <b>{total_found}</b>\n"
        f"🆕 Нових додано в БД: <b>{added}</b>\n"
        f"♻️ Дублікатів пропущено: <b>{skipped}</b>"
    )

    export_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📥 Завантажити ці результати в Excel",
                    callback_data="export_current_search",
                )
            ]
        ]
    )

    await status_msg.edit_text(summary_text, reply_markup=export_kb)

    # Відправка карток (до 5 позицій)
    if found_items:
        cards_to_send = found_items[:5]
        for item in cards_to_send:
            plat_str = (
                item.platform.value.upper()
                if hasattr(item.platform, "value")
                else str(item.platform).upper()
            )
            item_card = (
                f"<b>[{plat_str}] {html.escape(item.title)}</b>\n"
                f"💰 <b>Ціна:</b> {item.price} {html.escape(item.currency)}\n"
                f"📍 <b>Локація:</b> {html.escape(item.location or 'Не вказано')}\n"
                f"🔗 <a href=\"{item.url}\">Переглянути оголошення</a>"
            )
            try:
                await message.answer(item_card, disable_web_page_preview=False)
            except Exception as send_err:
                logger.warning("Failed to send item card [%s]: %s", item.id, send_err)


# --- Інлайн-експорт поточного пошуку ---
@router.callback_query(F.data == "export_current_search")
async def export_current_search_callback(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    items = user_search_cache.get(user_id)

    if not items:
        await callback.answer("Результати попереднього пошуку не знайдено в пам'яті.", show_alert=True)
        return

    await callback.answer("Генерую Excel файл...")
    filename = f"search_results_{int(time.time())}.xlsx"
    file_path_str = export_items_to_excel(items, filename=filename)
    file_path = Path(file_path_str)

    try:
        document = FSInputFile(path=file_path, filename=filename)
        await callback.message.answer_document(
            document=document,
            caption=f"📊 Звіт за результатами пошуку ({len(items)} товарів).",
        )
    finally:
        if file_path.exists():
            try:
                os.remove(file_path)
            except OSError as err:
                logger.warning("Error deleting temporary file %s: %s", file_path, err)


# --- Сценарій експорту всієї бази даних ---
@router.message(F.text == "📥 Експорт бази в Excel")
@router.message(Command("export"))
async def cmd_export(message: Message) -> None:
    recent_items = await db_manager.get_recent_items(limit=200)
    if not recent_items:
        await message.answer(
            "⚠️ База даних порожня. Спочатку запустіть пошук через клавіатуру."
        )
        return

    wait_msg = await message.answer("⏳ Формую Excel-звіт з бази даних...")
    filename = f"db_export_{int(time.time())}.xlsx"
    file_path_str = export_items_to_excel(recent_items, filename=filename)
    file_path = Path(file_path_str)

    try:
        document = FSInputFile(path=file_path, filename=filename)
        await message.answer_document(
            document=document,
            caption=f"📥 Вивантажено останніх <b>{len(recent_items)}</b> оголошень з бази даних.",
        )
        await wait_msg.delete()
    finally:
        if file_path.exists():
            try:
                os.remove(file_path)
            except OSError as err:
                logger.warning("Error deleting temporary file %s: %s", file_path, err)


# --- Сценарій статистики бази даних ---
@router.message(F.text == "📊 Статистика бази")
@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    stats = await db_manager.count_items()
    stats_text = (
        "📊 <b>Статистика збережених оголошень:</b>\n\n"
        f"📦 <b>Всього в базі:</b> {stats.get('total', 0)}\n"
        f"🟠 <b>OLX.ua:</b> {stats.get('olx', 0)}\n"
        f"🟣 <b>Prom.ua:</b> {stats.get('prom', 0)}"
    )
    await message.answer(stats_text)


# --- Головна функція запуску ---
async def main() -> None:
    await db_manager.init_db()

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)

    logger.info("Bot starting polling...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
