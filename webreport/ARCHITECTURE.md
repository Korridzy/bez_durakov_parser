# Архитектура системы веб-отчётов

## Обзор архитектуры

Система построена на основе **сервис-ориентированной архитектуры (SOA)** и состоит из нескольких независимых компонентов, взаимодействующих через чётко определённые интерфейсы.

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER INTERFACE                           │
│                      (Streamlit Frontend)                       │
│  ┌──────────────────┐              ┌──────────────────┐        │
│  │   Chat View      │              │   Report View    │        │
│  │  💬 Диалог с AI  │◄────────────►│  📊 Визуализация │        │
│  └──────────────────┘              └──────────────────┘        │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTP/REST
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                         REST API                                │
│                      (FastAPI Backend)                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │ Chat API     │  │ Data API     │  │ Health API   │         │
│  │ /api/chat    │  │ /api/games   │  │ /health      │         │
│  └──────┬───────┘  └──────┬───────┘  └──────────────┘         │
└─────────┼──────────────────┼──────────────────────────────────┘
          │                  │
          ▼                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                  BACKEND, ONE REPLICA ONLY                       │
│  Startup: deep LiteLLM probe elects `agent` or `fallback` once  │
│                                                                 │
│  agent: LangGraph ReAct graph ────────┐                         │
│  fallback: deterministic interpreter ─┼─> GameDataService      │
│                                        │       │                │
│  SQLite checkpoint store               │       ▼                │
│  ../vm/backend/checkpoints             │  bd_shared.Database    │
│  persists LangGraph thread state       │       │                │
└───────────────────────────┬────────────┴───────┼────────────────┘
                            │ HTTP model calls    │ game-data calls
                            ▼                     ▼
                 ┌──────────────────┐  ┌─────────────────────────┐
                 │ LiteLLM proxy    │  │ MySQL game data         │
                 │ litellm:4000     │  │ via SQLAlchemy          │
                 │ internal only    │  └─────────────────────────┘
                 └──────────────────┘
```

## Компоненты системы

### 1. Frontend (Streamlit)
**Файл**: `frontend/main.py`

**Ответственность**:
- Отображение пользовательского интерфейса
- Управление двумя представлениями (чат и отчёт)
- Взаимодействие с пользователем
- Отправка запросов к REST API
- Визуализация данных (таблицы, графики)

**Ключевые функции**:
- `render_chat_view()` - отображение чата
- `render_report_view()` - отображение отчёта
- `send_chat_message()` - отправка сообщений в API
- `get_conversation_history()` - получение истории

### 2. Backend (FastAPI)
**Файл**: `backend/main.py`

**Ответственность**:
- Предоставление REST API
- Маршрутизация запросов
- Управление сессиями пользователей
- Координация между агентами и сервисами

**Основные endpoints**:
- `POST /api/chat` - обработка сообщений пользователя
- `GET /api/history/{session_id}` - получение истории диалога
- `GET /api/games` - список всех игр
- `GET /api/teams` - список всех команд
- `GET /api/scores` - очки команд

### 3. Agent system (LangGraph)
**Файл**: `agents/report_agents.py`

**Ответственность**:
- Интерпретация требований пользователя
- Генерация запросов к данным
- Анализ результатов
- Формирование ответов

**Режимы работы**:
- **`agent`**: LangGraph ReAct graph вызывает инструменты `GameDataService` через LiteLLM на `litellm:4000`.
- **`fallback`**: Keyless deterministic interpreter обрабатывает поддержанные запросы и сохраняет ход в checkpoint store.

При запуске порядок фиксирован: сначала backend загружает и проверяет папку знаний, включая `manifest.toml` и документы тем. Затем инициализируются `GameDataService` и checkpoint store, после чего выполняется глубокая проверка LiteLLM и выбирается режим `agent` или `fallback`. Выбранный режим не меняется до перезапуска процесса.

При запуске агентской системы системный prompt составляется из persona из `manifest.toml`, независимых от БД правил работы, заданных в коде, и списка тем. Список содержит идентификатор, заголовок и краткое описание каждой темы. Полные Markdown документы не загружаются в prompt заранее: при наличии знаний агент вызывает `read_knowledge` с точным идентификатором темы и получает полный документ только по требованию.

Сейчас независим от БД только путь prompt и знаний: persona, правила работы, список тем и поиск документа. Замена папки знаний изменяет этот путь целиком без изменения кода. Путь данных пока зависит от игры: восемь инструментов данных, включая `get_team_wins` и `get_top_teams`, работают через `GameDataService`, а `FallbackInterpreter` с regex по-прежнему сопоставляет русские игровые ключевые слова. Обобщение этих частей отложено для будущей работы «Multi-DB Universal Agent». Поэтому другая БД получает подходящие persona и предметные знания, но пока не подходящие запросы.

Knowledge documents remain available within the turn that reads them. Prior-turn documents are removed from what the model sees and from the resumable head state; historical checkpoint rows may retain them until thread deletion by TTL/LRU eviction. The head is compacted on each completed model-node update, including current-turn reads when the model returns its final answer. If a model invocation fails, the head may remain uncompacted even though the outbound copy already excludes prior-turn documents.

### 3.1. Модельный клиент и рассуждения
Backend использует `ChatLiteLLM` из пакета `langchain-litellm` с диапазоном версий `>=0.7,<0.8` для вызовов через внутренний LiteLLM proxy. LiteLLM SDK теперь устанавливается в образ backend. Это осознанный разворот прежнего правила, по которому SDK не входил в образ. Proxy по-прежнему остаётся единой точкой маршрутизации и настройки моделей.

В опубликованном backend-манифесте эта зависимость имеет маркер Python `<3.15`: буквальная строка плана без маркера не разрешалась при текущей границе Python проекта. Версионный диапазон пакета сохранён. Образ backend основан на Python 3.11, поэтому маркер не меняет текущую поставку.

`OutboundReasoningFilter` возвращает reasoning content модели только в пределах текущего пользовательского хода. Checkpoint store сохраняет историю всех ходов, но reasoning из предыдущих ходов не отправляется модели повторно. Текст рассуждений попадает в `ChatResponse.reasoning` и записи ассистента в `/api/history`.

Frontend показывает непустой reasoning в свёрнутом блоке «Рассуждения» над ответом ассистента. Если запрос завершился ошибкой, но удалось восстановить сохранённую часть reasoning, блок называется «Рассуждения (неполные)». При отсутствии reasoning блок не отображается.

Anthropic-style thinking models пока не поддерживаются: backend не выполняет round-trip поля `thinking_blocks`. Это ограничение, а не настройка, которую можно включить в конфигурации.

`LLM_MAX_RETRIES` передаётся LiteLLM как `model_kwargs={"num_retries": ...}`, поскольку `ChatLiteLLM.max_retries` не пересылает это значение в SDK.

LiteLLM proxy использует moving tag `main-stable`, поэтому его поведение может меняться при обновлении образа. `langchain-litellm` также является молодым community-пакетом. Риск снижен minor-range pin и тестом AC-1, который фиксирует обязательный echo reasoning в tool loop.

### 4. Checkpoint store
Backend хранит состояние LangGraph по thread ID в service-local SQLite store: `../vm/backend/checkpoints`. Это отдельное состояние агентов, не замена MySQL для игровых данных.

SQLite saver рассчитан на один backend replica. Горизонтальное масштабирование backend не поддерживается.

### 5. Service Layer
**Файл**: `services/game_data_service.py`

**Ответственность**:
- Бизнес-логика работы с данными
- Абстракция над базой данных
- Использование ТОЛЬКО существующих методов из db.py

**Основные методы**:
- `get_all_games_summary()` - сводка по всем играм
- `get_game_by_id(game_id)` - данные конкретной игры
- `get_team_statistics(team_name)` - статистика команды
- `get_team_game_scores()` - очки команд по играм
- `get_all_teams()` - список всех команд

### 6. Database Access Layer
**Файлы**: `db.py`, `db_helpers.py` (из основного проекта)

**Ответственность**:
- ORM модели (SQLAlchemy)
- Прямой доступ к базе данных
- CRUD операции

**Используемые методы**:
- `Database.get_all_games()`
- `Database.get_game_data(game_id)`
- `Database.get_game_ids_by_date()`
- `Database.get_or_create_team()`

## Потоки данных

### Поток 1: Генерация отчёта

```
1. Пользователь вводит требования в чат
   ↓
2. Frontend отправляет POST /api/chat
   ↓
3. Backend передаёт запрос в startup-elected execution path
   ↓
4. LangGraph ReAct agent или fallback interpreter интерпретирует запрос
   ↓
5. AgentSystem вызывает метод GameDataService
   ↓
6. GameDataService использует методы из db.py
   ↓
7. Database возвращает данные
   ↓
8. Данные преобразуются в DataFrame
   ↓
9. Результат возвращается через API
   ↓
10. Frontend отображает отчёт
```

### Поток 2: Просмотр истории

```
1. Пользователь переключается на представление отчёта
   ↓
2. Frontend использует сохранённые данные из session_state
   ↓
3. Данные визуализируются (таблицы, графики)
```

## Принципы архитектуры

### 1. Разделение ответственности (Separation of Concerns)
- Каждый компонент имеет чёткую ответственность
- Минимальная связанность между компонентами
- Высокая когезия внутри компонентов

### 2. Сервис-ориентированная архитектура (SOA)
- Компоненты взаимодействуют через API
- Независимое развёртывание компонентов
- Frontend, data collector и MySQL имеют собственные границы ответственности

### 3. Слоистая архитектура (Layered Architecture)
- Presentation Layer (Streamlit)
- API Layer (FastAPI)
- Business Logic Layer (Agents + Services)
- Data Access Layer (db.py, db_helpers.py)
- Database Layer (MySQL)

### 4. Dependency Injection
- Сервисы создаются при инициализации
- Передаются через конструкторы
- Упрощает тестирование

## Технологический стек

| Компонент | Технология | Назначение |
|-----------|------------|------------|
| Frontend | Streamlit | UI framework |
| Backend | FastAPI | REST API framework |
| Agents | LangGraph | ReAct graph and checkpointed threads |
| Model client | ChatLiteLLM (`langchain-litellm`) | Calls the internal LiteLLM proxy and supports reasoning round-trip |
| Model proxy | LiteLLM | Internal model access at `litellm:4000` |
| ORM | SQLAlchemy | Database abstraction |
| Database | MySQL | Data storage |
| HTTP Server | Uvicorn | ASGI server |
| Data Processing | Pandas | Data manipulation |
| Validation | Pydantic | Data validation |

## Масштабируемость

### Горизонтальное масштабирование
- Backend запускается в одном экземпляре. SQLite checkpoint store не поддерживает несколько backend replicas.
- Frontend обращается к этому единственному backend через REST API.

### Вертикальное масштабирование
- Увеличение ресурсов для компонентов с высокой нагрузкой
- Database connection pooling для эффективного использования соединений

## Безопасность

### Текущая реализация (Development)
- CORS ограничен значениями из `[webreport].allowed_origins`
- Без аутентификации
- HTTP соединения

### Рекомендации для Production
- Ограничить CORS только доверенными frontend origins
- Добавить JWT аутентификацию
- Использовать HTTPS
- Rate limiting для API
- Валидация входных данных (Pydantic)
- SQL injection защита (SQLAlchemy ORM)

## Расширяемость

### Добавление новых функций
1. **Новый тип отчёта**: Добавить метод в GameDataService
2. **Новый endpoint**: Добавить в backend/main.py
3. **Новая визуализация**: Добавить в frontend/main.py
4. **Новый инструмент агента**: Добавить в LangGraph tool layer и сохранить доступ только через `GameDataService`

### Интеграция с другими системами
- REST API позволяет интеграцию с любыми клиентами
- Возможность экспорта данных в различных форматах
- Webhook support (будущее расширение)
