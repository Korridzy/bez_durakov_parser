#!/usr/bin/env python3
"""
Test script to verify Alembic migrations work with bd_shared structure.
Creates a temporary test database in MySQL, runs migrations, and verifies success.
Does not affect the current production database.

Requirements:
- MySQL service must be running (e.g., via docker-compose in webreport/)
- test_config.toml must be configured in bd_shared/
- MySQL user must have CREATE DATABASE privilege
"""

import os
import sys
import subprocess
from pathlib import Path
from urllib.parse import urlparse
import pymysql

# Using the standard tomllib module for Python 3.11+
if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


def test_alembic_migration():
    """Test Alembic migration on test MySQL database."""

    # Read test config
    test_config_path = Path(__file__).parent / 'bd_shared' / 'test_config.toml'
    
    print(f"Reading test configuration from {test_config_path}...")
    with open(test_config_path, 'rb') as f:
        test_config = tomllib.load(f)
    
    test_db_url = test_config['database']['url']
    print(f"Test DATABASE_URL: {test_db_url}")
    
    parsed = urlparse(test_db_url)
    
    mysql_host = parsed.hostname or 'localhost'
    mysql_port = parsed.port or 3306
    mysql_user = parsed.username
    mysql_password = parsed.password
    test_db_name = parsed.path.lstrip('/')

    try:
        # Connect to MySQL server and create test database
        print(f"Connecting to MySQL at {mysql_host}:{mysql_port} as {mysql_user}...")
        
        connection = pymysql.connect(
            host=mysql_host,
            port=mysql_port,
            user=mysql_user,
            password=mysql_password
        )

        with connection.cursor() as cursor:
            # Drop test database if exists (from previous run)
            print(f"Dropping test database if exists: {test_db_name}")
            cursor.execute(f"DROP DATABASE IF EXISTS {test_db_name}")
            
            # Create fresh test database
            print(f"Creating test database: {test_db_name}")
            cursor.execute(f"CREATE DATABASE {test_db_name}")

        connection.close()
        print(f"✅ Test database created: {test_db_name}")

        # Small delay to ensure database is fully created
        import time
        time.sleep(1)

        # Run alembic upgrade head with test config
        print("Running alembic upgrade head...")
        env = os.environ.copy()
        env['BD_CONFIG_FILE'] = 'test_config.toml'
        
        result = subprocess.run(
            ['alembic', 'upgrade', 'head'],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            env=env
        )

        if result.returncode == 0:
            print("✅ Alembic migration successful!")
            if result.stdout:
                print("Output:", result.stdout)
        else:
            print("❌ Alembic migration failed!")
            print("STDERR:", result.stderr)
            if result.stdout:
                print("STDOUT:", result.stdout)
            return False

        # Verify tables were created
        connection = pymysql.connect(
            host=mysql_host,
            port=mysql_port,
            user=mysql_user,
            password=mysql_password,
            database=test_db_name
        )

        with connection.cursor() as cursor:
            cursor.execute("SHOW TABLES")
            tables = cursor.fetchall()

            if len(tables) > 0:
                print(f"✅ Test database contains {len(tables)} tables")
                print(f"Tables: {[table[0] for table in tables]}")
                connection.close()
                return True
            else:
                print("❌ No tables created in test database")
                connection.close()
                return False

    except pymysql.Error as e:
        print(f"❌ MySQL error: {e}")
        print("Ensure that:")
        print("  - MySQL service is running")
        print("  - Database credentials in bd_shared/test_config.toml are correct")
        print("  - User has CREATE DATABASE privilege")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Clean up test database
        try:
            connection = pymysql.connect(
                host=mysql_host,
                port=mysql_port,
                user=mysql_user,
                password=mysql_password
            )

            with connection.cursor() as cursor:
                cursor.execute(f"DROP DATABASE IF EXISTS {test_db_name}")
                print(f"🧹 Cleaned up test database: {test_db_name}")
            connection.close()
        except Exception as e:
            print(f"⚠️  Warning: Failed to clean up test database {test_db_name}: {e}")


if __name__ == '__main__':
    print("=" * 60)
    print("Testing Alembic migrations with bd_shared structure")
    print("=" * 60)
    success = test_alembic_migration()
    print("=" * 60)
    sys.exit(0 if success else 1)

