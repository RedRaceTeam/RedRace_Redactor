from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime

from . import models, database, auth, rss, telegram
from .config import settings

# Создаём таблицы
models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(
    title="RedRace API",
    version="2.0",
    description="Редакторская система для публикации новостей Формулы-1"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Модели запросов ---
class LoginRequest(BaseModel):
    username: str
    password: str

class PostCreate(BaseModel):
    title: str
    content: str
    tags: str = ""
    source_url: Optional[str] = None
    source_name: Optional[str] = None

class RSSFetchRequest(BaseModel):
    url: Optional[str] = None
    source_key: Optional[str] = None

# --- Эндпоинты ---
@app.get("/")
def root():
    return {"message": "🏎️ RedRace API running", "status": "online"}

@app.get("/health")
def health():
    return {"status": "healthy", "version": "2.0"}

@app.post("/auth/login")
def login(req: LoginRequest, db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(
        models.User.username == req.username,
        models.User.is_active == True
    ).first()
    
    if not user:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    
    # helpSha проверка (закомментирована для теста)
    # if not auth.check_password(req.password, user.salt, user.password_hash, user.trash):
    #     raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    
    # Для теста: пароль = логин
    if req.password != req.username:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    
    # Обновляем время входа
    user.last_login = datetime.now()
    db.commit()
    
    return {
        "status": "ok",
        "user": {
            "username": user.username,
            "display_name": user.display_name,
            "role": user.role
        },
        "access_token": f"temp_{user.username}_{int(datetime.now().timestamp())}"
    }

@app.get("/rss/sources")
def get_rss_sources():
    return rss.get_all_sources()

@app.post("/rss/fetch")
def fetch_rss(req: RSSFetchRequest):
    if req.source_key:
        sources = rss.get_all_sources()
        if req.source_key not in sources:
            raise HTTPException(status_code=404, detail="Источник не найден")
        result = rss.fetch_rss_feed(sources[req.source_key]["url"])
    elif req.url:
        result = rss.fetch_rss_feed(req.url)
    else:
        raise HTTPException(status_code=400, detail="Укажите url или source_key")
    
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    
    return result

@app.get("/rss/all")
def get_all_news():
    return rss.fetch_all_sources()

@app.post("/posts")
def create_post(post: PostCreate, db: Session = Depends(database.get_db)):
    new_post = models.Post(
        title=post.title,
        content=post.content,
        source_url=post.source_url,
        source_name=post.source_name,
        tags=post.tags,
        author_id=1,
        status="pending"
    )
    db.add(new_post)
    db.commit()
    db.refresh(new_post)
    
    # Отправка в Telegram
    telegram.send_post_to_channel(post.title, post.content)
    
    return {
        "status": "ok",
        "post_id": new_post.id,
        "message": "Пост отправлен в канал"
    }

@app.get("/posts")
def get_posts(db: Session = Depends(database.get_db)):
    posts = db.query(models.Post).order_by(models.Post.created_at.desc()).limit(20).all()
    return posts
