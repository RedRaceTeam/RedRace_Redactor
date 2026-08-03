import asyncio
import logging
import os
import re
from datetime import datetime

import feedparser
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv
from openai import AsyncOpenAI
from newsfetch.news import Newspaper
from apscheduler.schedulers.asyncio import AsyncIOScheduler

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
CHANNEL_ID = os.getenv("CHANNEL_ID")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== ИНИЦИАЛИЗАЦИЯ ==========
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

openai_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# ========== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ==========
pending_posts = {}
CURRENT_MODEL = "openrouter/free"  # по умолчанию авто-роутер

# Список доступных моделей
AVAILABLE_MODELS = {
    "openrouter/free": "🚀 Авто (OpenRouter)",
    "nvidia/nemotron-3-ultra:free": "🧠 Nemotron Ultra (код, логика)",
    "nvidia/nemotron-3-super:free": "⚡ Nemotron Super (быстрый, 12B)",
    "tencent/hy3:free": "🐧 Tencent HY3 (логика, 21B)",
    "deepseek/deepseek-r1:free": "🤖 DeepSeek R1 (рассуждающая)",
    "qwen/qwen3-next-80b-a3b-instruct:free": "🐉 Qwen 3 Next (креатив)",
    "google/gemma-4-31b:free": "🧪 Gemma 4 (живой язык)",
}

# RSS-источники
RSS_SOURCES = [
    "https://www.f1news.ru/export/news.xml",
    "https://www.autosport.com/rss/feeds/f1",
    "https://www.bbc.com/sport/formula1/rss.xml",
    "https://www.grandprix247.com/feed",
    "https://www.gpblog.com/en/feed",
    "https://www.championat.com/rss/news/auto.xml",
]

scheduler = AsyncIOScheduler(timezone="UTC")

# ========== FSM ==========
class EditPost(StatesGroup):
    waiting_for_text = State()

# ========== ХЕЛПЕРЫ ==========
def clean_html(text):
    return re.sub(r'<[^>]+>', '', text)

def format_post(entry):
    title = clean_html(entry.title)
    summary = clean_html(entry.summary[:500] + "..." if len(entry.summary) > 500 else entry.summary)
    link = entry.link
    return f"<b>{title}</b>\n\n{summary}\n\n<a href='{link}'>Читать полностью</a>"

def get_buttons(post_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"publish_{post_id}"),
            InlineKeyboardButton(text="✏️ Рерайт", callback_data=f"rewrite_{post_id}"),
        ],
        [
            InlineKeyboardButton(text="❌ Пропустить", callback_data=f"skip_{post_id}"),
        ]
    ])

def get_model_buttons():
    """Клавиатура для выбора модели"""
    buttons = []
    for model_id, label in AVAILABLE_MODELS.items():
        # помечаем текущую модель
        is_current = model_id == CURRENT_MODEL
        text = f"{'✅ ' if is_current else ''}{label}"
        buttons.append([InlineKeyboardButton(text=text, callback_data=f"setmodel_{model_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ========== ПАРСИНГ RSS И СТАТЕЙ ==========
async def fetch_full_article(url: str) -> str:
    try:
        article = Newspaper(url)
        full_text = article.article
        if full_text and len(full_text) > 100:
            return full_text
        else:
            return None
    except Exception as e:
        logger.error(f"Ошибка парсинга {url}: {e}")
        return None

async def fetch_all_feeds():
    news = []
    for url in RSS_SOURCES:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]:
                link = entry.link
                full_text = await fetch_full_article(link)
                summary = full_text if full_text else (entry.summary[:250] if 'summary' in entry else '')
                news.append({
                    'title': entry.title,
                    'summary': summary,
                    'link': link,
                    'source': feed.feed.title if 'title' in feed.feed else 'Неизвестный'
                })
                await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"RSS error {url}: {e}")
    return news[:10]

# ========== AI ФУНКЦИИ ==========
async def ai_rewrite(text):
    try:
        response = await openai_client.chat.completions.create(
            model=CURRENT_MODEL,
            messages=[
                {"role": "system", "content": "Ты — редактор. Перепиши новость короче, интереснее, с эмодзи. Без маркдауна."},
                {"role": "user", "content": text}
            ],
            max_tokens=300
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"AI error: {e}")
        return text

async def translate_text(text):
    try:
        response = await openai_client.chat.completions.create(
            model=CURRENT_MODEL,
            messages=[
                {"role": "system", "content": "Ты — переводчик. Переведи следующий текст на русский язык. Сохрани смысл и терминологию Формулы-1. Не добавляй лишнего."},
                {"role": "user", "content": text}
            ],
            max_tokens=500
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Translation error: {e}")
        return text

# ========== КОМАНДЫ ==========
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 <b>Нико — AI-редактор RedRace</b>\n\n"
        "📰 <b>/news</b> — найти и опубликовать новости\n"
        "❓ <b>/ask</b> — задать вопрос ИИ\n"
        "📊 <b>/status</b> — статус бота\n"
        "🧠 <b>/model</b> — текущая модель ИИ\n"
        "🔧 <b>/admin</b> — админ-панель\n"
        "⚖️ <b>/legal</b> — юридическая информация"
    )

@dp.message(Command("model"))
async def cmd_model(message: Message):
    current_label = AVAILABLE_MODELS.get(CURRENT_MODEL, CURRENT_MODEL)
    await message.answer(f"🧠 Текущая модель: <b>{current_label}</b>")

@dp.message(Command("legal"))
async def cmd_legal(message: Message):
    legal_text = """
<b>Юридическая информация</b>

Разработчик: <b>P4/9 Dev</b>
Бот: <b>Nico™</b>

Данный бот и его контент не являются официальными и не имеют никакого отношения к Формуле-1, ее руководству, командам, пилотам или любым аффилированным лицам.

Все материалы предоставлены на основе открытых источников и не нарушают авторских прав.

© 2026 P4/9 Dev. Все права защищены.
"""
    await message.answer(legal_text, parse_mode="HTML")

@dp.message(Command("status"))
async def cmd_status(message: Message):
    current_label = AVAILABLE_MODELS.get(CURRENT_MODEL, CURRENT_MODEL)
    await message.answer(
        f"🤖 <b>Статус Нико</b>\n\n"
        f"📰 Постов в очереди: {len(pending_posts)}\n"
        f"📡 RSS источников: {len(RSS_SOURCES)}\n"
        f"🧠 Модель: {current_label}\n"
        f"🔄 Расписание: каждые 3 часа"
    )

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Доступ запрещён.")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📰 Проверить RSS", callback_data="admin_check_rss")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🔄 Очистить очередь", callback_data="admin_clear")],
        [InlineKeyboardButton(text="🧠 Сменить модель", callback_data="admin_show_models")],
    ])
    await message.answer("🔧 Админ-панель", reply_markup=keyboard)

@dp.message(Command("news"))
async def cmd_news(message: Message):
    await message.answer("📡 Сканирую RSS и собираю полные статьи...")
    posts = await fetch_all_feeds()
    if not posts:
        await message.answer("❌ Свежих новостей нет.")
        return
    for idx, post in enumerate(posts[:8]):
        post_id = f"post_{idx}_{datetime.now().timestamp()}"
        pending_posts[post_id] = post
        text = f"📰 <b>{post['title']}</b>\n\n{post['summary'][:300]}...\n\nИсточник: {post['source']}"
        await message.answer(text, reply_markup=get_buttons(post_id))
    await message.answer("✅ Новости загружены. Выберите действие.")

@dp.message(Command("ask"))
async def cmd_ask(message: Message):
    await message.answer("🧠 Задайте вопрос. Я отвечу через ИИ.")

@dp.message(lambda msg: not msg.text.startswith('/') and msg.text)
async def handle_question(message: Message):
    try:
        response = await openai_client.chat.completions.create(
            model=CURRENT_MODEL,
            messages=[{"role": "user", "content": message.text}]
        )
        await message.reply(response.choices[0].message.content)
    except Exception as e:
        await message.reply(f"⚠️ Ошибка: {e}")

# ========== КОЛБЭКИ ==========
@dp.callback_query(lambda c: c.data.startswith("publish_"))
async def publish_post(callback: CallbackQuery):
    post_id = callback.data.split("_")[1]
    await callback.answer()
    post = pending_posts.pop(post_id, None)
    if not post:
        await callback.message.edit_text("⏳ Эта новость уже была обработана.")
        return
    await bot.send_message(CHANNEL_ID, format_post(post), parse_mode="HTML")
    await callback.message.delete()

@dp.callback_query(lambda c: c.data.startswith("rewrite_"))
async def rewrite_post(callback: CallbackQuery):
    post_id = callback.data.split("_")[1]
    post = pending_posts.get(post_id)
    if not post:
        await callback.answer("Новость не найдена.", show_alert=True)
        return
    await callback.answer("🔄 Переписываю...")
    new_text = await ai_rewrite(post['summary'])
    post['summary'] = new_text
    await callback.message.edit_text(
        f"✏️ <b>Рерайт:</b>\n\n{new_text[:500]}...\n\nИсточник: {post['source']}",
        reply_markup=get_buttons(post_id)
    )

@dp.callback_query(lambda c: c.data.startswith("skip_"))
async def skip_post(callback: CallbackQuery):
    post_id = callback.data.split("_")[1]
    await callback.answer()
    post = pending_posts.pop(post_id, None)
    if not post:
        await callback.message.edit_text("⏳ Эта новость уже была пропущена.")
        return
    await callback.message.delete()

@dp.callback_query(lambda c: c.data.startswith("admin_"))
async def admin_callbacks(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    action = callback.data.split("_")[1]
    if action == "check_rss":
        await callback.answer("📡 Проверяю RSS...")
        posts = await fetch_all_feeds()
        if not posts:
            await callback.message.answer("❌ Новостей нет.")
            return
        for post in posts[:3]:
            await callback.message.answer(f"📰 {post['title']}\n{post['summary'][:150]}...")
        await callback.message.answer("✅ RSS работает.")
    elif action == "stats":
        await callback.answer(f"📊 В очереди: {len(pending_posts)}", show_alert=True)
    elif action == "clear":
        pending_posts.clear()
        await callback.answer("🗑️ Очередь очищена.", show_alert=True)
    elif action == "show_models":
        await callback.message.answer("🧠 <b>Выберите модель ИИ:</b>", reply_markup=get_model_buttons())
        await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("setmodel_"))
async def set_model(callback: CallbackQuery):
    global CURRENT_MODEL
    model_id = callback.data.replace("setmodel_", "")
    if model_id in AVAILABLE_MODELS:
        CURRENT_MODEL = model_id
        await callback.answer(f"✅ Модель изменена на {AVAILABLE_MODELS[model_id]}")
        # обновляем сообщение с кнопками, чтобы отметить текущую
        await callback.message.edit_text(
            f"✅ Текущая модель: <b>{AVAILABLE_MODELS[model_id]}</b>\n\nВыберите другую:",
            reply_markup=get_model_buttons()
        )
    else:
        await callback.answer("⚠️ Модель не найдена.", show_alert=True)

# ========== АВТО-ПУБЛИКАЦИЯ ==========
async def auto_publish():
    logger.info("🔄 Авто-публикация...")
    posts = await fetch_all_feeds()
    if not posts:
        return
    for post in posts[:2]:
        await bot.send_message(CHANNEL_ID, format_post(post), parse_mode="HTML")
        logger.info(f"✅ Опубликовано: {post['title']}")

scheduler.add_job(auto_publish, 'interval', hours=3)
scheduler.start()

# ========== ЗАПУСК ==========
async def main():
    logger.info("🚀 Нико запущен!")
    await dp.start_polling(bot)

from aiohttp import web

async def health_check(request):
    """Заглушка для Render. Просто отвечает 'OK'."""
    return web.Response(text="OK", status=200)

async def start_web_server():
    """Запускает веб-сервер на порту 8000, чтобы Render не перезапускал бота."""
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)  # Многие сервисы проверяют /health
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8000)
    await site.start()
    print("✅ Веб-сервер-заглушка запущен на порту 8000")

# Запускаем веб-сервер в фоне (не блокирует бота)
loop = asyncio.get_event_loop()
loop.create_task(start_web_server())

if __name__ == "__main__":
    asyncio.run(main())
