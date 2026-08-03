# bd_shared — Core Shared Library

## OVERVIEW

Central library providing ORM models, database operations, configuration, and game data structure for all project components.

## STRUCTURE

| File | Role |
|------|------|
| `db.py` | SQLAlchemy ORM models (10 tables) + `Database` class with all DB operations |
| `bd_game.py` | `BdGame` dataclass — in-memory game representation, XLSM parser logic |
| `db_helpers.py` | High-level helpers: `initialize_database()`, `save_game_to_database()` |
| `config.py` | TOML config loader. Constants: `DATABASE_URL`, `DEFAULT_GAME_DATE`, `XLSM_FETCH_CONFIG` |
| `config.toml` | Tracked base config. `config.local.toml` is an ignored server-local overlay; `BD_CONFIG_FILE` selects a complete alternate config |
| `test_config.toml` | Test DB config — used by `test_alembic_migration.py` |

## WHERE TO LOOK

| Task | File | Key symbol |
|------|------|-----------|
| Add/query games | `db.py` | `Database.add_game()`, `Database.get_game_data()`, `Database.get_all_games()` |
| Find duplicates | `db.py` | `Database.find_identical_game()`, `Database.get_game_ids_by_date()` |
| Team name handling | `db.py` | `normalize_team_name()` — NFC unicode, lowercase, whitespace-collapsed |
| Parse XLSM → data | `bd_game.py` | `BdGame.parse_from_file()` → populates `_game_data` dict |
| Game round structure | `bd_game.py` | `_initialize_team_structures()` — vybor, chisla, pref, pairs, razobl, auction, mot |
| DB connection | `config.py` | `DATABASE_URL` from `config.toml` `[database]` section |
| WebReport config | `config.py` | `WEBREPORT_BACKEND_PORT`, `WEBREPORT_FRONTEND_PORT`, `WEBREPORT_DEBUG` |

## ORM TABLES

`Game` → `Team` (M:M via `GameTeam`). Per-game round tables: `Vybor`, `Chisla`, `Pref`, `Pairs`, `Razobl`, `Auction`, `Mot` — all keyed by `(game_id, team_id)`.

## CONVENTIONS

- All DB queries go through `Database` class methods — never raw SQL
- `normalize_team_name()` MUST be called before any team name storage/comparison
- `BdGame._game_data` dict is the canonical in-memory representation; use `get_data()` to access
- Config loading is eager (module-level) — importing `config.py` loads `config.toml` and its optional `config.local.toml` overlay immediately
- `db_helpers.py` re-exports `normalize_team_name` for backward compat

## ANTI-PATTERNS

- **DO NOT** import with `from bd_shared import *` — use explicit submodule imports
- **DO NOT** create new Database methods in webreport services — extend `Database` class here
- **DO NOT** bypass duplicate detection in `save_game_to_database()`
