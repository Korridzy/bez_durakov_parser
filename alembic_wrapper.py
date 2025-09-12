#!/usr/bin/env python3
"""
Wrapper for alembic that automatically determines database type
and calls corresponding named section in alembic.ini
"""

import sys
import subprocess
import os

# Add current directory to sys.path for config import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from config import DATABASE_URL
except ImportError:
    print("Ошибка: не удалось импортировать DATABASE_URL из config.py")
    sys.exit(1)

def determine_db_type(database_url):
    """Determine database type by URL"""
    if database_url.startswith('sqlite'):
        return 'sqlite'
    elif database_url.startswith('mysql'):
        return 'mysql'
    else:
        print(f"Неподдерживаемый тип базы данных: {database_url}")
        sys.exit(1)

def main():
    """Main wrapper function"""
    if len(sys.argv) < 2:
        print("Использование: python alembic_wrapper.py <alembic_command> [args...]")
        print("Пример: python alembic_wrapper.py upgrade head")
        print("Пример: python alembic_wrapper.py revision --autogenerate -m 'migration message'")
        sys.exit(1)

    # Determine database type
    db_type = determine_db_type(DATABASE_URL)
    print(f"Определен тип базы данных: {db_type}")
    print(f"DATABASE_URL: {DATABASE_URL}")

    # Form alembic command with named section
    alembic_args = ['alembic', '--name', db_type] + sys.argv[1:]

    print(f"Выполняем команду: {' '.join(alembic_args)}")

    # Execute alembic command
    try:
        result = subprocess.run(alembic_args, check=False)
        print(f"Команда завершена с кодом: {result.returncode}")
        sys.exit(result.returncode)
    except subprocess.CalledProcessError as e:
        print(f"Ошибка выполнения alembic: {e}")
        sys.exit(e.returncode)
    except Exception as e:
        print(f"Неожиданная ошибка: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
