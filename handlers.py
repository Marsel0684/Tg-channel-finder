"""
handlers.py — обработчики команд Telegram-бота.
"""

import logging
import asyncio
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart, Command
from aiogram.utils.markdown import hbold, hlink

from scraper import search_channels, ChannelResult
from config import MAX_RESULTS, ALLOWED_USERS

router = Router()
logger = logging.getLogger(__name__)


def _check_access(user_id: int) -> bool:
    if not ALLOWED_USERS:
        return True  # открытый доступ
    return user_id in ALLOWED_USERS


def _format_channel(ch: ChannelResult, index: int) -> str:
    """Форматируем одну карточку канала."""
    lines = []
    lines.append(f"{index}. {hbold(ch.name)}")
    lines.append(f"👤 {ch.username}  |  👥 {ch.subscribers_fmt()} подписчиков")
    if ch.category:
        lines.append(f"📂 {ch.category}")
    if ch.description:
        lines.append(f"📝 {ch.description[:120]}{'…' if len(ch.description) > 120 else ''}")
    lines.append(f"🔗 {hlink('Открыть канал', ch.tg_link())}")
    return "\n".join(lines)


def _format_results(channels: list[ChannelResult], query: str) -> list[str]:
    """
    Разбиваем результаты на сообщения по 5 каналов
    (Telegram лимит ~4096 символов на сообщение).
    """
    if not channels:
        return [
            f"😔 По запросу <b>{query}</b> ничего не найдено.\n\n"
            "Попробуй другое ключевое слово, например:\n"
            "• маркетинг\n• инфобизнес\n• таргетинг\n• SMM"
        ]

    messages = []
    header = f"🔍 Найдено каналов по запросу <b>{query}</b>: {len(channels)}\n"
    header += f"Фильтр: публичные · от 1 000 подписчиков\n"
    header += "─" * 30
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


# ── Команды ───────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message):
    if not _check_access(message.from_user.id):
        return

    text = (
        "👋 <b>Channel Finder</b> — поиск Telegram-каналов для рекламы\n\n"
        "Как использовать:\n"
        "🔍 /search маркетинг\n"
        "🔍 /search инфобиз\n"
        "🔍 /search таргетинг\n\n"
        "Или просто напиши ключевое слово в чат.\n\n"
        "Фильтры: <b>публичные каналы · от 1 000 подписчиков</b>\n"
        "Источники: tgsearch.org, telemetr.me"
    )
    await message.answer(text)


@router.message(Command("help"))
async def cmd_help(message: Message):
    if not _check_access(message.from_user.id):
        return

    text = (
        "📖 <b>Справка</b>\n\n"
        "<b>Команды:</b>\n"
        "/search [запрос] — поиск каналов\n"
        "/help — эта справка\n\n"
        "<b>Примеры запросов:</b>\n"
        "• /search маркетинг\n"
        "• /search инфобизнес\n"
        "• /search таргетинг instagram\n"
        "• /search SMM агентство\n"
        "• /search бизнес курсы\n\n"
        "<b>Что показывает бот:</b>\n"
        "• Название и @username канала\n"
        "• Количество подписчиков\n"
        "• Описание\n"
        "• Прямую ссылку\n\n"
        f"Минимум подписчиков: 1 000\n"
        f"Максимум результатов: {MAX_RESULTS}"
    )
    await message.answer(text)


@router.message(Command("search"))
async def cmd_search(message: Message):
    if not _check_access(message.from_user.id):
        return

    # Извлекаем запрос из команды: /search маркетинг
    query = message.text.removeprefix("/search").strip()

    if not query:
        await message.answer(
            "❓ Укажи запрос после команды.\n"
            "Пример: /search маркетинг"
        )
        return

    await _do_search(message, query)


@router.message(F.text & ~F.text.startswith("/"))
async def msg_search(message: Message):
    """Просто текст без команды — тоже ищем."""
    if not _check_access(message.from_user.id):
        return

    query = message.text.strip()
    if len(query) < 2:
        return

    await _do_search(message, query)


# ── Логика поиска ─────────────────────────────────────────

async def _do_search(message: Message, query: str):
    # Показываем что бот работает
    wait_msg = await message.answer(f"🔍 Ищу каналы по запросу <b>{query}</b>...")

    try:
        # Парсинг в отдельном потоке (не блокируем event loop)
        loop = asyncio.get_event_loop()
        channels = await loop.run_in_executor(
            None, search_channels, query, MAX_RESULTS
        )

        # Удаляем сообщение-ожидание
        await wait_msg.delete()

        # Отправляем результаты по частям
        messages = _format_results(channels, query)
        for msg_text in messages:
            await message.answer(msg_text, disable_web_page_preview=True)
            await asyncio.sleep(0.3)  # небольшая пауза между сообщениями

    except Exception as e:
        logger.error(f"Ошибка поиска '{query}': {e}")
        await wait_msg.edit_text(
            "❌ Произошла ошибка при поиске. Попробуй снова."
        )


@router.message(Command("categories"))
async def cmd_categories(message: Message):
    if not _check_access(message.from_user.id):
        return

    text = (
        "📂 <b>Категории для поиска</b>\n\n"
        "Бот автоматически подбирает категорию по запросу:\n\n"
        "🎯 <b>маркетинг / реклама / таргет / SMM</b>\n"
        "   → Маркетинг & PR\n\n"
        "💼 <b>бизнес / продажи / заработок</b>\n"
        "   → Бизнес & финансы\n\n"
        "📚 <b>инфобиз / курс / обучение</b>\n"
        "   → Образование & Книги\n\n"
        "🤖 <b>нейросети / AI / digital / SEO</b>\n"
        "   → Технологии & IT + Маркетинг & PR\n\n"
        "Просто пиши запрос — категория подберётся сама!"
    )
    await message.answer(text)
