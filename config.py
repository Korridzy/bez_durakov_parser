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
DATABASE_URL = config["database"]["url"]
SQLALCHEMY_LOGGING = bool(config["database"].get("sqlalchemy_logging", False))
DEBUG = bool(config["application"].get("debug", False))
LOG_LEVEL = config["application"].get("log_level", "INFO")

# Function for getting the configuration (optional)
def get_config():
    return config