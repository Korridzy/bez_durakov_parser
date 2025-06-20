import pandas as pd
import numpy as np
import argparse
import os
import warnings
from datetime import datetime
from config import DATABASE_URL
from db import Database
from bd_game import BdGame


class XLSParseError(Exception):
    def __init__(self, message):
        super().__init__(message)


# Define parsing functions for each structure
def parse_date(all_sheets):
    try:
        # Get the value of cell A1 from the sheet "Общая таблица"
        cell_value = all_sheets['Общая таблица'].columns[0]
        # Convert the cell value to a datetime object
        return cell_value
    except Exception as e:
        # Raise XLSParseError with the problematic value
        raise XLSParseError(f"Error parsing date: {e}, problematic value: {cell_value}")


def parse_teams(all_sheets):
    try:
        # print(all_sheets['Команды']) # Debugging
        # Extract the first column from the 'Команды' sheet
        teams_data = all_sheets['Команды'].iloc[:, 0]
        # Filter out rows where the value is 0 or NaN
        filtered_teams = teams_data[(teams_data != 0) & (~teams_data.isna())].tolist()
        return filtered_teams
    except Exception as e:
        raise XLSParseError(f"Error parsing teams: {e}")


def parse_vybor(all_sheets, vybor_dict):
    try:
        # Get the list of teams
        teams = list(vybor_dict.keys())
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
            points = general_table.loc[row_index, 'I']
            # Add the team and points to the dictionary
            vybor_dict[team] = points
    except Exception as e:
        raise XLSParseError(f"Error parsing vybor: {e}")


def parse_chisla(all_sheets, chisla_dict):
    try:
        # Get the list of teams
        teams = list(chisla_dict.keys())
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
            chisla_dict[team]['I'] = i_value
            chisla_dict[team]['II'] = ii_value
            chisla_dict[team]['III'] = iii_value
            chisla_dict[team]['IV'] = iv_value
            chisla_dict[team]['V'] = v_value
            chisla_dict[team]['Сумма'] = sum_value
    except Exception as e:
        raise XLSParseError(f"Error parsing chisla: {e}")


def parse_pref(all_sheets, pref_dict):
    try:
        # Get the "Преферанс" sheet
        pref_table = all_sheets['Преферанс']
        # Get the list of teams
        teams = list(pref_dict.keys())

        # Iterate over each team
        for team in teams:
            # Find the row index of the team in the first column
            team_rows = pref_table[pref_table.iloc[:, 0] == team]
            if team_rows.empty:
                raise XLSParseError(f"Team '{team}' not found in 'Преферанс'")
            row_index = team_rows.index[0]

            # Store the team data in the dictionary directly
            pref_dict[team]['I'] = pref_table.loc[row_index, 'I']
            pref_dict[team]['II'] = pref_table.loc[row_index, 'II']
            pref_dict[team]['III'] = pref_table.loc[row_index, 'III']
            pref_dict[team]['IV'] = pref_table.loc[row_index, 'IV']
            pref_dict[team]['V'] = pref_table.loc[row_index, 'V']
            pref_dict[team]['VI'] = pref_table.loc[row_index, 'VI']
            pref_dict[team]['VII'] = pref_table.loc[row_index, 'VII']
            pref_dict[team]['Points'] = pref_table.loc[row_index, 'Points']
            pref_dict[team]['Penalty'] = pref_table.loc[row_index, 'Penalty']
            pref_dict[team]['Bonus'] = pref_table.loc[row_index, 'Bonus']
            pref_dict[team]['Сумма'] = pref_table.loc[row_index, 'Sum']
    except Exception as e:
        raise XLSParseError(f"Error parsing pref: {e}")


def parse_pairs(all_sheets, pairs_dict):
    try:
        # Get the list of teams
        teams = list(pairs_dict.keys())
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
            points = general_table.loc[row_index, 'IV']
            # Add the team and points to the dictionary
            pairs_dict[team] = points
    except Exception as e:
        raise XLSParseError(f"Error parsing pairs: {e}")


def parse_razobl(all_sheets, razobl_dict):
    try:
        # Get the list of teams
        teams = list(razobl_dict.keys())
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
            i_value = razobl_table.loc[row_index, 'I']
            ii_value = razobl_table.loc[row_index, 'II']
            iii_value = razobl_table.loc[row_index, 'III']
            iv_value = razobl_table.loc[row_index, 'IV']
            sum_value = razobl_table.loc[row_index, 'Сумма']
            # Check if the sum of I-IV equals the value in "Сумма"
            if sum_value != i_value + ii_value + iii_value + iv_value:
                raise XLSParseError(f"Sum mismatch for team '{team}' in 'Разоблачение'")
            # Store the team data in the dictionary
            razobl_dict[team]['I'] = i_value
            razobl_dict[team]['II'] = ii_value
            razobl_dict[team]['III'] = iii_value
            razobl_dict[team]['IV'] = iv_value
            razobl_dict[team]['Сумма'] = sum_value
    except Exception as e:
        raise XLSParseError(f"Error parsing razobl: {e}")


def get_rate_from_user(team_name, column_name, min_value=1.0, max_value=2.5):
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
            rate_value = float(input(f"Введите значение коэффициента ({min_value}-{max_value}) для команды \
            '{team_name}' в этапе '{column_name}': "))
            if min_value <= rate_value <= max_value:
                return rate_value
            else:
                print(f"Значение должно быть между {min_value} и {max_value}")
        except ValueError:
            print("Пожалуйста, введите корректное число")


def restore_auction_rates(rate_params, auction_data, full_game_data):
    try:
        # Initialize total points based on game data
        total_points = {}
        for team in auction_data.keys():
            total_points[team] = (
                full_game_data['vybor'][team] +
                full_game_data['chisla'][team]['Сумма'] +
                full_game_data['pref'][team]['Сумма'] +
                full_game_data['pairs'][team] +
                full_game_data['razobl'][team]['Сумма']
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
                    print(f"Команда: {team}, Ставка: {auction_data[team][col]['bid']}, "
                          f"Общие баллы: {total_points[team]}, Присвоенный коэф: {auction_data[team][col]['rate']}")

                # Update total_points
                total_points[team] += auction_data[team][col]['bid'] + auction_data[team][col]['points']

            # Assign user-input rates to conflicting teams for the current column
            for team in conflict_teams:
                auction_data[team][col]['rate'] = get_rate_from_user(team, col)

            # Clear the conflict_teams list for the next column
            conflict_teams.clear()
        return total_points
    except Exception as e:
        raise XLSParseError(f"Error restoring auction rates: {e}")

def parse_auction(all_sheets, auction_dict, full_game_data):
    try:
        # Get the list of teams
        teams = list(auction_dict.keys())
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
            i_value = auction_table.loc[row_index, 'I']
            i_points = auction_table.loc[row_index, auction_table.columns[auction_table.columns.get_loc('I') + 1]]
            ii_value = auction_table.loc[row_index, 'II']
            ii_points = auction_table.loc[row_index, auction_table.columns[auction_table.columns.get_loc('II') + 1]]
            iii_value = auction_table.loc[row_index, 'III']
            iii_points = auction_table.loc[row_index, auction_table.columns[auction_table.columns.get_loc('III') + 1]]
            iv_value = auction_table.loc[row_index, 'IV']
            iv_points = auction_table.loc[row_index, auction_table.columns[auction_table.columns.get_loc('IV') + 1]]
            sum_value = auction_table.loc[row_index, 'Сумма баллов в конкурсе']

            # Store the team data in the dictionary
            auction_dict[team]['I']['bid'] = i_value
            auction_dict[team]['I']['points'] = i_points
            auction_dict[team]['II']['bid'] = ii_value
            auction_dict[team]['II']['points'] = ii_points
            auction_dict[team]['III']['bid'] = iii_value
            auction_dict[team]['III']['points'] = iii_points
            auction_dict[team]['IV']['bid'] = iv_value
            auction_dict[team]['IV']['points'] = iv_points
            auction_dict[team]['Сумма'] = sum_value

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
        total_points = restore_auction_rates(rate_params, auction_dict, full_game_data)

        # Validate that total_points matches the values in the "Всего баллов" column
        for team in teams:
            team_rows = general_table[general_table.iloc[:, 0] == team]
            if team_rows.empty:
                raise XLSParseError(f"Team '{team}' not found in 'Аукцион'")
            row_index = team_rows.index[0]
            expected_total_points = (
                general_table.loc[row_index, 'I'] +
                general_table.loc[row_index, 'II'] +
                general_table.loc[row_index, 'III'] +
                general_table.loc[row_index, 'IV'] +
                general_table.loc[row_index, 'V'] +
                general_table.loc[row_index, 'VI']
            )
            if total_points[team] != expected_total_points:
                raise XLSParseError(f"Total points mismatch for team '{team}': {total_points[team]} != {expected_total_points}")
    except Exception as e:
        raise XLSParseError(f"Error parsing auction: {e}")


def parse_mot(all_sheets, mot_dict):
    try:
        # Get the "Момент истины" sheet
        mot_table = all_sheets['Момент истины']
        # Get the list of teams
        teams = list(mot_dict.keys())

        # Iterate over each team
        for team in teams:
            # Find the row index of the team in the first column
            team_rows = mot_table[mot_table.iloc[:, 1] == team]
            if team_rows.empty:
                raise XLSParseError(f"Team '{team}' not found in 'Момент истины'")
            row_index = team_rows.index[0]

            # Extract values from the specified columns
            i_value = mot_table.loc[row_index, 'I']
            ii_value = mot_table.loc[row_index, 'II']
            iii_value = mot_table.loc[row_index, 'III']
            sum_value = i_value + ii_value + iii_value

            # Store the team data in the dictionary with calculated sum
            mot_dict[team]['I'] = i_value
            mot_dict[team]['II'] = ii_value
            mot_dict[team]['III'] = iii_value
            mot_dict[team]['Сумма'] = sum_value
    except Exception as e:
        raise XLSParseError(f"Error parsing mot: {e}")


# Function to read a single file and parse all structures from all sheets
def parse_xlsm(file_path):
    try:
        all_sheets = pd.read_excel(file_path, sheet_name=None)
        # print(all_sheets)  # Debugging

        # First, get basic information about the game
        game_date = parse_date(all_sheets)
        teams = parse_teams(all_sheets)

        # Create a BdGame instance with basic information
        game = BdGame(teams=teams, date=game_date)
        # Get access to the data structure
        game_data = game.get_data()

        # Fill the data structure using parsers
        parse_vybor(all_sheets, game_data['vybor'])
        parse_chisla(all_sheets, game_data['chisla'])
        parse_pref(all_sheets, game_data['pref'])
        parse_pairs(all_sheets, game_data['pairs'])
        parse_razobl(all_sheets, game_data['razobl'])
        parse_auction(all_sheets, game_data['auction'], game_data)
        parse_mot(all_sheets, game_data['mot'])

        return game
    except XLSParseError as e:
        print(f"Error parsing file {file_path}: {e}")
        return None


def save_game_to_database(game_instance, db):
    """
    Saves game data to the database.

    Args:
        game_instance (BdGame): BdGame instance containing parsed data
        db: Database object for saving data

    Returns:
        bool: True if data is successfully saved, False otherwise
    """
    try:
        game_data = game_instance.get_data()
        # Check if an identical game already exists in the database
        identical_game = db.find_identical_game(game_instance)

        if identical_game:
            print(f"ℹ️ Identical game from {game_data['date'].strftime('%d.%m.%Y')} already exists in the database. "
                  f"Id: {identical_game.get_data()['game_id']}. Skipping.")
            return False

        # Save the data
        success = db.add_game(game_instance)

        # Display success/error message
        if success:
            print(f"✅ Data for game from {game_data['date'].strftime('%d.%m.%Y')} successfully saved to database")
            return True
        else:
            print(f"❌ Error saving game from {game_data['date'].strftime('%d.%m.%Y')} to database")
            return False
    except Exception as e:
        print(f"❌ Database error: {e}")
        return False

# Main code to get the list of files from the command line
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Parse all XLSM files in a directory.")
    parser.add_argument('directory', type=str, help='Path to the directory containing XLSM files')
    parser.add_argument('--no-save', action='store_true', help='Do not save data to database')
    parser.add_argument('-v', '--verbose', action='store_true', help='Display detailed parsing results')

    args = parser.parse_args()

    # Get the directory path from the command line arguments
    directory_path = args.directory

    # List all .xlsm files in the directory
    file_paths = [os.path.join(directory_path, f) for f in os.listdir(directory_path) if f.endswith('.xlsm')]

    # Set pandas options to display all data
    pd.set_option('display.max_rows', None)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.max_colwidth', None)
    pd.set_option('display.width', None)

    # Create database connection if saving is needed
    db = None
    if not args.no_save:
        db = Database(db_url=DATABASE_URL)

    # Process files sequentially
    for file_path in file_paths:
        print(f"\nProcessing file: {os.path.basename(file_path)}")
        print("=" * 80)

        # Parse a single file
        parsed_game = parse_xlsm(file_path)

        if parsed_game:
            # Output parsing results only if verbose flag is set
            if args.verbose:
                parsed_game.print_detailed()

            # Save to database if needed
            if not args.no_save and db:
                save_game_to_database(parsed_game, db)
        else:
            print(f"❌ Failed to process file {file_path}")

        print("\n")