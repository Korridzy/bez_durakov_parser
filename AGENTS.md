# PROJECT KNOWLEDGE BASE

**Generated:** 2026-03-06T14:48:54Z
**Commit:** 1d45d80
**Branch:** issue-86-create-ai-webreport

## OVERVIEW

Parser for "Без дураков. Белград." board game series results. Parses XLSM game files → MySQL via SQLAlchemy ORM. Includes a web reporting subsystem (FastAPI + Streamlit + AutoGen AI agents).

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
├── vm/                 # MySQL data volume (gitignored)
├── webreport/          # Web reporting system: FastAPI + Streamlit + AutoGen (see webreport/AGENTS.md)
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
| Configuration | `bd_shared/config.toml` + `bd_shared/config.py` | TOML config loaded via `tomllib`. Override with `BD_CONFIG_FILE` env var |
| DB migrations | `migrations/versions/` | Alembic, MySQL-only. `make upgrade-db` to apply |
| Fetch XLSM | `webreport/data_collector/` | Dockerized service using APScheduler. `make fetch-data` triggers manual fetch. `make fetch-data-log` shows logs since last run |
| Web reporting | `webreport/` | Separate subsystem with its own `AGENTS.md` |
| Analysis examples | `examples/four_buckets.py` | Shows ORM usage for custom analysis |

## CONVENTIONS

- **Language**: Python 3.11+ only. All deps via Poetry (`poetry install --no-root`)
- **DB**: MySQL 8.0 exclusively (SQLite support removed). Connection via `pymysql`
- **Config**: TOML-based (`bd_shared/config.toml`). Test config: `bd_shared/test_config.toml`
- **Team names**: Always normalized via `normalize_team_name()` — NFC unicode, lowercase, whitespace-collapsed
- **Game data**: All game data flows through `BdGame` dataclass. Never access raw XLSM directly after parsing
- **Imports**: Use `from bd_shared.db import Database` not `from bd_shared import *`
- **Tests**: No test framework configured. Tests are standalone scripts (`test_alembic_migration.py`, `webreport/test_system.py`)
- **No CI/CD**: No GitHub Actions. Manual deployment only
- **Monorepo-ish**: Root + `webreport/` have separate `pyproject.toml`. No Poetry workspaces — managed via Docker Compose for web components

## ANTI-PATTERNS (THIS PROJECT)

- **DO NOT** add SQLite support — intentionally removed (see issue-61)
- **DO NOT** access DB directly from web components — always go through `bd_shared/db.py` and `bd_shared/db_helpers.py`
- **DO NOT** bypass `normalize_team_name()` when storing/comparing team names
- **DO NOT** write new DB query methods in webreport services — use existing `Database` class methods only
- In AutoGen agents: agents must use existing `GameDataService` methods, never write raw SQL

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
```

## NOTES

- `env/` in root is a stale virtualenv (gitignored) — project uses `.venv/` via Poetry
- `xlsm_archive/` stores 178+ XLSM files — all gitignored except `.gitkeep`
- `range/` is entirely gitignored — contains ad-hoc analysis scripts and reports
- Game rounds: Выбор (vybor), Числа (chisla), Преферанс (pref), Пары (pairs), Разоблачение (razobl), Аукцион (auction), Момент Истины (mot)
- Default game date `02.03.2022` in config triggers a warning — means date was not set in the source file
- Web system has fallback mode without OpenAI API key — basic request interpretation without AutoGen
