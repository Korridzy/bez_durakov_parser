import os
import sys
from datetime import datetime

# Using the standard tomllib module for Python 3.11+
if sys.version_info >= (3, 11):
    import tomllib
else:
    # For earlier Python versions, we use an external package
    # pip install tomli
    import tomli as tomllib

# Path to the configuration file (relative to the project root)
# Use BD_CONFIG_FILE environment variable to override config file name
config_file_name = os.environ.get('BD_CONFIG_FILE', 'config.toml')
config_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), config_file_name)

# Loading the configuration
with open(config_file_path, "rb") as f:
    config = tomllib.load(f)

# Constants for convenient access
SQLALCHEMY_LOGGING = bool(config["database"].get("sqlalchemy_logging", False))
DEBUG = bool(config["application"].get("debug", False))
LOG_LEVEL = config["application"].get("log_level", "INFO")

# Parse default game date from config
DEFAULT_GAME_DATE_STR = config["application"].get("default_game_date", "02.03.2022")
DEFAULT_GAME_DATE = datetime.strptime(DEFAULT_GAME_DATE_STR, "%d.%m.%Y").date()

_bd_docker = os.environ.get('BD_DOCKER', '').lower() in ('1', 'true', 'yes')
DATABASE_URL = config["database"]["docker_url"] if _bd_docker else config["database"]["url"]

# Function for getting the configuration (optional)
def get_config():
    return config

# XLSM Fetch configuration
XLSM_FETCH_CONFIG = config.get("xlsm_fetch", {})
XLSM_FETCH_START_TIME = XLSM_FETCH_CONFIG.get("start_time", "20:00")
XLSM_FETCH_INTERVAL_HOURS = int(XLSM_FETCH_CONFIG.get("interval_hours", 24))
XLSM_FETCH_TIMEZONE = XLSM_FETCH_CONFIG.get("timezone", "Europe/Belgrade")

# WebReport configuration
WEBREPORT_BACKEND_PORT = int(config["webreport"].get("backend_port", 28000))
WEBREPORT_FRONTEND_PORT = int(config["webreport"].get("frontend_port", 28501))
WEBREPORT_DEBUG = config["webreport"].get("debug", False)
WEBREPORT_BACKEND_DEBUG_PORT = int(config["webreport"].get("backend_debug_port", 5678))
WEBREPORT_FRONTEND_DEBUG_PORT = int(config["webreport"].get("frontend_debug_port", 5679))
WEBREPORT_ALLOWED_ORIGINS = list(config["webreport"].get(
    "allowed_origins",
    [
        f"http://localhost:{WEBREPORT_FRONTEND_PORT}",
        f"http://127.0.0.1:{WEBREPORT_FRONTEND_PORT}",
    ],
))
