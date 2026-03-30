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
make restart       # Перезапуск сервисов
make logs          # Логи
make build         # Сборка образов
make rebuild       # Пересборка и запуск
make test          # Тесты
make clean         # Очистка
```

## 📂 Структура каталога

```
webreport/
├── backend/          # FastAPI + agents + services + tests
├── frontend/         # Streamlit
├── data_collector/   # XLSM fetch scheduler
├── generate_env.py   # Генерация .env из ../bd_shared/config.toml
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

## ⚙️ Конфигурация

```bash
cat ../bd_shared/config.toml

# Сгенерировать .env для docker-compose
poetry run python generate_env.py

# Для полного AutoGen режима (опционально)
export OPENAI_API_KEY=your-openai-api-key-here
```

### Секции в `bd_shared/config.toml`
- `[database]` — настройки подключения к БД
- `[application]` — общие флаги приложения
- `[webreport]` — порты, CORS (`allowed_origins`) и debug-настройки WebReport
- `[xlsm_fetch]` — URL источника, режимы загрузки, расписание и timezone

Для `[xlsm_fetch].modes` используйте только `browser_selenium`.
`public_api` и `gdown` пока не реализуют реальную загрузку файлов.

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
python3 backend/test_system.py

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
