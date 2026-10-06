# webreport — Web Reporting System

## OVERVIEW

SOA web system: React/nginx chat UI → FastAPI REST API → a dataset scope gate before the LangGraph ReAct agent when knowledge is loaded → the operator tool module named by `dataset.tools_module` → the configured database. LiteLLM is internal-only at `litellm:4000`; the backend owns separate SQLite checkpoint, archive and chat/report stores at `../vm/backend/checkpoints`.

## STRUCTURE

```
webreport/
├── backend/
│   ├── main.py                        # FastAPI app, legacy endpoints, Pydantic models
│   ├── chat_store.py                  # Durable chats, messages, runs and reports
│   ├── runs.py                        # Cancellable run executor and archive writer
│   ├── chat_routes.py                 # Chat CRUD, messages, status and cancellation
│   ├── report_routes.py               # Reports, bookmarks and deterministic Update
│   ├── api_errors.py                  # New-route error envelope
│   ├── archive.py                     # Durable conversation archive, independent of checkpoints
│   ├── archive_cli.py                 # CLI-only archive administration
│   ├── request_context.py             # ASGI request ID middleware and request logs
│   ├── agents/report_runtime.py       # LangGraph report agent over the discovered tools
│   ├── agent/toolmodule.py            # Loads the operator module and discovers its tools
│   ├── agent/correlation.py           # LiteLLM metadata and request header correlation
│   ├── agent/engine.py                # Builds the one engine, read-only per dialect
│   └── ../bd_shared/tools/bez_durakov.py  # The default operator module for this deployment
├── ui/
│   ├── src/                           # React/TypeScript: chats, reports, saved, layout
│   ├── tests_e2e/                     # Offline Playwright API stub lane
│   ├── package.json                   # npm dependencies and Vitest/Vite scripts
│   └── nginx.conf                     # SPA serving and /api/ proxy
├── ARCHIVE.md                         # Archive storage and Langfuse operations
├── DEPLOYMENT.md                      # Releases, server-local deploy, restore and isolation
├── docker-compose.prod.yml            # Production mounts, loopback ports and no builds
├── docker-compose.yml                 # MySQL + backend + frontend on webreport-network
├── Dockerfile.backend                 # Packaged backend, bd_shared and Alembic; dev mounts shadow code
├── Dockerfile.frontend                # Frontend container
├── LOGGING.md                         # Logging, correlation, redaction, and collection guide
├── Makefile                           # start/stop/restart/logs/build/test/clean
├── generate_env.py                    # Writes Compose + per-service env files
├── litellm_settings.generated.yaml    # Generated LiteLLM callback settings, gitignored
├── backend/test_system.py             # unittest-based tests for services, agents, API
└── validate_setup.py                  # Pre-flight checks for deployment
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add API endpoint | `backend/main.py` | FastAPI routes. Pydantic models in same file |
| Add data query | the module named by `dataset.tools_module` | For this deployment that is `bd_shared/tools/bez_durakov.py`. Every public method becomes a tool |
| Modify AI behavior | `backend/agent/knowledge.py` + `backend/main.py` | `compose_system_prompt()` composes the system prompt when startup constructs the agent |
| Read a knowledge topic | `backend/agent/tools.py` | `read_knowledge(topic)` returns loaded Markdown text |
| Model availability | `backend/main.py` | A startup probe decides whether the agent is built; without a model the backend refuses to serve and re-probes on each chat attempt |
| Conversation archive | `backend/archive.py` + `backend/archive_cli.py` | Fail-open storage from the run executor; CLI-only listing, display, and deletion |
| Langfuse | `backend/agent/correlation.py` + `generate_env.py` | `traceparent` and metadata correlate calls; generated settings enable `langfuse_otel` |
| UI changes | `ui/src/` | React Chats and Saved Reports, Vitest + Testing Library |
| Chat/report store | `backend/chat_store.py` | `[webreport].chats_db_path` defaults to `/data/chats.db`; `BD_CHATS_DB_PATH` wins; DATASET uses `/data/chats-<name>.db` |
| Background runs | `backend/runs.py` + `backend/chat_routes.py` | One active run per chat, status polling and cancellation |
| Report Update | `backend/report_routes.py` | Replays stored tool/args, no model call |
| Docker config | `docker-compose.yml` | `bd_shared` mounted read-only at `/bd_shared` |
| Release deployment | `../deploy/`, `../.github/workflows/`, [DEPLOYMENT.md](DEPLOYMENT.md) | Tested main candidates promoted by stable release, server-local executor, digest pins, backups and explicit recovery |
| Serve another dataset | `docker-compose.dataset.yml` + `Makefile` | `make start DATASET=<name>` binds `DATASET_DIR` at `/dataset`, points `BD_CONFIG_LOCAL_FILE` at its overlay, and starts only LiteLLM, backend and frontend |
| Source config | `../bd_shared/config.toml` + `config.local.toml` | Tracked defaults plus ignored server-local overrides in the same sections. `[dataset]` holds `tools_module` and `knowledge_dir`. `[webreport]` sets `agent_scope_gate_model`, which falls back to `agent_model` when empty, and `agent_scope_gate_history_turns`, the number of prior turns the gate may read |
| Generated env | `.env*` + `generate_env.py` | `.env` is Compose-only; each service gets its own file; LiteLLM receives OpenAI, OpenRouter, and OpenCode keys from `.env.litellm` |
| Tests | `backend/test_system.py` | Run via `make test` (Docker) or directly |

## CONVENTIONS

- **CI and releases**: Root `make test` runs on disposable GitHub runners for PRs and main. Passing main candidates are promoted without rebuilding when a stable release is published. The server pulls; no GitHub job connects to it.
- **Production**: `docker-compose.prod.yml` plus generated release pins removes application source mounts, requires the local config file, and disables backend reload/debug. One backend, loopback host ports, no DATASET executor support.
- **Container names**: Compose derives `<project>-<service>-1`. The dev project name is the directory name, normally `webreport`, unless overridden. Use service names in commands.
- **Data access**: this repository's `backend/agent/` and `backend/agents/` never reach the dataset themselves. They discover their tool surface from the object the operator's `build_service(engine)` returns, and the backend injects the one engine it built.
- **Agent tools**: every public method of that object becomes a tool, named after the method, described by its docstring and parameterised by its type hints. A helper that should not be a tool takes a leading underscore, and a property is never a tool.
- **Knowledge prompt**: The prompt is composed at startup, and the configured folder is read exactly once. Its manifest supplies the persona and scope. When knowledge is loaded, the scope gate runs before the agent.
- **Model availability**: a deep LiteLLM probe runs at startup. Without a reachable model the process stays up and refuses to serve, answering 503 from `/health` and `/api/chat`. Each later chat attempt re-probes once, and the first healthy verdict builds the agent and answers that request.
- **Checkpointing**: The backend persists LangGraph threads in its SQLite store at `../vm/backend/checkpoints`. The game data this deployment serves remains MySQL.
- **Backend-owned SQLite stores**: checkpoints, archive and chats are separate files; never cross their tables. They are not game-data stores.
- **Archive.** Only the run executor (`runs.py`) writes archive turns; `/api/chat` and `POST /api/chats/{id}/messages` both go through it. Archive writes fail open. Checkpoint TTL, LRU eviction, and `/api/clear` never touch archive rows.
- **LiteLLM callbacks.** Configure callbacks only through `litellm_settings.generated.yaml`, generated by `generate_env.py`.
- **Backend topology**: Run exactly one backend replica. Shared SQLite checkpoints do not support horizontal backend scaling.
- **Config flow**: `bd_shared/config.toml` + optional `config.local.toml` → `bd_shared/config.py` → `generate_env.py` → Compose/per-service `.env*` files → `docker-compose.yml`
- **ASGI wrapper**. Keep `application` as the outermost wrapper; start it with `uvicorn.run("main:application")`.
- `main.py` and `start.py` call `configure_logging` from `bd_shared.logging_setup` at module level before other code runs.
- **Dataset switch**: `DATASET` moves the overlay out of the repository through `BD_CONFIG_LOCAL_FILE`, and the dataset directory supplies its own tool module, knowledge folder and optional `webreport.compose.yml` for database networking. Nothing dataset-specific belongs in this directory.
- **CORS config**: backend reads allowed origins from the resolved `[webreport].allowed_origins`; use explicit frontend origins, never `*` with credentialed CORS
- **Container networking**: with the bundled MySQL the backend connects at `mysql:3306` on the Docker network, not localhost
- **Dependencies**: backend Poetry (`backend/pyproject.toml`) and `ui/` npm (`ui/package.json`), independent from root.
- **Dev container pattern**: backend and data_collector mount service code at runtime. The UI image is built with npm tests and Vite assets, with no source mount; code-only UI changes need `make restart`.

## ANTI-PATTERNS

- Never run `make test` or `make rebuild` on the server; use the release executor.
- Never add server identifiers or credentials to tracked files, shared logs, workflows, releases, artifacts or image labels.
- **DO NOT** put dataset queries in `backend/agent/` or `backend/agents/` — they belong in the operator tool module
- **DO NOT** add HTTP routes that read or delete archive rows.
- **DO NOT** put archive tables in `checkpoints.db`.
- **DO NOT** put report tables in `checkpoints.db` or `conversations.db`.
- **DO NOT** call the model from Update.
- **DO NOT** add SQLite support for game data, which remains MySQL-only. The three backend-owned stores are unrelated to the operator dataset, which may use SQLite.
- **DO NOT** log message text.
- **DO NOT** import `bd_shared` without the container package path (`sys.path.insert(0, '/')` is already in service). Release images package it at `/bd_shared`; dev mounts shadow that copy.
- **DO NOT** hardcode ports — always read from generated env vars or `bd_shared/config.toml`
- **DO NOT** build a second engine anywhere in the backend. Startup builds exactly one, makes it read-only for MySQL, PostgreSQL and SQLite, and injects it.
- **DO NOT** use broad Docker `COPY` patterns when explicit file/directory copies are sufficient; prefer narrow `COPY` instructions unless the image strictly needs the whole tree

## COMMANDS

```bash
make start      # docker compose up -d --build (generates env files first)
make stop       # docker compose down
make restart    # regenerate env files, run both preflights, build and recreate application services
make logs       # docker compose logs -f
make build      # docker compose build
make rebuild    # down + build + up
make test       # Run the backend suite plus both acceptance lanes (SQLite and PostgreSQL)
make archive-list LIMIT=5        # List archive rows
make archive-show ID=<id>        # Show one archive row
make archive-delete SESSION=<id> # Delete archive rows by session
make test-proxy-contract         # Prove the LiteLLM Langfuse contract offline
make test-ui    # Build frontend image, run Vitest and TypeScript/Vite build
make test-e2e-setup # Pull pinned Playwright image and install npm dependencies in Docker
make test-e2e   # Offline Chromium lane, normal and reduced motion
make clean      # Remove __pycache__, .pyc files
```

Production commands run from the repository root:

```bash
make deploy VERSION=v0.1.0 DEPLOY_ARGS="--llm-smoke"
make rollback DEPLOY_ARGS="--llm-smoke"
make deploy-smoke DEPLOY_ARGS="--llm-smoke"
make deploy-verify-isolation DEPLOY_ARGS=--container-probe
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for the operator checklist, migration approval, restore and exit codes. `make deploy-status` prints a read-only state report; Make itself returns 2 on recipe failures. State, audit, logs and backups default to `../vm/deploy/`.

The `make test` chain includes `test_request_context.py`, `test_agent_correlation.py`, `test_archive_store.py`, `test_archive_api.py`, `test_archive_cli.py`, `test_chat_store.py`, `test_runs.py`, `test_chat_routes.py`, and `test_report_routes.py`; it also runs the SQLite and PostgreSQL acceptance lanes plus `make test-proxy-contract`.

## NOTES

- Backend listens on port 8000 inside container, mapped to `WEBREPORT_BACKEND_PORT` (default 28000) on host
- nginx serves the React UI and proxies `/api/` on port 8501 inside container, mapped to `WEBREPORT_FRONTEND_PORT` (default 28501) on host
- Backend CORS uses explicit origins from `[webreport].allowed_origins`
- LiteLLM has no host port and is reachable only as `litellm:4000` on `webreport-network`
- `chats.db` (or `chats-<name>.db` under DATASET) retains transcripts and reports without TTL. Checkpoint expiry does not delete them. Stop before publication persists «Запрос отменён»; completed answers stay intact. Startup marks unfinished runs interrupted. Reasoning labels remain «Рассуждения» and «Рассуждения (неполные)».
- Existing docs in this directory (`ARCHITECTURE.md`, `README.md`, etc.) contain detailed architecture diagrams and usage guides
