# 🎮 ШПАРГАЛКА - Система веб-отчётов

## ⚡ Быстрый старт (2 команды)

```bash
cd webreport
make start
# Открыть http://localhost:28501
```

## 📍 Важные URL

| Что | URL |
|-----|-----|
| 🎨 Frontend | http://localhost:28501 |
| 🔌 API | http://localhost:28000 |
| 📚 API Docs | http://localhost:28000/docs |
| ❤️ Health | http://localhost:28000/health |

## 🎯 Примеры запросов в чат

```
покажи все игры
топ 10 команд
статистика команды ДЛТ-78
очки всех команд
список всех команд
```

## 🔧 Команды Make

```bash
make help          # Справка
make start         # Запуск всего стека
make stop          # Остановка контейнеров
make restart       # Перезапуск сервисов после обеих проверок
make validate-knowledge # Проверить папку знаний
make validate-tools     # Проверить модуль инструментов оператора
make logs          # Логи
make build         # Сборка образов
make rebuild       # Пересборка и запуск
make test          # Тесты, включая обе приёмочные полосы
make test-postgres # Приёмочная полоса против одноразового PostgreSQL
make archive-list LIMIT=5 # Список архивных ходов
make archive-show ID=1 # Полная строка архива
make archive-delete SESSION=<id> # Удалить одну сессию
make archive-delete USER=<id> # Удалить одного пользователя
make archive-delete BEFORE=<ISO-date-or-timestamp> # Удалить старые строки
make test-ui       # UI образ: Vitest и TypeScript/Vite сборка
make test-e2e-setup # Playwright image и npm-зависимости в Docker
make test-e2e      # Офлайн Chromium проверки UI
make clean         # Очистка
```

## 📂 Структура каталога

```
webreport/
├── backend/          # FastAPI + agents + services + tests
├── ui/               # React/TypeScript, Vitest, Playwright, nginx
├── data_collector/   # XLSM fetch scheduler
├── generate_env.py   # Генерация Compose/service env-файлов
├── *.md              # Документация
└── backend/test_system.py    # Тесты
```

## 🐛 Решение проблем

### Backend не запускается
```bash
# Проверить БД
mysql -u durak -p -e "USE bez_durakov; SHOW TABLES;"

# Проверить bd_shared/config.toml
cat ../bd_shared/config.toml

# Проверить порт
lsof -i :28000
```

### Frontend не подключается
```bash
# Проверить backend
curl http://localhost:28000/health

# Проверить nginx proxy
curl -i http://localhost:28501/api/chats

# Проверить статус контейнеров
docker compose ps
```

### Общая диагностика
```bash
poetry run python validate_setup.py  # Проверка файлов
make test                  # Запуск тестов
```

Для поиска записей одного запроса используйте его `request_id`.

```bash
docker compose logs backend | grep <request_id>
```

Чтобы включить JSON формат, задайте в `../bd_shared/config.local.toml` значение `log_format` и выполните `make restart`.

```toml
[application]
log_format = "json"
```

Ротация находится в `docker-compose.yml` в якоре `x-logging`. Параметры `max-size` и `max-file` ограничивают вывод контейнеров значениями `10m` и `3`.

## 🔄 Остановка системы

```bash
make stop
```

UI поставляется внутри nginx образа, без исходников в runtime mount. После изменений UI выполните `make restart`, даже если менялся только код.

## ⚙️ Конфигурация

```bash
cat ../bd_shared/config.toml

# Создать server-local overlay
cp ../bd_shared/config.local.toml.example ../bd_shared/config.local.toml
chmod 600 ../bd_shared/config.local.toml

# Сгенерировать Compose/service env-файлы
make generate-env
```

Для LangGraph `agent` mode (опционально) добавьте в `[webreport]` файла `../bd_shared/config.local.toml`:

```toml
openai_api_key = "your-openai-api-key-here"
```

Для DeepSeek V4 через OpenRouter добавьте в `../bd_shared/config.local.toml`:

```toml
[webreport]
openrouter_api_key = "your-openrouter-key"
agent_model = "deepseek-v4-flash-latest" # или "deepseek-v4-pro"
```

Затем выполните `make restart`. Алиасы LiteLLM: `deepseek-v4-flash-latest` и `deepseek-v4-pro`.

Для бесплатных моделей OpenCode Zen добавьте:

```toml
[webreport]
opencode_api_key = "your-opencode-key"
agent_model = "opencode/big-pickle"
```

Алиасы LiteLLM: `opencode/big-pickle`, `opencode/deepseek-v4-flash-free`, `opencode/mimo-v2.5-free`, `opencode/laguna-s-2.1-free`, `opencode/ling-3.0-flash-free`, `opencode/north-mini-code-free`, `opencode/nemotron-3-ultra-free`.

При запуске backend выполняет глубокий LiteLLM probe. Без доступной модели процесс остаётся запущенным и отвечает 503, а каждая следующая попытка чата повторяет проверку один раз. LiteLLM доступен только внутри Compose-сети как `litellm:4000`. Backend хранит agent state в SQLite по пути `../vm/backend/checkpoints`; данные набора лежат в базе, указанной в `[database]`. Используйте один backend replica, горизонтальное масштабирование не поддерживается.

### Хранилища backend

| Ключ [webreport] | По умолчанию | Назначение |
| --- | --- | --- |
| `checkpoint_db_path` | `/data/checkpoints.db` | Память LangGraph, с TTL/LRU |
| `archive_db_path` | `/data/conversations.db` | Архив оператора, отдельное управление retention |
| `chats_db_path` | `/data/chats.db` | Чаты, сообщения и reasoning, runs и отчёты, без TTL |

`BD_CHATS_DB_PATH` переопределяет `chats_db_path`. При `DATASET=<name>` все три файла получают суффикс `-<name>`; на хосте находятся под `../vm/backend/checkpoints`. Это не базы игровых данных.

### Секции в `bd_shared/config.toml` и `config.local.toml`
- `[database]` — настройки подключения к БД
- `[application]` — общие флаги приложения
- `[webreport]` — порты, CORS (`allowed_origins`), `openai_api_key`, пределы знаний и debug-настройки WebReport
- `[dataset]` — `tools_module` и `knowledge_dir`
- `[xlsm_fetch]` — URL источника, режимы загрузки, расписание и timezone

Для `[xlsm_fetch].modes` используйте только `browser_selenium`.
`public_api` и `gdown` пока не реализуют реальную загрузку файлов.

## 📊 API Endpoints (для интеграции)

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

### Система
```bash
GET /health                 # Здоровье
```

## 🎨 Интерфейс

### Навигация и действия

- «Чаты»: список, поиск, создание, переименование и удаление, сообщения и несколько отчётов справа.
- «Отправить» запускает запрос, «Остановить» отменяет его; история и status восстанавливаются после reload.
- «Рассуждения» и «Рассуждения (неполные)» свёрнуты, пустой reasoning не показывается.
- «Сохранить» ставит закладку, «Сохранённые отчёты» показывает общий список.
- «Обновить» повторяет tool/args без модели, меняет данные и дату того же отчёта. Аргументы не пересчитываются.
- «Параметры» показывает исходный вопрос, инструмент и аргументы, «Скачать CSV» экспортирует таблицу.
- До 900 px панели выдвижные, reduced motion отключает анимацию индикатора.
- Все посетители видят общие чаты и сохранённые отчёты, авторизации нет.

## 🧪 Тестирование

```bash
# Backend и приёмочные проверки
make test

# UI: unit тесты и сборка, затем офлайн браузерные проверки
make test-ui
make test-e2e

# Проверка setup
poetry run python validate_setup.py
```

Корневой `make test` запускает полный набор. `make -C webreport test` запускает проверки бэкенда, а корневая команда дополнительно запускает проверки сборщика данных.

Новые проверки корреляции и заданий находятся в следующих файлах.

- `backend/test_request_context.py`
- `backend/test_agent_correlation.py`
- `data_collector/test_logging_jobs.py`

## 🐳 Docker

```bash
# Запуск
poetry run python generate_env.py
docker compose up -d

# Остановка
docker compose down

# Логи
docker compose logs -f

# Пересборка
poetry run python generate_env.py
docker compose up -d --build
```

## 📖 Документация

| Файл | Описание |
|------|----------|
| INDEX.md | Оглавление |
| README.md | Основная документация |
| USER_GUIDE.md | Для пользователей |
| ARCHITECTURE.md | Для разработчиков |
| SUMMARY.md | Итоговая сводка |
| QUICK_REFERENCE.md | Эта шпаргалка |
| ARCHIVE.md | Архив разговоров, Langfuse и удаление |

## 💡 Советы

1. **Первый запуск**: Проверьте `bd_shared/config.toml`, затем используйте `make start`
2. **Быстрая проверка**: validate_setup.py
3. **Тестирование**: make test перед использованием
4. **Логи**: Смотрите вывод в терминале
5. **История**: Очищайте периодически
6. **Экспорт**: Сохраняйте важные отчёты в CSV

## ⚠️ Важно помнить

- ✅ База данных должна быть доступна
- ✅ Порты 8000 и 8501 свободны
- ✅ Python 3.11+
- ✅ Зависимости установлены
- ⚠️ Нужна доступная языковая модель: без неё backend отвечает 503

## 🆘 Помощь

```bash
# В системе
make help

# В документации
cat README.md
cat USER_GUIDE.md

# Контакты
# См. основной проект
```

---

**Версия**: 1.0
**Дата**: 28.11.2025
**Проект**: Без дураков. Белград.
