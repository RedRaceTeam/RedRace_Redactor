import asyncio
import logging
import os
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

# ========== AI ==========
CURRENT_PROVIDER = "agnes"

PROVIDERS = {
    "agnes": {
        "name": "Agnes AI",
        "client": AsyncOpenAI(base_url="https://api.agnes.ai/v1", api_key=AGNES_API_KEY) if AGNES_API_KEY else None,
        "model": "agnes-2.5-flash"
    },
    "openrouter": {
        "name": "OpenRouter",
        "client": AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY) if OPENROUTER_API_KEY else None,
        "model": "openrouter/free"
    }
}

def get_ai():
    return PROVIDERS.get(CURRENT_PROVIDER)

async def ask_ai(prompt, system_prompt):
    provider = get_ai()
    if not provider or not provider["client"]:
        return None
    try:
        response = await provider["client"].chat.completions.create(
            model=provider["model"],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            max_tokens=300,
            timeout=20.0
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"AI error: {e}")
        return None

# ========== RSS ==========
RSS_SOURCES = [
    "https://autosport.com.ru/rss",
    "https://www.f1news.ru/export/news.xml",
    "https://www.championat.com/rss/news/auto.xml",
]

async def get_news():
    result = []
    for url in RSS_SOURCES:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]:
                result.append({
                    "title": entry.title,
                    "summary": entry.summary[:350] if "summary" in entry else "",
                    "link": entry.link,
                    "source": feed.feed.title if "title" in feed.feed else "Неизвестный"
                })
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"RSS error: {e}")
    return result[:8]

SYSTEM_PROMPT = """Ты — Нико, голос канала RedRace. Пиши новости коротко, ёмко, с драйвом. Используй эмодзи, но не перебарщивай. Без маркдауна, без воды."""

async def make_post(news):
    ai_text = await ask_ai(
        f"Перепиши новость в стиле RedRace:\n\n{news['title']}\n{news['summary']}",
        SYSTEM_PROMPT
    )
    if ai_text:
        return ai_text
    return f"📰 {news['title']}\n\n{news['summary']}\n\n<a href='{news['link']}'>Читать полностью</a>"

# ========== КНОПКИ ==========
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📰 Новости", callback_data="publish")],
        [InlineKeyboardButton(text="📊 Статус", callback_data="status")],
        [InlineKeyboardButton(text="🧠 Сменить AI", callback_data="switch_ai")],
    ])

def ai_menu():
    buttons = []
    for key, provider in PROVIDERS.items():
        if provider["client"]:
            label = f"✅ {provider['name']}" if key == CURRENT_PROVIDER else provider['name']
            buttons.append([InlineKeyboardButton(text=label, callback_data=f"set_ai_{key}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ========== КОМАНДЫ ==========
@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "👋 <b>Нико — редактор RedRace</b>\n\n"
        "Разработан командой <b>P4/9</b>.\n\n"
        "Используй /admin для управления."
    )

@dp.message(Command("admin"))
async def admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Нет доступа.")
        return
    await message.answer("🔧 <b>Админ-панель</b>", reply_markup=main_menu())

@dp.message(Command("news"))
async def news_cmd(message: Message):
    await message.answer("📡 Собираю новости...")
    news = await get_news()
    if not news:
        await message.answer("❌ Свежих новостей нет.")
        return
    for item in news[:3]:
        text = await make_post(item)
        await bot.send_message(CHANNEL_ID, text, parse_mode="HTML")
        await asyncio.sleep(0.5)
    await message.answer("✅ Опубликовано!")

@dp.message(Command("status"))
async def status_cmd(message: Message):
    provider = get_ai()
    await message.answer(
        f"🤖 <b>Статус</b>\n\n"
        f"🧠 AI: {provider['name'] if provider else 'Нет'}\n"
        f"📡 RSS: {len(RSS_SOURCES)}\n"
        f"🔄 Авто: каждые 2 часа"
    )

# ========== КОЛБЭКИ ==========
@dp.callback_query()
async def callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Нет доступа.", show_alert=True)
        return

    data = callback.data

    if data == "publish":
        await callback.answer("📡 Публикую...")
        news = await get_news()
        if not news:
            await callback.message.answer("❌ Новостей нет.")
            return
        for item in news[:3]:
            text = await make_post(item)
            await bot.send_message(CHANNEL_ID, text, parse_mode="HTML")
            await asyncio.sleep(0.5)
        await callback.message.answer("✅ Готово!")

    elif data == "status":
        provider = get_ai()
        await callback.message.answer(
            f"🤖 <b>Статус</b>\n\n"
            f"🧠 AI: {provider['name'] if provider else 'Нет'}\n"
            f"📡 RSS: {len(RSS_SOURCES)}\n"
            f"🔄 Авто: каждые 2 часа"
        )
        await callback.answer()

    elif data == "switch_ai":
        await callback.message.edit_text("🧠 <b>Выбери AI:</b>", reply_markup=ai_menu())
        await callback.answer()

    elif data.startswith("set_ai_"):
        global CURRENT_PROVIDER
        key = data.replace("set_ai_", "")
        if key in PROVIDERS and PROVIDERS[key]["client"]:
            CURRENT_PROVIDER = key
            await callback.answer(f"✅ Переключено на {PROVIDERS[key]['name']}")
            await callback.message.edit_text(
                f"🧠 <b>Текущий AI: {PROVIDERS[key]['name']}</b>",
                reply_markup=main_menu()
            )
        else:
            await callback.answer("⚠️ Недоступно.", show_alert=True)

# ========== АВТО ==========
async def auto_publish():
    logger.info("🔄 Авто-публикация...")
    news = await get_news()
    if not news:
        return
    for item in news[:2]:
        text = await make_post(item)
        await bot.send_message(CHANNEL_ID, text, parse_mode="HTML")
        await asyncio.sleep(0.5)

scheduler = AsyncIOScheduler(timezone="UTC")
scheduler.add_job(auto_publish, "interval", hours=2)
scheduler.start()

# ========== RENDER ==========
async def health_check(request):
    return web.Response(text="OK")

async def web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8000).start()
    await asyncio.Event().wait()

# ========== ЗАПУСК ==========
async def main():
    asyncio.create_task(web_server())
    logger.info("🚀 Нико запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
