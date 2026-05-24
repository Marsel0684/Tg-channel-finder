"""
scraper.py — поиск Telegram-каналов через tgsearch.org
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

# ── Категории tgsearch.org ────────────────────────────────
# Ключ = что ищет пользователь, значение = категория на tgsearch
CATEGORY_MAP: dict[str, str] = {
    "маркетинг":     "Маркетинг & PR",
    "реклама":       "Маркетинг & PR",
    "таргет":        "Маркетинг & PR",
    "таргетинг":     "Маркетинг & PR",
    "smm":           "Маркетинг & PR",
    "pr":            "Маркетинг & PR",
    "пиар":          "Маркетинг & PR",
    "digital":       "Маркетинг & PR",
    "диджитал":      "Маркетинг & PR",
    "копирайт":      "Маркетинг & PR",
    "контент":       "Маркетинг & PR",
    "продвижение":   "Маркетинг & PR",
    "инфобиз":       "Образование & Книги",
    "инфобизнес":    "Образование & Книги",
    "курс":          "Образование & Книги",
    "обучение":      "Образование & Книги",
    "образование":   "Образование & Книги",
    "бизнес":        "Бизнес & финансы",
    "заработок":     "Бизнес & финансы",
    "продажи":       "Бизнес & финансы",
    "финансы":       "Бизнес & финансы",
    "предприниматель": "Бизнес & финансы",
    "стартап":       "Бизнес & финансы",
    "seo":           "Технологии & IT",
    "нейросет":      "Технологии & IT",
    "нейросеть":     "Технологии & IT",
    "ai":            "Технологии & IT",
    "программир":    "Технологии & IT",
    "python":        "Технологии & IT",
    "блогер":        "Блогеры",
    "блог":          "Блогеры",
    "youtube":       "Блогеры",
    "ютуб":          "Блогеры",
    "instagram":     "Инстаграм",
    "инстаграм":     "Инстаграм",
    "здоровье":      "Здоровье & Медицина",
    "медицин":       "Здоровье & Медицина",
    "спорт":         "Спорт",
    "фитнес":        "Спорт",
    "игр":           "Игры",
    "gaming":        "Игры",
    "крипт":         "Криптовалюты",
    "crypto":        "Криптовалюты",
    "новост":        "Новости & СМИ",
    "дизайн":        "Дизайн",
    "юмор":          "Юмор & Мемы",
    "мем":           "Юмор & Мемы",
    "психолог":      "Психология",
    "ислам":         "Религия",
    "коран":         "Религия",
    "таджвид":       "Религия",
    "молитв":        "Религия",
    "мусульман":     "Религия",
    "православ":     "Религия",
    "христиан":      "Религия",
    "путешеств":     "Путешествия",
    "туризм":        "Путешествия",
    "кулинар":       "Еда & Кулинария",
    "рецепт":        "Еда & Кулинария",
    "еда":           "Еда & Кулинария",
    "мода":          "Мода & Красота",
    "красота":       "Мода & Красота",
    "авто":          "Авто & Мото",
    "машин":         "Авто & Мото",
    "недвижим":      "Недвижимость",
    "квартир":       "Недвижимость",
}


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


def _parse_page(html: str) -> list[ChannelResult]:
    """Парсим одну страницу tgsearch.org."""
    soup = BeautifulSoup(html, "html.parser")
    results = []

    for h2 in soup.find_all("h2"):
        try:
            name = h2.get_text(strip=True)
            if not name or len(name) < 2:
                continue

            parent = h2.find_parent(["div", "section", "article", "li"])
            if not parent:
                continue

            block_text = parent.get_text(separator="\n", strip=True)

            # Username
            username = ""
            for a in parent.find_all("a", href=True):
                if "t.me/" in a["href"]:
                    slug = a["href"].split("t.me/")[-1].strip("/")
                    if slug and "+" not in slug and len(slug) >= 3:
                        username = "@" + slug
                        break
            if not username:
                m = re.search(r"@([\w_]{3,32})", block_text)
                if m:
                    username = "@" + m.group(1)
            if not username:
                continue

            # Подписчики
            subs = 0
            m = re.search(r"([\d]+[.,]?[\d]*\s*[KkМMмm])", block_text)
            if m:
                subs = _parse_subscribers(m.group(1))

            # Описание
            desc = ""
            p = parent.find("p")
            if p:
                desc = p.get_text(strip=True)[:200]

            # Категория
            cat = ""
            for a in parent.find_all("a", href=re.compile(r"query=")):
                t = a.get_text(strip=True)
                if t and t != name:
                    cat = t
                    break

            results.append(ChannelResult(
                name=name,
                username=username,
                subscribers=subs,
                description=desc,
                category=cat,
                source="tgsearch.org",
            ))
        except Exception as e:
            logger.debug(f"Ошибка карточки: {e}")
            continue

    return results


def _fetch(query: str, page: int = 1) -> list[ChannelResult]:
    """Один запрос к tgsearch.org."""
    url = f"https://tgsearch.org/search?query={query}&page={page}"
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
        if resp.status_code != 200:
            return []
        items = _parse_page(resp.text)
        logger.info(f"[tgsearch] '{query}' стр.{page}: {len(items)}")
        return items
    except Exception as e:
        logger.error(f"[tgsearch] '{query}': {e}")
        return []


def _detect_category(query: str) -> str | None:
    """Определяем категорию по ключевым словам в запросе."""
    q = query.lower()
    for keyword, category in CATEGORY_MAP.items():
        if keyword in q:
            return category
    return None


def search_channels(query: str, max_results: int = 30) -> list[ChannelResult]:
    """
    Поиск каналов.
    Логика:
      1. Определяем категорию по запросу
      2. Если категория найдена — ищем В КАТЕГОРИИ (релевантные результаты)
      3. Параллельно ищем по ключевому слову
      4. Фильтруем по подписчикам и сортируем
    """
    all_results: list[ChannelResult] = []
    seen: set[str] = set()

    def add(items: list[ChannelResult]):
        for ch in items:
            key = ch.username.lower().lstrip("@")
            if key and key not in seen:
                seen.add(key)
                all_results.append(ch)

    category = _detect_category(query)

    if category:
        # Режим категории: ищем В категории (главный источник)
        logger.info(f"Запрос '{query}' → категория '{category}'")
        for page in range(1, 6):
            items = _fetch(category, page)
            if not items:
                break
            add(items)
    else:
        # Нет категории — ищем по ключевому слову, несколько страниц
        logger.info(f"Запрос '{query}' → поиск по слову")
        for page in range(1, 6):
            items = _fetch(query, page)
            if not items:
                break
            add(items)

    # Всегда добавляем поиск по самому слову для полноты
    for page in range(1, 4):
        items = _fetch(query, page)
        if not items:
            break
        add(items)

    # Фильтр и сортировка
    filtered = [
        ch for ch in all_results
        if ch.subscribers >= MIN_SUBSCRIBERS
        and ch.username
        and "+" not in ch.username
    ]
    filtered.sort(key=lambda x: x.subscribers, reverse=True)

    logger.info(f"'{query}': всего {len(all_results)} → {len(filtered)} после фильтра")
    return filtered[:max_results]
