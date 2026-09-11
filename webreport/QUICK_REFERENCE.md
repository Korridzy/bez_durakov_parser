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
make clean         # Очистка
```

## 📂 Структура каталога

```
webreport/
├── backend/          # FastAPI + agents + services + tests
├── frontend/         # Streamlit
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

# Проверить статус контейнеров
docker compose ps
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

### Секции в `bd_shared/config.toml` и `config.local.toml`
- `[database]` — настройки подключения к БД
- `[application]` — общие флаги приложения
- `[webreport]` — порты, CORS (`allowed_origins`), `openai_api_key`, пределы знаний и debug-настройки WebReport
- `[dataset]` — `tools_module` и `knowledge_dir`
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

### Система
```bash
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
