import pandas as pd
import numpy as np
import warnings
from pprint import pprint
from datetime import datetime
import math

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

            # Define rate distribution based on rate_params
            rate_distribution = []
            for _ in range(rate_params['dvaipo_quan']):
                rate_distribution.append(2.5)
            for _ in range(rate_params['dva_quan']):
                rate_distribution.append(2.0)
            for _ in range(rate_params['jedanipo_quan']):
                rate_distribution.append(1.5)

            # Iterate over each column
            for col in columns:
                # Extract bids and corresponding team names with total points
                teams_data = [(team, auction_data[team][col]['bid'], total_points[team])
                              for team in auction_data]

                # Sort by bid (ascending - more negative = higher bid), then by total_points (ascending)
                # Lower bid value (more negative) = better position, same bid -> lower points = better position
                teams_data.sort(key=lambda x: (x[1], x[2]))


                # Track groups of teams with identical bid and total_points
                conflict_groups = []
                position = 0

                while position < len(teams_data):
                    current_bid = teams_data[position][1]
                    current_points = teams_data[position][2]

                    # Find all teams with the same bid and total_points
                    group = []
                    while (position < len(teams_data) and
                           teams_data[position][1] == current_bid and
                           teams_data[position][2] == current_points):
                        group.append(teams_data[position][0])
                        position += 1

                    conflict_groups.append(group)

                # Assign rates to each group
                rate_position = 0
                has_conflicts = False

                for group in conflict_groups:
                    group_size = len(group)

                    if group_size > 1 and rate_position < len(rate_distribution):
                        # Conflict: multiple teams with same bid and points
                        has_conflicts = True

                        # Calculate average rate for this group
                        rates_sum = 0.0
                        rates_count = 0

                        for i in range(group_size):
                            if rate_position + i < len(rate_distribution):
                                rates_sum += rate_distribution[rate_position + i]
                            else:
                                rates_sum += 1.0
                            rates_count += 1

                        avg_rate = rates_sum / rates_count

                        # Assign the average rate to all teams in the group
                        for team in group:
                            auction_data[team][col]['rate'] = avg_rate

                    else:
                        # No conflict: assign rates individually
                        for team in group:
                            if rate_position < len(rate_distribution):
                                auction_data[team][col]['rate'] = rate_distribution[rate_position]
                            else:
                                auction_data[team][col]['rate'] = 1.0

                    rate_position += group_size

                # DEBUG: Print detailed information if conflicts were detected
                # if has_conflicts:
                #     print("\n" + "=" * 120)
                #     print(f"КОНФЛИКТ КОЭФФИЦИЕНТОВ В КОЛОНКЕ '{col}'")
                #     print("=" * 120)
                #     print(f"{'№':<4} {'Команда':<40} {'Ставка':<12} {'Баллы до':<12} {'Коэфф.':<10} {'Конфликт':<10}")
                #     print("-" * 120)
                #
                #     for idx, (team, bid, points) in enumerate(teams_data, 1):
                #         # Check if this team is in a conflict group
                #         is_conflict = False
                #         for group in conflict_groups:
                #             if len(group) > 1 and team in group:
                #                 is_conflict = True
                #                 break
                #
                #         conflict_mark = "  ***" if is_conflict else ""
                #         rate = auction_data[team][col]['rate']
                #
                #         print(f"{idx:<4} {team:<40} {bid:<12.1f} "
                #               f"{points:<12.1f} {rate:<10.2f} {conflict_mark:<10}")
                #
                #     print("-" * 120)
                #     print(f"Команды с конфликтом отмечены звёздочками (***)")
                #     print(f"Параметры распределения коэффициентов:")
                #     print(f"  - 2.5x: первые {rate_params['dvaipo_quan']} команд(ы)")
                #     print(f"  - 2.0x: следующие {rate_params['dva_quan']} команд(ы)")
                #     print(f"  - 1.5x: следующие {rate_params['jedanipo_quan']} команд(ы)")
                #     print(f"  - 1.0x: остальные команды")
                #     print(f"Всего учитываются первые {rate_params['total_rates_quan']} команд(ы) для повышенных коэффициентов")
                #     print("=" * 120 + "\n")

                # Update total_points for the next column
                for team in auction_data:
                    total_points[team] += auction_data[team][col]['bid'] + auction_data[team][col]['points']

                # Validate that points divided by rate are in the valid range
                valid_values = {0, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 1100, 1200, 1300, 1400, 1500}
                for team in auction_data:
                    points = auction_data[team][col]['points']
                    rate = auction_data[team][col]['rate']

                    base_points = points / rate
                    # Round to nearest integer to handle floating point precision issues
                    base_points_rounded = round(base_points)

                    if base_points_rounded not in valid_values:
                        warnings.warn(
                            f"Invalid points calculation for team '{team}' in column '{col}': "
                            f"points={points}, rate={rate}, base_points={base_points:.2f} "
                            f"(rounded: {base_points_rounded}). Base points must be in range [0, 1500] with step 100."
                        )


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
                # Allow difference of exactly 5 or exact match. +5 or -5 points are possible due to 1,25 and 2,25 rates
                # with game rounding specifics.
                diff = abs(total_points[team] - expected_total_points)
                if diff != 0 and diff != 5:
                    raise XLSParseError(f"Total points mismatch for team '{team}': {total_points[team]} != {expected_total_points} (difference: {diff})")
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
