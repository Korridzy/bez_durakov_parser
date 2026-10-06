DOCKER_COMPOSE ?= docker compose
# The Compose command without file arguments. DOCKER_COMPOSE is rebuilt below from it and
# the ordered file list, so a DOCKER_COMPOSE given on the command line still picks the binary.
DOCKER_COMPOSE_BIN := $(DOCKER_COMPOSE)

# Release switch. RELEASE_COMPOSE names the generated per-release pin file that holds every
# service's image digest; with it the production overlay docker-compose.prod.yml applies.
# TEST_IMAGE_COMPOSE (CI only) names a file that replaces the backend, collector and frontend
# builds with prebuilt candidate images while the source mounts stay in place.
RELEASE_COMPOSE ?=
TEST_IMAGE_COMPOSE ?=

# Compose files in merge order. Make splits words on spaces, so a path taken from a variable
# is kept quoted in the list with its spaces stored as "|", and compose_with restores them.
empty :=
space := $(empty) $(empty)
compose_path = "$(subst $(space),|,$(strip $(1)))"
compose_with = $(DOCKER_COMPOSE_BIN) $(subst |,$(space),$(addprefix -f ,$(1)))
override COMPOSE_FILES := docker-compose.yml
ifneq ($(strip $(RELEASE_COMPOSE)),)
override COMPOSE_FILES += docker-compose.prod.yml
endif
ifneq ($(strip $(TEST_IMAGE_COMPOSE)),)
override COMPOSE_FILES += $(call compose_path,$(TEST_IMAGE_COMPOSE))
endif

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
override COMPOSE_FILES += docker-compose.dataset.yml
# A dataset may ship its own Compose fragment, which is how it joins the backend to the
# network its database already runs on. It stays in the dataset directory, so this
# repository knows nothing about any particular database topology. The existence check goes
# through the shell rather than $(wildcard), which would split a path containing spaces.
DATASET_COMPOSE_FILE ?= $(DATASET_DIR)/webreport.compose.yml
ifneq ($(shell test -f "$(DATASET_COMPOSE_FILE)" && echo found),)
override COMPOSE_FILES += $(call compose_path,$(DATASET_COMPOSE_FILE))
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

# The pin file comes last, so its image digests win over every file before it.
ifneq ($(strip $(RELEASE_COMPOSE)),)
override COMPOSE_FILES += $(call compose_path,$(RELEASE_COMPOSE))
endif
# override, because a DOCKER_COMPOSE given on the command line would otherwise win and
# silently start the base topology against the dataset or release files. With the base file
# alone the bare command stays, so Compose keeps its own default file discovery as before.
override DOCKER_COMPOSE := $(if $(filter-out docker-compose.yml,$(COMPOSE_FILES)),$(call compose_with,$(COMPOSE_FILES)),$(DOCKER_COMPOSE_BIN))

# Persistent host paths. Unset, Compose falls back to ../vm and ../xlsm_archive exactly as
# before; a CI run or a second checkout points them at its own scratch directories.
BD_VM_DIR ?=
BD_XLSM_ARCHIVE_DIR ?=
ifneq ($(strip $(BD_VM_DIR)),)
export BD_VM_DIR
endif
ifneq ($(strip $(BD_XLSM_ARCHIVE_DIR)),)
export BD_XLSM_ARCHIVE_DIR
endif
VM_DIR = $(if $(strip $(BD_VM_DIR)),$(BD_VM_DIR),../vm)

COMPOSE_TEST = $(call compose_with,$(COMPOSE_FILES) docker-compose.test.yml)
CASE_FILE ?=
ARCHIVE_USER = $(if $(filter command line,$(origin USER)),$(strip $(USER)))

# Keep this tag equal to the exact @playwright/test version in ui/package.json.
# mcr.microsoft.com/playwright:v1.55.0-noble, resolved 2026-10-06
PLAYWRIGHT_IMAGE ?= mcr.microsoft.com/playwright:v1.55.0-noble@sha256:b27e719ecbfef153e13fd24e8341736733bf2658b229677eb21ff57ff5d7fb29
# Per-run names, so two runs on one host share neither a container name nor npm dependencies.
# The defaults keep the shell PID suffix and the shared volume used so far.
E2E_RUN_ID ?= $$$$
E2E_NODE_MODULES_VOLUME ?= webreport-ui-node-modules
UI_E2E_RUN = docker run --rm --init --name sdae18-ui-e2e-$(E2E_RUN_ID) -v "$(abspath ui)":/work -v $(E2E_NODE_MODULES_VOLUME):/work/node_modules -w /work --network none -e CI=1 $(PLAYWRIGHT_IMAGE)
UI_E2E_RUN_WITH_NETWORK = docker run --rm --init --name sdae18-ui-e2e-setup-$(E2E_RUN_ID) -v "$(abspath ui)":/work -v $(E2E_NODE_MODULES_VOLUME):/work/node_modules -w /work -e CI=1 $(PLAYWRIGHT_IMAGE)
E2E_ARGS ?=

.PHONY: help generate-env validate-knowledge validate-tools archive-list archive-show archive-delete test-live-scope-eval test test-proxy-contract test-postgres test-ui test-e2e-setup test-e2e clean start stop restart logs build rebuild fetch-data fetch-data-log release-config release-pull release-up release-run release-start release-stop compose

# Release-scoped targets for the deploy executor. SERVICES and SERVICE are checked by Make
# before any shell sees them. The checks read the raw text through $(value), so Make never
# expands it, and accept only service names separated by single spaces: Make splits words
# on any whitespace, so the raw text must equal its own allowlisted words rejoined, which
# refuses a newline, carriage return or tab. Recipes then expand only those allowlisted
# words, never the raw text.
# RUN_ARGS, CMD, CONFIG_ARGS and ARGS are free-form by design: they come from the operator
# or the deploy executor, never from SERVICES, and are trusted. They are passed through
# $(value) unexpanded, and a line break or carriage return in them is refused, so one value
# can never become a second shell command.
RELEASE_SERVICE_NAMES := mysql litellm backend data_collector frontend
define newline


endef
carriage_return := $(shell printf '\r')
release_services = $(filter $(RELEASE_SERVICE_NAMES),$(value SERVICES))
release_service = $(filter $(RELEASE_SERVICE_NAMES),$(value SERVICE))
release_unknown_services = $(filter-out $(RELEASE_SERVICE_NAMES),$(value SERVICES))
# Non-empty when both texts are identical.
release_same = $(and $(findstring $(1),$(2)),$(findstring $(2),$(1)))
release_multiline = $(strip $(foreach v,$(1),$(if $(or $(findstring $(newline),$(value $(v))),$(findstring $(carriage_return),$(value $(v)))),$(v))))
release_require_single_line = $(if $(call release_multiline,$(1)),$(error $(call release_multiline,$(1)) must not contain a line break or carriage return))
define release_require_services
$(if $(strip $(value SERVICES)),,$(error Usage: make $@ SERVICES='<service> ...' with services from: $(RELEASE_SERVICE_NAMES)))
$(if $(release_unknown_services),$(error SERVICES names unknown services: $(release_unknown_services); known services: $(RELEASE_SERVICE_NAMES)))
$(if $(call release_same,$(value SERVICES),$(release_services)),,$(error SERVICES must be service names separated by single spaces with no other whitespace))
endef
define release_require_service
$(if $(and $(filter 1,$(words $(value SERVICE))),$(release_service),$(call release_same,$(value SERVICE),$(release_service))),,$(error Usage: make $@ SERVICE=<one of: $(RELEASE_SERVICE_NAMES)> [RUN_ARGS='...'] [CMD='...']))
$(call release_require_single_line,RUN_ARGS CMD)
endef
define release_require_compose
$(if $(strip $(RELEASE_COMPOSE)),,$(error $@ needs RELEASE_COMPOSE=<per-release pin file>))
endef

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
	@echo "Release (RELEASE_COMPOSE=<per-release pin file>, driven by the deploy executor):"
	@echo "  make release-config [CONFIG_ARGS='-q' or '--format json'] - Render the release configuration"
	@echo "  make release-pull SERVICES='<service> ...'  - Pull each pinned image explicitly and inspect it"
	@echo "  make release-up SERVICES='<service> ...'    - Recreate only these services, never build or pull"
	@echo "  make release-run SERVICE=<service> [RUN_ARGS='...'] [CMD='...'] - One-off container"
	@echo "                    (without RELEASE_COMPOSE only with ALLOW_DEV_COMPOSE=1)"
	@echo "  make release-start SERVICES='<service> ...' - Start these stopped services"
	@echo "  make release-stop SERVICES='<service> ...'  - Stop these services"
	@echo "  make compose ARGS='...' - Run docker compose with the selected file list"
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
	[ -d "$(VM_DIR)/backend/checkpoints" ] || mkdir -p "$(VM_DIR)/backend/checkpoints"
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

release-config:
	$(call release_require_single_line,CONFIG_ARGS)
	@$(DOCKER_COMPOSE) config $(value CONFIG_ARGS)

# compose pull skips services under pull_policy: never, so each pinned image is pulled by
# its rendered reference instead.
release-pull:
	$(release_require_services)
	@config=$$($(DOCKER_COMPOSE) config --format json) || exit 1; \
	for service in $(release_services); do \
	  ref=$$(printf '%s\n' "$$config" | jq -r --arg service "$$service" '.services[$$service].image // empty') || exit 1; \
	  if [ -z "$$ref" ]; then echo "❌ release-pull: service $$service has no image in the rendered configuration" >&2; exit 1; fi; \
	  echo "⬇️  $$service: $$ref"; \
	  docker pull "$$ref" || exit 1; \
	  docker image inspect --format '{{.Id}}' "$$ref" || exit 1; \
	done

release-up:
	$(release_require_compose)
	$(release_require_services)
	$(DOCKER_COMPOSE) up -d --no-deps --no-build --pull never $(release_services)

release-run:
	$(if $(or $(strip $(RELEASE_COMPOSE)),$(filter 1,$(ALLOW_DEV_COMPOSE))),,$(error release-run needs RELEASE_COMPOSE=<per-release pin file> or ALLOW_DEV_COMPOSE=1))
	$(release_require_service)
	$(DOCKER_COMPOSE) run --rm --no-deps $(value RUN_ARGS) $(release_service) $(value CMD)

release-start:
	$(release_require_services)
	$(DOCKER_COMPOSE) start $(release_services)

release-stop:
	$(release_require_services)
	$(DOCKER_COMPOSE) stop $(release_services)

compose:
	$(call release_require_single_line,ARGS)
	@$(DOCKER_COMPOSE) $(value ARGS)
