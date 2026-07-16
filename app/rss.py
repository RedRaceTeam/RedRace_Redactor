import feedparser
import re
import logging
from typing import Dict, List, Optional
from datetime import datetime
from cachetools import cached, TTLCache
from .config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Кеш на 5 минут
cache = TTLCache(maxsize=100, ttl=settings.rss_cache_ttl)

# Предустановленные источники
REDRACE_SOURCES = {
    "f1news": {
        "name": "F1News.ru",
        "url": "http://www.f1news.ru/export/news.xml",
        "icon": "🏎️"
    },
    "autosport": {
        "name": "Autosport.com.ru",
        "url": "https://autosport.com.ru/rss.xml",
        "icon": "🏁"
    },
    "championat": {
        "name": "Championat.com (авто)",
        "url": "https://www.championat.com/rss/news/auto.xml",
        "icon": "📰"
    }
}

def clean_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

@cached(cache)
def fetch_rss_feed(url: str) -> Dict:
    """Парсит RSS-ленту и возвращает последнюю новость"""
    try:
        feed = feedparser.parse(url)
        if not feed.entries:
            return {"error": "Нет записей в RSS"}
        
        entry = feed.entries[0]
        content = entry.get("description", entry.get("summary", ""))
        content = clean_html(content)
        
        return {
            "title": clean_html(entry.get("title", "Без заголовка")),
            "content": content,
            "link": entry.get("link", ""),
            "published": entry.get("published", datetime.now().strftime("%d.%m.%Y %H:%M")),
            "source": feed.feed.get("title", "Unknown"),
            "source_key": None
        }
    except Exception as e:
        logger.error(f"Ошибка RSS: {e}")
        return {"error": str(e)}

def fetch_all_sources() -> List[Dict]:
    """Парсит все источники"""
    results = []
    for key, source in REDRACE_SOURCES.items():
        result = fetch_rss_feed(source["url"])
        if "error" not in result:
            result["source_key"] = key
            result["source_name"] = source["name"]
            result["icon"] = source["icon"]
            results.append(result)
    return results

def get_all_sources() -> Dict:
    return REDRACE_SOURCES
