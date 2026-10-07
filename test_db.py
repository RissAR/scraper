import asyncio
import logging
from pathlib import Path

from config import settings
from database import DatabaseManager
from models import Platform, ProductItem

logger = logging.getLogger(__name__)


async def main() -> None:
    test_db_path = Path("data/test_scraped.db")
    if test_db_path.exists():
        test_db_path.unlink()

    db_manager = DatabaseManager(db_path=test_db_path)

    # 1. Ініціалізація бази даних
    await db_manager.init_db()

    # 2. Створення тестового запису OLX
    test_item = ProductItem(
        platform=Platform.OLX,
        external_id="918301048",
        title="Тестовий товар OLX",
        price=1500.0,
        currency="UAH",
        url="https://www.olx.ua/d/uk/obyavlenie/test-918301048.html",
        image_url="https://img.olx.ua/test.jpg",
        location="Київ",
        is_promoted=False,
    )

    # 3. Первинна вставка - має повернути True
    first_save = await db_manager.save_item(test_item)
    assert first_save is True, "Помилка: новий запис повинен повертати True при вставці"

    # 4. Повторна вставка (дедуплікація) - має повернути False
    duplicate_save = await db_manager.save_item(test_item)
    assert duplicate_save is False, "Помилка: дублікат повинен повертати False"

    # 5. Перевірка батч-вставки з частковим дублікатом
    batch_item_prom = ProductItem(
        platform=Platform.PROM,
        external_id="2763307073",
        title="Тестовий товар Prom",
        price=299.99,
        currency="UAH",
        url="https://prom.ua/p2763307073-test.html",
        location="Львів",
        is_promoted=True,
    )

    added, skipped = await db_manager.save_items_batch([test_item, batch_item_prom])
    assert added == 1, f"Очікувався 1 доданий запис у батчі, отримано {added}"
    assert skipped == 1, f"Очікувався 1 пропущений дублікат у батчі, отримано {skipped}"

    # 6. Зчитування записів
    recent_items = await db_manager.get_recent_items(limit=10)
    assert len(recent_items) == 2, f"Очікувалось 2 записи в БД, знайдено {len(recent_items)}"

    retrieved_olx = next((i for i in recent_items if i.id == test_item.id), None)
    assert retrieved_olx is not None, "Тестовий запис OLX не знайдено в БД"
    assert retrieved_olx.title == test_item.title
    assert retrieved_olx.price == test_item.price
    assert retrieved_olx.platform == Platform.OLX
    assert retrieved_olx.is_promoted is False

    # 7. Фільтрація за платформою
    prom_items = await db_manager.get_recent_items(platform=Platform.PROM)
    assert len(prom_items) == 1
    assert prom_items[0].id == "prom:2763307073"
    assert prom_items[0].is_promoted is True

    # Прибирання тестового файлу БД
    if test_db_path.exists():
        test_db_path.unlink()

    print("DB TEST PASSED")


if __name__ == "__main__":
    asyncio.run(main())
