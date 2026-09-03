# iRent-AI — 常用指令（在 repo 根執行 make <target>）
#
# 這裡只包 Docker 路徑。本機 venv 開發見 環節二_還車影像AI辨識/SETUP.md §4a。

# docker compose v2（外掛）優先，沒有就退回 docker-compose v1
COMPOSE := $(shell docker compose version >/dev/null 2>&1 && echo "docker compose" || echo "docker-compose")

.DEFAULT_GOAL := help
.PHONY: help up down logs shell restart nuke

help:  ## 列出可用指令
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/' | expand -t20
	@echo "\n測試在 venv 跑（image 不含 pytest）：cd backend && pytest tests/ -q"

up:  ## 啟動（確保 colima 在跑、建 .env、build、背景起）
	@colima status >/dev/null 2>&1 || colima start --cpu 4 --memory 6
	@test -f .env || { cp .env.example .env; echo "已從 .env.example 建立 .env —— 需要 AI 功能請填 GEMINI_API_KEY"; }
	$(COMPOSE) up --build -d
	@echo "→ http://localhost:8000"

down:  ## 停容器（保留 volume 資料）
	$(COMPOSE) down

restart:  ## 重啟 backend（不 rebuild，只重跑 process）
	$(COMPOSE) restart backend

logs:  ## 跟著看 backend log
	$(COMPOSE) logs -f backend

shell:  ## 進 backend 容器
	$(COMPOSE) exec backend sh

nuke:  ## 停容器並刪 volume（⚠️ 複核紀錄會清空）
	$(COMPOSE) down -v
