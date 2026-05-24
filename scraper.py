"""
scraper.py — парсинг каталогов Telegram-каналов.
Источники: tgsearch.org, telemetr.me
"""

import logging
import re
import httpx
from bs4 import BeautifulSoup
from dataclasses import dataclass, field
from config import MIN_SUBSCRIBERS

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
}


@dataclass
class ChannelResult:
    name: str
    username: str          # @handle
    subscribers: int
    description: str
    category: str = ""
    source: str = ""
    url: str = ""

    def tg_link(self) -> str:
        return f"https://t.me/{self.username.lstrip('@')}"

    def subscribers_fmt(self) -> str:
        if self.subscribers >= 1_000_000:
            return f"{self.subscribers / 1_000_000:.1f}M"
        if self.subscribers >= 1_000:
            return f"{self.subscribers / 1_000:.1f}K"
        return str(self.subscribers)


def _parse_subscribers(text: str) -> int:
    """'1.2M' → 1200000, '15.3K' → 15300, '9.02M' → 9020000"""
    text = text.strip().upper().replace(",", ".").replace(" ", "")
    try:
        if "M" in text:
            return int(float(text.replace("M", "")) * 1_000_000)
        if "K" in text:
            return int(float(text.replace("K", "")) * 1_000)
        return int(re.sub(r"[^\d]", "", text))
    except Exception:
        return 0


# ── tgsearch.org ──────────────────────────────────────────

def search_tgsearch(query: str, page: int = 1) -> list[ChannelResult]:
    """Поиск каналов на tgsearch.org."""
    url = f"https://tgsearch.org/search?query={query}&page={page}"
    results: list[ChannelResult] = []

    try:
        resp = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
        if resp.status_code != 200:
            logger.warning(f"[tgsearch] HTTP {resp.status_code}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")

        # Каждый канал — блок с классом содержащим channel/item
        cards = soup.find_all("div", class_=re.compile(r"channel|item|card", re.I))

        # Если не нашли через классы — ищем через структуру ссылок
        if not cards:
            cards = soup.find_all("li") or soup.find_all("article")

        for card in cards:
            try:
                # Имя канала
                name_el = card.find(["h2", "h3", "strong", "b"])
                name = name_el.get_text(strip=True) if name_el else ""
                if not name:
                    continue

                # Username (@handle)
                username = ""
                for a in card.find_all("a", href=True):
                    href = a["href"]
                    if "t.me/" in href:
                        username = "@" + href.split("t.me/")[-1].strip("/")
                        break
                    if href.startswith("@"):
                        username = href
                        break

                # Ищем @username в тексте карточки если не нашли в href
                if not username:
                    text_content = card.get_text()
                    match = re.search(r"@([\w_]{3,32})", text_content)
                    if match:
                        username = "@" + match.group(1)

                if not username:
                    continue

                # Подписчики
                subs_text = ""
                for el in card.find_all(["span", "div", "li"]):
                    t = el.get_text(strip=True)
                    if re.search(r"\d+[\.,]?\d*[KМMkм]?", t) and len(t) < 15:
                        subs_text = t
                        break

                subscribers = _parse_subscribers(subs_text) if subs_text else 0

                # Описание
                desc_el = card.find("p")
                description = desc_el.get_text(strip=True)[:200] if desc_el else ""

                # Категория
                cat_el = card.find("a", href=re.compile(r"search\?query=|category|cat"))
                category = cat_el.get_text(strip=True) if cat_el else ""

                results.append(ChannelResult(
                    name=name,
                    username=username,
                    subscribers=subscribers,
                    description=description,
                    category=category,
                    source="tgsearch.org",
                    url=f"https://t.me/{username.lstrip('@')}",
                ))

            except Exception as e:
                logger.debug(f"Ошибка парсинга карточки: {e}")
                continue

        logger.info(f"[tgsearch] '{query}': найдено {len(results)} каналов")

    except Exception as e:
        logger.error(f"[tgsearch] Ошибка: {e}")

    return results


# ── telemetr.me ───────────────────────────────────────────

def search_telemetr(query: str) -> list[ChannelResult]:
    """Поиск каналов на telemetr.me."""
    url = f"https://telemetr.me/search?q={query}&type=channel"
    results: list[ChannelResult] = []

    try:
        resp = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
        if resp.status_code != 200:
            logger.warning(f"[telemetr] HTTP {resp.status_code}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")

        # Ищем карточки каналов
        cards = soup.find_all("div", class_=re.compile(r"channel|card|item|result", re.I))
        if not cards:
            cards = soup.find_all("a", href=re.compile(r"/channel/|@"))

        for card in cards:
            try:
                text = card.get_text(separator=" ", strip=True)

                # Username
                username = ""
                for a in card.find_all("a", href=True):
                    if "t.me/" in a["href"]:
                        username = "@" + a["href"].split("t.me/")[-1].strip("/")
                        break
                match = re.search(r"@([\w_]{3,32})", text)
                if not username and match:
                    username = "@" + match.group(1)
                if not username:
                    continue

                # Имя
                name_el = card.find(["h2", "h3", "h4", "strong"])
                name = name_el.get_text(strip=True) if name_el else username

                # Подписчики
                subs_match = re.search(r"([\d\s]+[,.]?\d*\s*[KkМMмm]?)\s*(подписчик|subscriber|чел)", text, re.I)
                subscribers = _parse_subscribers(subs_match.group(1)) if subs_match else 0

                # Описание
                desc_el = card.find("p")
                description = desc_el.get_text(strip=True)[:200] if desc_el else ""

                results.append(ChannelResult(
                    name=name,
                    username=username,
                    subscribers=subscribers,
                    description=description,
                    source="telemetr.me",
                    url=f"https://t.me/{username.lstrip('@')}",
                ))
            except Exception:
                continue

        logger.info(f"[telemetr] '{query}': найдено {len(results)} каналов")

    except Exception as e:
        logger.error(f"[telemetr] Ошибка: {e}")

    return results


# ── Главная функция поиска ────────────────────────────────

def search_channels(query: str, max_results: int = 15) -> list[ChannelResult]:
    """
    Собираем результаты со всех источников,
    фильтруем и сортируем по подписчикам.
    """
    all_results: list[ChannelResult] = []

    # Собираем с обоих источников
    all_results.extend(search_tgsearch(query, page=1))
    all_results.extend(search_tgsearch(query, page=2))
    all_results.extend(search_telemetr(query))

    # Дедупликация по username
    seen: set[str] = set()
    unique: list[ChannelResult] = []
    for ch in all_results:
        key = ch.username.lower().lstrip("@")
        if key and key not in seen:
            seen.add(key)
            unique.append(ch)

    # Фильтр: публичный (есть @username) + минимум подписчиков
    filtered = [
        ch for ch in unique
        if ch.subscribers >= MIN_SUBSCRIBERS
        and ch.username
        and not ch.username.startswith("@+")  # исключаем invite-ссылки
    ]

    # Сортировка по убыванию подписчиков
    filtered.sort(key=lambda x: x.subscribers, reverse=True)

    logger.info(
        f"Поиск '{query}': всего {len(all_results)} → "
        f"уникальных {len(unique)} → после фильтра {len(filtered)}"
    )

    return filtered[:max_results]
