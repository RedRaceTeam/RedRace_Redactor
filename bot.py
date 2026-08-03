import asyncio
import logging
import os
import re
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import feedparser
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv
from openai import AsyncOpenAI

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

scheduler = AsyncIOScheduler(timezone="UTC")

# Хранилище постов на модерации
pending_posts = {}

# RSS-источники
RSS_SOURCES = [
    "https://www.f1news.ru/export/news.xml",
    "https://www.autosport.com/rss/feeds/f1",
    "https://www.bbc.com/sport/formula1/rss.xml",
    "https://www.grandprix247.com/feed",
    "https://www.gpblog.com/en/feed",
]

# ========== FSM ==========
class EditPost(StatesGroup):
    waiting_for_text = State()

# ========== ХЕЛПЕРЫ ==========
def clean_html(text):
    return re.sub(r'<[^>]+>', '', text)

def format_post(entry):
    title = clean_html(entry.title)
    summary = clean_html(entry.summary[:250] + "..." if len(entry.summary) > 250 else entry.summary)
    link = entry.link
    return f"<b>{title}</b>\n\n{summary}\n\n<a href='{link}'>Читать полностью</a>"

def get_buttons(post_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"publish_{post_id}"),
            InlineKeyboardButton(text="✏️ Рерайт", callback_data=f"rewrite_{post_id}"),
        ],
        [InlineKeyboardButton(text="❌ Пропустить", callback_data=f"skip_{post_id}")]
    ])

async def fetch_all_feeds():
    """Парсит все RSS-источники"""
    news = []
    for url in RSS_SOURCES:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]:
                link = entry.link
                news.append({
                    'title': entry.title,
                    'summary': entry.summary[:250] if 'summary' in entry else entry.description[:250],
                    'link': link,
                    'source': feed.feed.title if 'title' in feed.feed else 'Неизвестный'
                })
        except Exception as e:
            logger.error(f"RSS error {url}: {e}")
    return news[:10]

async def ai_rewrite(text):
    """Переписывает текст через AI (бесплатная модель)"""
    try:
        response = await openai_client.chat.completions.create(
            model="z-ai/glm-4.7-flash:free",
            messages=[
                {"role": "system", "content": "Ты — редактор. Перепиши новость короче, интереснее, с эмодзи. Без маркдауна."},
                {"role": "user", "content": text}
            ],
            max_tokens=200
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"AI error: {e}")
        return text

async def auto_publish():
    """Авто-публикация в канал (раз в 3 часа)"""
    logger.info("🔄 Авто-публикация...")
    posts = await fetch_all_feeds()
    if not posts:
        return
    for post in posts[:2]:
        await bot.send_message(CHANNEL_ID, format_post(post), parse_mode="HTML")
        logger.info(f"✅ Опубликовано: {post['title']}")

# ========== КОМАНДЫ ==========
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 <b>Нико — AI-редактор RedRace</b>\n\n"
        "📰 /news — найти и опубликовать новости\n"
        "❓ /ask — задать вопрос ИИ\n"
        "📊 /status — статус бота\n"
        "🔧 /admin — админ-панель"
    )

@dp.message(Command("status"))
async def cmd_status(message: Message):
    await message.answer(
        f"🤖 <b>Статус Нико</b>\n\n"
        f"📰 Постов в очереди: {len(pending_posts)}\n"
        f"📡 RSS источников: {len(RSS_SOURCES)}\n"
        f"🧠 AI модель: z-ai/glm-4.7-flash:free\n"
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
    ])
    await message.answer("🔧 Админ-панель", reply_markup=keyboard)

@dp.message(Command("news"))
async def cmd_news(message: Message):
    await message.answer("📡 Сканирую RSS...")
    posts = await fetch_all_feeds()
    if not posts:
        await message.answer("❌ Свежих новостей нет.")
        return
    for idx, post in enumerate(posts[:8]):
        post_id = f"post_{idx}_{datetime.now().timestamp()}"
        pending_posts[post_id] = post
        text = f"📰 <b>{post['title']}</b>\n\n{post['summary'][:200]}...\n\nИсточник: {post['source']}"
        await message.answer(text, reply_markup=get_buttons(post_id))
    await message.answer("✅ Новости загружены. Выберите действие.")

@dp.message(Command("ask"))
async def cmd_ask(message: Message):
    await message.answer("🧠 Задайте вопрос. Я отвечу через ИИ.")

@dp.message(lambda msg: not msg.text.startswith('/') and msg.text)
async def handle_question(message: Message):
    try:
        response = await openai_client.chat.completions.create(
            model="z-ai/glm-4.7-flash:free",
            messages=[{"role": "user", "content": message.text}]
        )
        await message.reply(response.choices[0].message.content)
    except Exception as e:
        await message.reply(f"⚠️ Ошибка: {e}")

# ========== КОЛБЭКИ ==========
@dp.callback_query(lambda c: c.data.startswith("publish_"))
async def publish_post(callback: CallbackQuery):
    post_id = callback.data.split("_")[1]
    post = pending_posts.pop(post_id, None)
    if not post:
        await callback.answer("Новость уже обработана.", show_alert=True)
        return
    await bot.send_message(CHANNEL_ID, format_post(post), parse_mode="HTML")
    await callback.answer("✅ Опубликовано!")
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
        f"✏️ <b>Рерайт:</b>\n\n{new_text}\n\nИсточник: {post['source']}",
        reply_markup=get_buttons(post_id)
    )

@dp.callback_query(lambda c: c.data.startswith("skip_"))
async def skip_post(callback: CallbackQuery):
    post_id = callback.data.split("_")[1]
    pending_posts.pop(post_id, None)
    await callback.answer("Пропущено.")
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

# ========== ЗАПУСК ==========
async def main():
    scheduler.add_job(auto_publish, 'interval', hours=3)
    scheduler.start()
    logger.info("✅ Планировщик запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
