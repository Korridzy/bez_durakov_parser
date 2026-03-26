.PHONY: help test clean start stop restart logs build rebuild fetch-data fetch-data-log

help:
	@echo "🎮 Web Reporting System - Docker Commands"
	@echo "=========================================="
	@echo ""
	@echo "Docker Operations:"
	@echo "  make start       - Start services with Docker Compose"
	@echo "  make stop        - Stop Docker containers"
	@echo "  make restart     - Restart services"
	@echo "  make logs        - View logs"
	@echo "  make build       - Build Docker images"
	@echo "  make rebuild     - Rebuild and restart services"
	@echo ""
	@echo "Testing:"
	@echo "  make test        - Run tests (requires running containers)"
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

start:
	@echo "🐳 Starting services with Docker Compose..."
	poetry run python generate_env.py
	docker-compose up -d
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
	docker-compose down
	@echo "✅ Containers stopped"

restart:
	@echo "🔄 Restarting services..."
	docker-compose restart
	@echo "✅ Services restarted"

logs:
	docker-compose logs -f $(SERVICE)

build:
	@echo "🔨 Building Docker images..."
	docker-compose build
	@echo "✅ Build complete"

rebuild:
	@echo "🔨 Rebuilding and restarting services..."
	poetry run python generate_env.py
	docker-compose down
	docker-compose build
	docker-compose up -d
	@echo "✅ Services rebuilt and started"

test:
	@echo "🧪 Running tests in Docker..."
	docker-compose run --rm backend python /app/test_system.py
	@echo ""

clean:
	@echo "🧹 Cleaning temporary files..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@echo "✅ Cleanup complete"

fetch-data:
	@echo "🔄 Starting manual XLSM fetch..."
	docker-compose exec -T data_collector python fetch_pipeline.py

fetch-data-log:
	@echo "📜 Fetch log since last run start (Ctrl+C to stop)..."
	docker-compose logs data_collector | tac | sed '/Fetch started at/q' | tac
