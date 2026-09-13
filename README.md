

## Парсер результатов серии игр "Без дураков. Белград."

Парсит результаты игр из xlsm и складывает их в реляционную БД.

Проект также содержит ORM на базе SQLAlchemy для упрощения анализа накопленных данных.

WebReport в Windows после первоначальной настройки можно запускать двойным кликом по `Start-WebReport.cmd` в корне проекта и останавливать через `Stop-WebReport.cmd`. Подробнее: [запуск в Windows](doc/windows-launcher.md).

### Как пользоваться парсером.

Все инструкции даны на примере linux. Если для других ОС обнаружатся существенные отличия, пишите о них в [трекер](https://github.com/Korridzy/bez_durakov_parser/issues). Или даже вносите изменения непосредственно в [этот документ](https://github.com/Korridzy/bez_durakov_parser/blob/main/README.md), если умеете.



#### Установка

Откройте терминал bash и выполните следующие команды:
- ```bash
  $ cd /your/comfortable/path
  ```

- ```bash
  $ git clone https://github.com/Korridzy/bez_durakov_parser.git
  ```

- ```bash
  $ cd bez_durakov_parser
  ```

- ```bash
  $ make setup
  ```

На этом этапе будет создана виртуальная среда в каталоге `/your/comfortable/path/bez_durakov_parser/.venv`, и в неё будут установлены все необходимые зависимости.

`bd_shared/config.toml` хранит отслеживаемые в Git значения по умолчанию. Для параметров конкретного сервера создайте игнорируемый overlay:

```bash
$ cp bd_shared/config.local.toml.example bd_shared/config.local.toml
$ chmod 600 bd_shared/config.local.toml
```

Далее пропишите в `bd_shared/config.local.toml` параметры доступа к БД. Парсер работает с MySQL, а WebReport дополнительно принимает PostgreSQL и SQLite. По умолчанию используется локальный контейнер с MySQL, который можно запустить командой:

```bash
$ make mysql-start
```

Строка подключения в `bd_shared/config.local.toml`:

```toml
[database]
url = "mysql+pymysql://durak:devpass@localhost:3306/bez_durakov"
docker_url = "mysql+pymysql://durak:devpass@mysql:3306/bez_durakov"
sqlalchemy_logging = false
```

`url` используется командами на хосте, а `docker_url` — backend и data collector внутри Docker. Команда `make mysql-start` генерирует в `webreport/` общий Compose env-файл и отдельные env-файлы сервисов перед запуском контейнера MySQL.

В конфиге имеется закомментированная строка подключения в качестве примера для подключения к удалённой базе данных с SSL:

```toml
url = "mysql+pymysql://username:password@srv_address:port/db_name?ssl_ca=/path/to/ca.pem&ssl_cert=/path/to/client-cert.pem&ssl_key=/path/to/client-key.pem"
```

Если вы настраиваете БД с нуля или апгрейдитесь до новой версии схемы, выполните обновление схемы:

```bash
$ make upgrade-db
```

Активируйте виртуальную среду:

```bash
$ source .venv/bin/activate
```



#### Обновление 

Код парсера или ORM можно обновить до последнего лежащего в ветке main при помощи команды:

```bash
$make upgrade-code
```

Локальный `bd_shared/config.local.toml` не отслеживается Git и сохраняется при обновлении кода. Если вы изменили ещё какие-то отслеживаемые файлы, то автоматического обновления не произойдёт.



#### Использование

Теперь вы можете использовать парсер для добавления игр в БД:

```bash
$ python parse_data.py -h
usage: parse_data.py [-h] [--no-save] [-v] directory

Parse all XLSM files in a directory.

positional arguments:
  directory      Path to the directory containing XLSM files

options:
  -h, --help     show this help message and exit
  --no-save      Do not save data to database
  -v, --verbose  Display detailed parsing results
```

А ещё можете посмотреть пример использования ORM для анализа:

```bash
$ cd examples/
$ python four_buckets.py 

Анализ 25 игр:
Выгодно сохранить баллы: 17 игр (68.0%)
Невыгодно сохранять баллы: 5 игр (20.0%)
Без разницы: 3 игр (12.0%)
Средняя выгода: +1.84 мест

```

![](./doc/img/README/4_bucket_strategy_analysis_on_team.png)

Этот пример анализирует хранящиеся в БД игры не старше 365 дней с текущей даты. Проверяет, улучшила ли бы свои результаты команда "Суровая реальность", если бы не делала ставки в финальном раунде, а просто сохранила очки. При этом предполагается, что все остальные команды сыграли бы как было в реальности. Результат выдаётся в виде небольшого текстового отчёта в командной строке и визуализации, которая сохраняется в png-файл в каталоге из которого запущен скрипт.



### Web Report System

Проект включает веб-систему для анализа данных с LangGraph ReAct агентом, FastAPI и React. В интерфейсе доступны проекты, чаты, подключения аналитики и собственные модели по API. Подробнее: [рабочее пространство WebReport](webreport/frontend-web/README.md). Backend обращается к внутреннему LiteLLM proxy по адресу `litellm:4000` для системной модели и хранит состояние диалогов в service-local SQLite checkpoint store: `../vm/backend/checkpoints`.

При запуске backend выполняет глубокую проверку LiteLLM. Если модель недоступна, процесс остаётся запущенным, но отказывается отвечать, и `/health` вместе с `/api/chat` возвращают 503. Каждая следующая попытка чата повторяет проверку один раз, и первый успешный результат собирает агента и отвечает на этот же запрос. WebReport поддерживает только один экземпляр backend, горизонтальное масштабирование backend не поддерживается.

#### Запуск WebReport

Для запуска полного стека (MySQL + Backend + Frontend):

```bash
$ make webreport-start
```

После запуска по умолчанию доступны:
- **Frontend** (React workspace): http://localhost:28501
- **Backend API**: http://localhost:28000
- **API документация**: http://localhost:28000/docs

Фактические порты берутся из секции `[webreport]` в `bd_shared/config.toml` и выводятся командой запуска.

Настройка и наполнение папки знаний описаны в [разделе «Знания о предметной области (для оператора)»](./webreport/USER_GUIDE.md#знания-о-предметной-области-для-оператора).

Остановка:

```bash
$ make webreport-stop
```

Перезапуск LiteLLM, backend и frontend с повторной генерацией service env-файлов. MySQL и data collector продолжают работать:

```bash
$ make restart
```

#### Только база данных

Если нужна только MySQL для работы с парсером (без WebReport):

```bash
$ make mysql-start  # Запуск
$ make mysql-stop   # Остановка
```

#### Загрузка XLSM файлов

XLSM файлы загружаются автоматически сервисом `data_collector` в составе WebReport. Для ручного запуска загрузки используйте:

```bash
$ make fetch-data
```

Для просмотра логов последней загрузки:

```bash
$ make fetch-data-log
```

Для просмотра всех логов контейнера `data_collector`:

```bash
$ make logs SERVICE=data_collector
```

Подробнее о WebReport см. [webreport/README.md](./webreport/README.md)



#### Вспомогательные материалы

Чтобы анализировать накопленные данные по играм и клепать такие же красивенькие отчёты, как в примере выше, будет полезно ознакомиться со следующими документами:

- [Описание ORM](./doc/ORM.md)
- [Описание структуры данных](./doc/bd_game.md) для хранения полной информации об игре. Её возвращает функция `Database.get_game_data()`.
- [Код примера анализа](./examples/four_buckets.py)
- [db_helpers](./db_helpers.py)
