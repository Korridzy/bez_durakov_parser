# PROJECT KNOWLEDGE BASE

**Generated:** 2026-03-06T14:48:54Z
**Commit:** 1d45d80
**Branch:** issue-86-create-ai-webreport

## OVERVIEW

Parser for "Без дураков. Белград." board game series results. Parses XLSM game files → MySQL via SQLAlchemy ORM. Includes a web reporting subsystem with FastAPI, Streamlit, a LangGraph ReAct agent, `ChatLiteLLM` and its LiteLLM SDK in the backend image, LiteLLM proxy, and SQLite checkpoints. `langchain-openai` is not a current backend dependency.

## STRUCTURE

```
parser/
├── bd_shared/          # Core shared library: ORM models, config, game data structure, DB helpers
├── data_to_parse/      # Input XLSM files (gitignored)
├── doc/                # ORM docs, data structure docs
├── examples/           # Analysis examples using ORM (four_buckets.py)
├── migrations/         # Alembic DB migrations (MySQL)
├── range/              # Utility scripts for statistics/calendars (gitignored)
├── secret/             # Credentials (gitignored)
├── vm/                 # MySQL data volume and backend checkpoints (gitignored)
├── webreport/          # Web reporting: FastAPI + Streamlit + LangGraph (see webreport/AGENTS.md)
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
| Operator knowledge | `bd_shared/knowledge/` + `webreport/backend/agent/knowledge.py` | `load_knowledge()` reads the manifest and topics; `read_knowledge` returns topic text on demand. `dataset.knowledge_dir` points at the folder |
| DB migrations | `migrations/versions/` | Alembic, MySQL-only. `make upgrade-db` to apply |
| Fetch XLSM | `webreport/data_collector/` | Dockerized service using APScheduler. `make fetch-data` triggers manual fetch. `make fetch-data-log` shows logs since last run |
| Web reporting | `webreport/` | FastAPI + Streamlit + LangGraph through ChatLiteLLM and the internal LiteLLM proxy; separate subsystem with its own `AGENTS.md` |
| Analysis examples | `examples/four_buckets.py` | Shows ORM usage for custom analysis |

## CONVENTIONS

- **Language**: Python 3.11+ only. All deps via Poetry (`poetry install --no-root`)
- **Game data and the parser**: MySQL 8.0 only, connected via `pymysql`. The webreport backend is not restricted this way, since it serves whatever MySQL, PostgreSQL or SQLite database `[database]` and `[dataset]` name
- **Agent checkpoints**: SQLite is allowed only for the backend-owned checkpoint store at `../vm/backend/checkpoints`; it is not a game-data store.
- **Config**: TOML-based (`bd_shared/config.toml`). Test config: `bd_shared/test_config.toml`
- **Team names**: Always normalized via `normalize_team_name()` — NFC unicode, lowercase, whitespace-collapsed
- **Game data**: All game data flows through `BdGame` dataclass. Never access raw XLSM directly after parsing
- **Imports**: Use `from bd_shared.db import Database` not `from bd_shared import *`
- **Tests**: No test framework configured. Tests are standalone scripts (`test_alembic_migration.py`, `webreport/test_system.py`)
- **No CI/CD**: No GitHub Actions. Manual deployment only
- **Monorepo-ish**: Root + `webreport/` have separate `pyproject.toml`. No Poetry workspaces — managed via Docker Compose for web components
- **Knowledge**: The configured folder is read once at backend startup, and its manifest supplies the agent persona

## ANTI-PATTERNS (THIS PROJECT)

- **DO NOT** add SQLite support for game data, which remains MySQL-only (see issue-61). SQLite is permitted for agent checkpoints at `../vm/backend/checkpoints` and for a webreport dataset an operator configures.
- **DO NOT** access the game database directly from this repository's own web components — go through `bd_shared/db.py` and `bd_shared/db_helpers.py`. An operator's own tool module reaches its database directly by design.
- **DO NOT** bypass `normalize_team_name()` when storing/comparing team names
- **DO NOT** put dataset queries in the backend. They belong in the operator tool module named by `dataset.tools_module`, which receives the engine the backend built and made read-only.
- `webreport/backend/agent/` and `webreport/backend/agents/` must never write dataset SQL of their own; they discover their tools from the operator module. The only sanctioned exception is the checkpoint saver’s own thread-recency enumeration query against its `checkpoints` table.
- **DO NOT** hardcode a dataset persona in agent code; put it in the knowledge manifest

## COMMANDS

```bash
make setup              # Create .venv, install Poetry deps
make upgrade-db         # Run Alembic migrations (poetry run alembic upgrade head)
make upgrade-code       # Pull from main, preserve config.toml
make webreport-start    # Start full stack: MySQL + FastAPI + Streamlit (Docker)
make webreport-stop     # Stop web stack
make mysql-start        # Start MySQL container only
make mysql-stop         # Stop MySQL container
poetry run python parse_data.py <dir>           # Parse XLSM files in directory
poetry run python parse_data.py <dir> --no-save # Parse without saving to DB
make fetch-data                                  # Manually trigger XLSM fetch in data_collector container
make fetch-data-log                              # Show logs since last fetch start
make logs SERVICE=data_collector                 # Show all data_collector container logs
cd webreport && make rebuild                     # Rebuild after backend dependency changes
cd webreport && make test-e2e-setup              # One-time e2e dependency and Chromium setup
cd webreport && make test-e2e                    # Offline Playwright reasoning-display tests
```

## NOTES

- `env/` in root is a stale virtualenv (gitignored) — project uses `.venv/` via Poetry
- `xlsm_archive/` stores 178+ XLSM files — all gitignored except `.gitkeep`
- `range/` is entirely gitignored — contains ad-hoc analysis scripts and reports
- Game rounds: Выбор (vybor), Числа (chisla), Преферанс (pref), Пары (pairs), Разоблачение (razobl), Аукцион (auction), Момент Истины (mot)
- Default game date `02.03.2022` in config triggers a warning — means date was not set in the source file
- The agent's persona now comes from the knowledge manifest, not from code.
- At backend startup, a deep LiteLLM probe decides whether the agent can be built. When no model is reachable the process stays up and refuses to serve: `/health` and `/api/chat` answer 503. Each later chat attempt re-probes once, and the first healthy verdict builds the agent and answers that same request.
- LiteLLM is internal-only at `litellm:4000`. The checkpoint-backed backend is limited to one replica.
- ChatLiteLLM (`langchain-litellm >=0.7,<0.8`) is the backend model client. Its LiteLLM SDK is deliberately installed in the backend image, reversing the prior SDK-out-of-image rule. The manifest keeps that version range with a dependency-level Python `<3.15` marker because the literal range was not lockable under the project Python bound; the shipped image uses Python 3.11.
- Reasoning round-trip is always on: `OutboundReasoningFilter` echoes reasoning only within the current user turn, while checkpoints retain all turns. `ChatResponse.reasoning` and `/api/history` carry it to the collapsed frontend labels «Рассуждения» and, for recovered failed requests, «Рассуждения (неполные)». No reasoning means no block.
- Anthropic-style thinking models are unsupported because `thinking_blocks` do not round-trip. There is no configuration switch for this. LiteLLM's `main-stable` image tag and the young community package `langchain-litellm` can change behavior; the minor-range pin and AC-1 echo tripwire are the mitigations.
