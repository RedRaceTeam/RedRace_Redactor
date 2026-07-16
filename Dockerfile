# ============================================================
# RedRace Backend — Dockerfile
# Многоступенчатая сборка для минимального размера
# ============================================================

# ---- Этап 1: Сборка зависимостей ----
FROM python:3.11-slim AS builder

WORKDIR /build

# Устанавливаем системные зависимости для сборки
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Копируем зависимости
COPY requirements.txt .

# Устанавливаем зависимости в отдельную папку
RUN pip install --no-cache-dir --user -r requirements.txt

# ---- Этап 2: Финальный образ ----
FROM python:3.11-slim

WORKDIR /app

# Устанавливаем runtime-зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Копируем установленные пакеты из builder-образа
COPY --from=builder /root/.local /root/.local

# Копируем код приложения
COPY ./app ./app

# Делаем переменные окружения доступными
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Открываем порт
EXPOSE 8000

# Запускаем приложение
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
