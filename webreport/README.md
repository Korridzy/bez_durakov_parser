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
   - обращается к модели через `ChatLiteLLM` и внутренний LiteLLM proxy `litellm:4000`
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

Backend использует `ChatLiteLLM` из `langchain-litellm` с диапазоном версий `>=0.7,<0.8`. LiteLLM SDK теперь входит в образ backend, что осознанно отменяет прежнее правило держать SDK вне образа. Proxy остаётся точкой маршрутизации и настройки моделей. После этой замены зависимости обязательно выполните `make rebuild`.

В манифесте backend зависимость дополнена маркером Python `<3.15`: буквальная строка без маркера не разрешалась при текущей верхней границе Python проекта. Диапазон версий пакета сохранён, а образ backend использует Python 3.11.

LiteLLM proxy использует moving tag `main-stable`, а `langchain-litellm` является молодым community-пакетом. Поэтому обновляйте образы осознанно. Minor-range pin пакета и тест AC-1 снижают риск изменения поведения reasoning tool loop.

### Настройка конфигурации

```bash
# Перейти в директорию webreport
cd webreport
```

Источник конфигурации для WebReport — `../bd_shared/config.toml`.

Используемые секции и полный список ключей `[webreport]`:

- `[database]`: `url`, `docker_url`, `sqlalchemy_logging`
- `[application]`: `debug`, `log_level`, `default_game_date`
- `[webreport]`:
  - Сеть и запуск: `backend_port`, `frontend_port`, `allowed_origins`, `debug`, `reload`, `backend_debug_port`, `frontend_debug_port`
  - Агент и состояние: `agent_recursion_limit`, `agent_timeout_seconds`, `chat_request_timeout_seconds`, `agent_max_rows_per_fetch`, `agent_max_rows_per_run`, `checkpoint_ttl_seconds`, `checkpoint_db_path`
  - LiteLLM: `litellm_base_url`, `agent_model`, `probe_retry_attempts`, `probe_retry_delay_seconds`, `probe_request_timeout_seconds`, `llm_max_retries`, `llm_request_timeout_seconds`
  - Ключи провайдеров: `openai_api_key`, `openrouter_api_key`, `opencode_api_key`
  - Знания:
    - `knowledge_dir = "knowledge/bez_durakov"`
    - `knowledge_max_title_chars = 80`
    - `knowledge_max_summary_chars = 200`
    - `knowledge_max_persona_chars = 2000`
    - `knowledge_max_topics = 50`
    - `knowledge_max_doc_bytes = 65536`
    - `knowledge_max_bytes_per_turn = 131072`
- `[xlsm_fetch]`: `google_drive_folder_url`, `modes`, `download_dir`, `start_time`, `interval_hours`, `timezone`

`../bd_shared/config.toml` содержит отслеживаемые значения по умолчанию. Для конкретного сервера скопируйте `../bd_shared/config.local.toml.example` в `../bd_shared/config.local.toml`, установите права `0600` и добавляйте только изменяемые значения в те же секции. Значения в local-файле заменяют значения базового файла; списки, например `allowed_origins`, заменяются целиком.

### Папка знаний

По умолчанию `knowledge_dir = "knowledge/bez_durakov"` указывает на поставляемую папку `bd_shared/knowledge/bez_durakov`. Если указанная папка отсутствует, backend записывает предупреждение и продолжает запуск без знаний. Если папка существует, но недействительна, например `manifest.toml` не проходит проверку, backend прерывает запуск.

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
| `.env.litellm` | `OPENAI_API_KEY`, `OPENROUTER_API_KEY` и `OPENCODE_API_KEY` для LiteLLM |

Не редактируйте сгенерированные `.env*` вручную. Для изменения серверных настроек обновите `../bd_shared/config.local.toml`, затем снова выполните `make start`, `make mysql-start` из корня проекта или `make generate-env`.

Запущенные на хосте `parse_data.py` и Alembic используют `[database].url`. Backend и data collector получают `[database].docker_url` через `bd_shared/config.py`, а контейнер MySQL — сгенерированные из этого URL значения `MYSQL_DATABASE`, `MYSQL_USER` и `MYSQL_PASSWORD`. Для совместимости dev-стека `MYSQL_ROOT_PASSWORD` получает тот же пароль из `docker_url`.

MySQL применяет эти значения при первой инициализации каталога данных. Изменение `config.local.toml` не меняет пользователей и пароли в уже существующем `../vm/mysql/mysql_data`.

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

Укажите ключ в секции `[webreport]` файла `bd_shared/config.local.toml`:

```toml
openai_api_key = "your-api-key-here"
```

`generate_env.py` записывает ключ в `.env.litellm` с правами `0600`; Docker Compose передаёт этот файл только контейнеру LiteLLM. Не экспортируйте `OPENAI_API_KEY` в shell. `bd_shared/config.local.toml` игнорируется Git и предназначен для настоящих ключей.
При запуске backend выполняет глубокую проверку LiteLLM. Если настроенная модель доступна, процесс выбирает LangGraph `agent` mode. Если ключ отсутствует или probe не проходит, процесс выбирает keyless `fallback` mode. Режим фиксирован до перезапуска backend.

После изменения ключа перезапустите стек командой `make restart`.

### OpenRouter: DeepSeek V4

Для DeepSeek через OpenRouter добавьте в `bd_shared/config.local.toml` ключ OpenRouter и один из proxy aliases:

```toml
[webreport]
openrouter_api_key = "your-openrouter-key"
agent_model = "deepseek-v4-flash-latest" # или "deepseek-v4-pro"
```

`deepseek-v4-flash-latest` маршрутизируется к `~deepseek/deepseek-v4-flash-latest`, который всегда указывает на актуальную модель семейства DeepSeek V4 Flash. `deepseek-v4-pro` маршрутизируется к `deepseek/deepseek-v4-pro` через OpenRouter. Эти aliases доступны только в local overlay; отслеживаемый `agent_model = "gpt-4o"` не изменяется. После выбора модели выполните `make restart`.

### OpenCode Zen: бесплатные модели

Для OpenCode Zen добавьте ключ и выберите один из proxy aliases в `bd_shared/config.local.toml`:

```toml
[webreport]
opencode_api_key = "your-opencode-key"
agent_model = "opencode/big-pickle"
```

Доступны: `opencode/big-pickle`, `opencode/deepseek-v4-flash-free`, `opencode/mimo-v2.5-free`, `opencode/laguna-s-2.1-free`, `opencode/ling-3.0-flash-free`, `opencode/north-mini-code-free` и `opencode/nemotron-3-ultra-free`. OpenCode помечает эти модели как временно бесплатные, поэтому при изменении каталога обновите конфигурацию. После изменения ключа или модели выполните `make restart`.

LiteLLM доступен только внутри `webreport-network` как `litellm:4000`, без host port. Backend хранит checkpoint state в `../vm/backend/checkpoints`; игровые данные остаются в MySQL. Запускайте ровно один backend replica, горизонтальное масштабирование backend не поддерживается.

### Рассуждения модели

Модели, которые передают reasoning через proxy, поддерживаются без отдельной настройки. Backend возвращает reasoning модели только в текущем пользовательском ходе, чтобы не отправлять reasoning из прежних ходов обратно в tool loop. Anthropic-style thinking models пока не поддерживаются, потому что `thinking_blocks` не проходят round-trip. Это ограничение текущей реализации.

Непустое reasoning показано над ответом ассистента в свёрнутом блоке «Рассуждения». Если запрос завершился ошибкой, но доступна сохранённая часть reasoning, блок называется «Рассуждения (неполные)». При пустом или отсутствующем reasoning блока нет.

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
- **ChatLiteLLM** (`langchain-litellm`) - model client for the internal LiteLLM proxy
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
3. Проверьте настройки в `../bd_shared/config.local.toml`
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
3. Укажите `openai_api_key` в секции `[webreport]` файла `../bd_shared/config.local.toml` и перезапустите backend через `make restart`.
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
make test-e2e-setup # Один раз: установить e2e-зависимости и Chromium
make test-e2e       # Offline Playwright e2e против stub backend
make fetch-data     # Ручной запуск XLSM fetch
make fetch-data-log # Логи data_collector с последнего fetch

# Сборка
make build          # Собрать образы
make rebuild        # Пересобрать и перезапустить, обязательно после замены зависимости backend

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
