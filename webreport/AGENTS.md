# webreport — Web Reporting System

## OVERVIEW

SOA web system: React workspace UI → FastAPI REST API → LangGraph ReAct agent → project-scoped analytics API connectors or the operator tool module named by `dataset.tools_module`. LiteLLM is internal-only at `litellm:4000`; the backend owns SQLite checkpoints and local workspace state at `../vm/backend/checkpoints`. See `frontend-web/README.md` for the current UI and connector contract. `frontend/` is legacy Streamlit and is no longer deployed by the primary Compose.

## STRUCTURE

```
webreport/
├── backend/
│   ├── main.py                        # FastAPI app, endpoints, Pydantic models
│   ├── agents/report_runtime.py       # LangGraph report agent over the discovered tools
│   ├── agent/toolmodule.py            # Loads the operator module and discovers its tools
│   ├── agent/engine.py                # Builds the one engine, read-only per dialect
│   └── ../bd_shared/tools/bez_durakov.py  # The default operator module for this deployment
├── frontend/
│   └── main.py                        # Streamlit UI: chat view + report view
├── docker-compose.yml                 # MySQL + backend + frontend on webreport-network
├── Dockerfile.backend                 # Backend container (mounts bd_shared as /bd_shared)
├── Dockerfile.frontend                # Frontend container
├── Makefile                           # start/stop/restart/logs/build/test/clean
├── generate_env.py                    # Writes Compose + per-service env files
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
| UI changes | `frontend-web/src/` | React/TypeScript, Vite build, nginx same-origin API proxy |
| Projects, chats, source/model connections | `backend/workspace/` | Local single-profile API, encrypted optional credentials, persistent jobs/transcripts |
| Analytics API tools and reports | `backend/connectors/` | Project-scoped tools discovered through the existing registry; no dataset SQL in agent code |
| Docker config | `docker-compose.yml` | `bd_shared` mounted read-only at `/bd_shared` |
| Serve another dataset | `docker-compose.dataset.yml` + `Makefile` | `make start DATASET=<name>` binds `DATASET_DIR` at `/dataset`, points `BD_CONFIG_LOCAL_FILE` at its overlay, and starts only LiteLLM, backend and frontend |
| Source config | `../bd_shared/config.toml` + `config.local.toml` | Tracked defaults plus ignored server-local overrides in the same sections. `[dataset]` holds `tools_module` and `knowledge_dir` |
| Generated env | `.env*` + `generate_env.py` | `.env` is Compose-only; each service gets its own file; LiteLLM receives OpenAI, OpenRouter, and OpenCode keys from `.env.litellm` |
| Tests | `backend/test_system.py` | Run via `make test` (Docker) or directly |

## CONVENTIONS

- **Data access**: this repository's `backend/agent/` and `backend/agents/` never reach the dataset themselves. They discover their tool surface from the object the operator's `build_service(engine)` returns, and the backend injects the one engine it built.
- **Agent tools**: every public method of that object becomes a tool, named after the method, described by its docstring and parameterised by its type hints. A helper that should not be a tool takes a leading underscore, and a property is never a tool.
- **Knowledge prompt**: The prompt is composed at startup, and the configured folder is read exactly once
- **Model availability**: a deep LiteLLM probe runs at startup. Without a reachable model the process stays up and refuses to serve, answering 503 from `/health` and `/api/chat`. Each later chat attempt re-probes once, and the first healthy verdict builds the agent and answers that request.
- **Checkpointing**: The backend persists LangGraph threads in its SQLite store at `../vm/backend/checkpoints`. The game data this deployment serves remains MySQL.
- **Backend topology**: Run exactly one backend replica. Shared SQLite checkpoints do not support horizontal backend scaling.
- **Config flow**: `bd_shared/config.toml` + optional `config.local.toml` → `bd_shared/config.py` → `generate_env.py` → Compose/per-service `.env*` files → `docker-compose.yml`
- **Dataset switch**: `DATASET` moves the overlay out of the repository through `BD_CONFIG_LOCAL_FILE`, and the dataset directory supplies its own tool module, knowledge folder and optional `webreport.compose.yml` for database networking. Nothing dataset-specific belongs in this directory.
- **CORS config**: backend reads allowed origins from the resolved `[webreport].allowed_origins`; use explicit frontend origins, never `*` with credentialed CORS
- **Container networking**: with the bundled MySQL the backend connects at `mysql:3306` on the Docker network, not localhost
- **Dependencies**: backend uses Poetry; the primary frontend uses npm with a tracked lockfile. Host Node.js is only needed for Vite development, not Docker builds.
- **Dev container pattern**: backend and data_collector mount code. Frontend is a compiled nginx image: `make start` rebuilds it; use Vite for hot reload.

## ANTI-PATTERNS

- **DO NOT** put dataset queries in `backend/agent/` or `backend/agents/` — they belong in the operator tool module
- **DO NOT** import `bd_shared` without the Docker mount path (`sys.path.insert(0, '/')` is already in service)
- **DO NOT** hardcode ports — always read from generated env vars or `bd_shared/config.toml`
- **DO NOT** build a second engine anywhere in the backend. Startup builds exactly one, makes it read-only for MySQL, PostgreSQL and SQLite, and injects it.
- **DO NOT** use broad Docker `COPY` patterns when explicit file/directory copies are sufficient; prefer narrow `COPY` instructions unless the image strictly needs the whole tree

## COMMANDS

```bash
make start      # docker compose up -d (generates all env files first)
make stop       # docker compose down
make restart    # regenerate env files, run both preflights, then force-recreate LiteLLM, backend, and frontend
make logs       # docker compose logs -f
make build      # docker compose build
make rebuild    # down + build + up
make test       # Run the backend suite plus both acceptance lanes (SQLite and PostgreSQL)
make clean      # Remove __pycache__, .pyc files
```

## NOTES

- Backend listens on port 8000 inside container, mapped to `WEBREPORT_BACKEND_PORT` (default 28000) on host
- Frontend listens on port 8501 inside container, mapped to `WEBREPORT_FRONTEND_PORT` (default 28501) on host
- Backend CORS uses explicit origins from `[webreport].allowed_origins`
- LiteLLM has no host port and is reachable only as `litellm:4000` on `webreport-network`
- Existing docs in this directory (`ARCHITECTURE.md`, `README.md`, etc.) contain detailed architecture diagrams and usage guides
