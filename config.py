import os
import sys

# Using the standard tomllib module for Python 3.11+
if sys.version_info >= (3, 11):
    import tomllib
else:
    # For earlier Python versions, we use an external package
    # pip install tomli
    import tomli as tomllib

# Path to the configuration file (relative to the project root)
config_file_name = "config.toml"
config_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), config_file_name)

# Loading the configuration
with open(config_file_path, "rb") as f:
    config = tomllib.load(f)

# Constants for convenient access
SQLALCHEMY_LOGGING = bool(config["database"].get("sqlalchemy_logging", False))
DEBUG = bool(config["application"].get("debug", False))
LOG_LEVEL = config["application"].get("log_level", "INFO")

DATABASE_URL = config["database"]["url"]
# Check if connection string contains a relative path to database
sqlite_prefix = "sqlite:///"
if DATABASE_URL.startswith(sqlite_prefix):
    # Split string by prefix
    _, db_path = DATABASE_URL.split(sqlite_prefix, 1)
    if not os.path.isabs(db_path):
        # Convert to absolute path
        abs_db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), db_path)
        DATABASE_URL = f"{sqlite_prefix}{abs_db_path}"

# Function for getting the configuration (optional)
def get_config():
    return config

# XLSM Fetch configuration
XLSM_FETCH_CONFIG = config.get("xlsm_fetch", {})
