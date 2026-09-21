# Логирование WebReport

## Архитектура

Один конвейер объединяет `structlog` и стандартную библиотеку `logging`. Точка входа каждого процесса явно вызывает `configure_logging`, после чего записи `structlog` и стандартной библиотеки проходят через один обработчик.

Имена сервисов:

- `webreport-backend`
- `webreport-frontend`
- `webreport-data-collector`
- `bd-parser-cli`
- `bd-clear-database`
- `bd-alembic`

Предпусковые CLI `agent/knowledge_cli.py` и `agent/tools_cli.py` печатают результат проверки. Они намеренно не инициализируют конвейер.

Известно ограничение. Собственные логгеры фреймворка `Streamlit` не передаются корневому логгеру и сохраняют формат `Streamlit`. Через конвейер проходят только записи приложения фронтенда.

## Конфигурация

Параметры находятся в секции `[application]` файлов `../bd_shared/config.toml` и `../bd_shared/config.local.toml`.

| Ключ | Назначение |
| --- | --- |
| `log_level` | Уровень записей |
| `log_format` | Формат `json` или `console` |
| `environment` | Имя среды |

`generate_env.py` создаёт для бэкенда, фронтенда и сборщика данных переменные: `BD_LOG_LEVEL`, `BD_LOG_FORMAT`, `BD_ENVIRONMENT`, `BD_APP_VERSION`.

На производственном сервере `config.local.toml` задаёт `environment = "production"` и `log_format = "json"`. Команды `make restart` и `make start` заново создают файлы окружения. Поэтому `BD_APP_VERSION` получает короткий идентификатор текущего проверенного коммита.

## Форматы

В `json` каждая запись является одной JSON строкой. Ниже приведён фактически полученный вывод локальной команды.

```json
{"method": "GET", "route": "/health", "status": 200, "duration_ms": 1.2, "event": "http_request", "request_id": "11111111111111111111111111111111", "session_id": "22222222222222222222222222222222", "logger": "webreport.backend.request", "level": "info", "timestamp": "2026-09-19T22:42:21.955410Z", "module": "<string>", "lineno": 1, "func_name": "<module>", "service": "webreport-backend", "environment": "production", "version": "abc1234"}
```

Формат `console` предназначен для чтения человеком. Ниже приведён фактически полученный вывод локальной команды.

```text
2026-09-19T22:42:21.964296Z [info     ] http_request                   [webreport.backend.request] duration_ms=1.2 environment=production func_name=<module> lineno=1 method=GET module=<string> request_id=11111111111111111111111111111111 route=/health service=webreport-backend session_id=22222222222222222222222222222222 status=200 version=abc1234
```

## Поля записи

Поля ниже добавляются конвейером или конкретным обработчиком. Часть полей присутствует только в соответствующем контексте.

| Поле | Значение |
| --- | --- |
| `timestamp` | Время записи в UTC |
| `level` | Уровень записи |
| `event` | Имя события |
| `logger` | Имя логгера |
| `service` | Имя процесса |
| `environment` | Среда из конфигурации |
| `version` | Версия из `BD_APP_VERSION` |
| `module` | Модуль, создавший запись |
| `lineno` | Номер строки, создавшей запись |
| `func_name` | Имя функции, создавшей запись |
| `request_id` | Идентификатор HTTP запроса |
| `trace_id` | Идентификатор trace, производный от `request_id` |
| `session_id` | Идентификатор сессии чата |
| `job_id` | Идентификатор запуска задания коллектора |
| `job_name` | Имя задания коллектора |
| `model` | Имя модели при вызове LiteLLM |
| `role` | Роль вызова модели в `llm_call` и `llm_call_failed` |
| `exception` | Структурированное исключение в `json` |

`trace_id` выдаётся вместе с `request_id`. Имена `span_id` и `user_id` остаются зарезервированными. Источник идентичности пользователя пока отсутствует.

## Корреляция

Значение `X-Request-ID` принимается, если оно полностью соответствует `[A-Za-z0-9._-]{1,128}`. При отсутствии или недопустимом значении бэкенд создаёт новый идентификатор. Ответ всегда содержит заголовок `X-Request-ID`.

Фронтенд создаёт один новый `X-Request-ID` для каждого вызова бэкенда. Бэкенд связывает `session_id` в `/api/chat`, `/api/history/{session_id}` и `/api/clear/{session_id}`.

Если `request_id` состоит из 32 строчных шестнадцатеричных символов, `trace_id` совпадает с ним. Иначе `trace_id` равен первым 32 символам SHA-256 от UTF-8 представления `request_id`.

При вызове LiteLLM в `metadata` передаются `request_id`, `session_id`, `trace_metadata` с `request_id`, `generation_name` и теги `webreport` с именем среды. Связанный `user_id` добавляется только как `trace_user_id`. Поле `user` не отправляется.

Заголовки вызова содержат `X-Request-ID` и `traceparent`. `traceparent` несёт общий trace id запроса и новый span id отдельного вызова модели.

Коллектор связывает один запуск с `job_id` и `job_name`. Для задания загрузки значение `job_name` равно `xlsm_fetch`.

Для поиска одного запроса выполните:

```bash
docker compose logs backend | grep <request_id>
```

## Чувствительные данные

Перед сравнением ключ приводится к нижнему регистру, а символы `-`, `_` и пробелы удаляются. Следующий набор ключей маскируется значением `[REDACTED]`.

`authorization`, `proxyauthorization`, `cookie`, `setcookie`, `apikey`, `xapikey`, `token`, `accesstoken`, `refreshtoken`, `secret`, `clientsecret`, `password`, `passwd`, `openaiapikey`, `openrouterapikey`, `opencodeapikey`, `langfusesecretkey`, `langfusepublickey`, `databaseurl`, `dburl`

Следующий набор ключей заменяется значением `[OMITTED]`.

`message`, `messages`, `prompt`, `prompts`, `response`, `content`, `reasoning`, `reasoningcontent`, `rows`, `result`, `results`, `queryresult`, `data`

Учётные данные URL между схемой и `@` заменяются значением `[REDACTED]`. Значения параметров `apikey`, `token`, `accesstoken`, `key`, `signature`, `sig`, `secret` и `password` в строке запроса также маскируются.

Содержимое разговора и данные запроса к модели не попадают в общие логи. Работа с таким содержимым относится к issue #108, а не к этому конвейеру.

## Docker

Якорь `x-logging` в `docker-compose.yml` задаёт драйвер `json-file` с `max-size` равным `10m` и `max-file` равным `3`. Просмотр доступен командой `docker compose logs`.

Приложение пишет только в `stderr`. Предел ротации одновременно ограничивает хранение, Docker оставляет не более трёх файлов по `10m` для контейнера.

По замыслу логи не содержат личных данных. `session_id` создаётся случайным вызовом `uuid.uuid4()`, а идентичность пользователя в приложении отсутствует.

Каждый перезапуск `Streamlit` опрашивает `/health`. Это создаёт одну запись `http_request` и одну запись `backend_request`. Такой объём на уровне `INFO` принят в пределах установленного ограничения.

## Интеграция с внешними системами

- `Loki` и `Promtail` могут читать Docker драйвер `json-file` или Docker плагин `Loki`. Сопоставляйте `timestamp`, `level`, `event`, `service`, `logger`, `environment`, `version`, `request_id` и `session_id`.
- `Elasticsearch` и `Filebeat` могут читать контейнерный ввод с `json.keys_under_root`. Сопоставляйте `timestamp`, `level`, `event`, `service`, `logger`, `request_id`, `session_id`, `job_id`, `job_name` и `model`.
- OpenTelemetry Collector может читать `filelog` с оператором `json_parser`. Сопоставляйте `timestamp`, `level`, `event`, `service`, `logger`, `request_id`, `session_id`, `job_id`, `job_name` и `model`.

## Связь с issue #108

Issue #108 добавляет постоянный архив разговоров и корреляцию вызовов модели. Полное описание хранения, удаления, CLI и Langfuse находится в [ARCHIVE.md](ARCHIVE.md).

Общие логи по-прежнему не содержат `message`, `messages`, `prompt`, `response`, `content`, `reasoning`, результаты запросов или данные запроса к модели. Для связи записей используйте `request_id`, `trace_id` и `session_id`.

## Тесты

| Файл | Команда |
| --- | --- |
| `bd_shared/test_logging_setup.py` | Корневой `make test` |
| `bd_shared/test_log_redaction.py` | Корневой `make test` |
| `webreport/backend/test_request_context.py` | `make -C webreport test` и корневой `make test` |
| `webreport/backend/test_agent_correlation.py` | `make -C webreport test` и корневой `make test` |
| `webreport/backend/test_archive_store.py` | `make -C webreport test` |
| `webreport/backend/test_archive_api.py` | `make -C webreport test` |
| `webreport/backend/test_archive_cli.py` | `make -C webreport test` |
| `webreport/backend/test_langfuse_proxy_contract.py` | `make -C webreport test-proxy-contract` и `make -C webreport test` |
| `webreport/data_collector/test_logging_jobs.py` | Корневой `make test` |
| `webreport/frontend/test_frontend_logging.py` | Корневой `make test` |

`make -C webreport test` запускает проверки бэкенда, включая archive и correlation проверки. `make -C webreport test-proxy-contract` выполняет контрактную проверку внутри образа LiteLLM. Корневой `make test` дополнительно запускает проверки общего кода, сборщика данных и фронтенда.
