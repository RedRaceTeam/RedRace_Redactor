import asyncio
import logging
import os
import feedparser
from datetime import datetime

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
import json

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
AGNES_API_KEY = os.getenv("AGNES_API_KEY")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# ========== AI КЛИЕНТ (Agnes через OpenAI SDK) ==========
agnes = AsyncOpenAI(
    base_url="https://apihub.agnes-ai.com/v1",
    api_key=AGNES_API_KEY,
    timeout=ClientTimeout(total=120)
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

# ========== AI ФУНКЦИИ ==========
SYSTEM_PROMPT = """Ты — Нико, голос канала RedRace.
Пиши новости коротко, ёмко, с драйвом. Используй эмодзи (1-2).
Без маркдауна, без воды, только факты и контекст.
Создан командой P4/9."""

async def ask_agnes(prompt: str, system: str = SYSTEM_PROMPT) -> str:
    try:
        resp = await agnes.chat.completions.create(
            model="agnes-2.5-flash",
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

async def generate_image(prompt: str) -> str:
    try:
        resp = await agnes.images.generate(
            model="agnes-image-2.1-flash",
            prompt=prompt,
            size="1024x768",
            n=1
        )
        return resp.data[0].url
    except Exception as e:
        logger.error(f"Image error: {e}")
        return None

async def generate_video(prompt: str) -> str:
    async with ClientSession() as session:
        headers = {"Authorization": f"Bearer {AGNES_API_KEY}"}
        data = {
            "model": "agnes-video-v2.0",
            "prompt": prompt,
            "num_frames": 121,
            "frame_rate": 24,
            "width": 1152,
            "height": 768
        }
        try:
            async with session.post("https://apihub.agnes-ai.com/v1/videos", headers=headers, json=data) as resp:
                if resp.status != 200:
                    return None
                result = await resp.json()
                video_id = result.get("video_id")
                if not video_id:
                    return None

            for _ in range(30):
                await asyncio.sleep(5)
                async with session.get(f"https://apihub.agnes-ai.com/agnesapi?video_id={video_id}", headers=headers) as resp:
                    if resp.status != 200:
                        continue
                    status_data = await resp.json()
                    if status_data.get("status") == "completed":
                        return status_data.get("video_url")
            return None
        except Exception as e:
            logger.error(f"Video error: {e}")
            return None

# ========== ИНТЕРФЕЙС ==========
def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📰 Новости", callback_data="publish")],
        [InlineKeyboardButton(text="🖼️ Картинка", callback_data="image")],
        [InlineKeyboardButton(text="🎬 Видео", callback_data="video")],
        [InlineKeyboardButton(text="📊 Статус", callback_data="status")],
    ])

# ========== КОМАНДЫ ==========
@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "👋 <b>Нико — редактор RedRace</b>\n\n"
        "Использует <b>Agnes AI</b>.\n"
        "/admin — управление"
    )

@dp.message(Command("admin"))
async def admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Нет доступа.")
        return
    await message.answer("🔧 Админ-панель", reply_markup=admin_menu())

# ========== КОЛБЭКИ ==========
@dp.callback_query()
async def callback(callback: CallbackQuery, state: FSMContext):
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
            text = await ask_agnes(prompt)
            if not text:
                text = f"📰 {item['title']}\n\n{item['summary']}\n\n<a href='{item['link']}'>Читать полностью</a>"
            await bot.send_message(CHANNEL_ID, text, parse_mode="HTML")
            await asyncio.sleep(0.5)
        await callback.message.answer("✅ Готово!")

    elif callback.data == "image":
        await callback.message.answer("🖼️ Напиши промпт для картинки (на английском):")
        await state.set_state(PromptStates.waiting_for_image_prompt)
        await callback.answer()

    elif callback.data == "video":
        await callback.message.answer("🎬 Напиши промпт для видео (на английском):")
        await state.set_state(PromptStates.waiting_for_video_prompt)
        await callback.answer()

    elif callback.data == "status":
        await callback.message.answer(
            f"🤖 <b>Статус</b>\n\n"
            f"🧠 AI: Agnes 2.5 Flash\n"
            f"🖼️ Image: Agnes Image 2.1 Flash\n"
            f"🎬 Video: Agnes Video V2.0\n"
            f"📡 RSS: {len(RSS_SOURCES)}\n"
            f"🔄 Авто: каждые 2 часа"
        )
        await callback.answer()

# ========== ОБРАБОТКА ПРОМПТОВ ==========
@dp.message(PromptStates.waiting_for_image_prompt)
async def handle_image_prompt(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("⏳ Генерирую картинку...")
    url = await generate_image(message.text)
    if url:
        await message.answer_photo(url, caption="🖼️ Сгенерировано Agnes AI")
    else:
        await message.answer("❌ Не удалось сгенерировать картинку.")

@dp.message(PromptStates.waiting_for_video_prompt)
async def handle_video_prompt(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🎬 Генерирую видео... Это может занять до 30 секунд.")
    url = await generate_video(message.text)
    if url:
        await message.answer(url, caption="🎬 Сгенерировано Agnes AI")
    else:
        await message.answer("❌ Не удалось сгенерировать видео.")

# ========== АВТО-ПУБЛИКАЦИЯ ==========
async def auto_publish():
    logger.info("🔄 Авто-публикация...")
    news = await fetch_news()
    if not news:
        return
    for item in news[:2]:
        prompt = f"Перепиши новость в стиле RedRace:\n\n{item['title']}\n{item['summary']}"
        text = await ask_agnes(prompt)
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
    logger.info("🚀 Нико с Agnes AI запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
