# ============================================================
# RedRace Backend — Makefile
# ============================================================

.PHONY: help build up down logs shell clean

help:
	@echo "🏎️ RedRace Backend Commands:"
	@echo "  make build   - Собрать Docker образ"
	@echo "  make up      - Запустить контейнеры"
	@echo "  make down    - Остановить контейнеры"
	@echo "  make logs    - Показать логи"
	@echo "  make shell   - Войти в контейнер"
	@echo "  make clean   - Очистить данные"

build:
	docker-compose build

up:
	docker-compose up -d

down:
	docker-compose down

logs:
	docker-compose logs -f

shell:
	docker-compose exec backend /bin/bash

clean:
	docker-compose down -v
	rm -rf data/
