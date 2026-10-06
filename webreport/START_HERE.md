# 🎮 Система веб-отчётов - Быстрый старт

## Production

Start with [DEPLOYMENT.md](DEPLOYMENT.md), including the operator's [first-rollout checklist](DEPLOYMENT.md#first-rollout). The quick-start steps below are for development. Production uses tested release images, not local rebuilds.

From the repository root on the server:

```bash
make deploy VERSION=v0.1.0 DEPLOY_ARGS="--llm-smoke"
make rollback DEPLOY_ARGS="--llm-smoke"
make deploy-verify-isolation
```

`make deploy-status` is wired but its handler currently exits 42. Don't run `make test` or rebuild on the server; read the guide for backups, migration approval and failure codes.

## ✅ Система создана и готова к использованию!

Создана полнофункциональная web-система для генерации отчётов по игровым данным с использованием AI-агентов.

---

## 🚀 Запуск за 3 шага

### Шаг 1: Настройка конфигурации
```bash
cd webreport
cat ../bd_shared/config.toml
```

### Шаг 2: Запуск системы
```bash
make start
```

### Шаг 3: Использование
Откройте в браузере: **http://localhost:28501**

---

## 📋 Что было создано

### 🏗️ Архитектура (SOA)
- ✅ **Frontend** - React/nginx UI с вкладками «Чаты» и «Сохранённые отчёты»
- ✅ **Backend** - FastAPI REST API
- ✅ **Agents** - LangGraph ReAct agent над инструментами, найденными в модуле оператора
- ✅ **Модуль инструментов** - модуль из `dataset.tools_module`, получающий движок от backend

### 📁 Структура
```
webreport/
├── 📚 Документация
│   ├── README.md              - Основная документация
│   ├── USER_GUIDE.md         - Руководство пользователя
│   ├── ARCHITECTURE.md       - Архитектура
│   ├── QUICK_REFERENCE.md    - Шпаргалка
│   └── ...
├── 💻 Код
│   ├── backend/main.py        - FastAPI
│   ├── backend/agents/report_runtime.py
│   ├── backend/agent/toolmodule.py
│   ├── ../bd_shared/tools/bez_durakov.py
│   ├── backend/chat_store.py - Чаты, сообщения, runs, отчёты
│   ├── backend/runs.py       - Фоновые запросы и отмена
│   ├── backend/chat_routes.py
│   ├── backend/report_routes.py
│   └── ui/src/               - React/TypeScript
│       ├── App.tsx           - Навигация
│       ├── chats/            - Список и разговор
│       ├── reports/          - Панель и предпросмотр
│       └── saved/            - Закладки и Update
├── 📥 Data collector
│   ├── data_collector/entrypoint.py
│   └── data_collector/fetch_pipeline.py
└── ⚙️ Конфигурация (6 файлов)
    ├── ../bd_shared/config.toml
    ├── generate_env.py
    ├── docker-compose.yml
    └── ...
```

---

## 🎯 Основные возможности

### 💬 Чат с AI-агентом
- Ввод требований на естественном языке
- Автоматическая интерпретация запросов
- Сохранение разговоров после перезагрузки, поиск, переименование и удаление
- Остановка активного запроса

**Примеры запросов:**
```
покажи все игры
топ 10 команд по очкам
статистика команды ДЛТ-78
очки всех команд
```

### 📊 Визуализация отчётов
- Таблицы с данными
- Графики и метрики
- Экспорт в CSV
- Параметры исходного инструмента и дата генерации
- Закладки и Update с неизменными аргументами, без модели

### 🔌 REST API
- `/api/chats` - список, поиск и создание чатов
- `/api/chats/{id}/messages`, `/status`, `/cancel` - фоновый запрос и остановка
- `/api/saved-reports`, `/api/reports/{id}/update` - закладки и Update
- `/api/chat` - совместимый синхронный маршрут
- `/api/history/{session_id}` - история диалога
- `/api/clear/{session_id}` - очистка истории
- `/health` - готовность сервиса

Документация: http://localhost:28000/docs

---

## 📖 Документация

| Документ | Для кого | Описание |
|----------|----------|----------|
| **INDEX.md** | Все | Оглавление всей документации |
| **README.md** | Все | Обзор и быстрый старт |
| **[DEPLOYMENT.md](DEPLOYMENT.md)** | Оператор | Релизы, deploy, rollback и изоляция |
| **USER_GUIDE.md** | Пользователи | Детальное руководство |
| **ARCHITECTURE.md** | Разработчики | Архитектура системы |
| **QUICK_REFERENCE.md** | Все | Шпаргалка |
| **[LOGGING.md](LOGGING.md)** | Оператор | Логи и корреляция запросов |

---

## 🛠️ Технологии

- **Python 3.11+**
- **React 19 + TypeScript 5 + Vite 6**, nginx раздаёт UI и проксирует `/api/`
- **FastAPI** - REST API framework  
- **LangGraph** - ReAct agent и checkpointed threads
- **LiteLLM** - internal model proxy `litellm:4000`
- **SQLAlchemy** - ORM (из основного проекта)
- **Pandas** - Data processing
- **MySQL, PostgreSQL или SQLite** - база набора данных (из bd_shared/config.toml)
- **SQLite**. Состояние агента, отдельный архив разговоров и chats.db находятся в `../vm/backend/checkpoints`

Backend при запуске выполняет глубокий LiteLLM probe. Без доступной модели процесс остаётся запущенным и отвечает 503, а каждая следующая попытка чата повторяет проверку один раз. LiteLLM не публикует host port, он доступен только на `litellm:4000` внутри сети. Поддерживается только один backend replica.

---

## ⚡ Быстрые команды

### Make команды
```bash
make help          # Справка
make start         # Запуск
make stop          # Остановка
make restart       # Перезапуск после обеих проверок
make validate-knowledge # Проверить папку знаний
make validate-tools     # Проверить модуль инструментов оператора
make test          # Тесты, включая обе приёмочные полосы
make test-ui       # UI образ, Vitest и TypeScript/Vite
make test-e2e-setup # Playwright image и npm-зависимости в Docker
make test-e2e      # Офлайн Playwright с API stub
make logs          # Логи
```

UI собран в nginx образе без монтирования исходников. После UI изменений нужен `make restart`. Node и Chromium на хосте для UI тестов не нужны.

### Проверка
```bash
poetry run python validate_setup.py  # Валидация установки
make test     # Тесты системы
```

### Остановка
```bash
Ctrl+C             # В терминале
make stop          # Через Make
```

---

## 🔍 Валидация

```bash
$ poetry run python validate_setup.py

🎉 All checks passed! System is ready to use.
```

---

## 🌐 URL-адреса

| Сервис | URL |
|--------|-----|
| 🎨 Frontend | http://localhost:28501 |
| 🔌 Backend API | http://localhost:28000 |
| 📚 API Docs | http://localhost:28000/docs |
| ❤️ Health Check | http://localhost:28000/health |

---

## 💡 Примеры использования

### 1. Просмотр всех игр
```
Чат → "покажи все игры"
Отчёт → Таблица со всеми играми
```

### 2. Топ команд
```
Чат → "топ 10 команд по очкам"
Отчёт → Таблица + график лучших команд
```

### 3. Статистика команды
```
Чат → "статистика команды ДЛТ-78"
Отчёт → Детальная статистика
```

---

## 🐳 Docker

```bash
# Запуск
make start

# Остановка
make stop

# Логи
docker compose logs -f
```

---

## 🔧 Интеграция с проектом

### Модуль инструментов оператора
Backend не содержит запросов к набору данных. Он импортирует модуль, названный в
`dataset.tools_module`, вызывает его фабрику `build_service(engine)` и превращает каждый
публичный метод возвращённого объекта в инструмент агента. Для этого развёртывания модуль —
`bd_shared/tools/bez_durakov.py`, и он работает через `bd_shared.Database` вокруг движка,
который построил backend.

### Модели ORM
- `Game`
- `Team`
- `TeamGameScore` (view)

---

## 🎓 Обучение

### Для начинающих
1. Прочитать **USER_GUIDE.md**
2. Запустить систему
3. Попробовать примеры
4. Изучить отчёты

### Для разработчиков
1. Прочитать **ARCHITECTURE.md**
2. Изучить код в порядке:
   - `../bd_shared/tools/bez_durakov.py`
   - `backend/agent/toolmodule.py`
   - `backend/agents/report_runtime.py`
   - `backend/main.py`
   - `backend/chat_store.py`, `backend/runs.py`
   - `backend/chat_routes.py`, `backend/report_routes.py`
   - `ui/src/App.tsx` и каталоги `ui/src/chats/`, `reports/`, `saved/`

---

## 🆘 Помощь

### Проблемы с установкой?
См. **README.md** → "Решение проблем"

### Вопросы по использованию?
См. **USER_GUIDE.md** → "FAQ"

### Вопросы по коду?
См. **ARCHITECTURE.md**

---

## ✅ Чеклист перед первым запуском

- [ ] База данных доступна (MySQL, PostgreSQL или SQLite)
- [ ] Создан `bd_shared/config.local.toml` для server-specific настроек
- [ ] Python 3.11+
- [ ] Порты 8000 и 8501 свободны
- [ ] `make validate-knowledge` проходит
- [ ] `make validate-tools` проходит
- [ ] Выполнен `make start` из каталога `webreport/`
- [ ] `openai_api_key` указан в `[webreport]` файла `bd_shared/config.local.toml`, иначе backend будет отвечать 503

---

## 🎉 Готово!

Система полностью создана и готова к использованию.

**Запустить:**
```bash
cd webreport
make start
```

**Использовать:**
- Откройте http://localhost:28501
- Введите запрос в чат
- Просмотрите отчёт

**Документация:**
- Начните с **INDEX.md**
- Для работы читайте **USER_GUIDE.md**
- Для понимания читайте **ARCHITECTURE.md**

---

**🎮 Удачи в использовании! 🎮**

*Проект: Без дураков. Белград*  
*Дата: 28.11.2025*
