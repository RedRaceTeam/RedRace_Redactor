import os
from typing import List, Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """Настройки приложения из переменных окружения"""
    
    # База данных
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./data/redrace.db")
    
    # Telegram
    bot_token: str = os.getenv("BOT_TOKEN", "")
    
    # Безопасность
    secret_key: str = os.getenv("SECRET_KEY", "change_me_in_production")
    
    # API
    api_base: str = os.getenv("API_BASE", "http://localhost:8000")
    
    # RSS
    rss_cache_ttl: int = int(os.getenv("RSS_CACHE_TTL", "300"))
    
    # CORS — доверенные источники
    cors_origins: List[str] = [
        "https://redrace-redactor.github.io",
        "https://p49dev.github.io",
        "http://localhost:8000",
        "http://localhost:3000",
        "https://redrace-backend.onrender.com",
        "https://redrace-redactor.onrender.com"
    ]
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
