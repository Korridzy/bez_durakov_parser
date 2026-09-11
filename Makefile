SHELL := /bin/bash
DOCKER_COMPOSE ?= docker compose
PYTHON_VERSION ?= 3.11

.PHONY: help setup test lint upgrade-db upgrade-code webreport-start webreport-stop validate-knowledge validate-tools restart mysql-start mysql-stop fetch-data fetch-data-log logs

help:
	@echo "🎲 Без дураков parser - available commands"
	@echo "========================================="
	@echo ""
	@echo "Core:"
	@echo "  make setup          - Create venv and install dependencies"
	@echo "  make lint           - Run Ruff checks"
	@echo "  make test           - Run the complete project test suite"
	@echo "  make upgrade-db     - Apply Alembic migrations"
	@echo "  make upgrade-code   - Pull updates from main safely"
	@echo ""
	@echo "WebReport stack:"
	@echo "  make webreport-start - Start MySQL + backend + frontend"
	@echo "  make webreport-stop   - Stop WebReport stack"
	@echo "  make validate-knowledge - Validate the configured knowledge folder"
	@echo "  make validate-tools   - Validate the configured operator tool module"
	@echo "  make restart          - Recreate LiteLLM, backend, and frontend"
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
	@if [ "$(OS)" = "Windows_NT" ]; then \
		PY_PATH=".venv/Scripts/python.exe"; \
	else \
		PY_PATH=".venv/bin/python"; \
	fi; \
	if ! command -v poetry > /dev/null 2>&1; then \
		echo "Poetry не найден, устанавливаю..."; \
		if command -v python3 > /dev/null 2>&1; then \
			python3 -m pip install --user poetry; \
		elif command -v python > /dev/null 2>&1; then \
			python -m pip install --user poetry; \
		else \
			echo "Для установки Poetry нужен Python с pip."; \
			exit 1; \
		fi; \
		export PATH="$$HOME/.local/bin:$$PATH"; \
	fi; \
	if ! command -v poetry > /dev/null 2>&1; then \
		echo "Poetry установлен, но не найден в PATH. Добавьте каталог пользовательских скриптов Python в PATH."; \
		exit 1; \
	fi; \
	if [ -d .venv ] && [ ! -x "$$PY_PATH" ]; then \
		echo "Удаляю повреждённое виртуальное окружение..."; \
		rm -rf .venv; \
	fi; \
	python_path=$$(poetry python list --managed | awk '$$1 == "$(PYTHON_VERSION)" || index($$1, "$(PYTHON_VERSION).") == 1 { print $$NF; exit }'); \
	if [ -z "$$python_path" ]; then \
		echo "Устанавливаю Python $(PYTHON_VERSION) через Poetry..."; \
		poetry python install "$(PYTHON_VERSION)"; \
		python_path=$$(poetry python list --managed | awk '$$1 == "$(PYTHON_VERSION)" || index($$1, "$(PYTHON_VERSION).") == 1 { print $$NF; exit }'); \
	fi; \
	if [ -z "$$python_path" ] || [ ! -x "$$python_path" ]; then \
		echo "Poetry не смог установить Python $(PYTHON_VERSION)."; \
		exit 1; \
	fi; \
	echo "Использую Python: $$python_path"; \
	poetry env use "$$python_path"; \
	poetry install --no-root; \
	poetry run python -V

lint:
	@poetry run ruff check .

test:
	@set -o pipefail; \
	$(MAKE) lint || { echo ""; echo "❌ make lint failed - aborting before the test suite runs"; exit 1; }; \
	status=0; \
	run() { \
		echo ""; \
		echo ">>> $$*"; \
		"$$@" || status=$$?; \
	}; \
	run poetry run python test_alembic_migration.py; \
	run poetry run python bd_shared/test_db_engine.py; \
	run env PYTHONPATH="$(CURDIR)" poetry run python webreport/test_generate_env.py; \
	run $(MAKE) -C webreport test; \
	run env PYTHONPATH="$(CURDIR)" bash -c 'set -e; cd webreport/data_collector; poetry run python test_entrypoint.py'; \
	run bash -c 'set -e; set -a; source webreport/.env; source webreport/.env.frontend; set +a; export WEBREPORT_FRONTEND_URL="http://127.0.0.1:$$WEBREPORT_FRONTEND_PORT"; cd webreport/frontend; poetry run python -m unittest discover -s . -p "test_*.py"'; \
	run $(MAKE) -C webreport test-e2e; \
	if [ $$status -eq 0 ]; then \
		echo ""; \
		echo "✅ Full test suite passed"; \
	else \
		echo ""; \
		echo "❌ Full test suite failed (exit $$status)"; \
	fi; \
	exit $$status

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

validate-knowledge:
	cd webreport && $(DOCKER_COMPOSE) run --rm --no-deps backend python -m agent.knowledge_cli

validate-tools:
	cd webreport && $(DOCKER_COMPOSE) run --rm --no-deps backend python -m agent.tools_cli

restart:
	$(MAKE) -C webreport restart

# MySQL only management
mysql-start:
	@echo "🗄️  Запуск MySQL..."
	cd webreport && PYTHONPATH="$(CURDIR)" poetry run python generate_env.py && $(DOCKER_COMPOSE) up -d mysql
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
