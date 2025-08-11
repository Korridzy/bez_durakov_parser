# Документация по ORM-моделям

В этом файле определены ORM-модели для работы с базой данных с помощью SQLAlchemy. Модели соответствуют таблицам и представлениям, используемым для хранения и анализа результатов игр.

## Основные сущности

### Game
**Таблица:** `games`
**Описание:** Хранит информацию об играх.
**Поля:**

- `game_id` (Integer, PK) - уникальный идентификатор игры
- `game_date` (Date, NOT NULL) - дата проведения игры  
- `created_at` (DateTime) - время создания записи

**Связи:**

- `teams` → GameTeam (игры и команды)
- `vybor_results` → Vybor (результаты раунда "Выбор")
- `chisla_results` → Chisla (результаты раунда "Числа")
- `pref_results` → Pref (результаты раунда "Преферанс")
- `pairs_results` → Pairs (результаты раунда "Пары")
- `razobl_results` → Razobl (результаты раунда "Разоблачение")
- `auction_results` → Auction (результаты раунда "Аукцион")
- `mot_results` → Mot (результаты раунда "Момент истины")

### Team
**Таблица:** `teams`
**Описание:** Хранит информацию о командах.
**Поля:**

- `team_id` (Integer, PK) - уникальный идентификатор команды
- `team_name` (String, NOT NULL, UNIQUE) - название команды

**Связи:**

- `teams` → GameTeam (игры и команды)
- `vybor_results` → Vybor (результаты раунда "Выбор")
- `chisla_results` → Chisla (результаты раунда "Числа")
- `pref_results` → Pref (результаты раунда "Преферанс")
- `pairs_results` → Pairs (результаты раунда "Пары")
- `razobl_results` → Razobl (результаты раунда "Разоблачение")
- `auction_results` → Auction (результаты раунда "Аукцион")
- `mot_results` → Mot (результаты раунда "Момент истины")

### GameTeam
**Таблица:** `game_teams`
**Описание:** Связующая таблица для связи многие-ко-многим между играми и командами.
**Поля:**

- `game_id` (Integer, FK, PK) - ссылка на игру
- `team_id` (Integer, FK, PK) - ссылка на команду

## Модели раундов игры

### Vybor (Выбор)
**Таблица:** `vybor`
**Поля:**

- `game_id`, `team_id` (FK, PK) - составной первичный ключ
- `points` (Numeric) - очки за раунд

### Chisla (Числа)
**Таблица:** `chisla`
**Поля:**

- `game_id`, `team_id` (FK, PK)
- `task_1` до `task_5` (Numeric) - очки за каждое задание
- `total_sum` (Numeric) - общая сумма очков

### Pref (Преферанс)
**Таблица:** `pref`
**Поля:**

- `game_id`, `team_id` (FK, PK)
- `task_1` до `task_7` (Numeric) - очки за задания
- `points` (Numeric) - базовые очки
- `penalty` (Numeric) - штрафные очки
- `bonus` (Numeric) - бонусные очки
- `total_sum` (Numeric) - итоговая сумма

### Pairs (Пары)
**Таблица:** `pairs`
**Поля:**

- `game_id`, `team_id` (FK, PK)
- `points` (Numeric) - очки за раунд

### Razobl (Разоблачение)
**Таблица:** `razobl`
**Поля:**

- `game_id`, `team_id` (FK, PK)
- `task_1` до `task_4` (Numeric) - очки за задания
- `total_sum` (Numeric) - общая сумма

### Auction (Аукцион)
**Таблица:** `auction`
**Поля:**

- `game_id`, `team_id` (FK, PK)
- `task_X_bid` (Numeric) - ставка для задания X
- `task_X_points` (Numeric) - очки за задание X
- `task_X_rate` (Numeric, nullable) - коэффициент для задания X
- `total_sum` (Numeric) - общая сумма

### Mot (Момент истины)
**Таблица:** `mot`
**Поля:**

- `game_id`, `team_id` (FK, PK)
- `task_1` до `task_3` (Numeric) - очки за задания
- `total_sum` (Numeric) - общая сумма

### TeamGameScore (Представление)
**Представление:** `team_game_scores`
**Описание:** Агрегированное представление результатов всех команд по играм.
**Назначение:**

- Быстрый доступ к итоговым очкам команд по раундам
- Удобное сравнение результатов между командами
- Поиск и идентификация идентичных игр

**Поля:**
- `game_id`, `team_id` (PK) - составной ключ
- `game_date` (Date) - дата игры
- `team_name` (String) - название команды
- `vybor_points`, `chisla_points`, `pref_points`, `pairs_points`, `razobl_points`, `auction_points`, `mot_points` (Numeric) - суммы очков по раундам
- `total_points` (Numeric) - общая сумма очков за игру

## Класс Database

### Основные методы:

**`__init__(db_url=None)`** - инициализация подключения к БД

**`get_or_create_team(session, team_name)`** - получение команды по имени или создание новой

**`add_game(bd_game)`** - добавление игры из экземпляра BdGame

**`remove_game(game_id)`** - удаление игры и всех связанных записей

**`get_all_games()`** - получение всех игр

**`get_game_data(game_id)`** - получение полных данных игры как экземпляр BdGame

**`get_game_ids_by_date(start_date, end_date=None)`** - получение ID игр по дате/диапазону дат

**`find_identical_game(game_instance)`** - поиск идентичной игры в БД. Идентичными считаются игры, у которых совпадает дата проведения, состав команд и итоговые суммы очков.

## Пример использования

```python
# Создание экземпляра БД
db = Database()

# Добавление игры
success = db.add_game(bd_game_instance)

# Получение данных игры
game_data = db.get_game_data(game_id)

# Поиск игр по дате
game_ids = db.get_game_ids_by_date(datetime.date(2024, 1, 15))

# Поиск дубликатов
duplicate = db.find_identical_game(new_game_instance)
```

## Особенности реализации

- Поддерживает автоматическое создание команд при добавлении игр
- Включает представление для эффективного поиска дубликатов
- Все числовые значения хранятся как Numeric(10, 2)
- Использует составные первичные ключи для таблиц результатов