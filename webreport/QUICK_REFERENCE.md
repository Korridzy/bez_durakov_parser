# 🎮 ШПАРГАЛКА - Система веб-отчётов

## ⚡ Быстрый старт (2 команды)

```bash
cd /home/homo/git/bez_durakov/parser/webreport
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
make install       # Установка зависимостей
make start-all     # Запуск всего
make test          # Тесты
make docker-up     # Docker запуск
make docker-down   # Docker остановка
make clean         # Очистка
```

## 📂 Структура каталога

```
webreport/
├── backend/          # FastAPI
├── frontend/         # Streamlit
├── agents/           # AutoGen
├── services/         # Бизнес-логика
├── *.sh              # Скрипты запуска
├── *.md              # Документация
└── test_system.py    # Тесты
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

# Проверить статус контейнеров
docker-compose ps
```

### Общая диагностика
```bash
python3 validate_setup.py  # Проверка файлов
make test                  # Запуск тестов
```

## 🔄 Остановка системы

```bash
# Ctrl+C в терминале где запущена система

# ИЛИ
make stop

# ИЛИ вручную
pkill -f uvicorn
pkill -f streamlit
```

## 📦 Установка зависимостей

```bash
pip install -r requirements.txt
```

### Основные пакеты:
- fastapi
- uvicorn
- streamlit
- pyautogen (опционально)
- pandas
- httpx

## 🔑 Переменные окружения

```bash
# Создать .env файл
cp .env.example .env

# Редактировать
nano .env

# Важные переменные:
# OPENAI_API_KEY=...        # Для AutoGen
# API_BASE_URL=...          # URL backend
```

## 📊 API Endpoints (для интеграции)

### Чат
```bash
POST /api/chat
GET  /api/history/{session_id}
POST /api/clear/{session_id}
```

### Данные
```bash
GET /api/games              # Все игры
GET /api/games/{game_id}    # Конкретная игра
GET /api/teams              # Все команды
GET /api/teams/{name}/stats # Статистика команды
GET /api/scores             # Очки
```

### Система
```bash
GET /                       # Информация
GET /health                 # Здоровье
```

## 🎨 Интерфейс

### Навигация
- **💬 Чат** - ввод требований
- **📊 Отчёт** - просмотр результатов

### Действия
- **Отправить** - создать отчёт
- **Очистить историю** - сброс
- **🔄 Обновить** - перезагрузка
- **📥 Скачать CSV** - экспорт

## 🧪 Тестирование

```bash
# Запуск всех тестов
python3 test_system.py

# Или через make
make test

# Проверка setup
python3 validate_setup.py
```

## 🐳 Docker

```bash
# Запуск
docker-compose up -d

# Остановка
docker-compose down

# Логи
docker-compose logs -f

# Пересборка
docker-compose up -d --build
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

## 💡 Советы

1. **Первый запуск**: Используйте setup.sh
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
- ⚠️ OpenAI API key опционален (fallback режим)

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

