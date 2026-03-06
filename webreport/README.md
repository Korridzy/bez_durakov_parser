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

3. **Agents (AutoGen)** - система агентов
   - DataCoder - генерирует запросы к данным
   - DataAnalyst - анализирует результаты
   - Организация диалога между агентами

4. **Services** - сервисный слой
   - GameDataService - доступ к данным игр
   - Использует ТОЛЬКО существующие методы из db.py и db_helpers.py

## 📁 Структура проекта

```
webreport/
├── backend/
│   ├── __init__.py
│   └── api.py              # FastAPI REST API
├── frontend/
│   ├── __init__.py
│   └── app.py              # Streamlit UI
├── agents/
│   ├── __init__.py
│   └── report_agents.py    # AutoGen агенты
├── services/
│   ├── __init__.py
│   └── game_data_service.py # Сервис для работы с БД
├── requirements.txt         # Python зависимости
├── start_backend.sh        # Запуск backend
├── start_frontend.sh       # Запуск frontend
├── start_all.sh            # Запуск всей системы
└── README.md               # Документация
```

## 🚀 Быстрый старт

### Установка зависимостей

```bash
# Перейти в директорию проекта
cd /home/homo/git/bez_durakov/parser

# Активировать виртуальное окружение (если есть)
source env/bin/activate

# Установить зависимости для webreport
pip install -r webreport/requirements.txt
```

### Настройка

1. **База данных**: Убедитесь, что `bd_shared/config.toml` содержит правильные настройки БД
2. **OpenAI API** (опционально): Для полной функциональности AutoGen установите переменную окружения:
   ```bash
   export OPENAI_API_KEY="your-api-key-here"
   ```

### Запуск

#### Вариант 1: Запуск всей системы одной командой

```bash
cd webreport
chmod +x start_all.sh
./start_all.sh
```

#### Вариант 2: Раздельный запуск

**Терминал 1 - Backend:**
```bash
cd webreport
chmod +x start_backend.sh
./start_backend.sh
```

**Терминал 2 - Frontend:**
```bash
cd webreport
chmod +x start_frontend.sh
./start_frontend.sh
```

### Доступ к системе

- **Frontend UI**: http://localhost:28501
- **Backend API**: http://localhost:28000
- **API Documentation**: http://localhost:28000/docs
- **API Health Check**: http://localhost:28000/health

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
- **AutoGen** - Multi-agent framework
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

- CORS настроен для локальной разработки
- В production необходимо:
  - Ограничить CORS origins
  - Добавить аутентификацию
  - Использовать HTTPS
  - Защитить API ключи

## 🐛 Решение проблем

### Backend не запускается

1. Проверьте логи: `make logs` или `docker-compose logs backend`
2. Проверьте, что база данных доступна на хосте
3. Проверьте настройки в `../bd_shared/config.toml`
4. Проверьте подключение к БД из контейнера:
   ```bash
   docker-compose exec backend ping host.docker.internal
   ```

### Frontend не может подключиться к Backend

1. Проверьте статус контейнеров: `docker-compose ps`
2. Проверьте backend: `curl http://localhost:28000/health`
3. Проверьте логи: `docker-compose logs frontend`
4. Проверьте сеть между контейнерами:
   ```bash
   docker-compose exec frontend ping backend
   ```

### Агенты не работают (fallback mode)

Система работает в fallback режиме без AutoGen. Для полной функциональности:
1. Создайте файл `.env` из `.env.example`
2. Добавьте `OPENAI_API_KEY=your-key-here`
3. Перезапустите: `make restart`

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

# Сборка
make build          # Собрать образы
make rebuild        # Пересобрать и перезапустить

# Отладка
docker-compose ps                    # Статус контейнеров
docker-compose logs -f backend       # Логи backend
docker-compose logs -f frontend      # Логи frontend
docker-compose exec backend bash     # Войти в backend
docker-compose exec frontend bash    # Войти в frontend

# Очистка
docker-compose down -v              # Остановить и удалить volumes
```

## 📝 Разработка

### Добавление новых методов запросов

1. Добавьте метод в `GameDataService` (services/game_data_service.py)
2. Используйте ТОЛЬКО существующие методы из db.py и db_helpers.py
3. Обновите `_interpret_request` в `ReportAgentSystem` для распознавания новых паттернов
4. При необходимости добавьте новый endpoint в API

### Расширение функциональности агентов

1. Редактируйте system messages в `agents/report_agents.py`
2. Добавляйте новые инструменты (tools) для агентов
3. Настройте параметры LLM в `llm_config`

## 📄 Лицензия

Следует лицензии основного проекта.

## 👥 Авторы

Создано для проекта "Без дураков. Белград."

