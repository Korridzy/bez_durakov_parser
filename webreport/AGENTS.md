# webreport — Web Reporting System

## OVERVIEW

SOA web system: Streamlit chat UI → FastAPI REST API → AutoGen AI agents → `GameDataService` → `bd_shared` DB layer. Fully containerized via Docker Compose.

## STRUCTURE

```
webreport/
├── backend/
│   ├── main.py                        # FastAPI app, endpoints, Pydantic models
│   ├── agents/report_agents.py        # AutoGen agents: DataCoder, DataAnalyst, UserProxy
│   └── services/game_data_service.py  # DB abstraction over bd_shared.Database
├── frontend/
│   └── main.py                        # Streamlit UI: chat view + report view
├── docker-compose.yml                 # MySQL + backend + frontend on webreport-network
├── Dockerfile.backend                 # Backend container (mounts bd_shared as /bd_shared)
├── Dockerfile.frontend                # Frontend container
├── Makefile                           # start/stop/restart/logs/build/test/clean
├── generate_env.py                    # Reads ../bd_shared/config.toml → writes .env
├── backend/test_system.py             # unittest-based tests for services, agents, API
└── validate_setup.py                  # Pre-flight checks for deployment
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add API endpoint | `backend/main.py` | FastAPI routes. Pydantic models in same file |
| Add data query | `backend/services/game_data_service.py` | Must use existing `bd_shared.Database` methods only |
| Modify AI behavior | `backend/agents/report_agents.py` | `_setup_agents()` for LLM config, system messages |
| Fallback mode | `backend/agents/report_agents.py` | `_interpret_request()` — regex-based, no LLM needed |
| UI changes | `frontend/main.py` | Streamlit. Custom CSS at top. Two views: chat + report |
| Docker config | `docker-compose.yml` | `bd_shared` mounted read-only at `/bd_shared` |
| Source config | `../bd_shared/config.toml` | Sections: `[database]`, `[application]`, `[webreport]`, `[xlsm_fetch]` |
| Generated env | `.env` + `generate_env.py` | Ports/debug/timezone are generated; `OPENAI_API_KEY` comes from shell/docker env |
| Tests | `backend/test_system.py` | Run via `make test` (Docker) or directly |

## CONVENTIONS

- **Data access**: `GameDataService` → `bd_shared.Database` methods only. Never raw SQL, never new ORM queries
- **Agent tools**: Agents call `GameDataService` methods — never access DB directly
- **Dual mode**: System works without OpenAI API key (fallback: `_interpret_request()` with regex). Full mode requires `OPENAI_API_KEY`
- **Config flow**: `bd_shared/config.toml` → `bd_shared/config.py` → `generate_env.py` → `.env` → `docker-compose.yml` env vars
- **CORS config**: backend reads allowed origins from `bd_shared/config.toml` `[webreport].allowed_origins`; use explicit frontend origins, never `*` with credentialed CORS
- **Container networking**: Backend connects to MySQL at `mysql:3306` (Docker network), not localhost
- **Separate Poetry envs**: `backend/pyproject.toml` and `frontend/pyproject.toml` — independent from root
- **Dev container pattern**: backend, frontend, and data_collector install dependencies in the image and mount service code at runtime; code-only changes should not require image rebuilds

## ANTI-PATTERNS

- **DO NOT** write new DB query methods here — add them to `bd_shared/db.py` `Database` class
- **DO NOT** import `bd_shared` without the Docker mount path (`sys.path.insert(0, '/')` is already in service)
- **DO NOT** hardcode ports — always read from generated env vars or `bd_shared/config.toml`
- **DO NOT** rely on AutoGen being available — always handle `autogen = None` fallback
- **DO NOT** use broad Docker `COPY` patterns when explicit file/directory copies are sufficient; prefer narrow `COPY` instructions unless the image strictly needs the whole tree

## COMMANDS

```bash
make start      # docker-compose up -d (generates .env first)
make stop       # docker-compose down
make restart    # docker-compose restart
make logs       # docker-compose logs -f
make build      # docker-compose build
make rebuild    # down + build + up
make test       # Run backend/test_system.py in backend container
make clean      # Remove __pycache__, .pyc files
```

## NOTES

- Backend listens on port 8000 inside container, mapped to `WEBREPORT_BACKEND_PORT` (default 28000) on host
- Frontend listens on port 8501 inside container, mapped to `WEBREPORT_FRONTEND_PORT` (default 28501) on host
- Backend CORS uses explicit origins from `[webreport].allowed_origins`
- Existing docs in this directory (`ARCHITECTURE.md`, `README.md`, etc.) contain detailed architecture diagrams and usage guides
