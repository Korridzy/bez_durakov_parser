# Данные о результатах

Схема хранит числовые поля по раундам и итогам, а `GameDataService` выдаёт сводки игр, данные команд и их агрегаты.

- В `Vybor` и `Pairs` есть поле `points`.
- В `Chisla` есть `task_1`, `task_2`, `task_3`, `task_4`, `task_5` и `total_sum`.
- В `Razobl` есть `task_1`, `task_2`, `task_3`, `task_4` и `total_sum`, а в `Mot` есть `task_1`, `task_2`, `task_3` и `total_sum`.
- В `Pref` есть `task_1`, `task_2`, `task_3`, `task_4`, `task_5`, `task_6`, `task_7`, `goal`, `points`, `penalty`, `bonus` и `total_sum`.
- В `Auction` есть `task_1_bid`, `task_1_points`, `task_1_rate`, `task_2_bid`, `task_2_points`, `task_2_rate`, `task_3_bid`, `task_3_points`, `task_3_rate`, `task_4_bid`, `task_4_points`, `task_4_rate` и `total_sum`.
- Представление `TeamGameScore` содержит поля очков по каждому раунду и `total_points`.
- `GameDataService` предоставляет `get_all_games_summary`, `get_game_by_id`, `get_games_by_date_range`, `get_team_game_scores`, `get_all_teams`, `get_team_statistics`, `get_team_wins` и `get_top_teams`.
- Оператору необходимо заполнить: формулы расчёта `points` и `total_sum`, назначение `goal`, `penalty`, `bonus`, полей с суффиксами `_bid` и `_rate`, а также официальные критерии победы и поражения.
