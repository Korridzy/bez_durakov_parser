# Web-based Game Data Reporting System

Веб-система для генерации отчётов по игровым данным с использованием AI-агентов.

## 🏗️ Архитектура

Система построена на сервис-ориентированной архитектуре (SOA) и включает:

### Компоненты

1. **Backend (FastAPI)** - REST API сервер
   - Обработка запросов от фронтенда
   - Маршрутизация запросов к агентам
   - Доступ к данным через сервисный слой

2. **Frontend (React + nginx)** - пользовательский интерфейс
   - Чаты: список, поиск, история, отправка и остановка запроса
   - Несколько отчётов каждого чата с таблицей, графиком, CSV и параметрами
   - Сохранённые отчёты: закладки и обновление по исходным аргументам

3. **Agents (LangGraph)** - ReAct агент с сохранением thread state
   - обращается к модели через `ChatLiteLLM` и внутренний LiteLLM proxy `litellm:4000`
   - сохраняет state в service-local SQLite checkpoint store `../vm/backend/checkpoints`
   - при запуске проверяет доступность модели; без неё backend отказывается отвечать и повторяет проверку при следующем запросе

4. **Модуль инструментов оператора** - слой доступа к данным
   - путь модуля задаётся ключом `dataset.tools_module`
   - каждый публичный метод возвращаемого объекта становится инструментом агента
   - для этого развёртывания это `bd_shared/tools/bez_durakov.py`

## 📁 Структура проекта

```
webreport/
├── backend/
│   ├── agents/
│   │   └── report_runtime.py      # LangGraph agent over the discovered tools
│   ├── agent/
│   │   ├── toolmodule.py          # Loads the operator module and discovers its tools
│   │   ├── engine.py              # Builds the one engine, read-only per dialect
│   │   └── tools_cli.py           # `make validate-tools` preflight
│   ├── acceptance_fixture.py       # Dialect-neutral stand-in operator module for the lanes
│   ├── chat_store.py               # Чаты, сообщения, запуски и отчёты в chats.db
│   ├── runs.py                     # Фоновые запросы и отмена
│   ├── chat_routes.py              # CRUD чатов, сообщения, status и cancel
│   ├── report_routes.py            # Отчёты, закладки и Update
│   ├── api_errors.py               # Ошибки новых маршрутов
│   ├── main.py                     # FastAPI application and legacy routes
│   ├── start.py                    # Container launcher for Uvicorn/debugger
│   ├── test_system.py              # Docker-based backend tests
│   └── pyproject.toml              # Backend Poetry dependencies
├── ui/
│   ├── src/                        # React/TypeScript: chats, reports, saved, layout
│   ├── tests_e2e/                  # Офлайн Playwright с API stub
│   ├── package.json                # npm, Vitest, Vite
│   └── nginx.conf                  # SPA и proxy /api/ на backend:8000
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
Python зависимости описаны в `backend/pyproject.toml` и `data_collector/pyproject.toml`. React UI использует `ui/package.json` и `ui/package-lock.json`.

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

Используемые секции и полный список ключей `[webreport]` и `[dataset]`:

- `[database]`: `url`, `docker_url`, `sqlalchemy_logging`
- `[application]`: `debug`, `log_level`, `environment`, `log_format`, `default_game_date`
- `[webreport]`:
  - Сеть и запуск: `backend_port`, `frontend_port`, `allowed_origins`, `debug`, `reload`, `backend_debug_port`, `frontend_debug_port`
  - Агент и состояние: `agent_recursion_limit`, `agent_timeout_seconds`, `chat_request_timeout_seconds`, `agent_max_rows_per_fetch`, `agent_max_rows_per_run`, `checkpoint_ttl_seconds`, `checkpoint_db_path`, `chats_db_path`
  - Архив: `archive_enabled`, `archive_db_path`, `archive_retention_days`, `archive_store_reasoning`, `archive_reasoning_retention_days`, `archive_sweep_interval_seconds`
  - Scope gate: `agent_scope_gate_model`, `agent_scope_gate_history_turns`
  - LiteLLM: `litellm_base_url`, `agent_model`, `probe_retry_attempts`, `probe_retry_delay_seconds`, `probe_request_timeout_seconds`, `llm_max_retries`, `llm_request_timeout_seconds`
  - Langfuse: `langfuse_host`, `langfuse_public_key`, `langfuse_secret_key`
  - Ключи провайдеров: `openai_api_key`, `openrouter_api_key`, `opencode_api_key`
  - Пределы знаний:
    - `knowledge_max_title_chars = 80`
    - `knowledge_max_summary_chars = 200`
    - `knowledge_max_persona_chars = 2000`
    - `knowledge_max_topics = 50`
    - `knowledge_max_doc_bytes = 65536`
    - `knowledge_max_bytes_per_turn = 131072`
    - `knowledge_max_scope_chars = 2000`
- `[dataset]`:
  - `tools_module = "bd_shared.tools.bez_durakov"` — точка импорта модуля с фабрикой `build_service(engine)`
  - `knowledge_dir = "knowledge/bez_durakov"` — папка знаний, переехавшая сюда из `[webreport]`
- `[xlsm_fetch]`: `google_drive_folder_url`, `modes`, `download_dir`, `start_time`, `interval_hours`, `timezone`

`../bd_shared/config.toml` содержит отслеживаемые значения по умолчанию. Для конкретного сервера скопируйте `../bd_shared/config.local.toml.example` в `../bd_shared/config.local.toml`, установите права `0600` и добавляйте только изменяемые значения в те же секции. Значения в local-файле заменяют значения базового файла; списки, например `allowed_origins`, заменяются целиком.

`chats_db_path = "/data/chats.db"` задаёт отдельное хранилище чатов и отчётов. `BD_CHATS_DB_PATH` имеет приоритет; `DATASET=<name>` задаёт `/data/chats-<name>.db`. Checkpoints, архив и чаты находятся в отдельных файлах под `../vm/backend/checkpoints`. `frontend_debug_port` и `chat_request_timeout_seconds` сохранены для старых overlay, но не используются после #112.

### Логирование

Ключи `[application]` `log_level`, `log_format` и `environment` управляют уровнем, форматом и именем среды. Полное описание конвейера, полей и поиска записей находится в [LOGGING.md](LOGGING.md).

### Документация

- [LOGGING.md](LOGGING.md) описывает общий конвейер логов.
- [ARCHIVE.md](ARCHIVE.md) описывает постоянный архив разговоров, CLI, срок хранения и Langfuse.

### Папка знаний

По умолчанию `dataset.knowledge_dir = "knowledge/bez_durakov"` указывает на поставляемую папку `bd_shared/knowledge/bez_durakov`. Если указанная папка отсутствует, backend записывает предупреждение и продолжает запуск без знаний. Если папка существует, но недействительна, например `manifest.toml` не проходит проверку, backend прерывает запуск. Когда папка знаний загружена, агент выполняет поиск полного Markdown-документа по требованию инструментом `read_knowledge`, передавая ему точный идентификатор темы.

В `modes` сейчас поддерживается только `browser_selenium`.
`public_api` и `gdown` пока являются заглушками и должны считаться неподдерживаемыми.

`generate_env.py` создаёт общий файл для интерполяции Docker Compose и env-файлы для MySQL, backend, data collector и LiteLLM. nginx не использует env-файл. Все перечисленные файлы создаются сразу с правами `0600`:

| Файл | Назначение |
|---|---|
| `.env` | Host-порты для интерполяции Docker Compose |
| `.env.mysql` | `MYSQL_*` для контейнера MySQL |
| `.env.backend` | `BD_DOCKER` и debug/reload backend |
| `.env.data_collector` | `BD_DOCKER` и timezone data collector |
| `.env.litellm` | `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `OPENCODE_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` и `LANGFUSE_HOST` для LiteLLM |

Не редактируйте сгенерированные `.env*` вручную. Для изменения серверных настроек обновите `../bd_shared/config.local.toml`, затем снова выполните `make start`, `make mysql-start` из корня проекта или `make generate-env`.

Запущенные на хосте `parse_data.py` и Alembic используют `[database].url`. Backend и data collector получают `[database].docker_url` через `bd_shared/config.py`, а контейнер MySQL — сгенерированные из этого URL значения `MYSQL_DATABASE`, `MYSQL_USER` и `MYSQL_PASSWORD`. Для совместимости dev-стека `MYSQL_ROOT_PASSWORD` получает тот же пароль из `docker_url`.

MySQL применяет эти значения при первой инициализации каталога данных. Изменение `config.local.toml` не меняет пользователей и пароли в уже существующем `../vm/mysql/mysql_data`.

`[webreport].allowed_origins` управляет CORS для backend. По умолчанию используются локальные frontend origins:

- `http://localhost:28501`
- `http://127.0.0.1:28501`

Для production замените их на реальные доверенные frontend URL и не используйте `*` вместе с credentialed CORS.

`[webreport].reload` управляет автоматической перезагрузкой только backend через Uvicorn при изменении кода. Она отключается при `[webreport].debug = true`. UI поставляется как собранные файлы в nginx образе без монтирования исходников, поэтому после изменений UI нужен `make restart` или `make rebuild`. Цель `make restart` пересобирает образ и заново создаёт контейнеры приложения.

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

Три непустых ключа Langfuse включают callback proxy. Генератор передаёт их только LiteLLM. Правила архива и ограничения Langfuse описаны в [ARCHIVE.md](ARCHIVE.md).
При запуске backend выполняет глубокую проверку LiteLLM. Если настроенная модель доступна, собирается агент LangGraph. Если модель недоступна, процесс остаётся запущенным, но отказывается отвечать, и `/health` вместе с `/api/chat` возвращают 503 с одним русским предложением. Каждая следующая попытка чата повторяет проверку ровно один раз, и первый успешный результат собирает агента и отвечает на этот же запрос.

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

LiteLLM доступен только внутри `webreport-network` как `litellm:4000`, без host port. Backend хранит checkpoint state, отдельный архив разговоров и chats.db в `../vm/backend/checkpoints`; игровые данные остаются в MySQL. Запускайте ровно один backend replica, горизонтальное масштабирование backend не поддерживается.

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

«Чаты» содержит список с поиском, создание, переименование и удаление чатов. Сообщения, рассуждения и отчёты восстанавливаются после перезагрузки. Пока запрос выполняется, доступна кнопка остановки. Завершённый ответ с помеченными агентом данными автоматически становится отчётом, текстовый ответ не создаёт отчёт.

Справа находятся отчёты выбранного чата. Их можно открыть и сохранить; вкладка «Сохранённые отчёты» показывает все закладки и кнопку «Обновить». Закладка не копирует отчёт: обновление меняет данные и дату в обоих местах. Аргументы инструмента зафиксированы при генерации, включая конкретную игру, которую исходный запрос назвал последней.

На узких экранах список чатов и отчёты открываются в выдвижных панелях. При reduced motion индикатор выполнения статичен. Авторизации нет: все посетители этого развёртывания видят все чаты и сохранённые отчёты.

### API Endpoints

### Чаты и фоновые запросы

| Метод и путь | Назначение |
| --- | --- |
| `POST /api/chats` | Создать чат, 201; необязательный `title` |
| `GET /api/chats?q=&limit=50&cursor=` | Поиск по названию, вопросам и ответам, список `items` и `next_cursor`; limit 1-100 |
| `GET /api/chats/{id}` | Чат, сообщения, карточки отчётов, `active_run` и `last_run` |
| `PATCH /api/chats/{id}` | Переименовать: `{"title":"Название"}`, 1-80 символов после схлопывания пробелов |
| `DELETE /api/chats/{id}` | Удалить чат, 204; сохранённые отчёты остаются с `chat_id=null` |
| `POST /api/chats/{id}/messages` | `{"request_id":"<32 строчных hex>","message":"Вопрос"}`, 202 Run; повтор того же id и текста даёт 200 существующий Run |
| `GET /api/chats/{id}/status` | `active_run` и `last_run` для polling |
| `POST /api/chats/{id}/cancel` | `{"request_id":"<id запуска>"}`, 202 при остановке, 200 для завершённого запуска |
| `GET /api/runs/{request_id}` | Состояние одного запуска |

На чат допускается один активный запуск. Состояния: `running`, `cancelling`, `succeeded`, `failed`, `cancelled`, `interrupted`. В публичном Run поле `response.data` равно null; данные читаются из отчёта. Конфликт активного запуска даёт 409 `chat_busy`, повтор id с другим текстом или чатом даёт 409 `request_conflict`.

### Отчёты и закладки

| Метод и путь | Назначение |
| --- | --- |
| `GET /api/chats/{id}/reports` | Карточки отчётов чата, новые первыми |
| `GET /api/reports/{id}` | Карточка и полные `data` |
| `PUT /api/reports/{id}/saved` | Поставить закладку, 200, идемпотентно |
| `DELETE /api/reports/{id}/saved` | Снять закладку, 204; отчёт остаётся в чате |
| `GET /api/saved-reports` | Все закладки, по `saved_at` от новых к старым |
| `POST /api/reports/{id}/update` | Повторить сохранённые tool/args без модели, 200 Report с новой датой и версией |

Update выполняется в HTTP запросе с пределом `agent_timeout_seconds`. Занятый отчёт или активный запуск его чата дают 409 `report_busy`; ошибка инструмента даёт 502 `update_failed` и прежний отчёт в поле `report`. Неизвестный объект даёт 404 `not_found`. Новые ошибки имеют форму `{"error":{"code":"...","message":"..."}}`; стандартная валидация FastAPI сохраняет `detail`.

### Совместимые маршруты

`POST /api/chat` ожидает завершения фонового запуска и возвращает прежний ChatResponse с дополнительным необязательным `report`. Параллельный запрос в том же чате даёт 409 `detail="Чат занят, дождитесь ответа"`. Закрытие вкладки не обещает отмену запуска, для отмены нужен явный cancel.

`GET /api/history/{session_id}` читает checkpoint историю. `POST /api/clear/{session_id}` удаляет checkpoint, сообщения и запуски, но оставляет чат и все его отчёты; при активном запуске возвращает 409. Ни один из этих маршрутов не удаляет архив.

## 🔧 Технический стек

- **Python 3.11+**
- **FastAPI** - REST API framework
- **React 19 + TypeScript 5 + Vite 6**, nginx раздаёт SPA и проксирует `/api/`
- **LangGraph** - ReAct agent and checkpointed threads
- **ChatLiteLLM** (`langchain-litellm`) - model client for the internal LiteLLM proxy
- **LiteLLM** - internal model proxy at `litellm:4000`
- **SQLite**. Checkpoint state, отдельный архив разговоров и chats.db находятся в `../vm/backend/checkpoints`
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

1. Проверьте контейнеры: `docker compose ps`.
2. Проверьте backend: `curl -i http://localhost:28000/health`.
3. Проверьте nginx и proxy: `curl -i http://localhost:28501/health` и `curl -i http://localhost:28501/api/chats`.
4. Прочитайте `docker compose logs frontend`. Ошибка 502 от nginx означает проблему доступа к backend, а nginx `/health` проверяет только сам frontend.
5. После изменений UI выполните `make restart`: исходники не монтируются, assets находятся в собранном образе. Правила proxy находятся в `ui/nginx.conf`, переменной `API_BASE_URL` у UI нет.

### Агенты не работают

1. Проверьте логи backend на результат глубокого LiteLLM probe: `make logs SERVICE=backend`.
2. Проверьте LiteLLM из Compose-сети по адресу `http://litellm:4000`, он не имеет host port.
3. Укажите `openai_api_key` в секции `[webreport]` файла `../bd_shared/config.local.toml` и перезапустите backend через `make restart`.
4. Если ключ отсутствует или probe не проходит, backend остаётся запущенным и отвечает 503, пока проверка не пройдёт. Перезапуск для этого не нужен, повторная проверка выполняется при следующей попытке чата.

### Приёмочная полоса PostgreSQL не стартует

`make test-postgres` поднимает одноразовый `postgres:16-alpine`. Первый запуск на машине, где
этого образа ещё нет, требует доступа к Docker Hub, дальше он работает офлайн. Полоса
объявлена в отдельном файле `docker-compose.test.yml`, который рабочий стек никогда не
загружает, и после прогона удаляется только сервис `postgres_test`.

Нужен Docker Compose не ниже 2.24: полоса использует тег `!override` в `depends_on`, чтобы
заменить карту зависимостей, а не дополнить её. На более старых версиях теги сливаются
аддитивно, и полоса потянет за собой `mysql` и `litellm` из основного compose-файла. Проверить
версию можно командой `docker compose version`.

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
make test           # Backend-набор плюс обе приёмочные полосы (SQLite и PostgreSQL)
make test-postgres  # Только приёмочная полоса против одноразового PostgreSQL
make validate-knowledge # Проверить папку знаний
make validate-tools # Проверить модуль инструментов оператора
make test-ui        # Сборка UI образа с Vitest и TypeScript/Vite
make test-e2e-setup # Один раз: Playwright image и npm-зависимости в Docker
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

### Разработка UI

Редактируйте `ui/src/`. `make test-ui` собирает frontend образ и выполняет `npm test` и `npm run build` в нём. `make test-e2e-setup` подготавливает pinned Playwright `v1.55.0-noble`, а `make test-e2e` запускает офлайн Chromium проверки с API stub для обычного и reduced-motion режима. На хосте Node и Chromium не нужны. После изменений UI выполните `make restart`, даже если зависимости не менялись.

### Добавление новых методов запросов

1. Добавьте публичный метод с docstring и аннотациями типов в модуль, указанный в `dataset.tools_module`
2. Проверьте его командой `make validate-tools`, она печатает список найденных инструментов
3. Ничего больше менять не нужно: backend узнаёт инструмент из сигнатуры метода

### Расширение функциональности агентов

1. Редактируйте persona в `manifest.toml` папки знаний; правила работы собираются в `backend/agent/knowledge.py` функцией `compose_system_prompt`
2. Добавляйте новые инструменты как публичные методы модуля из `dataset.tools_module`
3. Настройте model and temperature through the configuration consumed by LiteLLM

## 📄 Лицензия

Следует лицензии основного проекта.

## 👥 Авторы

Создано для проекта "Без дураков. Белград."
