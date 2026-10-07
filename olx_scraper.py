import asyncio
import logging
from typing import Any, Optional

import httpx

from models import Platform, ProductItem

logger = logging.getLogger(__name__)


class OLXScraper:
    """Асинхронний модуль скрейпінгу оголошень із маркетплейсу OLX.ua."""

    API_URL = "https://www.olx.ua/api/v1/offers/"

    def __init__(self, timeout: float = 15.0) -> None:
        """
        Ініціалізація та налаштування заголовків браузера та таймаутів.
        """
        self.timeout = timeout
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
            "Referer": "https://www.olx.ua/",
            "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Linux"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

    def _parse_item(self, raw: dict[str, Any]) -> Optional[ProductItem]:
        """
        Безпечний мапінг сирих даних оголошення OLX у модель ProductItem.
        """
        external_id = str(raw.get("id", "")).strip()
        if not external_id:
            logger.debug("Skipping ad without id: %s", raw)
            return None

        title = raw.get("title") or "Без назви"
        url = raw.get("url") or ""

        # 1. Екстракція ціни та валюти
        price = 0.0
        currency = "UAH"

        params = raw.get("params")
        if isinstance(params, list):
            for param in params:
                if isinstance(param, dict) and param.get("key") == "price":
                    val_dict = param.get("value")
                    if isinstance(val_dict, dict):
                        raw_val = val_dict.get("value")
                        if raw_val is not None:
                            try:
                                price = float(raw_val)
                            except (ValueError, TypeError):
                                price = 0.0
                        currency = str(val_dict.get("currency") or "UAH")
                    elif val_dict is not None:
                        try:
                            price = float(val_dict)
                        except (ValueError, TypeError):
                            price = 0.0
                    break

        if price == 0.0 and raw.get("price") is not None:
            try:
                price = float(raw["price"])
            except (ValueError, TypeError):
                price = 0.0

        # 2. Екстракція зображення
        image_url: Optional[str] = None
        photos = raw.get("photos")
        if isinstance(photos, list) and photos:
            first_photo = photos[0]
            if isinstance(first_photo, dict):
                raw_link = first_photo.get("link", "")
                if raw_link:
                    width = first_photo.get("width") or 800
                    height = first_photo.get("height") or 600
                    image_url = raw_link.replace("{width}x{height}", f"{width}x{height}")
                elif first_photo.get("url"):
                    image_url = str(first_photo["url"])

        # 3. Екстракція локації (місто / область)
        loc_obj = raw.get("location")
        location: Optional[str] = None
        if isinstance(loc_obj, dict):
            city_dict = loc_obj.get("city")
            region_dict = loc_obj.get("region")
            city = city_dict.get("name") if isinstance(city_dict, dict) else None
            region = region_dict.get("name") if isinstance(region_dict, dict) else None
            location = city or region

        # 4. Визначення статусу промоції/топу
        promo = raw.get("promotion")
        is_promoted = bool(
            raw.get("is_promoted")
            or raw.get("promoted")
            or raw.get("highlight")
            or (
                isinstance(promo, dict)
                and (promo.get("top_ad") or promo.get("highlighted") or promo.get("urgent"))
            )
        )

        return ProductItem(
            id=f"olx:{external_id}",
            platform=Platform.OLX,
            external_id=external_id,
            title=title,
            price=price,
            currency=currency,
            url=url,
            image_url=image_url,
            location=location,
            is_promoted=is_promoted,
        )

    async def scrape_page(
        self,
        client: httpx.AsyncClient,
        query: str,
        offset: int = 0,
        limit: int = 40,
        max_retries: int = 3,
    ) -> list[ProductItem]:
        """
        Асинхронний запит до API OLX, безпечний парсинг JSON-відповіді та мапінг у ProductItem.
        """
        params = {
            "query": query,
            "offset": offset,
            "limit": limit,
        }
        logger.info(
            "Scraping OLX API: query='%s', offset=%d, limit=%d",
            query,
            offset,
            limit,
        )

        for attempt in range(1, max_retries + 1):
            try:
                response = await client.get(
                    self.API_URL,
                    params=params,
                    headers=self.headers,
                    timeout=self.timeout,
                )

                if response.status_code == 200:
                    data = response.json()
                    raw_items = data.get("data", []) if isinstance(data, dict) else []
                    logger.info("Retrieved %d raw items from OLX API", len(raw_items))

                    items: list[ProductItem] = []
                    for raw in raw_items:
                        if isinstance(raw, dict):
                            item = self._parse_item(raw)
                            if item:
                                items.append(item)
                    return items

                logger.warning(
                    "Unexpected status %d on attempt %d/%d for OLX API (query='%s', offset=%d)",
                    response.status_code,
                    attempt,
                    max_retries,
                    query,
                    offset,
                )
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                logger.warning(
                    "Network error on attempt %d/%d for OLX API: %s",
                    attempt,
                    max_retries,
                    exc,
                )

            if attempt < max_retries:
                await asyncio.sleep(1.0 * attempt)
            else:
                logger.error(
                    "Failed to retrieve OLX data for query '%s' offset %d after %d attempts",
                    query,
                    offset,
                    max_retries,
                )

        return []

    async def scrape(self, query: str, max_pages: int = 1) -> list[ProductItem]:
        """
        Ініціалізація сесії httpx, обхід сторінок за offset із мікропаузами та агрегація результатів.
        """
        limit = 40
        all_items: list[ProductItem] = []

        async with httpx.AsyncClient(
            http2=True,
            follow_redirects=True,
            timeout=self.timeout,
        ) as client:
            for page_index in range(max_pages):
                offset = page_index * limit
                page_items = await self.scrape_page(
                    client=client,
                    query=query,
                    offset=offset,
                    limit=limit,
                )
                all_items.extend(page_items)

                if page_index + 1 < max_pages:
                    await asyncio.sleep(1.2)

        logger.info(
            "OLX scraping finished for query '%s'. Total items collected: %d",
            query,
            len(all_items),
        )
        return all_items
