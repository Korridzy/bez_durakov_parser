DOCKER_COMPOSE ?= docker compose

.PHONY: help generate-env test test-e2e-setup test-e2e clean start stop restart logs build rebuild fetch-data fetch-data-log

help:
	@echo "🎮 Web Reporting System - Docker Commands"
	@echo "=========================================="
	@echo ""
	@echo "Docker Operations:"
	@echo "  make generate-env - Generate Compose and service env files"
	@echo "  make start       - Start services with Docker Compose"
	@echo "  make stop        - Stop Docker containers"
	@echo "  make restart     - Recreate LiteLLM, backend, and frontend"
	@echo "  make logs        - View logs"
	@echo "  make build       - Build Docker images"
	@echo "  make rebuild     - Rebuild and restart services"
	@echo ""
	@echo "Testing:"
	@echo "  make test           - Run the offline backend suite (no running stack needed)"
	@echo "  make test-e2e-setup - One-time: install frontend dev deps and Chromium (needs network)"
	@echo "  make test-e2e       - Run the offline stub-backed Playwright lane"
	@echo ""
	@echo "Maintenance:"
	@echo "  make clean       - Clean temporary files"
	@echo ""
	@echo "Data collector:"
	@echo "  make fetch-data      - Run XLSM fetch manually"
	@echo "  make fetch-data-log  - Show logs since last fetch start"
	@echo ""
	@echo "Tips:"
	@echo "  make logs SERVICE=data_collector"
	@echo "  make logs SERVICE=backend"
	@echo ""

generate-env:
	[ -d ../vm/backend/checkpoints ] || mkdir -p ../vm/backend/checkpoints
	poetry run python generate_env.py

start: generate-env
	@echo "🐳 Starting services with Docker Compose..."
	$(DOCKER_COMPOSE) up -d
	@echo ""
	@echo "✅ Services started!"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "🎨 Frontend:  http://localhost:$$(grep WEBREPORT_FRONTEND_PORT .env | cut -d'=' -f2)"
	@echo "🔌 Backend:   http://localhost:$$(grep WEBREPORT_BACKEND_PORT .env | cut -d'=' -f2)"
	@echo "📚 API Docs:  http://localhost:$$(grep WEBREPORT_BACKEND_PORT .env | cut -d'=' -f2)/docs"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "View logs:    make logs"
	@echo "Stop:         make stop"

stop:
	@echo "🐳 Stopping Docker containers..."
	$(DOCKER_COMPOSE) down
	@echo "✅ Containers stopped"

restart: generate-env
	@echo "🔄 Recreating LiteLLM, backend, and frontend..."
	$(DOCKER_COMPOSE) up -d --force-recreate litellm backend frontend
	@echo "✅ Application services recreated"

logs:
	$(DOCKER_COMPOSE) logs -f $(SERVICE)

build: generate-env
	@echo "🔨 Building Docker images..."
	$(DOCKER_COMPOSE) build
	@echo "✅ Build complete"

rebuild: generate-env
	@echo "🔨 Rebuilding and restarting services..."
	$(DOCKER_COMPOSE) down
	$(DOCKER_COMPOSE) build
	$(DOCKER_COMPOSE) up -d
	@echo "✅ Services rebuilt and started"

test: generate-env
	@echo "🧪 Running tests in Docker..."
	$(DOCKER_COMPOSE) run --rm --no-deps -e BD_CHECKPOINT_DB_PATH=/tmp/test-checkpoints.db backend sh -c "python /app/test_system.py && python /app/test_agent.py && python /app/test_top_team_limit.py && python /app/test_reasoning.py"
	@echo ""

test-e2e-setup:
	@echo "🎭 Installing frontend dev dependencies and Chromium (one-time, needs network)..."
	cd frontend && PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring poetry install --with dev --no-root && poetry run playwright install chromium
	@echo "✅ e2e lane ready. Run: make test-e2e"

test-e2e:
	@echo "🎭 Running the offline stub-backed Playwright lane..."
	cd frontend && poetry run pytest tests_e2e -x -q
	@echo ""

clean:
	@echo "🧹 Cleaning temporary files..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@echo "✅ Cleanup complete"

fetch-data: generate-env
	@echo "🔄 Starting manual XLSM fetch..."
	$(DOCKER_COMPOSE) exec -T data_collector python fetch_pipeline.py

fetch-data-log:
	@echo "📜 Fetch log since last run start (Ctrl+C to stop)..."
	$(DOCKER_COMPOSE) logs data_collector | awk '/Fetch started at/ { output = "" } { output = output $$0 ORS } END { printf "%s", output }'
