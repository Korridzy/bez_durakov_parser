# PROJECT KNOWLEDGE BASE

**Generated:** 2026-03-06T14:48:54Z
**Commit:** 1d45d80
**Branch:** issue-86-create-ai-webreport

## OVERVIEW

Parser for "Без дураков. Белград." board game series results. Parses XLSM game files → MySQL via SQLAlchemy ORM. Includes a web reporting subsystem with FastAPI, React/nginx, a LangGraph ReAct agent, `ChatLiteLLM` and its LiteLLM SDK in the backend image, LiteLLM proxy, and SQLite checkpoints. `langchain-openai` is not a current backend dependency.

## STRUCTURE

```
parser/
├── bd_shared/          # Core shared library: ORM models, config, game data structure, DB helpers
├── data_to_parse/      # Input XLSM files (gitignored)
├── doc/                # ORM docs, data structure docs
├── deploy/             # Server-local executor, promotion, isolation and local rehearsal
├── examples/           # Analysis examples using ORM (four_buckets.py)
├── migrations/         # Alembic DB migrations (MySQL)
├── range/              # Utility scripts for statistics/calendars (gitignored)
├── secret/             # Credentials (gitignored)
├── vm/                 # MySQL volume and three backend-owned SQLite stores (gitignored)
├── webreport/          # Web reporting: FastAPI + React/nginx + LangGraph (see webreport/AGENTS.md)
├── xlsm_archive/       # Fetched XLSM files storage (gitignored)
├── parse_data.py       # CLI entry point: parse XLSM → DB
├── clear_database.py   # Utility: wipe all game data from DB
├── Makefile            # setup, upgrade-db, upgrade-code, webreport-start/stop, mysql-start/stop
├── pyproject.toml      # Poetry config (package-mode=false), Python 3.11+
└── alembic.ini         # Alembic migration config (script_location=migrations)
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Parse XLSM files | `parse_data.py` → `bd_shared/bd_game.py` | `BdGame.parse_from_file()` does the heavy lifting |
| DB models / ORM | `bd_shared/db.py` | SQLAlchemy models: Game, Team, GameTeam, Vybor, Chisla, Pref, Pairs, Razobl, Auction, Mot |
| Add game to DB | `bd_shared/db_helpers.py` | `save_game_to_database()` with duplicate detection |
| Configuration | `bd_shared/config.toml` + `bd_shared/config.py` | TOML config loaded via `tomllib`. Override with `BD_CONFIG_FILE` env var. The `[dataset]` section names the operator tool module and the knowledge folder |
| Operator knowledge | `bd_shared/knowledge/` + `webreport/backend/agent/knowledge.py` | `load_knowledge()` reads the manifest and topics; `read_knowledge` returns topic text on demand. `dataset.knowledge_dir` points at the folder. The manifest supplies the agent persona and dataset scope |
| DB migrations | `migrations/versions/` | Alembic, MySQL-only. `make upgrade-db` to apply |
| Releases and deployment | `deploy/`, `.github/workflows/`, [webreport/DEPLOYMENT.md](webreport/DEPLOYMENT.md) | CI tests PRs/main, publishes passing main candidates; release promotion keeps tested digests; server-local deploy, rollback and isolation |
| Fetch XLSM | `webreport/data_collector/` | Dockerized service using APScheduler. `make fetch-data` triggers manual fetch. `make fetch-data-log` shows logs since last run |
| Web reporting | `webreport/` | FastAPI + React/nginx + LangGraph through ChatLiteLLM and the internal LiteLLM proxy; separate subsystem with its own `AGENTS.md` |
| Chats and reports | `webreport/backend/chat_store.py`, `runs.py`, `chat_routes.py`, `report_routes.py` | Durable transcripts, cancellable runs and saved report replay; `[webreport].chats_db_path` defaults to `/data/chats.db`, `BD_CHATS_DB_PATH` overrides it |
| UI | `webreport/ui/src/` | React client served from a built nginx image, no UI source mount |
| Conversation archive | `webreport/backend/archive.py` + `archive_cli.py` | fail-open, independent of checkpoints, CLI-only deletion |
| Logging | `bd_shared/logging_setup.py` | Shared structlog and standard-library pipeline. Entry points configure it once per process |
| Serve another dataset | `make webreport-start DATASET=<name>` | Reads `DATASET_DIR` (default `range/<name>`), merges its `config/config.local.toml` over the tracked config and mounts it at `/dataset` in the backend |
| Analysis examples | `examples/four_buckets.py` | Shows ORM usage for custom analysis |

## CONVENTIONS

- **Language**: Python 3.11+ with Poetry for the parser and backend; React 19 + TypeScript + Vite in `webreport/ui/` uses npm.
- **Game data and the parser**: MySQL 8.0 only, connected via `pymysql`. The webreport backend is not restricted this way, since it serves whatever MySQL, PostgreSQL or SQLite database `[database]` and `[dataset]` name
- **Agent checkpoints**. Backend-owned SQLite stores: checkpoints, the conversation archive and the chat/report store at `../vm/backend/checkpoints`; none is a game-data store.
- **Config**: TOML-based (`bd_shared/config.toml`). Test config: `bd_shared/test_config.toml`
- **Logging**. Libraries never call `basicConfig`; entry points call `configure_logging`.
- **Team names**: Always normalized via `normalize_team_name()` — NFC unicode, lowercase, whitespace-collapsed
- **Game data**: All game data flows through `BdGame` dataclass. Never access raw XLSM directly after parsing
- **Imports**: Use `from bd_shared.db import Database` not `from bd_shared import *`
- **Tests**: No test framework configured. Tests are standalone scripts (`test_alembic_migration.py`, `webreport/test_system.py`)
- **CI and releases**: GitHub Actions runs the full root `make test` on PRs and main. Passing main pushes publish candidates; stable GitHub Releases promote the same digests. The server pulls through `deploy/deploy.sh`; GitHub never contacts it. See [DEPLOYMENT.md](webreport/DEPLOYMENT.md).
- **Monorepo-ish**: Root + `webreport/` have separate `pyproject.toml`. No Poetry workspaces — managed via Docker Compose for web components
- **Knowledge**: The configured folder is read once at backend startup, and its manifest supplies the agent persona and dataset scope

## ANTI-PATTERNS (THIS PROJECT)

- Never run `make test` or `make rebuild` on the server. Tests and builds belong to development and disposable CI runners.
- Never add server identifiers or credentials to tracked files, shared logs, workflows, releases, artifacts or image labels.
- **DO NOT** add SQLite support for game data, which remains MySQL-only (see issue-61). Backend-owned SQLite stores: checkpoints, the conversation archive and the chat/report store at `../vm/backend/checkpoints`; none is a game-data store. An operator may configure a webreport dataset with SQLite.
- **DO NOT** access the game database directly from this repository's own web components — go through `bd_shared/db.py` and `bd_shared/db_helpers.py`. An operator's own tool module reaches its database directly by design.
- **DO NOT** bypass `normalize_team_name()` when storing/comparing team names
- **DO NOT** put dataset queries in the backend. They belong in the operator tool module named by `dataset.tools_module`, which receives the engine the backend built and made read-only.
- `webreport/backend/agent/` and `webreport/backend/agents/` must never write dataset SQL of their own; they discover their tools from the operator module. The only sanctioned exception is the checkpoint saver’s own thread-recency enumeration query against its `checkpoints` table.
- **DO NOT** hardcode a dataset persona or scope in agent code; put them in the knowledge manifest
- **DO NOT** call `basicConfig` from a library. Process entry points own `configure_logging`.

## COMMANDS

```bash
make setup              # Create .venv, install Poetry deps
make upgrade-db         # Run Alembic migrations (poetry run alembic upgrade head)
make upgrade-code       # Pull from main, preserve config.toml
make webreport-start    # Start full stack: MySQL + FastAPI + React/nginx (Docker)
make webreport-start DATASET=<name>             # Development: serve another dataset
make webreport-start DATASET=<name> DATASET_DIR=<absolute-path> # Dataset stored elsewhere
make webreport-stop     # Stop web stack
make mysql-start        # Start MySQL container only
make mysql-stop         # Stop MySQL container
poetry run python parse_data.py <dir>           # Parse XLSM files in directory
poetry run python parse_data.py <dir> --no-save # Parse without saving to DB
make fetch-data                                  # Manually trigger XLSM fetch in data_collector container
make fetch-data-log                              # Show logs since last fetch start
make logs SERVICE=data_collector                 # Show all data_collector container logs
cd webreport && make rebuild                     # Rebuild after backend dependency changes
cd webreport && make test-ui                     # Build UI image, run Vitest and TypeScript/Vite build
cd webreport && make test-e2e-setup               # Pull pinned Playwright image and install npm dependencies in Docker
cd webreport && make test-e2e                     # Offline Playwright chat/report/reasoning/layout tests
cd webreport && make restart                     # Build UI image and recreate application services after UI edits
```

Release commands run from root; the executor doesn't support DATASET:

```bash
make deploy VERSION=v0.1.0 DEPLOY_ARGS="--llm-smoke"
make rollback DEPLOY_ARGS="--llm-smoke"
make deploy-smoke DEPLOY_ARGS="--llm-smoke"
make deploy-verify-isolation DEPLOY_ARGS=--container-probe
```

`make deploy-status` prints a read-only report of the executor state (`DEPLOY_ARGS=--json` for JSON) and takes no lock. Make collapses recipe failures to exit 2; deployment JSON stderr carries the executor code. Default local state, logs and backups are under `vm/deploy/`.

## NOTES

- `env/` in root is a stale virtualenv (gitignored) — project uses `.venv/` via Poetry
- `xlsm_archive/` stores 178+ XLSM files — all gitignored except `.gitkeep`
- `range/` is entirely gitignored — contains ad-hoc analysis scripts and reports
- Game rounds: Выбор (vybor), Числа (chisla), Преферанс (pref), Пары (pairs), Разоблачение (razobl), Аукцион (auction), Момент Истины (mot)
- `BD_LOG_*` configures logging. `BD_ENVIRONMENT` and `BD_APP_VERSION` attach static fields. `X-Request-ID` follows each HTTP request through backend processing.
- Default game date `02.03.2022` in config triggers a warning — means date was not set in the source file
- The agent's persona and dataset scope come from the knowledge manifest, not from code. With dataset knowledge loaded, each chat turn passes the dataset scope gate before the ReAct agent runs.
- `DATASET` selects a dataset directory that lives outside the repository. It supplies its own config overlay (`config/config.local.toml`, exported as `BD_CONFIG_LOCAL_FILE`), tool module, knowledge folder and an optional `webreport.compose.yml` that connects the backend to the network its database runs on. With `DATASET` set only LiteLLM, backend and frontend start, the three SQLite stores move to `checkpoints-<name>.db`, `conversations-<name>.db` and `chats-<name>.db`, and `upgrade-db`, `mysql-start`, `mysql-stop`, `fetch-data` and `fetch-data-log` refuse to run. With `DATASET` unset nothing changes. One dataset is served at a time: the Compose project is the same one, so `make webreport-stop` takes the whole stack down whichever dataset it was serving.
- At backend startup, a deep LiteLLM probe decides whether the agent can be built. When no model is reachable the process stays up and refuses to serve: `/health` and `/api/chat` answer 503. Each later chat attempt re-probes once, and the first healthy verdict builds the agent and answers that same request.
- LiteLLM is internal-only at `litellm:4000`. The checkpoint-backed backend is limited to one replica.
- ChatLiteLLM (`langchain-litellm >=0.7,<0.8`) is the backend model client. Its LiteLLM SDK is deliberately installed in the backend image, reversing the prior SDK-out-of-image rule. The manifest keeps that version range with a dependency-level Python `<3.15` marker because the literal range was not lockable under the project Python bound; the shipped image uses Python 3.11.
- Reasoning round-trip is always on: `OutboundReasoningFilter` echoes reasoning only within the current user turn, while checkpoints retain all turns. `ChatResponse.reasoning` and `/api/history` carry it to the collapsed frontend labels «Рассуждения» and, for recovered failed requests, «Рассуждения (неполные)». No reasoning means no block.
- Anthropic-style thinking models are unsupported because `thinking_blocks` do not round-trip. There is no configuration switch for this. LiteLLM is digest-pinned from `main-stable`; future digest updates and the young community package `langchain-litellm` can change behavior. The minor-range pin and AC-1 echo tripwire are the mitigations.
- Chats, messages (including reasoning), runs and reports live in `chats.db` with no TTL. Only one run per chat may be active. Stop before publication persists «Запрос отменён»; an already completed answer stays intact. A server restart marks unfinished runs interrupted. Checkpoint expiry does not remove the stored transcript. `/api/clear` removes transcript and runs but keeps the chat and reports. Deleting a chat keeps saved reports as orphans.
- The conversation archive has its own SQLite file. Checkpoint TTL, LRU eviction, `/api/history`, and `/api/clear` do not modify archive rows. `archive_retention_days` and `archive_reasoning_retention_days` set the archive and reasoning retention windows. `0` keeps the applicable data forever.
- LiteLLM uses `langfuse_otel` only when `langfuse_host`, `langfuse_public_key`, and `langfuse_secret_key` are all non-empty. Correlation uses `traceparent` and metadata.
