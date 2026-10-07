import asyncio
import logging

from database import DatabaseManager
from prom_scraper import PromScraper

logger = logging.getLogger(__name__)


async def main() -> None:
    scraper = PromScraper(timeout=15.0)
    query = "зимова куртка"

    logger.info("Starting Prom.ua scraper test with query: '%s'", query)
    items = await scraper.scrape(query=query, max_pages=1)

    assert len(items) > 0, "Отриманий список товарів порожній!"

    # Ініціалізація БД та збереження батчу
    db_manager = DatabaseManager()
    await db_manager.init_db()

    added, skipped = await db_manager.save_items_batch(items)

    print("\n--- Перші 3 спарсені товари ---")
    for i, item in enumerate(items[:3], start=1):
        print(f"{i}. Назва: {item.title}")
        print(f"   Ціна: {item.price} {item.currency}")
        print(f"   URL: {item.url}")
        print(f"   Магазин/Локація: {item.location}")
        print(f"   Реклама: {item.is_promoted}")
        print()

    print(f"Додано нових записів у БД: {added}, пропущено дублікатів: {skipped}")
    print("PROM SCRAPER TEST PASSED")


if __name__ == "__main__":
    asyncio.run(main())
