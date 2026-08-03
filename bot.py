import asyncio
import logging
import os
import re
from datetime import datetime
import feedparser
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv
from openai import AsyncOpenAI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiohttp import web

# Готовая библиотека для новостей
# pip install f1-blog-pipeline
try:
    from f1_blog_pipeline import RSSReader, PostGenerator
    USE_PIPELINE = True
except ImportError:
    USE_PIPELINE = False
    logging.warning("f1-blog-pipeline не установлена, используем встроенный RSS-парсер")

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# AI-ключи (без Ofox)
AGNES_API_KEY = os.getenv("AGNES_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# ========== AI-РОУТЕР (Agnes AI → OpenRouter) ==========
class AIRouter:
    def __init__(self):
        self.providers = []
        
        if AGNES_API_KEY:
            self.providers.append({
                "name": "Agnes AI",
                "client": AsyncOpenAI(base_url="https://api.agnes.ai/v1", api_key=AGNES_API_KEY),
                "model": "agnes-2.5-flash"
            })
        if OPENROUTER_API_KEY:
            self.providers.append({
                "name": "OpenRouter",
                "client": AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY),
                "model": "openrouter/free"
            })
    
    async def call(self, prompt, system_prompt, max_tokens=300):
        for provider in self.providers:
            try:
                response = await provider["client"].chat.completions.create(
                    model=provider["model"],
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=max_tokens,
                    timeout=20.0
                )
                result = response.choices[0].message.content
                logger.info(f"✅ {provider['name']} ответил")
                return result
            except Exception as e:
                logger.warning(f"⚠️ {provider['name']} не ответил: {e}")
                continue
        return None

ai = AIRouter()

# ========== НОВОСТНОЙ ДВИЖОК ==========
RSS_SOURCES = [
    "https://autosport.com.ru/rss",
    "https://www.f1news.ru/export/news.xml",
    "https://www.championat.com/rss/news/auto.xml",
]

if USE_PIPELINE:
    # Используем готовую библиотеку
    rss_reader = RSSReader()
    post_gen = PostGenerator(ai_client=ai)
    
    async def fetch_news():
        posts = []
        for url in RSS_SOURCES:
            try:
                items = rss_reader.fetch(url, limit=3)
                for item in items:
                    posts.append({
                        "title": item.title,
                        "summary": item.summary[:350] if item.summary else "",
                        "link": item.link,
                        "source": item.feed_title if hasattr(item, "feed_title") else "Неизвестный"
                    })
            except Exception as e:
                logger.error(f"Pipeline RSS error {url}: {e}")
        return posts[:8]
else:
    # Встроенный парсер
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

# ========== СИСТЕМНЫЙ ПРОМПТ ==========
SYSTEM_PROMPT = """Ты — Нико, редактор новостей и голос канала RedRace. 
Ты пишешь коротко, ёмко, с драйвом. Используй эмодзи (1-2 на пост). 
Без воды, без маркдауна. Только факты и контекст. 
Ты — голос RedRace. Создан командой P4/9."""

async def format_news_for_channel(news_item):
    """Форматирует новость для публикации в канал с помощью AI"""
    if USE_PIPELINE:
        try:
            text = await post_gen.generate(news_item, system_prompt=SYSTEM_PROMPT)
            if text:
                return text
        except Exception as e:
            logger.error(f"Pipeline generation error: {e}")
    
    # Fallback на встроенный формат
    prompt = f"Перепиши эту новость в стиле RedRace:\n\n{news_item['title']}\n{news_item['summary']}"
    ai_text = await ai.call(prompt, SYSTEM_PROMPT, 300)
    if ai_text:
        return ai_text
    else:
        return f"📰 {news_item['title']}\n\n{news_item['summary']}\n\n<a href='{news_item['link']}'>Читать полностью</a>"

# ========== КОМАНДЫ ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 <b>Нико — AI-редактор RedRace</b>\n\n"
        "Разработан командой <b>P4/9</b>.\n\n"
        "📰 /news — найти и опубликовать новости\n"
        "📊 /status — статус бота\n"
        "🔧 /admin — админ-панель\n"
        "⚖️ /legal — юридическая информация"
    )

@dp.message(Command("news"))
async def cmd_news(message: types.Message):
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
async def cmd_status(message: types.Message):
    await message.answer(
        f"🤖 <b>Статус Нико</b>\n\n"
        f"📡 RSS источников: {len(RSS_SOURCES)}\n"
        f"🧠 AI-провайдеров: {len(ai.providers)}\n"
        f"📦 Библиотека f1-blog-pipeline: {'✅' if USE_PIPELINE else '❌'}\n"
        f"🔄 Авто-публикация: каждые 2 часа"
    )

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Доступ запрещён.")
        return
    await message.answer("🔧 Админ-панель доступна. Используй /news для ручной публикации.")

@dp.message(Command("legal"))
async def cmd_legal(message: types.Message):
    await message.answer(
        "<b>Юридическая информация</b>\n\n"
        "Бот: <b>Нико</b> — голос канала <b>RedRace</b>\n"
        "Разработчик: <b>P4/9 Dev</b>\n\n"
        "Данный бот и его контент не являются официальными и не имеют отношения к Формуле-1.\n"
        "Все материалы предоставлены на основе открытых источников.\n\n"
        "© 2026 P4/9 Dev. Все права защищены.",
        parse_mode="HTML"
    )

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
