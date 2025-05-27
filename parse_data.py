import pandas as pd
import argparse
import os
import warnings
from datetime import datetime
from pprint import pprint
from config import DATABASE_URL
from db import Database


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


def parse_vybor(all_sheets):
    try:
        # Get the list of teams
        teams = parse_teams(all_sheets)
        # Get the "Общая таблица" sheet
        general_table = all_sheets['Общая таблица']
        # Initialize the dictionary to store the results
        vybor_dict = {}

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

        return vybor_dict
    except Exception as e:
        raise XLSParseError(f"Error parsing vybor: {e}")


def parse_chisla(all_sheets):
    try:
        # print(all_sheets['Числа'])  # Debugging
        # Get the list of teams
        teams = parse_teams(all_sheets)
        # Get the "Числа" sheet
        chisla_table = all_sheets['Числа']
        chisla_table.columns = chisla_table.iloc[0]
        chisla_table = chisla_table[1:].reset_index(drop=True)
        # print(chisla_table) # Debugging
        # Initialize the dictionary to store the results
        chisla_dict = {}

        # Iterate over each team
        for team in teams:
            # Find the row index of the team in the first column
            team_rows = chisla_table[chisla_table.iloc[:, 0] == team]
            if team_rows.empty:
                raise XLSParseError(f"Team '{team}' not found in 'Числа'")
            row_index = team_rows.index[0]
            # Get the values from the specified columns
            i_value = chisla_table.loc[row_index, 'I']
            ii_value = chisla_table.loc[row_index, 'II']
            iii_value = chisla_table.loc[row_index, 'III']
            iv_value = chisla_table.loc[row_index, 'IV']
            v_value = chisla_table.loc[row_index, 'V']
            sum_value = chisla_table.loc[row_index, 'Сумма']
            # Check if the sum of I-V equals the value in "Сумма"
            if sum_value != i_value + ii_value + iii_value + iv_value + v_value:
                raise XLSParseError(f"Sum mismatch for team '{team}' in 'Числа'")
            # Store the team data in the dictionary
            chisla_dict[team] = {
                "I": i_value,
                "II": ii_value,
                "III": iii_value,
                "IV": iv_value,
                "V": v_value,
                "Сумма": sum_value
            }

        return chisla_dict
    except Exception as e:
        raise XLSParseError(f"Error parsing chisla: {e}")


def parse_pref(all_sheets):
    try:
        # Get the "Преферанс" sheet
        pref_table = all_sheets['Преферанс']

        # Get the list of teams
        teams = parse_teams(all_sheets)

        # Initialize the dictionary to store the results
        pref_dict = {}

        # Iterate over each team
        for team in teams:
            # Find the row index of the team in the first column
            team_rows = pref_table[pref_table.iloc[:, 0] == team]
            if team_rows.empty:
                raise XLSParseError(f"Team '{team}' not found in 'Преферанс'")
            row_index = team_rows.index[0]

            # Store the team data in the dictionary directly
            pref_dict[team] = {
                "I": pref_table.loc[row_index, 'I'],
                "II": pref_table.loc[row_index, 'II'],
                "III": pref_table.loc[row_index, 'III'],
                "IV": pref_table.loc[row_index, 'IV'],
                "V": pref_table.loc[row_index, 'V'],
                "VI": pref_table.loc[row_index, 'VI'],
                "VII": pref_table.loc[row_index, 'VII'],
                "Points": pref_table.loc[row_index, 'Points'],
                "Penalty": pref_table.loc[row_index, 'Penalty'],
                "Bonus": pref_table.loc[row_index, 'Bonus'],
                "Сумма": pref_table.loc[row_index, 'Sum']
            }

        return pref_dict
    except Exception as e:
        raise XLSParseError(f"Error parsing pref: {e}")


def parse_pairs(all_sheets):
    try:
        # Get the list of teams
        teams = parse_teams(all_sheets)
        # Get the "Общая таблица" sheet
        general_table = all_sheets['Общая таблица']
        # Initialize the dictionary to store the results
        pairs_dict = {}

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

        return pairs_dict
    except Exception as e:
        raise XLSParseError(f"Error parsing pairs: {e}")


def parse_razobl(all_sheets):
    try:
        # Get the list of teams
        teams = parse_teams(all_sheets)
        # Get the "Разоблачение" sheet
        razobl_table = all_sheets['Разоблачение']
        razobl_table.columns = razobl_table.iloc[0]
        razobl_table = razobl_table[1:].reset_index(drop=True)
        # Initialize the dictionary to store the results
        razobl_dict = {}

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
            razobl_dict[team] = {
                "I": i_value,
                "II": ii_value,
                "III": iii_value,
                "IV": iv_value,
                "Сумма": sum_value
            }

        return razobl_dict
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


def restore_auction_rates(rate_params, auction_data, total_points):
    try:
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
                # Because this information is needed for user to make a decision
                if conflict_teams:
                    print(f"Команда: {team}, Ставка: {auction_data[team][col]['bid']}, "
                          f"Общие баллы: {total_points[team]}, Присвоенный коэф: {auction_data[team][col]['rate']}")

                # Update total_points
                total_points[team] += auction_data[team][col]['bid'] + auction_data[team][col]['points']

            # Assign None to the rate of conflicting teams for the current column
            for team in conflict_teams:
                auction_data[team][col]['rate'] = get_rate_from_user(team, col)

            # Clear the conflict_teams list for the next column
            conflict_teams.clear()

        return auction_data, total_points
    except Exception as e:
        raise XLSParseError(f"Error restoring auction rates: {e}")

def parse_auction(all_sheets):
    try:
        # Get the list of teams
        teams = parse_teams(all_sheets)
        # Get the "Аукцион" sheet
        auction_table = all_sheets['Аукцион']
        # Get the "Общая таблица" sheet
        general_table = all_sheets['Общая таблица']
        # print(auction_table)  # Debugging

        # Initialize the dictionary to store the results
        auction_dict = {}

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
            auction_dict[team] = {
                "I": {"bid": i_value, "points": i_points},
                "II": {"bid": ii_value, "points": ii_points},
                "III": {"bid": iii_value, "points": iii_points},
                "IV": {"bid": iv_value, "points": iv_points},
                "Сумма": sum_value
            }

        # Initialize total points with the sum of values from columns I-V on the "Общая таблица" sheet
        total_points = {}
        for team in teams:
            team_rows = general_table[general_table.iloc[:, 0] == team]
            if team_rows.empty:
                raise XLSParseError(f"Team '{team}' not found in 'Общая таблица'")
            row_index = team_rows.index[0]
            total_points[team] = (
                general_table.loc[row_index, 'I'] +
                general_table.loc[row_index, 'II'] +
                general_table.loc[row_index, 'III'] +
                general_table.loc[row_index, 'IV'] +
                general_table.loc[row_index, 'V']
            )

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
        auction_dict, total_points = restore_auction_rates(rate_params, auction_dict, total_points)

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

        return auction_dict
    except Exception as e:
        raise XLSParseError(f"Error parsing auction: {e}")


def parse_mot(all_sheets):
    try:
        # Get the "Момент истины" sheet
        mot_table = all_sheets['Момент истины']

        # Get the list of teams
        teams = parse_teams(all_sheets)

        # Initialize the dictionary to store the results
        mot_dict = {}

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

            # Store the team data in the dictionary with calculated sum
            mot_dict[team] = {
                "I": i_value,
                "II": ii_value,
                "III": iii_value,
                "Сумма": i_value + ii_value + iii_value
            }

        return mot_dict
    except Exception as e:
        raise XLSParseError(f"Error parsing mot: {e}")


# Function to read a single file and parse all structures from all sheets
def parse_xlsm(file_path):
    try:
        all_sheets = pd.read_excel(file_path, sheet_name=None)
        # print(all_sheets)  # Debugging
        parsed_data = {
            'date': parse_date(all_sheets),
            'teams': parse_teams(all_sheets),
            'vybor': parse_vybor(all_sheets),
            'chisla': parse_chisla(all_sheets),
            'pref': parse_pref(all_sheets),
            'pairs': parse_pairs(all_sheets),
            'razobl': parse_razobl(all_sheets),
            'auction': parse_auction(all_sheets),
            'mot': parse_mot(all_sheets)
        }
        return parsed_data
    except XLSParseError as e:
        print(f"Error parsing file {file_path}: {e}")
        return None


# Function to print parsed data
def print_parsed_data(data):
    # Iterate over each element in the data list
    for item in data:
        # Print the date in the desired format
        print(f"Date: {item['date'].strftime('%d.%m.%Y')}")
        # Print the item using pprint
        pprint(item)
        # Print a separator for better readability
        print('-' * 40)


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
        parsed_data = parse_xlsm(file_path)

        if parsed_data:
            # Output parsing results only if verbose flag is set
            if args.verbose:
                print(f"Game date: {parsed_data['date'].strftime('%d.%m.%Y')}")
                pprint(parsed_data)
                print("-" * 80)

            # Save to database if needed
            if not args.no_save and db:
                success = db.add_game_data(parsed_data)
                if success:
                    print(f"✅ Data for game from {parsed_data['date'].strftime('%d.%m.%Y')} successfully saved to database")
                else:
                    print(f"❌ Error saving game from {parsed_data['date'].strftime('%d.%m.%Y')} to database")
        else:
            print(f"❌ Failed to process file {file_path}")

        print("\n")