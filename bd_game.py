import pandas as pd
import numpy as np
import warnings
from pprint import pprint
from datetime import datetime

class XLSParseError(Exception):
    def __init__(self, message):
        super().__init__(message)

class BdGame:
    """
    Class for storing and managing game data structure.
    Provides a standard data structure for use throughout the application.
    """

    def __init__(self, teams=None, game_id=None, date=None):
        """
        Initialize the game data structure.

        Args:
            teams (list, optional): List of team names
            game_id (int, optional): Game ID
            date (datetime.date, optional): Game date
        """
        # Initialize basic data structure
        self._game_data = {
            'game_id': game_id,
            'date': date,
            'teams': teams or [],
            'vybor': {},
            'chisla': {},
            'pref': {},
            'pairs': {},
            'razobl': {},
            'auction': {},
            'mot': {}
        }

        # Initialize structure for each team if teams are provided
        if teams:
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

    def parse_from_file(self, file_path):
        """
        Parse XLSM file and populate game data.

        Args:
            file_path (str): Path to the XLSM file to parse

        Returns:
            bool: True if parsing was successful, False otherwise
        """
        try:
            all_sheets = pd.read_excel(file_path, sheet_name=None)

            # First, get basic information about the game
            game_date = self._parse_date(all_sheets)
            teams = self._parse_teams(all_sheets)

            # Set the parsed data
            self._game_data['date'] = game_date
            self._game_data['teams'] = teams

            # Initialize structure for teams
            self._initialize_team_structures()

            # Fill the data structure using parsers
            self._parse_vybor(all_sheets)
            self._parse_chisla(all_sheets)
            self._parse_pref(all_sheets)
            self._parse_pairs(all_sheets)
            self._parse_razobl(all_sheets)
            self._parse_auction(all_sheets)
            self._parse_mot(all_sheets)

            return True
        except XLSParseError as e:
            print(f"Error parsing file {file_path}: {e}")
            return False
        except Exception as e:
            print(f"Unexpected error parsing file {file_path}: {e}")
            return False

    def _parse_date(self, all_sheets):
        """Parse date from the XLSM sheets."""
        try:
            # Get the value of cell A1 from the sheet "Общая таблица"
            cell_value = all_sheets['Общая таблица'].columns[0]

            # Convert the cell value to a datetime object
            if isinstance(cell_value, datetime):
                return cell_value
            elif isinstance(cell_value, pd.Timestamp):
                return cell_value.to_pydatetime()
            else:
                # Try pandas to_datetime for strings and other types
                return pd.to_datetime(cell_value)
        except Exception as e:
            # Raise XLSParseError with the problematic value
            raise XLSParseError(f"Error parsing date: {e}, problematic value: {locals().get('cell_value', 'N/A')}")

    def _parse_teams(self, all_sheets):
        """Parse teams from the XLSM sheets."""
        try:
            # Extract the first column from the 'Команды' sheet
            teams_data = all_sheets['Команды'].iloc[:, 0]
            # Filter out rows where the value is 0 or NaN
            filtered_teams = teams_data[(teams_data != 0) & (~teams_data.isna())].tolist()
            return filtered_teams
        except Exception as e:
            raise XLSParseError(f"Error parsing teams: {e}")

    def _parse_vybor(self, all_sheets):
        """Parse vybor data from the XLSM sheets."""
        try:
            # Get the list of teams
            teams = list(self._game_data['vybor'].keys())
            # Get the "Общая таблица" sheet
            general_table = all_sheets['Общая таблица']

            # Iterate over each team
            for team in teams:
                # Find the row index of the team in the first column
                team_rows = general_table[general_table.iloc[:, 0] == team]
                if team_rows.empty:
                    raise XLSParseError(f"Team '{team}' not found in 'Общая таблица'")
                row_index = team_rows.index[0]
                # Get the points from the column named "I"
                points = np.nan_to_num(general_table.loc[row_index, 'I'])
                # Add the team and points to the dictionary
                self._game_data['vybor'][team] = points
        except Exception as e:
            raise XLSParseError(f"Error parsing vybor: {e}")

    def _parse_chisla(self, all_sheets):
        """Parse chisla data from the XLSM sheets."""
        try:
            # Get the list of teams
            teams = list(self._game_data['chisla'].keys())
            # Get the "Числа" sheet
            chisla_table = all_sheets['Числа']
            chisla_table.columns = chisla_table.iloc[0]
            chisla_table = chisla_table[1:].reset_index(drop=True)

            # Iterate over each team
            for team in teams:
                # Find the row index of the team in the first column
                team_rows = chisla_table[chisla_table.iloc[:, 0] == team]
                if team_rows.empty:
                    raise XLSParseError(f"Team '{team}' not found in 'Числа'")
                row_index = team_rows.index[0]
                # Get the values from the specified columns
                i_value = np.nan_to_num(chisla_table.loc[row_index, 'I'])
                ii_value = np.nan_to_num(chisla_table.loc[row_index, 'II'])
                iii_value = np.nan_to_num(chisla_table.loc[row_index, 'III'])
                iv_value = np.nan_to_num(chisla_table.loc[row_index, 'IV'])
                v_value = np.nan_to_num(chisla_table.loc[row_index, 'V'])
                sum_value = np.nan_to_num(chisla_table.loc[row_index, 'Сумма'])
                # Check if the sum of I-V equals the value in "Сумма"
                if sum_value != i_value + ii_value + iii_value + iv_value + v_value:
                    raise XLSParseError(f"Sum mismatch for team '{team}' in 'Числа'")
                # Store the team data in the dictionary
                self._game_data['chisla'][team]['I'] = i_value
                self._game_data['chisla'][team]['II'] = ii_value
                self._game_data['chisla'][team]['III'] = iii_value
                self._game_data['chisla'][team]['IV'] = iv_value
                self._game_data['chisla'][team]['V'] = v_value
                self._game_data['chisla'][team]['Сумма'] = sum_value
        except Exception as e:
            raise XLSParseError(f"Error parsing chisla: {e}")

    def _parse_pref(self, all_sheets):
        """Parse pref data from the XLSM sheets."""
        try:
            # Get the "Преферанс" sheet
            pref_table = all_sheets['Преферанс']
            # Get the list of teams
            teams = list(self._game_data['pref'].keys())

            # Iterate over each team
            for team in teams:
                # Find the row index of the team in the first column
                team_rows = pref_table[pref_table.iloc[:, 0] == team]
                if team_rows.empty:
                    raise XLSParseError(f"Team '{team}' not found in 'Преферанс'")
                row_index = team_rows.index[0]

                # Store the team data in the dictionary directly
                self._game_data['pref'][team]['I'] = np.nan_to_num(pref_table.loc[row_index, 'I'])
                self._game_data['pref'][team]['II'] = np.nan_to_num(pref_table.loc[row_index, 'II'])
                self._game_data['pref'][team]['III'] = np.nan_to_num(pref_table.loc[row_index, 'III'])
                self._game_data['pref'][team]['IV'] = np.nan_to_num(pref_table.loc[row_index, 'IV'])
                self._game_data['pref'][team]['V'] = np.nan_to_num(pref_table.loc[row_index, 'V'])
                self._game_data['pref'][team]['VI'] = np.nan_to_num(pref_table.loc[row_index, 'VI'])
                self._game_data['pref'][team]['VII'] = np.nan_to_num(pref_table.loc[row_index, 'VII'])
                self._game_data['pref'][team]['Points'] = np.nan_to_num(pref_table.loc[row_index, 'Points'])
                self._game_data['pref'][team]['Penalty'] = np.nan_to_num(pref_table.loc[row_index, 'Penalty'])
                self._game_data['pref'][team]['Bonus'] = np.nan_to_num(pref_table.loc[row_index, 'Bonus'])
                self._game_data['pref'][team]['Сумма'] = np.nan_to_num(pref_table.loc[row_index, 'Sum'])
        except Exception as e:
            raise XLSParseError(f"Error parsing pref: {e}")

    def _parse_pairs(self, all_sheets):
        """Parse pairs data from the XLSM sheets."""
        try:
            # Get the list of teams
            teams = list(self._game_data['pairs'].keys())
            # Get the "Общая таблица" sheet
            general_table = all_sheets['Общая таблица']

            # Iterate over each team
            for team in teams:
                # Find the row index of the team in the first column
                team_rows = general_table[general_table.iloc[:, 0] == team]
                if team_rows.empty:
                    raise XLSParseError(f"Team '{team}' not found in 'Общая таблица'")
                row_index = team_rows.index[0]
                # Get the points from the column named "IV"
                points = np.nan_to_num(general_table.loc[row_index, 'IV'])
                # Add the team and points to the dictionary
                self._game_data['pairs'][team] = points
        except Exception as e:
            raise XLSParseError(f"Error parsing pairs: {e}")

    def _parse_razobl(self, all_sheets):
        """Parse razobl data from the XLSM sheets."""
        try:
            # Get the list of teams
            teams = list(self._game_data['razobl'].keys())
            # Get the "Разоблачение" sheet
            razobl_table = all_sheets['Разоблачение']
            razobl_table.columns = razobl_table.iloc[0]
            razobl_table = razobl_table[1:].reset_index(drop=True)

            # Iterate over each team
            for team in teams:
                # Find the row index of the team in the first column
                team_rows = razobl_table[razobl_table.iloc[:, 0] == team]
                if team_rows.empty:
                    raise XLSParseError(f"Team '{team}' not found in 'Разоблачение'")
                row_index = team_rows.index[0]
                # Get the values from the specified columns
                i_value = np.nan_to_num(razobl_table.loc[row_index, 'I'])
                ii_value = np.nan_to_num(razobl_table.loc[row_index, 'II'])
                iii_value = np.nan_to_num(razobl_table.loc[row_index, 'III'])
                iv_value = np.nan_to_num(razobl_table.loc[row_index, 'IV'])
                sum_value = np.nan_to_num(razobl_table.loc[row_index, 'Сумма'])
                # Check if the sum of I-IV equals the value in "Сумма"
                if sum_value != i_value + ii_value + iii_value + iv_value:
                    raise XLSParseError(f"Sum mismatch for team '{team}' in 'Разоблачение'")
                # Store the team data in the dictionary
                self._game_data['razobl'][team]['I'] = i_value
                self._game_data['razobl'][team]['II'] = ii_value
                self._game_data['razobl'][team]['III'] = iii_value
                self._game_data['razobl'][team]['IV'] = iv_value
                self._game_data['razobl'][team]['Сумма'] = sum_value
        except Exception as e:
            raise XLSParseError(f"Error parsing razobl: {e}")

    def _get_rate_from_user(self, team_name, column_name, min_value=1.0, max_value=2.5):
        """
        Ask user to input a rate value within specified range.

        Args:
            team_name (str): Name of the team for which the rate is requested
            column_name (str): Column identifier (I, II, III, IV)
            min_value (float): Minimum allowed value (default: 1.0)
            max_value (float): Maximum allowed value (default: 2.5)

        Returns:
            float: Rate value input by user
        """
        while True:
            try:
                rate_value = float(input(f"Введите значение коэффициента ({min_value}-{max_value}) для команды "
                                       f"'{team_name}' в этапе '{column_name}': "))
                if min_value <= rate_value <= max_value:
                    return rate_value
                else:
                    print(f"Значение должно быть между {min_value} и {max_value}")
            except ValueError:
                print("Пожалуйста, введите корректное число")

    def _restore_auction_rates(self, rate_params):
        """Restore auction rates based on game data."""
        try:
            auction_data = self._game_data['auction']

            # Initialize total points based on game data
            total_points = {}
            for team in auction_data.keys():
                total_points[team] = (
                    self._game_data['vybor'][team] +
                    self._game_data['chisla'][team]['Сумма'] +
                    self._game_data['pref'][team]['Сумма'] +
                    self._game_data['pairs'][team] +
                    self._game_data['razobl'][team]['Сумма']
                )

            # Define the columns to process
            columns = ['I', 'II', 'III', 'IV']
            conflict_teams = []  # List to track teams with rate conflicts

            # Iterate over each column
            for col in columns:
                # Extract bids and corresponding team names
                bids = [(team, auction_data[team][col]['bid']) for team in auction_data]

                # Sort bids by bid value, then by total points
                bids.sort(key=lambda x: (x[1], total_points[x[0]]))

                # Check for duplicate bids with the same total points within the top total_rates_quan bids
                for i in range(1, len(bids)):
                    if i <= rate_params["total_rates_quan"] and \
                            bids[i][1] == bids[i-1][1] and total_points[bids[i][0]] == total_points[bids[i-1][0]]:
                        warnings.warn(
                            f"Conflict detected: Duplicate bids with the same total points for teams '{bids[i][0]}' "
                            f"and '{bids[i-1][0]}' in column '{col}'. Bid: {bids[i][1]}, Total Points: {total_points[bids[i][0]]}"
                        )
                        # Add conflicting teams to the list
                        conflict_teams.extend([bids[i][0], bids[i-1][0]])

                # Assign rates based on the sorted list and rate_params
                for i, (team, bid) in enumerate(bids):
                    if i < rate_params['dvaipo_quan']:
                        auction_data[team][col]['rate'] = 2.5
                    elif i < rate_params['dvaipo_quan'] + rate_params['dva_quan']:
                        auction_data[team][col]['rate'] = 2.0
                    elif i < rate_params['dvaipo_quan'] + rate_params['dva_quan'] + rate_params['jedanipo_quan']:
                        auction_data[team][col]['rate'] = 1.5
                    else:
                        auction_data[team][col]['rate'] = 1.0

                    # If there are conflicting teams, print all rates data for this column
                    if conflict_teams:
                        raise XLSParseError(f"Rate conflict detected for column '{col}'. Please resolve manually.")
                        print(f"Команда: {team}, Ставка: {auction_data[team][col]['bid']}, "
                              f"Общие баллы: {total_points[team]}, Присвоенный коэф: {auction_data[team][col]['rate']}")

                    # Update total_points
                    total_points[team] += auction_data[team][col]['bid'] + auction_data[team][col]['points']

                # Assign user-input rates to conflicting teams for the current column
                for team in conflict_teams:
                    auction_data[team][col]['rate'] = self._get_rate_from_user(team, col)

                # Clear the conflict_teams list for the next column
                conflict_teams.clear()
            return total_points
        except Exception as e:
            raise XLSParseError(f"Error restoring auction rates: {e}")

    def _parse_auction(self, all_sheets):
        """Parse auction data from the XLSM sheets."""
        try:
            # Get the list of teams
            teams = list(self._game_data['auction'].keys())
            # Get the "Аукцион" sheet
            auction_table = all_sheets['Аукцион']
            # Get the "Общая таблица" sheet
            general_table = all_sheets['Общая таблица']

            # Iterate over each team
            for team in teams:
                # Find the row index of the team in the first column
                team_rows = auction_table[auction_table.iloc[:, 0] == team]
                if team_rows.empty:
                    raise XLSParseError(f"Team '{team}' not found in 'Аукцион'")
                row_index = team_rows.index[0]

                # Collect values from columns I-IV and the columns following each of them
                i_value = np.nan_to_num(auction_table.loc[row_index, 'I'])
                i_points = np.nan_to_num(auction_table.loc[row_index, auction_table.columns[auction_table.columns.get_loc('I') + 1]])
                ii_value = np.nan_to_num(auction_table.loc[row_index, 'II'])
                ii_points = np.nan_to_num(auction_table.loc[row_index, auction_table.columns[auction_table.columns.get_loc('II') + 1]])
                iii_value = np.nan_to_num(auction_table.loc[row_index, 'III'])
                iii_points = np.nan_to_num(auction_table.loc[row_index, auction_table.columns[auction_table.columns.get_loc('III') + 1]])
                iv_value = np.nan_to_num(auction_table.loc[row_index, 'IV'])
                iv_points = np.nan_to_num(auction_table.loc[row_index, auction_table.columns[auction_table.columns.get_loc('IV') + 1]])
                sum_value = np.nan_to_num(auction_table.loc[row_index, 'Сумма баллов в конкурсе'])

                # Store the team data in the dictionary
                self._game_data['auction'][team]['I']['bid'] = i_value
                self._game_data['auction'][team]['I']['points'] = i_points
                self._game_data['auction'][team]['II']['bid'] = ii_value
                self._game_data['auction'][team]['II']['points'] = ii_points
                self._game_data['auction'][team]['III']['bid'] = iii_value
                self._game_data['auction'][team]['III']['points'] = iii_points
                self._game_data['auction'][team]['IV']['bid'] = iv_value
                self._game_data['auction'][team]['IV']['points'] = iv_points
                self._game_data['auction'][team]['Сумма'] = sum_value

            # Retrieve rate parameters from the specified cells
            total_rates_quan = auction_table.loc[31, 'Unnamed: 2']
            dvaipo_quan = auction_table.loc[28, 'Unnamed: 2']
            dva_quan = auction_table.loc[29, 'Unnamed: 2']
            jedanipo_quan = auction_table.loc[30, 'Unnamed: 2']

            # Validate that the values are correct
            if total_rates_quan not in [3, 5]:
                raise XLSParseError(f"Invalid value for total_rates_quan: {total_rates_quan}. Must be 3 or 5.")
            for param, value in zip(['dvaipo_quan', 'dva_quan', 'jedanipo_quan'],
                                    [dvaipo_quan, dva_quan, jedanipo_quan]):
                if value not in [1, 2]:
                    raise XLSParseError(f"Invalid value for {param}: {value}. Must be 1 or 2.")

            # Define rate parameters
            rate_params = {
                'total_rates_quan': int(total_rates_quan),
                'dvaipo_quan': int(dvaipo_quan),
                'dva_quan': int(dva_quan),
                'jedanipo_quan': int(jedanipo_quan)
            }

            # Call the restore_auction_rates function
            total_points = self._restore_auction_rates(rate_params)

            # Validate that total_points matches the values in the "Всего баллов" column
            for team in teams:
                team_rows = general_table[general_table.iloc[:, 0] == team]
                if team_rows.empty:
                    raise XLSParseError(f"Team '{team}' not found in 'Аукцион'")
                row_index = team_rows.index[0]
                expected_total_points = (
                    np.nan_to_num(general_table.loc[row_index, 'I']) +
                    np.nan_to_num(general_table.loc[row_index, 'II']) +
                    np.nan_to_num(general_table.loc[row_index, 'III']) +
                    np.nan_to_num(general_table.loc[row_index, 'IV']) +
                    np.nan_to_num(general_table.loc[row_index, 'V']) +
                    np.nan_to_num(general_table.loc[row_index, 'VI'])
                )
                if total_points[team] != expected_total_points:
                    raise XLSParseError(f"Total points mismatch for team '{team}': {total_points[team]} != {expected_total_points}")
        except Exception as e:
            raise XLSParseError(f"Error parsing auction: {e}")

    def _parse_mot(self, all_sheets):
        """Parse mot data from the XLSM sheets."""
        try:
            # Get the "Момент истины" sheet
            mot_table = all_sheets['Момент истины']
            # Get the list of teams
            teams = list(self._game_data['mot'].keys())

            # Iterate over each team
            for team in teams:
                # Find the row index of the team in the first column
                team_rows = mot_table[mot_table.iloc[:, 1] == team]
                if team_rows.empty:
                    raise XLSParseError(f"Team '{team}' not found in 'Момент истины'")
                row_index = team_rows.index[0]

                # Extract values from the specified columns
                i_value = np.nan_to_num(mot_table.loc[row_index, 'I'])
                ii_value = np.nan_to_num(mot_table.loc[row_index, 'II'])
                iii_value = np.nan_to_num(mot_table.loc[row_index, 'III'])
                sum_value = i_value + ii_value + iii_value

                # Store the team data in the dictionary with calculated sum
                self._game_data['mot'][team]['I'] = i_value
                self._game_data['mot'][team]['II'] = ii_value
                self._game_data['mot'][team]['III'] = iii_value
                self._game_data['mot'][team]['Сумма'] = sum_value
        except Exception as e:
            raise XLSParseError(f"Error parsing mot: {e}")

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