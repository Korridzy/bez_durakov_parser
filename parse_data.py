import argparse
import os
from bd_game import BdGame
from db_helpers import initialize_database, save_game_to_database


def parse_xlsm(file_path):
    """
    Parse a single XLSM file using the new BdGame paradigm.

    Args:
        file_path (str): Path to the XLSM file

    Returns:
        BdGame or None: Parsed game instance or None if parsing failed
    """
    # Create a new BdGame instance
    game = BdGame()

    # Parse the file using the object's method
    if game.parse_from_file(file_path):
        return game
    else:
        return None


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
    xlsm_files = [f for f in os.listdir(directory_path) if f.endswith('.xlsm')]

    if not xlsm_files:
        print(f"No XLSM files found in directory: {directory_path}")
        exit(1)

    print(f"Found {len(xlsm_files)} XLSM file(s) in {directory_path}")

    # Initialize database connection if saving is enabled
    db = None
    if not args.no_save:
        db = initialize_database()
        if not db:
            exit(1)

    # Process each file
    successful_parses = 0
    successful_saves = 0

    for xlsm_file in xlsm_files:
        file_path = os.path.join(directory_path, xlsm_file)
        print(f"\nProcessing: {xlsm_file}")

        # Parse the file using the new paradigm
        game_instance = parse_xlsm(file_path)

        if game_instance:
            successful_parses += 1

            # Display detailed results if verbose mode is enabled
            if args.verbose:
                game_instance.print_detailed()

            # Save to database if not disabled
            if not args.no_save and db:
                if save_game_to_database(game_instance, db):
                    successful_saves += 1
        else:
            print(f"❌ Failed to parse: {xlsm_file}")

    # Print summary
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"Files processed: {len(xlsm_files)}")
    print(f"Successfully parsed: {successful_parses}")

    if not args.no_save:
        print(f"Successfully saved to database: {successful_saves}")

    if successful_parses < len(xlsm_files):
        print(f"Failed to parse: {len(xlsm_files) - successful_parses}")

    if not args.no_save and successful_saves < successful_parses:
        print(f"Failed to save: {successful_parses - successful_saves}")
