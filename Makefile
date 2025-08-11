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
	@poetry run alembic upgrade head