# 🎮 Web-based Game Data Reporting System

## 📋 Оглавление документации

### 🚀 Начало работы
1. **[README.md](README.md)** - Главная страница
   - Обзор системы
   - Быстрый старт
   - Установка и запуск
   - Основные возможности

2. **[SUMMARY.md](SUMMARY.md)** - Итоговая сводка
   - Что было создано
   - Структура проекта
   - Технологии
   - Достижения

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

## 📁 Структура файлов

### Основные компоненты
```
webreport/
├── backend/main.py                       - REST API (FastAPI)
├── backend/agents/report_agents.py       - LangGraph ReAct agent и fallback adapter
├── backend/services/game_data_service.py - Сервис данных
└── frontend/main.py                      - UI (Streamlit)
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

## 🎯 Быстрые ссылки

### Запуск (Docker только)
```bash
make start
# ИЛИ вручную
poetry run python generate_env.py
docker compose up -d
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
python3 validate_setup.py # Проверка файлов
```

### Доступ
- **Frontend**: http://localhost:28501
- **Backend API**: http://localhost:28000
- **API Docs**: http://localhost:28000/docs

## 📊 Схема работы

```
Пользователь
    ↓ (вводит требования)
Frontend (Streamlit)
    ↓ (HTTP/REST)
Backend (FastAPI, one replica)
    ↓ (startup election)
LangGraph ReAct agent or fallback
    ↓                ↘
LiteLLM `litellm:4000`   SQLite checkpoints
    ↓                    `../vm/backend/checkpoints`
GameDataService
    ↓
Database (MySQL game data)
```

Backend performs the LiteLLM probe once at startup, then keeps its elected `agent` or `fallback` mode until restart. LangGraph thread state lives in `../vm/backend/checkpoints`. Run one backend replica only; horizontal backend scaling is not supported.

## 🛠️ Технологии

| Слой | Технология |
|------|------------|
| Frontend | Streamlit |
| Backend | FastAPI |
| Agents | LangGraph ReAct |
| Model proxy | LiteLLM at `litellm:4000` |
| Agent state | SQLite checkpoints |
| Services | Python + Pandas |
| ORM | SQLAlchemy |
| Database | MySQL |

## ✅ Проверка системы

```bash
# Валидация файлов
cd webreport
python3 validate_setup.py

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
3. [SUMMARY.md](SUMMARY.md) - Детали реализации
4. Изучение кода
5. Расширение функциональности

## 🏆 Статус проекта

✅ **Готов к использованию**

Все компоненты реализованы и протестированы:
- ✅ 28/28 проверок пройдено
- ✅ Frontend (Streamlit)
- ✅ Backend (FastAPI)
- ✅ LangGraph agents with startup-elected `agent` or `fallback` mode
- ✅ Services
- ✅ Документация
- ✅ Тесты
- ✅ Docker поддержка

---

**Создано: 28.11.2025**

**Проект: Без дураков. Белград.**
