import asyncio
import logging
import re
from typing import Optional
from urllib.parse import quote

from bs4 import BeautifulSoup
import httpx

from models import Platform, ProductItem

logger = logging.getLogger(__name__)


class PromScraper:
    """Асинхронний скрейпер товарів для маркетплейсу Prom.ua."""

    def __init__(self, timeout: float = 15.0) -> None:
        """
        Ініціалізація заголовків та налаштувань сесії.
        """
        self.timeout = timeout
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Language": "uk,uk-UA;q=0.9",
            "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Linux"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }

    @staticmethod
    def _clean_price(raw_price: str) -> float:
        """
        Очищення рядка з ціною від пробілів, нерозривних пробілів (\\xa0),
        символів валюти (грн, ₴) та приведення до float.
        """
        if not raw_price:
            return 0.0

        cleaned = (
            raw_price.replace("\xa0", "")
            .replace(" ", "")
            .replace("грн", "")
            .replace("₴", "")
            .replace(",", ".")
            .strip()
        )

        match = re.search(r"(\d+(?:\.\d+)?)", cleaned)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return 0.0
        return 0.0

    @staticmethod
    def _build_search_url(query: str, page: int = 1) -> str:
        """
        Формування URL пошуку Prom.ua за ключовим словом та номером сторінки.
        """
        return f"https://prom.ua/ua/search?search_term={quote(query)}&page={page}"

    async def scrape_page(
        self,
        client: httpx.AsyncClient,
        query: str,
        page: int = 1,
        max_retries: int = 3,
    ) -> list[ProductItem]:
        """
        Завантаження та парсинг однієї сторінки пошукової видачі Prom.ua.
        """
        url = self._build_search_url(query, page)
        logger.info("Scraping Prom.ua page %d for query '%s': %s", page, query, url)

        html_content = ""
        for attempt in range(1, max_retries + 1):
            try:
                response = await client.get(url, headers=self.headers, timeout=self.timeout)
                if response.status_code == 200:
                    html_content = response.text
                    break
                logger.warning(
                    "Unexpected status code %d on attempt %d/%d for URL: %s",
                    response.status_code,
                    attempt,
                    max_retries,
                    url,
                )
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                logger.warning(
                    "Network error on attempt %d/%d for URL %s: %s",
                    attempt,
                    max_retries,
                    url,
                    exc,
                )

            if attempt < max_retries:
                await asyncio.sleep(1.0 * attempt)
            else:
                logger.error("Failed to retrieve URL %s after %d attempts", url, max_retries)
                return []

        if not html_content:
            return []

        soup = BeautifulSoup(html_content, "lxml")
        cards = soup.select('div[data-qaid="product_block"]')
        logger.info("Found %d product cards on page %d", len(cards), page)

        items: list[ProductItem] = []

        for card in cards:
            link_elem = card.select_one('a[data-qaid="product_link"]')
            if not link_elem:
                continue

            # 1. URL
            href = link_elem.get("href", "")
            if href.startswith("/"):
                product_url = f"https://prom.ua{href}"
            else:
                product_url = href

            # 2. External ID & Composite ID
            external_id = card.get("data-product-id")
            if not external_id and product_url:
                id_match = re.search(r"/p(\d+)", product_url)
                if id_match:
                    external_id = id_match.group(1)

            if not external_id:
                logger.debug("Skipping card without identifiable external_id")
                continue

            # 3. Title
            title = link_elem.get("title") or link_elem.get_text(strip=True)
            if not title:
                name_elem = card.select_one('[data-qaid="product_name"]')
                if name_elem:
                    title = name_elem.get_text(strip=True)

            if not title:
                title = "Без назви"

            # 4. Price
            price_elem = card.select_one('[data-qaid="product_price"]')
            if price_elem:
                raw_price = price_elem.get("data-qaprice") or price_elem.get_text(strip=True)
                price = self._clean_price(raw_price)
            else:
                price = 0.0

            # 5. Image URL
            img_elem = card.select_one("img")
            image_url: Optional[str] = None
            if img_elem:
                image_url = (
                    img_elem.get("src")
                    or img_elem.get("data-src")
                    or img_elem.get("data-srcset")
                )
                if image_url and image_url.startswith("//"):
                    image_url = f"https:{image_url}"

            # 6. Location / Seller
            company_elem = (
                card.select_one('a[data-qaid="company_name"]')
                or card.select_one('[data-qaid="company_name"]')
                or card.select_one('[data-qaid="company_link"]')
            )
            location = company_elem.get_text(strip=True) if company_elem else None

            # 7. is_promoted
            promo_elem = card.select_one('[data-qaid="promo_label"]')
            is_promoted = bool(
                promo_elem
                or card.get("data-qa-advtoken")
                or any("pro" in c.lower() for c in card.get("class", []))
            )

            item = ProductItem(
                id=f"prom:{external_id}",
                platform=Platform.PROM,
                external_id=str(external_id),
                title=title,
                price=price,
                currency="UAH",
                url=product_url,
                image_url=image_url,
                location=location,
                is_promoted=is_promoted,
            )
            items.append(item)

        return items

    async def scrape(self, query: str, max_pages: int = 1) -> list[ProductItem]:
        """
        Створення сесії httpx.AsyncClient(http2=True, follow_redirects=True),
        послідовний обхід сторінок із мікропаузою та агрегація результатів.
        """
        all_items: list[ProductItem] = []

        async with httpx.AsyncClient(
            http2=True,
            follow_redirects=True,
            timeout=self.timeout,
        ) as client:
            for page in range(1, max_pages + 1):
                page_items = await self.scrape_page(client, query, page=page)
                all_items.extend(page_items)

                if page < max_pages:
                    await asyncio.sleep(1.2)

        logger.info(
            "Scraping completed for '%s'. Total items collected: %d",
            query,
            len(all_items),
        )
        return all_items
