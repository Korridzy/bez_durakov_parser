from config import DATABASE_URL
from db import Database


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
