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
from newspaper import Article
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiohttp import web

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
CHANNEL_ID = os.getenv("CHANNEL_ID")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

openai_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

pending_posts = {}
CURRENT_MODEL = "openrouter/free"

AVAILABLE_MODELS = {
    "openrouter/free": "🚀 Авто (OpenRouter)",
    "nvidia/nemotron-3-ultra:free": "🧠 Nemotron Ultra",
    "deepseek/deepseek-r1:free": "🤖 DeepSeek R1",
    "qwen/qwen-3-7b:free": "🐉 Qwen 3",
    "google/gemini-2.0-flash-thinking:free": "⚡ Gemini Flash",
}

RSS_SOURCES = [
    "https://www.f1news.ru/export/news.xml",
    "https://www.autosport.com/rss/feeds/f1",
    "https://www.bbc.com/sport/formula1/rss.xml",
    "https://www.grandprix247.com/feed",
    "https://www.gpblog.com/en/feed",
]

scheduler = AsyncIOScheduler(timezone="UTC")

class EditPost(StatesGroup):
    waiting_for_text = State()

def clean_html(text):
    return re.sub(r'<[^>]+>', '', text)

def format_post(entry):
    title = clean_html(entry.title)
    summary = clean_html(entry.summary[:500] + "..." if len(entry.summary) > 500 else entry.summary)
    link = entry.link
    return f"<b>{title}</b>\n\n{summary}\n\n<a href='{link}'>Читать полностью</a>"

def get_buttons(post_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"publish_{post_id}"),
         InlineKeyboardButton(text="✏️ Рерайт", callback_data=f"rewrite_{post_id}")],
        [InlineKeyboardButton(text="❌ Пропустить", callback_data=f"skip_{post_id}")]
    ])

def get_model_buttons():
    buttons = []
    for model_id, label in AVAILABLE_MODELS.items():
        is_current = model_id == CURRENT_MODEL
        text = f"{'✅ ' if is_current else ''}{label}"
        buttons.append([InlineKeyboardButton(text=text, callback_data=f"setmodel_{model_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def fetch_full_article(url: str) -> str:
    try:
        article = Article(url)
        article.download()
        article.parse()
        return article.text[:500] if article.text else None
    except Exception as e:
        logger.error(f"Ошибка парсинга {url}: {e}")
        return None

async def fetch_all_feeds():
    news = []
    for url in RSS_SOURCES:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]:
                full_text = await fetch_full_article(entry.link)
                news.append({
                    'title': entry.title,
                    'summary': full_text if full_text else entry.summary[:250] if 'summary' in entry else '',
                    'link': entry.link,
                    'source': feed.feed.title if 'title' in feed.feed else 'Неизвестный'
                })
                await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"RSS error {url}: {e}")
    return news[:10]

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
                {"role": "system", "content": "Ты — переводчик. Переведи текст на русский. Сохрани смысл и терминологию F1."},
                {"role": "user", "content": text}
            ],
            max_tokens=500
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Translation error: {e}")
        return text

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 <b>Нико — AI-редактор RedRace</b>\n\n"
        "📰 /news — найти новости\n"
        "❓ /ask — спросить ИИ\n"
        "📊 /status — статус\n"
        "🧠 /model — текущая модель\n"
        "🔧 /admin — админ-панель\n"
        "⚖️ /legal — юр. информация"
    )

@dp.message(Command("model"))
async def cmd_model(message: Message):
    current_label = AVAILABLE_MODELS.get(CURRENT_MODEL, CURRENT_MODEL)
    await message.answer(f"🧠 Текущая модель: <b>{current_label}</b>")

@dp.message(Command("legal"))
async def cmd_legal(message: Message):
    await message.answer(
        "<b>Юридическая информация</b>\n\n"
        "Разработчик: <b>P4/9 Dev</b>\n"
        "Бот: <b>Nico™</b>\n\n"
        "Данный бот и его контент не являются официальными и не имеют отношения к Формуле-1.\n"
        "Все материалы предоставлены на основе открытых источников.\n\n"
        "© 2026 P4/9 Dev. Все права защищены.",
        parse_mode="HTML"
    )

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
    await message.answer("📡 Сканирую RSS...")
    posts = await fetch_all_feeds()
    if not posts:
        await message.answer("❌ Свежих новостей нет.")
        return
    for idx, post in enumerate(posts[:8]):
        post_id = f"post_{idx}_{datetime.now().timestamp()}"
        pending_posts[post_id] = post
        text = f"📰 <b>{post['title']}</b>\n\n{post['summary'][:300]}...\n\nИсточник: {post['source']}"
        await message.answer(text, reply_markup=get_buttons(post_id))
    await message.answer("✅ Новости загружены.")

@dp.message(Command("ask"))
async def cmd_ask(message: Message):
    await message.answer("🧠 Задайте вопрос.")

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

@dp.callback_query(lambda c: c.data.startswith("publish_"))
async def publish_post(callback: CallbackQuery):
    post_id = callback.data.split("_")[1]
    await callback.answer()
    post = pending_posts.pop(post_id, None)
    if not post:
        await callback.message.edit_text("⏳ Новость уже обработана.")
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
        await callback.message.edit_text("⏳ Новость уже пропущена.")
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

# ========== ЗАГЛУШКА ДЛЯ RENDER ==========
async def health_check(request):
    return web.Response(text="OK", status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8000)
    await site.start()
    print("✅ Веб-сервер-заглушка запущен на порту 8000")

loop = asyncio.get_event_loop()
loop.create_task(start_web_server())

# ========== ЗАПУСК БОТА ==========
async def main():
    logger.info("🚀 Нико запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
