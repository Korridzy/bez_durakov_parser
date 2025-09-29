SHELL := /bin/bash
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
	python_min_version=$$(grep -Po '(?<=python = ")[^"]+' pyproject.toml | head -1 | grep -o '[0-9]\+\.[0-9]\+'); \
	python_found=""; \
	if [ "$$OS_TYPE" = "WIN" ]; then \
		for py in $$(where python 2>nul); do \
			if "$${py}" -c "import sys; min=tuple(map(int, '$$python_min_version'.split('.'))); sys.exit(0) if sys.version_info[:2] >= min else sys.exit(1)" 2>nul; then \
				python_found=$$py; \
				break; \
			fi; \
		done; \
	else \
		for py in $$(compgen -c | grep -E '^python[0-9]+\.[0-9]+$$' | sort -Vr); do \
			if "$$py" -c "import sys; min=tuple(map(int, '$$python_min_version'.split('.'))); sys.exit(0) if sys.version_info[:2] >= min else sys.exit(1)" 2>/dev/null; then \
				python_found=$$py; \
				break; \
			fi; \
		done; \
	fi; \
	echo "Найден Python: $$python_found"; \
	if [ -z "$$python_found" ]; then \
		echo "Не найден Python версии $$python_min_version или выше. Установите подходящую версию и добавьте в PATH."; \
		exit 1; \
	fi; \
	poetry env use "$$python_found"; \
	poetry install --no-root; \
	if [ "$$OS_TYPE" = "WIN" ]; then \
		.venv\\Scripts\\python -V; \
	else \
		.venv/bin/python -V; \
	fi

upgrade-db:
	@poetry run python alembic_wrapper.py upgrade head

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
	elif [ "$$all_changes" = "config.toml" ]; then \
		echo "Обнаружены изменения только в config.toml, сохраняю локальную версию..."; \
		if cp config.toml config.toml.backup; then \
			if git stash push -m "temp config.toml" -- config.toml; then \
				git pull origin main; \
				if cp config.toml.backup config.toml; then \
					rm config.toml.backup; \
					echo "Обновление завершено, локальная версия config.toml восстановлена"; \
					echo "Устанавливаю зависимости..."; \
					poetry install; \
				else \
					echo "Ошибка при восстановлении config.toml из backup."; \
					echo "Ваш конфиг лежит в файле config.toml.backup."; \
					echo "Попробуйте сами переименовать его в config.toml."; \
				fi; \
				git stash drop; \
			else \
				echo "Ошибка при создании stash для config.toml"; \
				echo "Обновление прервано"; \
				rm -f config.toml.backup; \
				exit 1; \
			fi; \
		else \
			echo "Ошибка при создании backup файла config.toml.backup"; \
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
