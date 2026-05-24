"""
handlers.py — обработчики команд Telegram-бота.
"""

import logging
import asyncio
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart, Command
from aiogram.utils.markdown import hbold, hlink

from scraper import search_channels, ChannelResult, _detect_category
from config import MAX_RESULTS, ALLOWED_USERS

router = Router()
logger = logging.getLogger(__name__)


def _check_access(user_id: int) -> bool:
    if not ALLOWED_USERS:
        return True
    return user_id in ALLOWED_USERS


def _format_channel(ch: ChannelResult, index: int) -> str:
    lines = []
    lines.append(f"{index}. {hbold(ch.name)}")
    lines.append(f"👤 {ch.username}  |  👥 {ch.subscribers_fmt()} подписчиков")
    if ch.category:
        lines.append(f"📂 {ch.category}")
    if ch.description:
        desc = ch.description[:120]
        if len(ch.description) > 120:
            desc += "…"
        lines.append(f"📝 {desc}")
    lines.append(f"🔗 {hlink('Открыть канал', ch.tg_link())}")
    return "\n".join(lines)


def _format_results(channels: list[ChannelResult], query: str, category: str | None) -> list[str]:
    if not channels:
        return [
            f"😔 По запросу <b>{query}</b> ничего не найдено.\n\n"
            "Попробуй другое ключевое слово:\n"
            "• маркетинг\n• инфобизнес\n• таргетинг\n• SMM\n• бизнес"
        ]

    messages = []
    cat_info = f" (категория: {category})" if category else ""
    header = (
        f"🔍 Найдено каналов по запросу <b>{query}</b>{cat_info}: {len(channels)}\n"
        f"Фильтр: публичные · от 1 000 подписчиков\n"
        + "─" * 30
    )
    messages.append(header)

    chunk = []
    for i, ch in enumerate(channels, 1):
        chunk.append(_format_channel(ch, i))
        if len(chunk) == 5:
            messages.append("\n\n".join(chunk))
            chunk = []
    if chunk:
        messages.append("\n\n".join(chunk))

    return messages


@router.message(CommandStart())
async def cmd_start(message: Message):
    if not _check_access(message.from_user.id):
        return
    text = (
        "👋 <b>Channel Finder</b> — поиск Telegram-каналов для рекламы\n\n"
        "<b>Как использовать:</b>\n"
        "/search маркетинг\n"
        "/search таджвид\n"
        "/search фитнес\n\n"
        "Или просто напиши ключевое слово.\n\n"
        "Бот автоматически определяет категорию и ищет релевантные каналы.\n"
        "/categories — посмотреть все категории"
    )
    await message.answer(text)


@router.message(Command("categories"))
async def cmd_categories(message: Message):
    if not _check_access(message.from_user.id):
        return
    text = (
        "📂 <b>Поддерживаемые категории</b>\n\n"
        "🎯 <b>Маркетинг & PR</b>\n"
        "   маркетинг, реклама, таргет, SMM, digital, контент, продвижение\n\n"
        "💼 <b>Бизнес & финансы</b>\n"
        "   бизнес, продажи, заработок, финансы, стартап\n\n"
        "📚 <b>Образование & Книги</b>\n"
        "   инфобиз, курс, обучение, образование\n\n"
        "💻 <b>Технологии & IT</b>\n"
        "   SEO, нейросети, AI, программирование, python\n\n"
        "🕌 <b>Религия</b>\n"
        "   ислам, коран, таджвид, молитва, православие\n\n"
        "💪 <b>Спорт</b>\n"
        "   спорт, фитнес\n\n"
        "✈️ <b>Путешествия</b>\n"
        "   путешествия, туризм\n\n"
        "🍕 <b>Еда & Кулинария</b>\n"
        "   кулинария, рецепты, еда\n\n"
        "И ещё 15+ категорий — просто пиши любое слово!"
    )
    await message.answer(text)


@router.message(Command("help"))
async def cmd_help(message: Message):
    if not _check_access(message.from_user.id):
        return
    text = (
        "📖 <b>Справка</b>\n\n"
        "/search [запрос] — поиск каналов\n"
        "/categories — список категорий\n"
        "/help — эта справка\n\n"
        f"Минимум подписчиков: 1 000\n"
        f"Максимум результатов: {MAX_RESULTS}"
    )
    await message.answer(text)


@router.message(Command("search"))
async def cmd_search(message: Message):
    if not _check_access(message.from_user.id):
        return
    query = message.text.removeprefix("/search").strip()
    if not query:
        await message.answer("❓ Укажи запрос. Пример: /search маркетинг")
        return
    await _do_search(message, query)


@router.message(F.text & ~F.text.startswith("/"))
async def msg_search(message: Message):
    if not _check_access(message.from_user.id):
        return
    query = message.text.strip()
    if len(query) < 2:
        return
    await _do_search(message, query)


async def _do_search(message: Message, query: str):
    category = _detect_category(query)
    cat_hint = f" в категории <b>{category}</b>" if category else ""
    wait_msg = await message.answer(f"🔍 Ищу каналы{cat_hint}...")

    try:
        loop = asyncio.get_event_loop()
        channels = await loop.run_in_executor(
            None, search_channels, query, MAX_RESULTS
        )
        await wait_msg.delete()

        messages = _format_results(channels, query, category)
        for msg_text in messages:
            await message.answer(msg_text, disable_web_page_preview=True)
            await asyncio.sleep(0.3)

    except Exception as e:
        logger.error(f"Ошибка поиска '{query}': {e}")
        await wait_msg.edit_text("❌ Ошибка при поиске. Попробуй снова.")
