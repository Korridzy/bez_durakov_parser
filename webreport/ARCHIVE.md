# Архив разговоров

## Назначение

Архив сохраняет допущенные ходы из исполнителя `runs.py`, через который проходят `/api/chat` и `POST /api/chats/{id}/messages`, в отдельной SQLite базе. Он не зависит от checkpoint store и не является историей, которую использует агент.

Строки архива переживают TTL checkpoint store, вытеснение LRU, `/api/clear` и перезапуск backend. Очистка `/api/clear` удаляет checkpoint state, сообщения и runs в chats.db, но не архив. Незавершённая строка предыдущего запуска при следующем запуске получает состояние `failed` и ошибку `interrupted_at_restart`.

Архив не имеет HTTP маршрутов для чтения или удаления. Эти действия выполняет только оператор через CLI.

`chats.db` является третьим backend-owned SQLite хранилищем, отдельно от `checkpoints.db` и `conversations.db`. Он хранит чаты, transcript с `messages.reasoning`, runs и отчёты без TTL; под DATASET используется `chats-<name>.db`. Настройки retention архива к нему не применяются. Архив и его CLI управление остаются независимыми, удаление чата или закладки не удаляет архивные строки.

## Хранилище

`ConversationArchive` из `webreport/backend/archive.py` открывает отдельное соединение SQLite. Для файла включён WAL. Backend должен работать в одной реплике.

| Режим | Путь в контейнере | Путь на хосте |
| --- | --- | --- |
| Обычный | `/data/conversations.db` | ../vm/backend/checkpoints/conversations.db |
| Набор данных | `/data/conversations-${DATASET}.db` | ../vm/backend/checkpoints/conversations-${DATASET}.db |

Обычный путь задаёт `archive_db_path`. Переменная `BD_ARCHIVE_DB_PATH` имеет приоритет. Режим набора данных устанавливает переменную в `webreport/docker-compose.dataset.yml`.

Файлы базы, WAL и SHM получают права `0600`, когда они существуют. Для файловой резервной копии остановите backend и копируйте файл базы вместе с существующими файлами WAL и SHM. Для работающего backend используйте операцию `.backup` программы `sqlite3`.

## Схема

База содержит одну таблицу `turns`.

| Столбец | Значение |
| --- | --- |
| `id` | Целочисленный идентификатор строки |
| `request_id` | Идентификатор HTTP запроса |
| `trace_id` | 32 строчных шестнадцатеричных символа для связи с вызовами модели |
| `session_id` | Идентификатор чата |
| `user_id` | Зарезервированный идентификатор пользователя |
| `boot_id` | Идентификатор запуска backend, начавшего ход |
| `status` | Состояние `started`, `ok` или `failed` |
| `error` | Код ошибки либо `NULL` |
| `scope_verdict` | Вердикт scope gate |
| `model` | Настроенная модель агента |
| `user_message` | Текст пользователя |
| `assistant_message` | Текст ответа |
| `reasoning` | Рассуждения модели, если их хранение включено |
| `tool_calls` | JSON список вызовов инструментов |
| `report` | JSON сводка отчёта без строк данных |
| `created_at` | Время создания в UTC |
| `completed_at` | Время завершения в UTC либо `NULL` |

Значение `status` равно `started` до завершения обработки. Успешный ответ меняет его на `ok`. Ошибка агента или backend меняет его на `failed`.

| Значение `error` | Причина |
| --- | --- |
| `timeout` | Превышен лимит времени агента |
| `recursion_limit` | Превышен лимит рекурсии агента |
| `internal:<Type>` | В обработчике чата возникло неожиданное исключение типа `<Type>` |
| `interrupted_at_restart` | Строка осталась `started` после завершения предыдущего запуска |

Если `request_id` уже состоит из 32 строчных шестнадцатеричных символов, `trace_id` совпадает с ним. Иначе `trace_id` равен первым 32 символам SHA-256 от UTF-8 представления `request_id`.

`user_id` зарезервирован для будущего источника идентичности. Сейчас backend всегда записывает `NULL`.

Поле `model` содержит модель агента, даже если scope gate вызвал другую модель. В `report` поля `tool` и `args` берутся из последнего вызова инструмента. При отсутствии вызова оба поля равны `null`.

## Что сохраняется и что не сохраняется

| Сохраняется | Не сохраняется |
| --- | --- |
| Идентификаторы запроса, trace и сессии | Строки отчёта |
| Текст пользователя и ответ ассистента | Необработанные запросы к провайдеру |
| Вердикт scope gate и код ошибки | Учётные данные провайдеров и Langfuse |
| JSON вызовов инструментов | Отдельная таблица checkpoint state |
| Последний инструмент, аргументы, число строк и имена колонок | |

Поле `report` содержит только `tool`, `args`, `row_count` и `columns`. Значения самих строк отчёта в него не попадают.

`reasoning` сохраняется только при `archive_store_reasoning = true`. При значении `false` backend не записывает это поле.

## Конфигурация

Все параметры находятся в секции `[webreport]` файла `bd_shared/config.toml`. Серверные значения обычно задаются в локальном overlay конфигурации.

| Ключ | Значение по умолчанию | Назначение |
| --- | --- | --- |
| `archive_enabled` | `false` | Включает запись новых ходов |
| `archive_db_path` | `"/data/conversations.db"` | Путь базы внутри контейнера |
| `archive_retention_days` | `0` | Срок хранения завершённых строк в днях. `0` хранит их без срока |
| `archive_store_reasoning` | `true` | Разрешает запись reasoning |
| `archive_reasoning_retention_days` | `30` | Срок хранения reasoning в днях. `0` не очищает reasoning по сроку |
| `archive_sweep_interval_seconds` | `600` | Минимальный интервал проверки при новом ходе |
| `langfuse_host` | `""` | Адрес внешнего Langfuse |
| `langfuse_public_key` | `""` | Публичный ключ Langfuse |
| `langfuse_secret_key` | `""` | Секретный ключ Langfuse |

Langfuse включается только при непустых трёх значениях `langfuse_host`, `langfuse_public_key` и `langfuse_secret_key`. Значение `archive_sweep_interval_seconds = 0` отключает проверку при новом ходе. Явная проверка при запуске backend остаётся включённой.

## Хранение и удаление

Backend выполняет явный sweep один раз при запуске. Этот вызов не изменяет `_last_sweep_at`, поэтому первый `begin` при ненулевом `archive_sweep_interval_seconds` может немедленно запланировать ещё один sweep. После первой автоматической постановки `maybe_sweep` измеряет интервал от времени постановки этой задачи и не создаёт новую задачу, пока предыдущая не завершена.

При `archive_retention_days > 0` sweep удаляет завершённые строки с `created_at` раньше границы срока. Строки `started` не удаляются этим правилом. Удаление идёт пакетами по 500 строк. При значении `0` строки не удаляются по сроку.

При `archive_reasoning_retention_days > 0` sweep очищает только `reasoning` у более старых строк. Это правило независимо от удаления строк. При значении `0` sweep не очищает reasoning.

Цель `make archive-delete` требует ровно один селектор.

| Форма | Результат |
| --- | --- |
| `make archive-delete SESSION=<id>` | Удаляет строки одной сессии |
| `make archive-delete USER=<id>` | Удаляет строки одного пользователя |
| `make archive-delete BEFORE=<ISO-date-or-timestamp>` | Удаляет строки старше даты или времени ISO 8601 |

`/api/clear` не удаляет строки архива. TTL и LRU checkpoint store также не удаляют их.

Если Langfuse включён, CLI сначала выбирает trace id строк, которые ещё присутствуют локально, затем удаляет строки и отправляет выбранные trace id в Langfuse пакетами до 30. Удаление в Langfuse асинхронно. Ошибка внешнего запроса не отменяет уже выполненное локальное удаление.

## Просмотр

Цель `make archive-list` выводит только `id`, `created_at`, `status`, `error`, `session_id`, `request_id` и `trace_id`. Текст сообщений в этом списке отсутствует. Цель `make archive-show` печатает полную строку как JSON.

```bash
make archive-list LIMIT=5
make archive-list SESSION=qa-session
make archive-show ID=1
```

Файл архива получает права `0600`, поэтому просматривайте его внутри контейнера backend.

```bash
docker compose -f webreport/docker-compose.yml exec backend python -c "import sqlite3; print(sqlite3.connect('/data/conversations.db').execute('select id,status,error,session_id from turns order by id').fetchall())"
```

Команда `make archive-delete` выводит число удалённых локальных строк. В проверке CLI удаление сессии удалило две строки, а несуществующая сессия дала ноль.

## Langfuse

LiteLLM proxy получает контекст от backend и передаёт его в callback `langfuse_otel`.

| Контекст backend | Поле Langfuse |
| --- | --- |
| `session_id` | `session.id` |
| `generation_name` | `langfuse.generation.name` |
| `tags` | Теги trace, включая `webreport` и среду |
| `trace_metadata.request_id` | Метаданные trace с `request_id` |
| Заголовок `traceparent` | Общий trace id и отдельный span id вызова |

Backend также передаёт `request_id`. Если когда нибудь будет связан `user_id`, proxy передаст его как `trace_user_id` и Langfuse получит `user.id`.

Укажите три ключа Langfuse в конфигурации и выполните `make restart`. Генератор записывает `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` и `LANGFUSE_HOST` в `.env.litellm`. При включении он добавляет callback в сгенерированные настройки LiteLLM.

Langfuse не поставляется в этом проекте. Экземпляр на хосте контейнер видит по имени `host.docker.internal`.

Захват сообщений в Langfuse включён. Контрактный тест подтверждает наличие входа и выхода generation. Это не меняет правило архива, который не хранит необработанные запросы провайдера.

Backend не экспортирует корневой span. Поэтому Langfuse группирует generation по общему trace id и `session.id`. Повторное использование `X-Request-ID` намеренно приводит к общему trace.

На Windows и Docker Desktop следите за `disk I/O error` SQLite при WAL на bind mount. Эта ошибка означает, что слой монтирования требует проверки.

## Конфиденциальность

Архив содержит пользовательскую и ассистентскую прозу. При включённом хранении reasoning он содержит и reasoning. Доступ к данным получают пользователи тома `/data` и контейнера backend.

Конфигурационные секреты не имеют полей в архиве. Необработанные запросы провайдеров также не записываются. Секрет, который пользователь сам введёт в чат, остаётся частью пользовательской прозы. Не передавайте секреты в чат.

Общий конвейер логов маскирует ключи `langfusesecretkey` и `langfusepublickey`. Ограничивайте доступ к тому и контейнеру. Удаление доступно только через CLI, а не через HTTP.

## Тесты

| Файл | Полоса |
| --- | --- |
| `backend/test_archive_store.py` | `make test` |
| `backend/test_archive_api.py` | `make test` |
| `backend/test_archive_cli.py` | `make test` |
| `backend/test_langfuse_proxy_contract.py` | `make test-proxy-contract` и `make test` |
