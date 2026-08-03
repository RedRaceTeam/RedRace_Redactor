import asyncio
import logging
import os
import re
from datetime import datetime
import feedparser
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv
from openai import AsyncOpenAI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiohttp import web

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

AGNES_API_KEY = os.getenv("AGNES_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# ========== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ==========
CURRENT_PROVIDER = "agnes"  # agnes или openrouter
AVAILABLE_MODELS = {
    "agnes": {
        "name": "Agnes AI",
        "models": ["agnes-2.5-flash", "agnes-2.0-flash"],
        "default": "agnes-2.5-flash"
    },
    "openrouter": {
        "name": "OpenRouter",
        "models": ["openrouter/free", "deepseek/deepseek-r1:free", "google/gemini-2.0-flash-thinking:free"],
        "default": "openrouter/free"
    }
}

# ========== AI-КЛИЕНТЫ ==========
clients = {}
if AGNES_API_KEY:
    clients["agnes"] = AsyncOpenAI(base_url="https://api.agnes.ai/v1", api_key=AGNES_API_KEY)
if OPENROUTER_API_KEY:
    clients["openrouter"] = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)

def get_current_model():
    """Возвращает текущую модель для выбранного провайдера"""
    provider = AVAILABLE_MODELS[CURRENT_PROVIDER]
    return provider["default"]

async def call_ai(prompt, system_prompt, max_tokens=300):
    """Вызывает AI через текущего провайдера"""
    provider_name = CURRENT_PROVIDER
    provider = AVAILABLE_MODELS.get(provider_name)
    client = clients.get(provider_name)
    model = provider["default"] if provider else None
    
    if not client or not model:
        return None
    
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            max_tokens=max_tokens,
            timeout=30.0
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"AI error ({provider_name}): {e}")
        return None

# ========== RSS-СБОРЩИК ==========
RSS_SOURCES = [
    "https://autosport.com.ru/rss",
    "https://www.f1news.ru/export/news.xml",
    "https://www.championat.com/rss/news/auto.xml",
]

async def fetch_news():
    news = []
    for url in RSS_SOURCES:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]:
                news.append({
                    "title": entry.title,
                    "summary": entry.summary[:350] if "summary" in entry else entry.description[:350] if "description" in entry else "",
                    "link": entry.link,
                    "source": feed.feed.title if "title" in feed.feed else "Неизвестный"
                })
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"RSS error {url}: {e}")
    return news[:8]

SYSTEM_PROMPT = """Ты — Нико, редактор новостей и голос канала RedRace. 
Ты пишешь коротко, ёмко, с драйвом. Используй эмодзи (1-2 на пост). 
Без воды, без маркдауна. Только факты и контекст. 
Ты — голос RedRace. Создан командой P4/9."""

async def format_news_for_channel(news_item):
    prompt = f"Перепиши эту новость в стиле RedRace:\n\n{news_item['title']}\n{news_item['summary']}"
    ai_text = await call_ai(prompt, SYSTEM_PROMPT, 300)
    if ai_text:
        return ai_text
    else:
        return f"📰 {news_item['title']}\n\n{news_item['summary']}\n\n<a href='{news_item['link']}'>Читать полностью</a>"

# ========== КНОПКИ ДЛЯ СМЕНЫ МОДЕЛИ ==========
def get_model_buttons():
    buttons = []
    for key, provider in AVAILABLE_MODELS.items():
        is_current = key == CURRENT_PROVIDER
        label = f"{'✅ ' if is_current else ''}{provider['name']}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"setmodel_{key}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ========== КОМАНДЫ ==========
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 <b>Нико — AI-редактор RedRace</b>\n\n"
        "Разработан командой <b>P4/9</b>.\n\n"
        "📰 /news — найти и опубликовать новости\n"
        "📊 /status — статус бота\n"
        "🔧 /admin — админ-панель\n"
        "⚖️ /legal — юридическая информация"
    )

@dp.message(Command("news"))
async def cmd_news(message: Message):
    await message.answer("📡 Собираю новости...")
    news = await fetch_news()
    if not news:
        await message.answer("❌ Свежих новостей нет.")
        return
    for item in news[:3]:
        text = await format_news_for_channel(item)
        await bot.send_message(CHANNEL_ID, text, parse_mode="HTML")
        await asyncio.sleep(0.5)
    await message.answer("✅ Новости опубликованы в канале!")

@dp.message(Command("status"))
async def cmd_status(message: Message):
    current_provider = AVAILABLE_MODELS[CURRENT_PROVIDER]["name"]
    current_model = get_current_model()
    await message.answer(
        f"🤖 <b>Статус Нико</b>\n\n"
        f"🧠 Текущий AI: <b>{current_provider}</b>\n"
        f"📦 Модель: <code>{current_model}</code>\n"
        f"📡 RSS источников: {len(RSS_SOURCES)}\n"
        f"🔄 Авто-публикация: каждые 2 часа"
    )

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Доступ запрещён.")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧠 Сменить AI-модель", callback_data="admin_show_models")],
        [InlineKeyboardButton(text="📰 Опубликовать сейчас", callback_data="admin_publish_now")],
    ])
    await message.answer("🔧 <b>Админ-панель</b>", reply_markup=keyboard)

@dp.message(Command("legal"))
async def cmd_legal(message: Message):
    await message.answer(
        "<b>Юридическая информация</b>\n\n"
        "Бот: <b>Нико</b> — голос канала <b>RedRace</b>\n"
        "Разработчик: <b>P4/9 Dev</b>\n\n"
        "Данный бот и его контент не являются официальными и не имеют отношения к Формуле-1.\n"
        "Все материалы предоставлены на основе открытых источников.\n\n"
        "© 2026 P4/9 Dev. Все права защищены.",
        parse_mode="HTML"
    )

# ========== КОЛБЭКИ ==========
@dp.callback_query(lambda c: c.data.startswith("admin_"))
async def admin_callbacks(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    
    action = callback.data.split("_")[1]
    if action == "show_models":
        await callback.message.edit_text(
            "🧠 <b>Выберите AI-провайдера:</b>",
            reply_markup=get_model_buttons()
        )
        await callback.answer()
    elif action == "publish_now":
        await callback.answer("📡 Публикую...")
        news = await fetch_news()
        if not news:
            await callback.message.answer("❌ Свежих новостей нет.")
            return
        for item in news[:3]:
            text = await format_news_for_channel(item)
            await bot.send_message(CHANNEL_ID, text, parse_mode="HTML")
            await asyncio.sleep(0.5)
        await callback.message.answer("✅ Новости опубликованы!")
    else:
        await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("setmodel_"))
async def set_model(callback: CallbackQuery):
    global CURRENT_PROVIDER
    provider_key = callback.data.replace("setmodel_", "")
    if provider_key in AVAILABLE_MODELS:
        CURRENT_PROVIDER = provider_key
        provider_name = AVAILABLE_MODELS[provider_key]["name"]
        model_name = AVAILABLE_MODELS[provider_key]["default"]
        await callback.answer(f"✅ Переключено на {provider_name} ({model_name})")
        await callback.message.edit_text(
            f"✅ <b>Текущий AI: {provider_name}</b>\n"
            f"📦 Модель: <code>{model_name}</code>\n\n"
            "Выберите другого провайдера:",
            reply_markup=get_model_buttons()
        )
    else:
        await callback.answer("⚠️ Провайдер не найден.", show_alert=True)

# ========== АВТО-ПУБЛИКАЦИЯ ==========
async def auto_publish():
    logger.info("🔄 Авто-публикация...")
    news = await fetch_news()
    if not news:
        return
    for item in news[:2]:
        text = await format_news_for_channel(item)
        await bot.send_message(CHANNEL_ID, text, parse_mode="HTML")
        logger.info(f"✅ Опубликовано: {item['title']}")
        await asyncio.sleep(0.5)

scheduler = AsyncIOScheduler(timezone="UTC")
scheduler.add_job(auto_publish, 'interval', hours=2)
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
    await asyncio.Event().wait()

async def main():
    asyncio.create_task(start_web_server())
    logger.info("🚀 Нико запущен!")
    await dp.start_polling(bot, timeout=120)

if __name__ == "__main__":
    asyncio.run(main())
