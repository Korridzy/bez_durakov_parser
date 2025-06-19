from pprint import pprint

class BdGame:
    """
    Class for storing and managing game data structure.
    Provides a standard data structure for use throughout the application.
    """

    def __init__(self, teams, game_id=None, date=None):
        """
        Initialize the game data structure.

        Args:
            teams (list): List of team names
            game_id (int, optional): Game ID
            date (datetime.date, optional): Game date
        """
        # Initialize basic data structure
        self._game_data = {
            'game_id': game_id,
            'date': date,
            'teams': teams,
            'vybor': {},
            'chisla': {},
            'pref': {},
            'pairs': {},
            'razobl': {},
            'auction': {},
            'mot': {}
        }

        # Initialize structure for each team
        self._initialize_team_structures()

    def _initialize_team_structures(self):
        """Initialize data structure for each team."""
        for team in self._game_data['teams']:
            # Vybor - simple points
            self._game_data['vybor'][team] = 0.0

            # Chisla - 5 tasks + sum
            self._game_data['chisla'][team] = {
                'I': 0.0, 'II': 0.0, 'III': 0.0, 'IV': 0.0, 'V': 0.0, 'Сумма': 0.0
            }

            # Preferans - 7 tasks + points, penalties, bonuses, sum
            self._game_data['pref'][team] = {
                'I': 0.0, 'II': 0.0, 'III': 0.0, 'IV': 0.0, 'V': 0.0, 'VI': 0.0, 'VII': 0.0,
                'Points': 0.0, 'Penalty': 0.0, 'Bonus': 0.0, 'Сумма': 0.0
            }

            # Pairs - simple points
            self._game_data['pairs'][team] = 0.0

            # Razoblachenie - 4 tasks + sum
            self._game_data['razobl'][team] = {
                'I': 0.0, 'II': 0.0, 'III': 0.0, 'IV': 0.0, 'Сумма': 0.0
            }

            # Auction - 4 tasks with bid, points, rate + sum
            self._game_data['auction'][team] = {
                'I': {'bid': 0.0, 'points': 0.0, 'rate': None},
                'II': {'bid': 0.0, 'points': 0.0, 'rate': None},
                'III': {'bid': 0.0, 'points': 0.0, 'rate': None},
                'IV': {'bid': 0.0, 'points': 0.0, 'rate': None},
                'Сумма': 0.0
            }

            # Moment of truth - 3 tasks + sum
            self._game_data['mot'][team] = {
                'I': 0.0, 'II': 0.0, 'III': 0.0, 'Сумма': 0.0
            }

    def get_data(self):
        """
        Returns the game data structure.

        Returns:
            dict: Game data structure
        """
        return self._game_data

    def print_detailed(self):
        """
        Prints detailed game data in a formatted way.
        Used for verbose output mode.

        Returns:
            None
        """
        print(f"Дата игры: {self._game_data['date'].strftime('%d.%m.%Y')}")
        print(f"Команды: {', '.join(self._game_data['teams'])}")
        print("\nДетальные данные:")
        pprint(self._game_data)
        print("-" * 80)