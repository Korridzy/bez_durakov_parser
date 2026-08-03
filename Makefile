SHELL := /bin/bash
DOCKER_COMPOSE ?= docker compose

.PHONY: help setup upgrade-db upgrade-code webreport-start webreport-stop restart mysql-start mysql-stop fetch-data fetch-data-log logs

help:
	@echo "🎲 Без дураков parser - available commands"
	@echo "========================================="
	@echo ""
	@echo "Core:"
	@echo "  make setup          - Create venv and install dependencies"
	@echo "  make upgrade-db     - Apply Alembic migrations"
	@echo "  make upgrade-code   - Pull updates from main safely"
	@echo ""
	@echo "WebReport stack:"
	@echo "  make webreport-start - Start MySQL + backend + frontend"
	@echo "  make webreport-stop  - Stop WebReport stack"
	@echo "  make restart         - Restart WebReport stack"
	@echo "  make mysql-start     - Start only MySQL container"
	@echo "  make mysql-stop      - Stop only MySQL container"
	@echo ""
	@echo "Data collector:"
	@echo "  make fetch-data      - Run XLSM fetch manually"
	@echo "  make fetch-data-log  - Show logs since last fetch start"
	@echo "  make logs SERVICE=name - Stream selected service logs"
	@echo ""
	@echo "Tip: make -C webreport help"

setup:
	@OS_TYPE=""; \
	if [ "$(OS)" = "Windows_NT" ]; then \
		OS_TYPE="WIN"; \
		CMD_CHECK="where"; \
		PY_PATH=".venv\\Scripts\\python"; \
	else \
		OS_TYPE="UNIX"; \
		CMD_CHECK="command -v"; \
		PY_PATH=".venv/bin/python"; \
	fi; \
	if ! $$CMD_CHECK poetry > /dev/null 2>&1; then \
		echo "Poetry не найден, устанавливаю..."; \
		pip install --user poetry; \
	fi; \
	python_found=""; \
	if [ "$$OS_TYPE" = "WIN" ]; then \
		for py in $$(where python 2>nul); do \
			if poetry env use "$${py}" > /dev/null 2>&1; then \
				python_found=$$py; \
				break; \
			fi; \
		done; \
	else \
		for py in python3 python $$(compgen -c | grep -E '^python[0-9]+\.[0-9]+$$' | sort -Vr); do \
			if command -v "$$py" > /dev/null 2>&1 && poetry env use "$$py" > /dev/null 2>&1; then \
				python_found=$$py; \
				break; \
			fi; \
		done; \
	fi; \
	echo "Найден Python: $$python_found"; \
	if [ -z "$$python_found" ]; then \
		echo "Не найден Python, совместимый с pyproject.toml. Установите подходящую версию и добавьте в PATH."; \
		exit 1; \
	fi; \
	poetry env use "$$python_found"; \
	poetry install --no-root; \
	poetry run python -V

upgrade-db:
	@poetry run alembic upgrade head

upgrade-code:
	@echo "Проверяю статус репозитория..."; \
	if ! git rev-parse --git-dir > /dev/null 2>&1; then \
		echo "Ошибка: не находимся в git репозитории"; \
		exit 1; \
	fi; \
	changed_files=$$(git diff --name-only HEAD); \
	staged_files=$$(git diff --cached --name-only); \
	untracked_files=$$(git ls-files --others --exclude-standard); \
	all_changes="$$changed_files$$staged_files$$untracked_files"; \
	if [ -z "$$all_changes" ]; then \
		echo "Нет локальных изменений, выполняю обновление..."; \
		git pull origin main; \
		echo "Устанавливаю зависимости..."; \
		poetry install; \
	elif [ "$$all_changes" = "bd_shared/config.toml" ]; then \
		echo "Обнаружены изменения только в bd_shared/config.toml, сохраняю локальную версию..."; \
		if cp bd_shared/config.toml bd_shared/config.toml.backup; then \
			if git stash push -m "temp bd_shared/config.toml" -- bd_shared/config.toml; then \
				git pull origin main; \
				if cp bd_shared/config.toml.backup bd_shared/config.toml; then \
					rm bd_shared/config.toml.backup; \
					echo "Обновление завершено, локальная версия bd_shared/config.toml восстановлена"; \
					echo "Устанавливаю зависимости..."; \
					poetry install; \
				else \
					echo "Ошибка при восстановлении bd_shared/config.toml из backup."; \
					echo "Ваш конфиг лежит в файле bd_shared/config.toml.backup."; \
					echo "Попробуйте сами переименовать его в bd_shared/config.toml."; \
				fi; \
				git stash drop; \
			else \
				echo "Ошибка при создании stash для bd_shared/config.toml"; \
				echo "Обновление прервано"; \
				rm -f bd_shared/config.toml.backup; \
				exit 1; \
			fi; \
		else \
			echo "Ошибка при создании backup файла bd_shared/config.toml.backup"; \
			echo "Обновление прервано"; \
			exit 1; \
		fi; \
	else \
		all_changes="$$changed_files $$staged_files $$untracked_files"; \
		echo "ВНИМАНИЕ: Обнаружены локальные изменения в следующих файлах:"; \
		echo "$$all_changes" | tr ' ' '\n' | grep -v '^$$' | sed 's/^/  - /'; \
		echo "Для безопасности автоматическое обновление отменено."; \
		echo "Выполните обновление вручную или зафиксируйте изменения."; \
		exit 1; \
	fi

# WebReport Docker management
webreport-start:
	@echo "🚀 Запуск WebReport (MySQL + Backend + Frontend)..."
	cd webreport && $(MAKE) start
	@echo ""
	@echo "✅ WebReport запущен!"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "🎨 Frontend:  http://localhost:$$(grep WEBREPORT_FRONTEND_PORT webreport/.env | cut -d'=' -f2)"
	@echo "🔌 Backend:   http://localhost:$$(grep WEBREPORT_BACKEND_PORT webreport/.env | cut -d'=' -f2)"
	@echo "📚 API Docs:  http://localhost:$$(grep WEBREPORT_BACKEND_PORT webreport/.env | cut -d'=' -f2)/docs"
	@echo "🗄️  MySQL:    localhost:3306"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

webreport-stop:
	@echo "🛑 Остановка WebReport..."
	cd webreport && $(MAKE) stop

restart:
	$(MAKE) -C webreport restart

# MySQL only management
mysql-start:
	@echo "🗄️  Запуск MySQL..."
	cd webreport && poetry run python generate_env.py && $(DOCKER_COMPOSE) up -d mysql
	@echo "✅ MySQL запущен на localhost:3306"

mysql-stop:
	@echo "🛑 Остановка MySQL..."
	cd webreport && $(DOCKER_COMPOSE) stop mysql
	@echo "✅ MySQL остановлен"

# Data Collector targets
fetch-data:
	cd webreport && $(MAKE) fetch-data

fetch-data-log:
	cd webreport && $(MAKE) fetch-data-log

logs:
	cd webreport && $(MAKE) logs SERVICE=$(SERVICE)
