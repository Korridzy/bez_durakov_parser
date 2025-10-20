#!/usr/bin/env python3
"""
Script to clear all data from the database using existing ORM methods.
"""

import argparse
from db import Database, Team

def clear_database(clear_teams=False):
    """
    Clear all games from the database using existing ORM methods.

    Args:
        clear_teams (bool): If True, also clear the teams table after removing all games.
    """
    db = Database()

    # Get all games
    games = db.get_all_games()

    if not games:
        print("База данных игр уже пуста.")
    else:
        total_games = len(games)
        print(f"Найдено игр в базе данных: {total_games}")
        print("Начинаю удаление игр...")

        # Remove each game
        deleted_count = 0
        failed_count = 0

        for game in games:
            try:
                db.remove_game(game.game_id)
                deleted_count += 1
                if deleted_count % 10 == 0:
                    print(f"Удалено игр: {deleted_count}/{total_games}")
            except Exception as e:
                failed_count += 1
                print(f"Ошибка при удалении игры {game.game_id}: {e}")

        print(f"\nИгры удалены!")
        print(f"Успешно удалено: {deleted_count}")
        if failed_count > 0:
            print(f"Ошибок: {failed_count}")

        # Verify database is empty
        remaining_games = db.get_all_games()
        if remaining_games:
            print(f"\nВнимание: в базе данных осталось {len(remaining_games)} игр(ы)")

    # Clear teams table if requested
    if clear_teams:
        print("\n" + "=" * 50)
        print("Очистка таблицы команд...")
        session = db.Session()
        try:
            team_count = session.query(Team).count()
            if team_count == 0:
                print("Таблица команд уже пуста.")
            else:
                print(f"Найдено команд в базе данных: {team_count}")
                session.query(Team).delete()
                session.commit()
                print(f"Таблица teams очищена. Удалено команд: {team_count}")
        except Exception as e:
            session.rollback()
            print(f"Ошибка при очистке таблицы команд: {e}")
        finally:
            session.close()

    print("\nГотово!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Очистка базы данных игр и (опционально) команд.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  %(prog)s                    # Очистить только игры
  %(prog)s --teams            # Очистить игры и команды
  %(prog)s -t                 # Короткая форма для очистки игр и команд
        """
    )
    parser.add_argument(
        '-t', '--teams',
        action='store_true',
        help='Также очистить таблицу команд после удаления всех игр'
    )

    args = parser.parse_args()
    clear_database(clear_teams=args.teams)

