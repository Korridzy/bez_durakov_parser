# 🎮 Web-based Game Data Reporting System

## 📋 Оглавление документации

### Production releases

[DEPLOYMENT.md](DEPLOYMENT.md) covers server setup, cutting a release, migration approval, rollback, restore, smoke, isolation and privacy. The [first-rollout checklist](DEPLOYMENT.md#first-rollout) is for the operator; the agent never contacts the server.

From the repository root:

```bash
make deploy VERSION=v0.1.0 DEPLOY_ARGS="--llm-smoke"
make rollback DEPLOY_ARGS="--llm-smoke"
make deploy-verify-isolation
```

`make deploy-status` prints a read-only report of the deployment state. Start, stop, rebuild and test recipes elsewhere in this index are for development. Production uses the server-local executor and doesn't run tests or builds.

### 🚀 Начало работы
1. **[README.md](README.md)** - Главная страница
   - Обзор системы
   - Быстрый старт
   - Установка и запуск
   - Основные возможности

2. **[QUICK_REFERENCE.md](QUICK_REFERENCE.md)** - Шпаргалка
   - Команды разработки и production
   - Конфигурация
   - API и диагностика

### 📖 Для пользователей
3. **[USER_GUIDE.md](USER_GUIDE.md)** - Руководство пользователя
   - Работа с интерфейсом
   - Примеры запросов
   - Визуализация отчётов
   - FAQ

### 🏗️ Для разработчиков
4. **[ARCHITECTURE.md](ARCHITECTURE.md)** - Архитектура системы
   - Компоненты системы
   - Потоки данных
   - Принципы архитектуры
   - Расширяемость

5. **[LOGGING.md](LOGGING.md)** Логирование и корреляция
   - Конвейер записей
   - Поля и идентификаторы запроса
   - Сбор логов Docker

6. **[ARCHIVE.md](ARCHIVE.md)** Архив разговоров
   - Хранилище и схема
   - Хранение и удаление
   - Langfuse и конфиденциальность

## 📁 Структура файлов

### Основные компоненты
```
webreport/
├── backend/main.py                       - REST API (FastAPI)
├── backend/agents/report_runtime.py      - LangGraph ReAct agent над найденными инструментами
├── backend/agent/toolmodule.py           - Загрузка модуля оператора и обнаружение инструментов
├── ../bd_shared/tools/bez_durakov.py     - Модуль инструментов этого развёртывания
├── backend/chat_store.py                 - Чаты, сообщения, runs, отчёты
├── backend/runs.py                       - Фоновые запросы, отмена и архив
├── backend/chat_routes.py                - Список, сообщения, status, cancel
├── backend/report_routes.py              - Закладки и Update
├── ui/src/                              - React/TypeScript UI
├── ui/tests_e2e/                        - Офлайн Playwright
└── ui/nginx.conf                        - SPA и /api/ proxy
```

### Конфигурация
```
webreport/
├── generate_env.py      - Генерирует Compose/service env-файлы из `config.toml`
└── docker-compose.yml   - Docker конфигурация
```

Источник схемы конфигурации: отслеживаемый `../bd_shared/config.toml` с секциями `[database]`, `[application]`, `[webreport]`, `[xlsm_fetch]`. Серверные параметры задаются в игнорируемом `../bd_shared/config.local.toml`, который заменяет значения базового файла по секциям.

### Docker и утилиты
```
webreport/
├── docker-compose.yml    - Docker Compose конфигурация
├── Dockerfile.backend    - Backend образ
├── Dockerfile.frontend   - Frontend образ
├── Makefile              - Docker команды
├── backend/test_system.py        - Тесты
└── validate_setup.py     - Валидация установки
```

Для Docker и утилит смотрите [LOGGING.md](LOGGING.md). В документе описаны ротация, поиск записей и внешние получатели.

## 🎯 Быстрые ссылки

### Запуск (Docker только)
```bash
make start
# ИЛИ вручную
poetry run python generate_env.py
docker compose up -d --build
```

### Остановка
```bash
make stop
# ИЛИ
docker compose down
```

### Логи и проверка
```bash
make logs                 # Просмотр логов
docker compose ps         # Статус контейнеров
poetry run python validate_setup.py # Проверка файлов
```

UI образ содержит собранные assets, поэтому после изменений UI нужен `make restart`. `make test-ui` выполняет Vitest и сборку, `make test-e2e-setup` и `make test-e2e` обслуживают pinned Playwright в Docker.

### Доступ
- **Frontend**: http://localhost:28501
- **Backend API**: http://localhost:28000
- **API Docs**: http://localhost:28000/docs

## 📊 Схема работы

```
Пользователь
    ↓ (вводит требования)
Frontend (React/nginx)
    ↓ (HTTP/REST)
Backend (FastAPI, one replica)
    ↓
LangGraph ReAct agent over discovered tools
    ↓                ↘
LiteLLM `litellm:4000`   SQLite checkpoints, архив и chats.db
    ↓                    `../vm/backend/checkpoints`
operator tool module (dataset.tools_module)
    ↓
MySQL, PostgreSQL or SQLite, read-only
```

Backend performs the LiteLLM probe at startup. Without a reachable model it stays up and refuses to serve, answering 503 from `/health` and `/api/chat`, and each later chat attempt re-probes once. LangGraph thread state и отдельный SQLite архив находятся в `../vm/backend/checkpoints`. Run one backend replica only; horizontal backend scaling is not supported.

## 🛠️ Технологии

| Слой | Технология |
|------|------------|
| Frontend | React/nginx |
| Backend | FastAPI |
| Agents | LangGraph ReAct |
| Model proxy | LiteLLM at `litellm:4000` |
| Agent state | SQLite checkpoints |
| Архив разговоров | Отдельный SQLite архив рядом с checkpoints |
| Чаты и отчёты | chats.db, отдельный от checkpoints и архива |
| Services | Python + Pandas |
| ORM | SQLAlchemy |
| Database | MySQL |

## ✅ Проверка системы

```bash
# Валидация файлов
cd webreport
poetry run python validate_setup.py

# Проверка контейнеров
docker compose ps

# Проверка здоровья API
curl http://localhost:28000/health
```

Валидация должна вывести:
```
🎉 All checks passed! System is ready to use.
```

## 📞 Помощь

### Проблемы с установкой?
См. [README.md](README.md) раздел "Решение проблем"

### Вопросы по использованию?
См. [USER_GUIDE.md](USER_GUIDE.md) раздел "FAQ"

### Вопросы по архитектуре?
См. [ARCHITECTURE.md](ARCHITECTURE.md)

## 🎓 Обучающий путь

### Для пользователей
1. [README.md](README.md) - Обзор
2. [USER_GUIDE.md](USER_GUIDE.md) - Работа с системой
3. Практика с примерами

### Для разработчиков
1. [README.md](README.md) - Обзор
2. [ARCHITECTURE.md](ARCHITECTURE.md) - Архитектура
3. [QUICK_REFERENCE.md](QUICK_REFERENCE.md) - Команды и диагностика
4. Изучение кода
5. Расширение функциональности

## 🏆 Статус проекта

✅ **Готов к использованию**

Все компоненты реализованы и протестированы:
- Проверки файлов: `poetry run python validate_setup.py`; проверки поведения: `make test`, `make test-ui`, `make test-e2e`
- ✅ Frontend (React/nginx)
- ✅ Backend (FastAPI)
- ✅ LangGraph agents over the operator's discovered tools
- ✅ Operator tool module contract with a read-only injected engine
- ✅ Документация
- ✅ Тесты
- ✅ Docker поддержка

---

**Создано: 28.11.2025**

**Проект: Без дураков. Белград.**
