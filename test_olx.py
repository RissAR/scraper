import asyncio
import logging

from database import DatabaseManager
from olx_scraper import OLXScraper

logger = logging.getLogger(__name__)


async def main() -> None:
    scraper = OLXScraper(timeout=15.0)
    query = "зимова куртка"

    logger.info("Starting OLX.ua scraper test with query: '%s'", query)
    items = await scraper.scrape(query=query, max_pages=1)

    assert len(items) > 0, "Отриманий список оголошень OLX порожній!"

    # Ініціалізація БД та збереження батчу
    db_manager = DatabaseManager()
    await db_manager.init_db()

    added, skipped = await db_manager.save_items_batch(items)

    print("\n--- Перші 3 спарсені оголошення OLX ---")
    for i, item in enumerate(items[:3], start=1):
        print(f"{i}. ID: {item.id}")
        print(f"   Назва: {item.title}")
        print(f"   Ціна: {item.price} {item.currency}")
        print(f"   Місто/Локація: {item.location}")
        print(f"   URL: {item.url}")
        print(f"   Реклама (ТОП): {item.is_promoted}")
        print()

    print(f"Додано нових записів у БД: {added}, пропущено дублікатів: {skipped}")
    print("OLX SCRAPER TEST PASSED")


if __name__ == "__main__":
    asyncio.run(main())
