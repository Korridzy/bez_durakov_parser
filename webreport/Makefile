DOCKER_COMPOSE ?= docker compose

# Dataset switch. DATASET names a dataset directory kept outside this repository, by
# default ../range/$(DATASET); override DATASET_DIR with an absolute path when the
# directory lives elsewhere, which is the normal case on Windows. With DATASET unset every
# target below behaves exactly as before and serves bez_durakov from the bundled MySQL.
DATASET ?=
ifneq ($(strip $(DATASET)),)
DATASET_DIR ?= $(abspath ../range/$(DATASET))
BD_CONFIG_LOCAL_FILE ?= $(DATASET_DIR)/config/config.local.toml
export DATASET
export DATASET_DIR
export BD_CONFIG_LOCAL_FILE
# override, because a DOCKER_COMPOSE given on the command line would otherwise win and
# silently start the base topology against the dataset config.
override DOCKER_COMPOSE := $(DOCKER_COMPOSE) -f docker-compose.yml -f docker-compose.dataset.yml
# A dataset may ship its own Compose fragment, which is how it joins the backend to the
# network its database already runs on. It stays in the dataset directory, so this
# repository knows nothing about any particular database topology. The existence check goes
# through the shell rather than $(wildcard), which would split a path containing spaces.
DATASET_COMPOSE_FILE ?= $(DATASET_DIR)/webreport.compose.yml
ifneq ($(shell test -f "$(DATASET_COMPOSE_FILE)" && echo found),)
override DOCKER_COMPOSE := $(DOCKER_COMPOSE) -f "$(DATASET_COMPOSE_FILE)"
endif
COMPOSE_SERVICES := litellm backend frontend
COMPOSE_BUILD_SERVICES := backend frontend
define dataset_preflight
@test -d "$(DATASET_DIR)" || { echo "❌ DATASET=$(DATASET): no dataset directory at $(DATASET_DIR)"; exit 1; }
@test -f "$(BD_CONFIG_LOCAL_FILE)" || { echo "❌ DATASET=$(DATASET): no config overlay at $(BD_CONFIG_LOCAL_FILE)"; exit 1; }
@echo "📦 Dataset: $(DATASET) ($(DATASET_DIR))"
endef
else
COMPOSE_SERVICES :=
COMPOSE_BUILD_SERVICES :=
define dataset_preflight
@:
endef
endif

COMPOSE_TEST = $(DOCKER_COMPOSE) -f docker-compose.yml -f docker-compose.test.yml
CASE_FILE ?=
ARCHIVE_USER = $(if $(filter command line,$(origin USER)),$(strip $(USER)))

# Keep this tag equal to the exact @playwright/test version in ui/package.json.
PLAYWRIGHT_IMAGE ?= mcr.microsoft.com/playwright:v1.55.0-noble
UI_E2E_RUN = docker run --rm --init --name sdae18-ui-e2e-$$$$ -v "$(abspath ui)":/work -v webreport-ui-node-modules:/work/node_modules -w /work --network none -e CI=1 $(PLAYWRIGHT_IMAGE)
UI_E2E_RUN_WITH_NETWORK = docker run --rm --init --name sdae18-ui-e2e-setup-$$$$ -v "$(abspath ui)":/work -v webreport-ui-node-modules:/work/node_modules -w /work -e CI=1 $(PLAYWRIGHT_IMAGE)
E2E_ARGS ?=

.PHONY: help generate-env validate-knowledge validate-tools archive-list archive-show archive-delete test-live-scope-eval test test-proxy-contract test-postgres test-ui test-e2e-setup test-e2e clean start stop restart logs build rebuild fetch-data fetch-data-log

help:
	@echo "🎮 Web Reporting System - Docker Commands"
	@echo "=========================================="
	@echo ""
	@echo "Docker Operations:"
	@echo "  make generate-env - Generate Compose and service env files"
	@echo "  make start DATASET=<name> - Start against the dataset in ../range/<name>"
	@echo "                              (add DATASET_DIR=<abs path> when it lives elsewhere)"
	@echo "  make start       - Build the UI image and start services with Docker Compose"
	@echo "  make stop        - Stop Docker containers"
	@echo "  make validate-knowledge - Validate the configured knowledge folder"
	@echo "  make validate-tools - Validate the configured operator tool module"
	@echo "  make restart     - Validate, build the UI image, then recreate application services"
	@echo "  make logs        - View logs"
	@echo "  make build       - Build Docker images"
	@echo "  make rebuild     - Validate, rebuild, and restart services"
	@echo ""
	@echo "Testing:"
	@echo "  make test                - Run the offline backend suite (no running stack needed)"
	@echo "  make test-proxy-contract - Prove the LiteLLM Langfuse contract offline"
	@echo "  make test-postgres       - Run the acceptance lane against a throwaway PostgreSQL"
	@echo "  make test-ui             - Build the frontend image with Vitest and TypeScript checks"
	@echo "  make test-e2e-setup      - One-time: pull Playwright and install npm deps in Docker (needs network)"
	@echo "  make test-e2e            - Run offline Chromium in Docker, both motion projects (no host Node)"
	@echo ""
	@echo "Conversation archive:"
	@echo "  make archive-list [SESSION=<id>] [USER=<id>] [LIMIT=<n>]"
	@echo "  make archive-show ID=<id>"
	@echo "  make archive-delete SESSION=<id> | USER=<id> | BEFORE=<ISO-date-or-timestamp>"
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
	$(dataset_preflight)
	[ -d ../vm/backend/checkpoints ] || mkdir -p ../vm/backend/checkpoints
	PYTHONPATH="$(abspath ..)" poetry run python generate_env.py

start: generate-env
	@echo "🐳 Starting services with Docker Compose..."
	$(DOCKER_COMPOSE) up -d --build $(COMPOSE_SERVICES)
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

validate-knowledge:
	@echo "🔎 Validating the configured knowledge folder..."
	$(DOCKER_COMPOSE) run --rm --no-deps backend python -m agent.knowledge_cli

validate-tools:
	@echo "🔎 Validating the configured operator tool module..."
	$(DOCKER_COMPOSE) run --rm --no-deps backend python -m agent.tools_cli

archive-list: generate-env
	$(DOCKER_COMPOSE) run --rm --no-deps backend python -m archive_cli list $(if $(strip $(SESSION)),--session "$(SESSION)") $(if $(ARCHIVE_USER),--user "$(ARCHIVE_USER)") $(if $(strip $(LIMIT)),--limit "$(LIMIT)")

archive-show: generate-env
	$(DOCKER_COMPOSE) run --rm --no-deps backend python -m archive_cli show --id "$(ID)"

archive-delete: generate-env
	@selectors=0; \
	if [ -n "$(strip $(SESSION))" ]; then selectors=$$((selectors + 1)); fi; \
	if [ -n "$(ARCHIVE_USER)" ]; then selectors=$$((selectors + 1)); fi; \
	if [ -n "$(strip $(BEFORE))" ]; then selectors=$$((selectors + 1)); fi; \
	if [ "$$selectors" -ne 1 ]; then \
		echo "Usage: make archive-delete SESSION=<id> | USER=<id> | BEFORE=<ISO-date-or-timestamp>" >&2; \
		exit 2; \
	fi
	$(DOCKER_COMPOSE) run --rm --no-deps backend python -m archive_cli delete $(if $(strip $(SESSION)),--session "$(SESSION)") $(if $(ARCHIVE_USER),--user "$(ARCHIVE_USER)") $(if $(strip $(BEFORE)),--before "$(BEFORE)")

test-live-scope-eval:
	@echo "🔎 Running the live dataset scope evaluation..."
	$(DOCKER_COMPOSE) run --rm --no-deps backend python -m test_live_scope_eval.driver $(CASE_FILE)

restart: generate-env validate-knowledge validate-tools
	@echo "🔄 Recreating LiteLLM, backend, and frontend..."
	$(DOCKER_COMPOSE) up -d --build --force-recreate litellm backend frontend
	@echo "✅ Application services recreated"

logs:
	$(DOCKER_COMPOSE) logs -f $(SERVICE)

build: generate-env
	@echo "🔨 Building Docker images..."
	$(DOCKER_COMPOSE) build $(COMPOSE_BUILD_SERVICES)
	@echo "✅ Build complete"

rebuild: generate-env validate-knowledge validate-tools
	@echo "🔨 Rebuilding and restarting services..."
	$(DOCKER_COMPOSE) down
	$(DOCKER_COMPOSE) build $(COMPOSE_BUILD_SERVICES)
	$(DOCKER_COMPOSE) up -d $(COMPOSE_SERVICES)
	@echo "✅ Services rebuilt and started"

test: generate-env
	@echo "🧪 Running tests in Docker..."
	$(DOCKER_COMPOSE) run --rm --no-deps -e BD_CHECKPOINT_DB_PATH=/tmp/test-checkpoints.db -e BD_ARCHIVE_DB_PATH=/tmp/test-conversations.db -e BD_CHATS_DB_PATH=/tmp/test-chats.db backend sh -c "python /app/test_system.py && python /app/test_agent.py && python /app/test_reasoning.py && python /app/test_knowledge_cli.py && python /app/test_tools_cli.py && python /app/test_request_context.py && python /app/test_agent_correlation.py && python /app/test_archive_store.py && python /app/test_archive_api.py && python /app/test_archive_cli.py && \
	  python /app/test_chat_store.py && \
	  python /app/test_runs.py && \
	  python /app/test_chat_routes.py && \
	  python /app/test_report_routes.py"
	$(DOCKER_COMPOSE) run --rm --no-deps -e BD_CHECKPOINT_DB_PATH=/tmp/test-checkpoints.db -e BD_ARCHIVE_DB_PATH=/tmp/test-conversations.db -e BD_CHATS_DB_PATH=/tmp/test-chats.db -e BD_CONFIG_FILE=test_config_sqlite.toml backend python /app/test_acceptance_swap.py
	$(MAKE) test-proxy-contract
	$(MAKE) test-postgres
	@echo ""

test-proxy-contract: generate-env
	@echo "🔭 Proving the LiteLLM Langfuse correlation contract offline..."
	$(DOCKER_COMPOSE) run --rm --no-deps --entrypoint python -e LITELLM_LOCAL_MODEL_COST_MAP=True -e BD_CHATS_DB_PATH=/tmp/test-chats.db -v "$(abspath backend/test_langfuse_proxy_contract.py):/app/test_langfuse_proxy_contract.py:ro" litellm /app/test_langfuse_proxy_contract.py

test-postgres: generate-env
	@echo "🐘 Running the PostgreSQL acceptance lane..."
	@set +e; \
	 $(COMPOSE_TEST) up -d --wait postgres_test; \
	 status=$$?; \
	 if [ $$status -eq 0 ]; then \
	   $(COMPOSE_TEST) run --rm -e BD_CHECKPOINT_DB_PATH=/tmp/test-checkpoints.db -e BD_ARCHIVE_DB_PATH=/tmp/test-conversations.db -e BD_CHATS_DB_PATH=/tmp/test-chats.db -e BD_CONFIG_FILE=test_config_postgres.toml backend python /app/test_acceptance_swap.py; \
	   status=$$?; \
	 fi; \
	 $(COMPOSE_TEST) rm -fsv postgres_test; \
	 exit $$status

test-ui:
	$(DOCKER_COMPOSE) build frontend

test-e2e-setup:
	@echo "🎭 Installing the pinned Playwright image and npm dependencies in Docker..."
	docker pull $(PLAYWRIGHT_IMAGE)
	$(UI_E2E_RUN_WITH_NETWORK) npm ci --no-audit --no-fund
	@echo "✅ e2e lane ready. Run: make test-e2e"

test-e2e:
	@echo "🎭 Running the offline stub-backed Playwright lane..."
	$(UI_E2E_RUN) npx --no-install playwright test $(E2E_ARGS)
	@echo ""

clean:
	@echo "🧹 Cleaning temporary files..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@echo "✅ Cleanup complete"

fetch-data: generate-env
	@if [ -n "$(strip $(DATASET))" ]; then \
		echo "❌ fetch-data collects bez_durakov XLSM files; it does not apply to DATASET=$(DATASET)"; \
		exit 1; \
	fi
	@echo "🔄 Starting manual XLSM fetch..."
	$(DOCKER_COMPOSE) run --rm --no-deps data_collector python fetch_pipeline.py

fetch-data-log:
	@echo "📜 Fetch log since last run start (Ctrl+C to stop)..."
	$(DOCKER_COMPOSE) logs data_collector | awk '/Fetch started at/ { output = "" } { output = output $$0 ORS } END { printf "%s", output }'
