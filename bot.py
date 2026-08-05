import asyncio
import logging
import os
import feedparser
from datetime import datetime
import requests

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv
from openai import AsyncOpenAI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiohttp import web, ClientSession, ClientTimeout

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# ========== AI КЛИЕНТ (OpenRouter) ==========
openrouter = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
    timeout=ClientTimeout(total=60)
)

# ========== FSM ==========
class PromptStates(StatesGroup):
    waiting_for_image_prompt = State()
    waiting_for_video_prompt = State()

# ========== RSS ==========
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
                    "summary": entry.summary[:350] if "summary" in entry else "",
                    "link": entry.link,
                })
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"RSS error: {e}")
    return news[:8]

# ========== AI ФУНКЦИИ (OpenRouter) ==========
SYSTEM_PROMPT = """Ты — Нико, голос канала RedRace.
Пиши новости коротко, ёмко, с драйвом. Используй эмодзи (1-2).
Без маркдауна, без воды, только факты и контекст.
Создан командой P4/9."""

async def ask_openrouter(prompt: str, system: str = SYSTEM_PROMPT) -> str:
    try:
        resp = await openrouter.chat.completions.create(
            model="openrouter/free",  # бесплатная модель
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            max_tokens=500,
            temperature=0.7
        )
        return resp.choices[0].message.content
    except Exception as e:
        logger.error(f"AI error: {e}")
        return None

# ========== ИНТЕРФЕЙС ==========
def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📰 Новости", callback_data="publish")],
        [InlineKeyboardButton(text="📊 Статус", callback_data="status")],
    ])

# ========== КОМАНДЫ ==========
@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "👋 <b>Нико — редактор RedRace</b>\n\n"
        "Использует <b>OpenRouter</b> (бесплатно).\n"
        "Просто напиши мне что-нибудь — я отвечу.\n\n"
        "/admin — управление"
    )

@dp.message(Command("admin"))
async def admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Нет доступа.")
        return
    await message.answer("🔧 Админ-панель", reply_markup=admin_menu())

# ========== ОБРАБОТКА ЛЮБЫХ СООБЩЕНИЙ ==========
@dp.message(F.text)
async def chat_reply(message: Message):
    if message.text.startswith('/'):
        return
    
    await bot.send_chat_action(message.chat.id, "typing")
    reply = await ask_openrouter(
        message.text,
        "Ты — Нико, голос канала RedRace. Отвечай дружелюбно, коротко и по делу. Используй эмодзи."
    )
    if reply:
        await message.answer(reply)
    else:
        await message.answer("❌ Не удалось обработать запрос.")

# ========== КОЛБЭКИ ==========
@dp.callback_query()
async def callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Нет доступа.", show_alert=True)
        return

    if callback.data == "publish":
        await callback.answer("📡 Публикую...")
        news = await fetch_news()
        if not news:
            await callback.message.answer("❌ Новостей нет.")
            return
        for item in news[:3]:
            prompt = f"Перепиши новость в стиле RedRace:\n\n{item['title']}\n{item['summary']}"
            text = await ask_openrouter(prompt)
            if not text:
                text = f"📰 {item['title']}\n\n{item['summary']}\n\n<a href='{item['link']}'>Читать полностью</a>"
            await bot.send_message(CHANNEL_ID, text, parse_mode="HTML")
            await asyncio.sleep(0.5)
        await callback.message.answer("✅ Готово!")

    elif callback.data == "status":
        await callback.message.answer(
            f"🤖 <b>Статус</b>\n\n"
            f"🧠 AI: OpenRouter (бесплатно)\n"
            f"📡 RSS: {len(RSS_SOURCES)}\n"
            f"🔄 Авто: каждые 2 часа"
        )
        await callback.answer()

# ========== АВТО-ПУБЛИКАЦИЯ ==========
async def auto_publish():
    logger.info("🔄 Авто-публикация...")
    news = await fetch_news()
    if not news:
        return
    for item in news[:2]:
        prompt = f"Перепиши новость в стиле RedRace:\n\n{item['title']}\n{item['summary']}"
        text = await ask_openrouter(prompt)
        if not text:
            text = f"📰 {item['title']}\n\n{item['summary']}\n\n<a href='{item['link']}'>Читать полностью</a>"
        await bot.send_message(CHANNEL_ID, text, parse_mode="HTML")
        await asyncio.sleep(0.5)

scheduler = AsyncIOScheduler()
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
    logger.info("🚀 Нико на OpenRouter запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
