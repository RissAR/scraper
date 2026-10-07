import logging
from pathlib import Path
from typing import Optional

import aiosqlite

from config import settings
from models import Platform, ProductItem

logger = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self, db_path: Path | str = settings.DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    async def init_db(self) -> None:
        """Створює таблицю items та відповідні індекси, якщо вони відсутні."""
        logger.info("Initializing database at: %s", self.db_path)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS items (
                    id TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    price REAL NOT NULL,
                    currency TEXT NOT NULL,
                    url TEXT NOT NULL,
                    image_url TEXT,
                    location TEXT,
                    is_promoted INTEGER NOT NULL DEFAULT 0,
                    scraped_at TEXT NOT NULL
                );
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_items_platform ON items(platform);"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_items_scraped_at ON items(scraped_at);"
            )
            await db.commit()
        logger.info("Database initialized successfully at: %s", self.db_path)

    async def save_item(self, item: ProductItem) -> bool:
        """
        Вставляє запис за методом INSERT OR IGNORE.
        Повертає True, якщо запис новий (додано), і False, якщо дублікат (пропущено).
        """
        sql = """
        INSERT OR IGNORE INTO items (
            id, platform, external_id, title, price, currency,
            url, image_url, location, is_promoted, scraped_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        platform_val = item.platform.value if isinstance(item.platform, Platform) else str(item.platform)
        params = (
            item.id,
            platform_val,
            item.external_id,
            item.title,
            item.price,
            item.currency,
            item.url,
            item.image_url,
            item.location,
            1 if item.is_promoted else 0,
            item.scraped_at.isoformat(),
        )

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(sql, params)
            await db.commit()
            is_inserted = cursor.rowcount > 0

        if is_inserted:
            logger.info("Inserted new item [%s] (%s): '%s'", item.id, platform_val, item.title)
        else:
            logger.info("Duplicate detected, skipped item [%s]", item.id)

        return is_inserted

    async def save_items_batch(self, items: list[ProductItem]) -> tuple[int, int]:
        """
        Батч-вставка записів.
        Повертає кортеж (додано_нових, пропущено_дублікатів).
        """
        if not items:
            return 0, 0

        sql = """
        INSERT OR IGNORE INTO items (
            id, platform, external_id, title, price, currency,
            url, image_url, location, is_promoted, scraped_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        params_list = [
            (
                item.id,
                item.platform.value if isinstance(item.platform, Platform) else str(item.platform),
                item.external_id,
                item.title,
                item.price,
                item.currency,
                item.url,
                item.image_url,
                item.location,
                1 if item.is_promoted else 0,
                item.scraped_at.isoformat(),
            )
            for item in items
        ]

        async with aiosqlite.connect(self.db_path) as db:
            initial_changes = db.total_changes
            await db.executemany(sql, params_list)
            await db.commit()
            added = db.total_changes - initial_changes

        skipped = len(items) - added
        logger.info(
            "Batch execution finished: %d added, %d skipped out of %d total",
            added,
            skipped,
            len(items),
        )
        return added, skipped

    async def get_recent_items(
        self, limit: int = 50, platform: Optional[Platform] = None
    ) -> list[ProductItem]:
        """
        Отримання останніх записів із сортуванням DESC за scraped_at.
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            if platform:
                platform_val = platform.value if isinstance(platform, Platform) else str(platform)
                query = "SELECT * FROM items WHERE platform = ? ORDER BY scraped_at DESC LIMIT ?"
                cursor = await db.execute(query, (platform_val, limit))
            else:
                query = "SELECT * FROM items ORDER BY scraped_at DESC LIMIT ?"
                cursor = await db.execute(query, (limit,))

            rows = await cursor.fetchall()

        items: list[ProductItem] = [ProductItem(**dict(row)) for row in rows]
        logger.info(
            "Retrieved %d recent items (platform=%s, limit=%d)",
            len(items),
            platform.value if platform else "ALL",
            limit,
        )
        return items
