# ✅ SEPARATE CODE BASES WITH POETRY - MIGRATION COMPLETE

## Summary

The Docker setup has been completely restructured to have:
- **Separate code bases** for backend and frontend
- **No shared volumes** between containers
- **Poetry** for dependency management instead of requirements.txt

## New Structure

```
webreport/
├── backend/
│   ├── app/
│   │   ├── agents/           # AutoGen agents
│   │   ├── services/         # Data services
│   │   ├── __init__.py
│   │   └── main.py           # FastAPI app
│   ├── pyproject.toml        # Backend dependencies (Poetry)
│   └── __init__.py
│
├── frontend/
│   ├── app/
│   │   ├── __init__.py
│   │   └── main.py           # Streamlit app
│   ├── pyproject.toml        # Frontend dependencies (Poetry)
│   └── __init__.py
│
├── Dockerfile.backend        # Backend container (Poetry-based)
├── Dockerfile.frontend       # Frontend container (Poetry-based)
└── docker-compose.yml        # Mounts parent parser dir as /bd_shared
```

## Database Modules Access

Instead of copying database files, the parent `parser/` directory is mounted as `/bd_shared` in the backend container:

```yaml
# docker-compose.yml
backend:
  volumes:
    - ..:/bd_shared:ro  # Read-only mount of parser directory
```

Backend services import directly from the mounted directory:
```python
# backend/app/services/game_data_service.py
sys.path.insert(0, '/bd_shared')
from db import Database, Game, Team, TeamGameScore
from db_helpers import initialize_database
```

**No code duplication!** All database modules (db.py, db_helpers.py, config.py, bd_game.py, config.toml) are used directly from the parent parser directory.

## Backend Dependencies (pyproject.toml)

```toml
dependencies = [
    "fastapi>=0.104.0",
    "uvicorn[standard]>=0.24.0",
    "pydantic>=2.0.0",
    "python-dotenv>=1.0.0",
    "pandas>=2.0.0",
    "sqlalchemy>=2.0.0",
    "pymysql[rsa]>=1.1.0",
    "pyautogen>=0.2.0",
]
```

## Frontend Dependencies (pyproject.toml)

```toml
dependencies = [
    "streamlit>=1.28.0",
    "httpx>=0.25.0",
    "pandas>=2.0.0",
    "python-dotenv>=1.0.0",
]
```

## Key Changes

### 1. Separate Code Bases ✅
- Backend has its own `/app` directory with all needed code
- Frontend has its own `/app` directory  
- Shared DB modules copied to `backend/app/shared/`
- **No code sharing between containers**

### 2. Poetry Instead of requirements.txt ✅
- Each service has `pyproject.toml` with its dependencies
- Poetry installed in Dockerfiles
- Poetry manages dependencies: `poetry install`
- No virtual environments in containers

### 3. Docker Configuration ✅
- **Dockerfile.backend**: Copies `webreport/backend` → installs with Poetry
- **Dockerfile.frontend**: Copies `webreport/frontend` → installs with Poetry
- **docker-compose.yml**: Removed all volume mounts
- Code is **baked into images**, not mounted

### 4. Import Paths Updated ✅
- Backend: `from services.game_data_service import ...`
- Backend: `from agents.report_agents import ...`
- Services: Use `../shared` for DB modules
- No more `webreport.` prefixes

## Benefits

1. **Complete Isolation**: Each container has its own dependencies
2. **Smaller Images**: Only necessary dependencies per service
3. **Better Dependency Management**: Poetry handles versions and conflicts
4. **Production Ready**: No development volumes
5. **Clearer Architecture**: Explicit separation of concerns

## Usage

### Build Images
```bash
cd /home/homo/git/bez_durakov/parser/webreport
make rebuild
```

### Start Services
```bash
make start
```

### View Logs
```bash
make logs
```

## What Changed

### Before:
- ❌ Shared code through volumes (`..:/app`)
- ❌ requirements.txt for dependencies
- ❌ Code on host mounted at runtime

### Now:
- ✅ Separate code bases per container
- ✅ Poetry (pyproject.toml) for dependencies
- ✅ **Backend code mounted**: `./backend:/app` (live reload)
- ✅ **Frontend code mounted**: `./frontend:/app` (live reload)
- ✅ **DB modules mounted**: `..:/bd_shared:ro` (no duplication)
- ✅ Dependencies baked into image once
- ✅ No code copying, only dependencies installation

## File Locations

### Backend
- **Code**: `webreport/backend/` (agents/, services/, main.py)
- **Dependencies**: `webreport/backend/pyproject.toml`
- **DB Modules**: Mounted from parent parser/ as `/bd_shared`

### Frontend
- **Code**: `webreport/frontend/` (main.py)
- **Dependencies**: `webreport/frontend/pyproject.toml`

## Ports (dynamically configured)
- Backend: Configured in `../config.toml` [webreport.backend_port] (default: 28000)
- Frontend: Configured in `../config.toml` [webreport.frontend_port] (default: 28501)

## Cleanup

The following old directories and files were removed as they're no longer needed:
- ❌ `webreport/agents/` - Moved to `backend/app/agents/`
- ❌ `webreport/services/` - Moved to `backend/app/services/`
- ❌ `webreport/backend/app/shared/` - Removed (was code duplication)
- ❌ `webreport/requirements.txt` - Replaced by Poetry pyproject.toml files

**Note:** Database modules (db.py, db_helpers.py, config.py, etc.) are accessed via mounted `/bd_shared` volume from parent parser directory - no duplication!

## Current Clean Structure

```
webreport/
├── backend/
│   ├── app/
│   │   ├── agents/
│   │   ├── services/
│   │   └── main.py
│   └── pyproject.toml
├── frontend/
│   ├── app/
│   │   └── main.py
│   └── pyproject.toml
├── Dockerfile.backend
├── Dockerfile.frontend
├── docker-compose.yml    # Mounts ..:/bd_shared:ro for backend
└── *.md
```

Parser directory mounted at `/bd_shared` (read-only) in backend container.

---

**Migration Date**: 2025-11-29
**Status**: ✅ COMPLETE
**Cleanup**: ✅ COMPLETE
