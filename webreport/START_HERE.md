# 🎮 Система веб-отчётов - Быстрый старт

## ✅ Система создана и готова к использованию!

Создана полнофункциональная web-система для генерации отчётов по игровым данным с использованием AI-агентов.

---

## 🚀 Запуск за 3 шага

### Шаг 1: Установка зависимостей
```bash
cd /home/homo/git/bez_durakov/parser/webreport
./setup.sh
```

### Шаг 2: Запуск системы
```bash
./start_all.sh
```

### Шаг 3: Использование
Откройте в браузере: **http://localhost:28501**

---

## 📋 Что было создано

### 🏗️ Архитектура (SOA)
- ✅ **Frontend** - Streamlit UI с двумя представлениями (Чат и Отчёт)
- ✅ **Backend** - FastAPI REST API
- ✅ **Agents** - AutoGen агенты для обработки запросов
- ✅ **Services** - Сервисный слой (использует только существующие методы db.py)

### 📁 Структура (28 файлов)
```
webreport/
├── 📚 Документация (8 файлов)
│   ├── README.md              - Основная документация
│   ├── USER_GUIDE.md         - Руководство пользователя
│   ├── ARCHITECTURE.md       - Архитектура
│   ├── QUICK_REFERENCE.md    - Шпаргалка
│   └── ...
├── 💻 Код (8 файлов)
│   ├── backend/api.py         - FastAPI
│   ├── frontend/app.py        - Streamlit
│   ├── agents/report_agents.py - AutoGen
│   └── services/game_data_service.py
├── 🚀 Скрипты (6 файлов)
│   ├── setup.sh               - Установка
│   ├── start_all.sh           - Запуск
│   └── ...
└── ⚙️ Конфигурация (6 файлов)
    ├── requirements.txt
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
- `/api/games` - данные игр
- `/api/teams` - команды
- `/api/scores` - очки

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
- **AutoGen** - Multi-agent orchestration
- **SQLAlchemy** - ORM (из основного проекта)
- **Pandas** - Data processing
- **MySQL** - Database (из bd_shared/config.toml)

---

## ⚡ Быстрые команды

### Make команды
```bash
make help          # Справка
make install       # Установка
make start-all     # Запуск
make test          # Тесты
make docker-up     # Docker
```

### Проверка
```bash
python3 validate_setup.py  # Валидация установки
python3 test_system.py     # Тесты системы
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

✅ Passed: 28/28 checks
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
make docker-up

# Остановка
make docker-down

# Логи
docker-compose logs -f
```

---

## 🔧 Интеграция с проектом

### Используемые методы из db.py
Система использует **ТОЛЬКО существующие методы**:

- `Database.__init__(db_url)`
- `Database.get_all_games()`
- `Database.get_game_data(game_id)`
- `Database.get_game_ids_by_date(start_date, end_date)`
- `initialize_database()` из db_helpers.py

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
   - `services/game_data_service.py`
   - `agents/report_agents.py`
   - `backend/api.py`
   - `frontend/app.py`

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

- [ ] База данных доступна (MySQL)
- [ ] bd_shared/config.toml настроен правильно
- [ ] Python 3.11+
- [ ] Порты 8000 и 8501 свободны
- [ ] Запущен `./setup.sh`
- [ ] (Опционально) OpenAI API key в .env

---

## 🎉 Готово!

Система полностью создана и готова к использованию.

**Запустить:**
```bash
cd /home/homo/git/bez_durakov/parser/webreport
./start_all.sh
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

