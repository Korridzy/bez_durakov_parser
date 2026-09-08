# Глоссарий схемы данных

Здесь перечислены ORM-классы и названия раундов, которые присутствуют в схеме данных проекта.

- `Game` (`games`): `game_id`, `game_date`, `created_at`.
- `Team` (`teams`): `team_id` и уникальное `team_name`.
- `GameTeam` (`game_teams`): `game_id` и `team_id`, образующие составной первичный ключ.
- `Vybor` (`vybor`): `game_id`, `team_id`, `points`.
- `Chisla` (`chisla`): `game_id`, `team_id`, `task_1`, `task_2`, `task_3`, `task_4`, `task_5`, `total_sum`.
- `Pref` (`pref`): `game_id`, `team_id`, `task_1`, `task_2`, `task_3`, `task_4`, `task_5`, `task_6`, `task_7`, `goal`, `points`, `penalty`, `bonus`, `total_sum`.
- `Pairs` (`pairs`): `game_id`, `team_id`, `points`.
- `Razobl` (`razobl`): `game_id`, `team_id`, `task_1`, `task_2`, `task_3`, `task_4`, `total_sum`.
- `Auction` (`auction`): `game_id`, `team_id`, `task_1_bid`, `task_1_points`, `task_1_rate`, `task_2_bid`, `task_2_points`, `task_2_rate`, `task_3_bid`, `task_3_points`, `task_3_rate`, `task_4_bid`, `task_4_points`, `task_4_rate`, `total_sum`.
- `Mot` (`mot`): `game_id`, `team_id`, `task_1`, `task_2`, `task_3`, `total_sum`.
- Выбор (`vybor`): название раунда.
- Числа (`chisla`): название раунда.
- Преферанс (`pref`): название раунда.
- Пары (`pairs`): название раунда.
- Разоблачение (`razobl`): название раунда.
- Аукцион (`auction`): название раунда.
- Момент Истины (`mot`): название раунда.
