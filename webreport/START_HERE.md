# 🎮 Система веб-отчётов - Быстрый старт

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
- ✅ **Frontend** - Streamlit UI с двумя представлениями (Чат и Отчёт)
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
│   └── frontend/main.py       - Streamlit
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
- История диалога

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
- Интерактивные элементы

### 🔌 REST API
- `/api/chat` - диалог с агентом
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
| **USER_GUIDE.md** | Пользователи | Детальное руководство |
| **ARCHITECTURE.md** | Разработчики | Архитектура системы |
| **QUICK_REFERENCE.md** | Все | Шпаргалка |
| **PROJECT_STATUS.md** | Все | Статус проекта |

---

## 🛠️ Технологии

- **Python 3.11+**
- **Streamlit** - UI framework
- **FastAPI** - REST API framework  
- **LangGraph** - ReAct agent и checkpointed threads
- **LiteLLM** - internal model proxy `litellm:4000`
- **SQLAlchemy** - ORM (из основного проекта)
- **Pandas** - Data processing
- **MySQL, PostgreSQL или SQLite** - база набора данных (из bd_shared/config.toml)
- **SQLite** - backend checkpoint store `../vm/backend/checkpoints`

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
make logs          # Логи
```

### Проверка
```bash
python3 validate_setup.py  # Валидация установки
python3 backend/test_system.py     # Тесты системы
```

### Остановка
```bash
Ctrl+C             # В терминале
make stop          # Через Make
```

---

## 🔍 Валидация

```bash
$ python3 validate_setup.py

✅ Passed: 33/33 checks
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
   - `frontend/main.py`

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
