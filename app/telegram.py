import requests
import logging
from .config import settings

logger = logging.getLogger(__name__)

def send_post_to_channel(title: str, content: str, image_url: str = None) -> bool:
    """
    Отправляет пост в Telegram-канал
    """
    if not settings.bot_token:
        logger.error("BOT_TOKEN не задан")
        return False
    
    channel_id = "@redrace_news"
    message = f"🏁 <b>{title}</b>\n\n{content}"
    
    url = f"https://api.telegram.org/bot{settings.bot_token}/sendMessage"
    payload = {
        "chat_id": channel_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info(f"Пост отправлен в канал: {title}")
            return True
        else:
            logger.error(f"Ошибка Telegram: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Ошибка отправки в Telegram: {e}")
        return False
