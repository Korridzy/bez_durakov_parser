# Web-based Game Data Reporting System

Веб-система для генерации отчётов по игровым данным с использованием AI-агентов.

## 🏗️ Архитектура

Система построена на сервис-ориентированной архитектуре (SOA) и включает:

### Компоненты

1. **Backend (FastAPI)** - REST API сервер
   - Обработка запросов от фронтенда
   - Маршрутизация запросов к агентам
   - Доступ к данным через сервисный слой

2. **Frontend (Streamlit)** - пользовательский интерфейс
   - Чат с AI-агентом
   - Отображение отчётов
   - Переключение между представлениями

3. **Agents (LangGraph)** - ReAct агент с сохранением thread state
   - обращается к модели через внутренний LiteLLM proxy `litellm:4000`
   - сохраняет state в service-local SQLite checkpoint store `../vm/backend/checkpoints`
   - при запуске выбирает `agent` или `fallback` режим и не меняет его до перезапуска

4. **Services** - сервисный слой
   - GameDataService - доступ к данным игр
   - Использует ТОЛЬКО существующие методы из db.py и db_helpers.py

## 📁 Структура проекта

```
webreport/
├── backend/
│   ├── agents/
│   │   └── report_agents.py       # LangGraph / fallback agent system
│   ├── services/
│   │   └── game_data_service.py   # Access to bd_shared.Database methods
│   ├── main.py                     # FastAPI application and API routes
│   ├── start.py                    # Container launcher for Uvicorn/debugger
│   ├── test_system.py              # Docker-based backend tests
│   └── pyproject.toml              # Backend Poetry dependencies
├── frontend/
│   ├── main.py                     # Streamlit application
│   ├── start.py                    # Container launcher for Streamlit/debugger
│   └── pyproject.toml              # Frontend Poetry dependencies
├── data_collector/
│   ├── entrypoint.py               # APScheduler entrypoint
│   ├── fetch_pipeline.py           # Manual/scheduled XLSM fetch pipeline
│   ├── xlsm_fetch/                 # Fetcher implementations
│   └── pyproject.toml              # Data collector Poetry dependencies
├── docker-compose.yml              # mysql + backend + frontend + data_collector
├── Dockerfile.backend              # Backend image build
├── Dockerfile.frontend             # Frontend image build
├── Dockerfile.data_collector       # Data collector image build
├── generate_env.py                 # Generate Compose/service env files from config.toml
├── validate_setup.py               # Validate expected layout and integration files
├── Makefile                        # Start/stop/build/test helper commands
└── README.md                       # Documentation
```

## 🚀 Быстрый старт

### Требования

- Docker и Docker Compose
- Python 3.11+ и Poetry на хосте для ручного запуска `generate_env.py`
- Настроенный `../bd_shared/config.toml`

### Зависимости

У WebReport нет общего `requirements.txt`.
Зависимости разделены по сервисам и описаны в Poetry-манифестах:

- `backend/pyproject.toml`
- `frontend/pyproject.toml`
- `data_collector/pyproject.toml`

При обычном Docker-запуске вручную устанавливать их не нужно: Docker-образы устанавливают зависимости во время сборки.

### Настройка конфигурации

```bash
# Перейти в директорию webreport
cd webreport
```

Источник конфигурации для WebReport — `../bd_shared/config.toml`.

Используемые секции:

- `[database]` — `url`, `docker_url`, `sqlalchemy_logging`
- `[application]` — `debug`, `log_level`, `default_game_date`
- `[webreport]` — `backend_port`, `frontend_port`, `allowed_origins`, `debug`, `reload`, `backend_debug_port`, `frontend_debug_port`
- `[xlsm_fetch]` — `google_drive_folder_url`, `modes`, `download_dir`, `start_time`, `interval_hours`, `timezone`

В `modes` сейчас поддерживается только `browser_selenium`.
`public_api` и `gdown` пока являются заглушками и должны считаться неподдерживаемыми.

`generate_env.py` создаёт общий файл для интерполяции Docker Compose и отдельный env-файл для каждого сервиса. Все файлы создаются сразу с правами `0600`:

| Файл | Назначение |
|---|---|
| `.env` | Host-порты для интерполяции Docker Compose |
| `.env.mysql` | `MYSQL_*` для контейнера MySQL |
| `.env.backend` | `BD_DOCKER` и debug/reload backend |
| `.env.data_collector` | `BD_DOCKER` и timezone data collector |
| `.env.frontend` | URL backend и debug/reload frontend |

Не редактируйте сгенерированные `.env*` вручную. Для изменения настроек обновите `../bd_shared/config.toml`, затем снова выполните `make start`, `make mysql-start` из корня проекта или `make generate-env`.

Запущенные на хосте `parse_data.py` и Alembic используют `[database].url`. Backend и data collector получают `[database].docker_url` через `bd_shared/config.py`, а контейнер MySQL — сгенерированные из этого URL значения `MYSQL_DATABASE`, `MYSQL_USER` и `MYSQL_PASSWORD`. Для совместимости dev-стека `MYSQL_ROOT_PASSWORD` получает тот же пароль из `docker_url`.

MySQL применяет эти значения при первой инициализации каталога данных. Изменение `config.toml` не меняет пользователей и пароли в уже существующем `../vm/mysql/mysql_data`.

`[webreport].allowed_origins` управляет CORS для backend. По умолчанию используются локальные frontend origins:

- `http://localhost:28501`
- `http://127.0.0.1:28501`

Для production замените их на реальные доверенные frontend URL и не используйте `*` вместе с credentialed CORS.

`[webreport].reload` управляет автоматической перезагрузкой backend и frontend при изменении кода. Она всегда отключается при `[webreport].debug = true`.

### Запуск

#### Вариант 1: Через Makefile (рекомендуется)

```bash
make start
```

Эта команда:

1. запускает `generate_env.py`
2. генерирует `.env` и отдельные env-файлы сервисов
3. поднимает `mysql`, `backend`, `frontend` и `data_collector` через Docker Compose

#### Вариант 2: Вручную через Docker Compose

```bash
poetry run python generate_env.py
docker compose up -d
```

### API key и режим агента (опционально)

Укажите ключ в секции `[webreport]` файла `bd_shared/config.toml`:

```toml
openai_api_key = "your-api-key-here"
```

`generate_env.py` записывает ключ в `.env.litellm` с правами `0600`; Docker Compose передаёт этот файл только контейнеру LiteLLM. Не экспортируйте `OPENAI_API_KEY` в shell. `bd_shared/config.toml` отслеживается Git, поэтому не коммитьте локальную правку с настоящим ключом.
При запуске backend выполняет глубокую проверку LiteLLM. Если настроенная модель доступна, процесс выбирает LangGraph `agent` mode. Если ключ отсутствует или probe не проходит, процесс выбирает keyless `fallback` mode. Режим фиксирован до перезапуска backend.

После изменения ключа перезапустите стек командой `make restart`.

LiteLLM доступен только внутри `webreport-network` как `litellm:4000`, без host port. Backend хранит checkpoint state в `../vm/backend/checkpoints`; игровые данные остаются в MySQL. Запускайте ровно один backend replica, горизонтальное масштабирование backend не поддерживается.

### Доступ к системе

- **Frontend UI** (по умолчанию): http://localhost:28501
- **Backend API** (по умолчанию): http://localhost:28000
- **API Documentation**: http://localhost:28000/docs
- **API Health Check**: http://localhost:28000/health

Host-порты берутся из секции `[webreport]` в `../bd_shared/config.toml` и попадают в Compose-файл `.env` через `generate_env.py`.

## 📖 Использование

### Интерфейс пользователя

Система имеет два представления, между которыми можно переключаться:

#### 1. Чат с AI-агентом 💬

- Введите требования к отчёту на естественном языке
- Агент интерпретирует запрос и генерирует отчёт
- История диалога сохраняется

**Примеры запросов:**
- "покажи все игры"
- "топ 10 команд по очкам"
- "статистика команды [название]"
- "очки всех команд"

#### 2. Отчёт 📊

- Отображение данных в виде таблиц
- Метрики и статистика
- Визуализация (графики)
- Экспорт в CSV

### API Endpoints

#### Chat
- `POST /api/chat` - отправить сообщение агенту
- `GET /api/history/{session_id}` - получить историю диалога
- `POST /api/clear/{session_id}` - очистить историю

#### Data
- `GET /api/games` - получить все игры
- `GET /api/games/{game_id}` - получить данные игры
- `GET /api/teams` - получить все команды
- `GET /api/teams/{team_name}/stats` - статистика команды
- `GET /api/scores` - очки команд по играм

## 🔧 Технический стек

- **Python 3.11+**
- **FastAPI** - REST API framework
- **Streamlit** - UI framework
- **LangGraph** - ReAct agent and checkpointed threads
- **LiteLLM** - internal model proxy at `litellm:4000`
- **SQLite** - backend checkpoint store at `../vm/backend/checkpoints`
- **SQLAlchemy** - ORM для работы с БД
- **Pandas** - обработка данных
- **Uvicorn** - ASGI сервер

## 🎯 Основные возможности

1. **Чат-интерфейс** для общения с AI-агентом
2. **Автоматическая генерация отчётов** на основе требований пользователя
3. **Визуализация данных** (таблицы, графики)
4. **Экспорт отчётов** в CSV
5. **История диалогов** с возможностью очистки
6. **RESTful API** для интеграции с другими системами
7. **Сервис-ориентированная архитектура** (SOA)

## 🔐 Безопасность

- CORS ограничен списком origins из `[webreport].allowed_origins`
- В production необходимо:
  - Указать только реальные frontend origins в `[webreport].allowed_origins`
  - Добавить аутентификацию
  - Использовать HTTPS
  - Защитить API ключи

## 🐛 Решение проблем

### Backend не запускается

1. Проверьте логи: `make logs SERVICE=backend` или `docker compose logs backend`
2. Проверьте статус сервисов: `docker compose ps`
3. Проверьте настройки в `../bd_shared/config.toml`
4. Проверьте, что контейнер `mysql` поднят и доступен в Compose-сети
5. Проверьте подключение backend к MySQL-сервису:
   ```bash
   docker compose exec backend sh -lc 'python -c "import socket; print(socket.gethostbyname(\"mysql\"))"'
   ```

Backend в Docker подключается к БД по имени хоста `mysql`, а не через `localhost`.

### Frontend не может подключиться к Backend

1. Проверьте статус контейнеров: `docker compose ps`
2. Проверьте backend: `curl http://localhost:28000/health`
3. Проверьте логи: `docker compose logs frontend`
4. Проверьте переменную `API_BASE_URL` в `docker-compose.yml` — по умолчанию frontend обращается к `http://backend:8000`
5. Проверьте, что backend отвечает из Compose-сети:
   ```bash
   docker compose exec frontend sh -lc 'python -c "import urllib.request; print(urllib.request.urlopen(\"http://backend:8000/health\").read().decode())"'
   ```

### Агенты не работают

1. Проверьте логи backend на результат глубокого LiteLLM probe: `make logs SERVICE=backend`.
2. Проверьте LiteLLM из Compose-сети по адресу `http://litellm:4000`, он не имеет host port.
3. Укажите `openai_api_key` в секции `[webreport]` файла `../bd_shared/config.toml` и перезапустите backend через `make restart`.
4. Без ключа или при неуспешном probe backend намеренно запускается в keyless `fallback` mode. Он не переключается в `agent` mode во время работы, перезапуск нужен для новой проверки.

### Порты заняты

```bash
# Проверить что использует порты
lsof -i :28000
lsof -i :28501

# Остановить старые контейнеры
make stop
```

## 🐳 Docker команды

```bash
# Основные операции
make start          # Запуск в фоне
make stop           # Остановка
make restart        # Перезапуск
make logs           # Все логи (Ctrl+C для выхода)
make test           # Тесты backend в Docker
make fetch-data     # Ручной запуск XLSM fetch
make fetch-data-log # Логи data_collector с последнего fetch

# Сборка
make build          # Собрать образы
make rebuild        # Пересобрать и перезапустить

# Отладка
docker compose ps                    # Статус контейнеров
docker compose logs -f backend       # Логи backend
docker compose logs -f frontend      # Логи frontend
docker compose logs -f data_collector # Логи data_collector
docker compose exec backend sh       # Войти в backend
docker compose exec frontend sh      # Войти во frontend

# Очистка
docker compose down -v              # Остановить и удалить volumes
```

## 📝 Разработка

### Добавление новых методов запросов

1. Добавьте метод в `GameDataService` (`backend/services/game_data_service.py`)
2. Используйте ТОЛЬКО существующие методы из db.py и db_helpers.py
3. Обновите LangGraph tools или fallback interpreter для нужного маршрута
4. При необходимости добавьте новый endpoint в API

### Расширение функциональности агентов

1. Редактируйте system messages в `backend/agents/report_agents.py`
2. Добавляйте новые инструменты (tools) для агентов
3. Настройте model and temperature through the configuration consumed by LiteLLM

## 📄 Лицензия

Следует лицензии основного проекта.

## 👥 Авторы

Создано для проекта "Без дураков. Белград."
