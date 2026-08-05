import asyncio
import logging
import os
import feedparser
from datetime import datetime
from collections import defaultdict

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
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
SAMBANOVA_API_KEY = os.getenv("SAMBANOVA_API_KEY")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# ========== AI КЛИЕНТ SambaNova ==========
sambanova = AsyncOpenAI(
    base_url="https://api.sambanova.ai/v1",
    api_key=SAMBANOVA_API_KEY,
)

# ========== FSM ==========
class PromptStates(StatesGroup):
    waiting_for_prompt = State()

# ========== RSS ==========
RSS_SOURCES = [
    "https://autosport.com.ru/rss",
    "https://www.f1news.ru/export/news.xml",
    "https://www.championat.com/rss/news/auto.xml",
]

# ========== СИСТЕМНЫЙ ПРОМПТ ==========
SYSTEM_PROMPT = """Ты — Нико, голос канала RedRace.
Твоя задача — делать новости Формулы-1 живыми, точными и увлекательными для фанатов.

🔹 Стиль:
— Пиши как комментатор: коротко, ёмко, с драйвом.
— Используй эмодзи 🏎️🔥🏁, но не перебарщивай (1–2 на пост).
— Без воды. Только факты и контекст.
— Если новость техническая — объясни простыми словами.

🔹 Тон:
— Дружелюбный, но уважительный.
— Без излишнего пафоса. Без политики.
— Если шутка — уместная, лёгкая.

🔹 Формат поста:
— Заголовок: ёмкий, кликбейтный, но честный.
— Основной текст: 3–5 предложений, суть.
— В конце: ссылка на источник (если есть).

🔹 Запрещено:
— Маркдаун, звёздочки, подчёркивания.
— Спекуляции без подтверждения.
— Оскорбления пилотов, команд или болельщиков.

Ты — голос RedRace. Создан командой P4/9. Будь профессионалом."""

# ========== AI ФУНКЦИИ ==========
async def ask_sambanova(prompt: str, system: str = SYSTEM_PROMPT) -> str:
    try:
        resp = await sambanova.chat.completions.create(
            model="Meta-Llama-3.3-70B-Instruct",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            max_tokens=500,
            temperature=0.7
        )
        return resp.choices[0].message.content
    except Exception as e:
        logger.error(f"SambaNova error: {e}")
        return None

# ========== ПАРСЕР НОВОСТЕЙ ==========
# Хранилище для отслеживания публикаций
published_links = set()
pending_posts = {}

async def fetch_news(limit=8):
    """Собирает новости из RSS-лент с защитой от дублей"""
    news = []
    for url in RSS_SOURCES:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]:
                link = entry.link
                if link in published_links:
                    continue
                news.append({
                    "title": entry.title,
                    "summary": entry.summary[:350] if "summary" in entry else "",
                    "link": link,
                    "source": feed.feed.title if "title" in feed.feed else "Неизвестный"
                })
                published_links.add(link)
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"RSS error: {e}")
    return news[:limit]

def format_post_text(title, summary, link, source):
    """Форматирует пост для канала"""
    return f"📰 <b>{title}</b>\n\n{summary}\n\n<a href='{link}'>Читать полностью</a>"

async def create_post(news_item):
    """Создаёт пост через AI"""
    prompt = f"Перепиши эту новость в стиле RedRace:\n\n{news_item['title']}\n{news_item['summary']}"
    text = await ask_sambanova(prompt)
    if text:
        return text
    return format_post_text(
        news_item['title'],
        news_item['summary'],
        news_item['link'],
        news_item['source']
    )

# ========== КНОПКИ ==========
def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📰 Новости", callback_data="publish")],
        [InlineKeyboardButton(text="📊 Статус", callback_data="status")],
    ])

def news_buttons(post_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"confirm_{post_id}"),
            InlineKeyboardButton(text="✏️ Рерайт", callback_data=f"rewrite_{post_id}")
        ],
        [InlineKeyboardButton(text="❌ Пропустить", callback_data=f"skip_{post_id}")]
    ])

# ========== КОМАНДЫ ==========
@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "👋 <b>Нико — редактор RedRace</b>\n\n"
        "Использует <b>SambaNova AI</b>.\n"
        "Просто напиши мне что-нибудь — я отвечу.\n\n"
        "/admin — управление"
    )

@dp.message(Command("admin"))
async def admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Нет доступа.")
        return
    await message.answer("🔧 Админ-панель", reply_markup=admin_menu())

# ========== ЧАТ ==========
@dp.message(F.text)
async def chat_reply(message: Message):
    if message.text.startswith('/'):
        return
    
    await bot.send_chat_action(message.chat.id, "typing")
    reply = await ask_sambanova(message.text)
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

    data = callback.data

    if data == "publish":
        await callback.answer("📡 Собираю новости...")
        news = await fetch_news()
        if not news:
            await callback.message.answer("❌ Свежих новостей нет.")
            return
        
        for idx, item in enumerate(news):
            post_id = f"post_{idx}_{int(datetime.now().timestamp())}"
            pending_posts[post_id] = item
            text = f"📰 <b>{item['title']}</b>\n\n{item['summary']}\n\nИсточник: {item['source']}"
            await callback.message.answer(text, reply_markup=news_buttons(post_id))
        
        await callback.message.answer("✅ Новости загружены. Выберите действие.")

    elif data == "status":
        await callback.message.answer(
            f"🤖 <b>Статус Нико</b>\n\n"
            f"🧠 AI: SambaNova\n"
            f"📡 RSS: {len(RSS_SOURCES)}\n"
            f"📰 В очереди: {len(pending_posts)}\n"
            f"🔄 Авто: каждые 2 часа"
        )
        await callback.answer()

    elif data.startswith("confirm_"):
        post_id = data.replace("confirm_", "")
        post = pending_posts.pop(post_id, None)
        if not post:
            await callback.answer("Новость уже обработана.", show_alert=True)
            return
        text = await create_post(post)
        await bot.send_message(CHANNEL_ID, text, parse_mode="HTML")
        await callback.message.answer("✅ Новость опубликована!")
        await callback.answer()

    elif data.startswith("rewrite_"):
        post_id = data.replace("rewrite_", "")
        post = pending_posts.get(post_id)
        if not post:
            await callback.answer("Новость не найдена.", show_alert=True)
            return
        await callback.answer("🔄 Переписываю...")
        text = await create_post(post)
        post['summary'] = text[:350] + "..." if len(text) > 350 else text
        await callback.message.edit_text(
            f"✏️ <b>Рерайт:</b>\n\n{text}\n\nИсточник: {post['source']}",
            reply_markup=news_buttons(post_id)
        )
        await callback.answer()

    elif data.startswith("skip_"):
        post_id = data.replace("skip_", "")
        pending_posts.pop(post_id, None)
        await callback.answer("Пропущено.")
        await callback.message.delete()

# ========== АВТО-ПУБЛИКАЦИЯ ==========
async def auto_publish():
    logger.info("🔄 Авто-публикация...")
    news = await fetch_news(limit=2)
    if not news:
        return
    for item in news:
        text = await create_post(item)
        if text:
            await bot.send_message(CHANNEL_ID, text, parse_mode="HTML")
            logger.info(f"✅ Авто-публикация: {item['title']}")
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
    logger.info("🚀 Нико на SambaNova запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
