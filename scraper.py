"""
scraper.py — парсинг tgsearch.org по категориям + ключевым словам.
"""

import logging
import re
import httpx
from bs4 import BeautifulSoup
from dataclasses import dataclass
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

# ── Карта: ключевые слова → категории tgsearch.org ────────
# При поиске бот автоматически добавляет нужные категории
KEYWORD_TO_CATEGORIES: dict[str, list[str]] = {
    "маркетинг":        ["Маркетинг & PR", "Бизнес & финансы"],
    "реклама":          ["Маркетинг & PR", "Бизнес & финансы"],
    "таргет":           ["Маркетинг & PR"],
    "таргетинг":        ["Маркетинг & PR"],
    "smm":              ["Маркетинг & PR", "Блогеры"],
    "инфобиз":          ["Образование & Книги", "Бизнес & финансы"],
    "инфобизнес":       ["Образование & Книги", "Бизнес & финансы"],
    "курс":             ["Образование & Книги"],
    "обучение":         ["Образование & Книги"],
    "бизнес":           ["Бизнес & финансы"],
    "заработок":        ["Бизнес & финансы"],
    "продажи":          ["Бизнес & финансы", "Маркетинг & PR"],
    "контент":          ["Маркетинг & PR", "Блогеры"],
    "telegram":         ["Маркетинг & PR"],
    "телеграм":         ["Маркетинг & PR"],
    "digital":          ["Маркетинг & PR"],
    "диджитал":         ["Маркетинг & PR"],
    "seo":              ["Маркетинг & PR", "Технологии & IT"],
    "копирайт":         ["Маркетинг & PR"],
    "нейросет":         ["Технологии & IT", "Маркетинг & PR"],
    "ai":               ["Технологии & IT"],
}

# Категории по умолчанию если ключевое слово не найдено в карте
DEFAULT_CATEGORIES = ["Маркетинг & PR", "Бизнес & финансы"]


@dataclass
class ChannelResult:
    name: str
    username: str
    subscribers: int
    description: str
    category: str = ""
    source: str = ""

    def tg_link(self) -> str:
        return f"https://t.me/{self.username.lstrip('@')}"

    def subscribers_fmt(self) -> str:
        if self.subscribers >= 1_000_000:
            return f"{self.subscribers / 1_000_000:.1f}M"
        if self.subscribers >= 1_000:
            return f"{self.subscribers / 1_000:.1f}K"
        return str(self.subscribers)


def _parse_subscribers(text: str) -> int:
    text = text.strip().upper().replace(",", ".").replace("\xa0", "").replace(" ", "")
    try:
        if "M" in text or "М" in text:
            num = re.sub(r"[^\d.]", "", text)
            return int(float(num) * 1_000_000)
        if "K" in text or "К" in text:
            num = re.sub(r"[^\d.]", "", text)
            return int(float(num) * 1_000)
        digits = re.sub(r"[^\d]", "", text)
        return int(digits) if digits else 0
    except Exception:
        return 0


def _parse_page(html: str, source_label: str) -> list[ChannelResult]:
    """Парсим одну страницу tgsearch.org."""
    soup = BeautifulSoup(html, "html.parser")
    results = []

    # Каждый канал — секция с заголовком h2 и списком ul
    for h2 in soup.find_all("h2"):
        try:
            # Имя канала
            name = h2.get_text(strip=True)
            if not name or len(name) < 2:
                continue

            # Родительский блок
            parent = h2.find_parent(["div", "section", "article", "li"])
            if not parent:
                continue

            block_text = parent.get_text(separator="\n", strip=True)

            # Username — ищем @handle в блоке
            username = ""
            username_match = re.search(r"@([\w_]{3,32})", block_text)
            if username_match:
                username = "@" + username_match.group(1)

            # Ищем в ссылках t.me/
            if not username:
                for a in parent.find_all("a", href=True):
                    if "t.me/" in a["href"]:
                        slug = a["href"].split("t.me/")[-1].strip("/")
                        if slug and "+" not in slug:
                            username = "@" + slug
                            break

            if not username:
                continue

            # Подписчики — ищем паттерн числа с K/M
            subs = 0
            subs_match = re.search(
                r"([\d]+[.,]?[\d]*\s*[KkМMмm])",
                block_text
            )
            if subs_match:
                subs = _parse_subscribers(subs_match.group(1))

            # Описание — параграф внутри блока
            desc = ""
            p = parent.find("p")
            if p:
                desc = p.get_text(strip=True)[:200]

            # Категория — ссылка с query=
            cat = ""
            for a in parent.find_all("a", href=re.compile(r"query=")):
                cat_text = a.get_text(strip=True)
                if cat_text and cat_text != name:
                    cat = cat_text
                    break

            results.append(ChannelResult(
                name=name,
                username=username,
                subscribers=subs,
                description=desc,
                category=cat,
                source=source_label,
            ))

        except Exception as e:
            logger.debug(f"Ошибка карточки: {e}")
            continue

    return results


def _fetch_tgsearch(query: str, page: int = 1) -> list[ChannelResult]:
    """Один запрос к tgsearch.org."""
    url = f"https://tgsearch.org/search?query={query}&page={page}"
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
        if resp.status_code != 200:
            logger.warning(f"[tgsearch] HTTP {resp.status_code} для '{query}' стр.{page}")
            return []
        results = _parse_page(resp.text, "tgsearch.org")
        logger.info(f"[tgsearch] '{query}' стр.{page}: {len(results)} каналов")
        return results
    except Exception as e:
        logger.error(f"[tgsearch] Ошибка '{query}': {e}")
        return []


def _get_categories_for_query(query: str) -> list[str]:
    """Определяем какие категории добавить к поиску."""
    query_lower = query.lower()
    categories = []
    for keyword, cats in KEYWORD_TO_CATEGORIES.items():
        if keyword in query_lower:
            for c in cats:
                if c not in categories:
                    categories.append(c)
    if not categories:
        categories = DEFAULT_CATEGORIES
    return categories


def search_channels(query: str, max_results: int = 30) -> list[ChannelResult]:
    """
    Главная функция поиска.
    Ищет по ключевому слову + по релевантным категориям,
    парсит несколько страниц, фильтрует и сортирует.
    """
    all_results: list[ChannelResult] = []
    seen_usernames: set[str] = set()

    def add_results(items: list[ChannelResult]):
        for ch in items:
            key = ch.username.lower().lstrip("@")
            if key and key not in seen_usernames:
                seen_usernames.add(key)
                all_results.append(ch)

    # 1. Поиск по ключевому слову (5 страниц)
    for page in range(1, 6):
        items = _fetch_tgsearch(query, page)
        if not items:
            break
        add_results(items)

    # 2. Поиск по категориям (3 страницы каждая)
    categories = _get_categories_for_query(query)
    for category in categories:
        for page in range(1, 4):
            items = _fetch_tgsearch(category, page)
            if not items:
                break
            add_results(items)

    logger.info(f"Всего уникальных до фильтра: {len(all_results)}")

    # Фильтр: публичный канал + минимум подписчиков
    filtered = [
        ch for ch in all_results
        if ch.subscribers >= MIN_SUBSCRIBERS
        and ch.username
        and not ch.username.startswith("@+")
    ]

    # Сортировка по подписчикам
    filtered.sort(key=lambda x: x.subscribers, reverse=True)

    logger.info(
        f"Поиск '{query}': {len(all_results)} → "
        f"после фильтра {len(filtered)} → возвращаем {min(len(filtered), max_results)}"
    )

    return filtered[:max_results]
