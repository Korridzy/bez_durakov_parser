from config import DATABASE_URL, DEFAULT_GAME_DATE
from db import Database, normalize_team_name
import warnings


# Re-export normalize_team_name for backwards compatibility
__all__ = ['Database', 'normalize_team_name', 'initialize_database', 'save_game_to_database']


def initialize_database():
    """
    Initialize database connection.

    Returns:
        Database: Database instance if connection successful, None otherwise
    """
    try:
        db = Database(DATABASE_URL)
        print(f"Connected to database: {DATABASE_URL}")
        return db
    except Exception as e:
        print(f"❌ Failed to connect to database: {e}")
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

        # Get game date
        game_date = game_data['date']
        # Normalize game_date to a date object if it's a datetime
        if hasattr(game_date, 'date'):
            game_date = game_date.date()

        # Check if game date matches the default date
        if game_date == DEFAULT_GAME_DATE:
            warnings.warn(
                f"\n{'='*80}\n"
                f"WARNING: Game date matches the default date ({DEFAULT_GAME_DATE.strftime('%d.%m.%Y')})!\n"
                f"The date was probably not set in the game file.\n"
                f"Please correct the date in the source file and import the game again.\n"
                f"The game may still be saved to the database with the specified date, unless it is detected as a duplicate.\n"
                f"{'='*80}",
                UserWarning
            )

        # Check if an identical game already exists in the database
        identical_game = db.find_identical_game(game_instance)

        if identical_game:
            print(f"ℹ️ Identical game from {game_data['date'].strftime('%d.%m.%Y')} already exists in the database. "
                  f"Id: {identical_game.get_data()['game_id']}. Skipping.")
            return False

        # Check if there are any games with the same date in the database
        existing_game_ids = db.get_game_ids_by_date(game_date)
        if existing_game_ids:
            warnings.warn(
                f"\n{'='*80}\n"
                f"WARNING: Database already contains {len(existing_game_ids)} game(s) with date {game_date.strftime('%d.%m.%Y')}!\n"
                f"Game ID(s): {', '.join(map(str, existing_game_ids))}\n"
                f"Please verify if this is a duplicate or a legitimate new game.\n"
                f"{'='*80}",
                UserWarning
            )

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
