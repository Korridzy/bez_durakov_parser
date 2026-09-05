import os
import sys
from datetime import datetime
from pathlib import Path
from typing import TypeAlias
from sqlalchemy.engine import make_url

# Using the standard tomllib module for Python 3.11+
if sys.version_info >= (3, 11):
    import tomllib
else:
    # For earlier Python versions, we use an external package
    # pip install tomli
    import tomli as tomllib

LocalConfigValue: TypeAlias = str | int | float | bool | list[str]

# Path to the configuration file (relative to the project root)
# Use BD_CONFIG_FILE environment variable to select a complete alternate config.
config_directory = os.path.dirname(os.path.abspath(__file__))
config_file_name = os.environ.get('BD_CONFIG_FILE', 'config.toml')
config_file_path = os.path.join(config_directory, config_file_name)

# Loading the configuration
with open(config_file_path, "rb") as f:
    config = tomllib.load(f)

if 'BD_CONFIG_FILE' not in os.environ:
    local_config_file_path = os.path.join(config_directory, 'config.local.toml')
    if os.path.isfile(local_config_file_path):
        with open(local_config_file_path, "rb") as f:
            local_config: dict[str, LocalConfigValue | dict[str, LocalConfigValue]] = tomllib.load(f)
        for section, local_value in local_config.items():
            base_value = config.get(section)
            if isinstance(base_value, dict) and isinstance(local_value, dict):
                config[section] = {**base_value, **local_value}
            else:
                config[section] = local_value

# Constants for convenient access
SQLALCHEMY_LOGGING = bool(config["database"].get("sqlalchemy_logging", False))
DEBUG = bool(config["application"].get("debug", False))
LOG_LEVEL = config["application"].get("log_level", "INFO")

# Parse default game date from config
DEFAULT_GAME_DATE_STR = config["application"].get("default_game_date", "02.03.2022")
DEFAULT_GAME_DATE = datetime.strptime(DEFAULT_GAME_DATE_STR, "%d.%m.%Y").date()

_bd_docker = os.environ.get('BD_DOCKER', '').lower() in ('1', 'true', 'yes')
DATABASE_URL = config["database"]["docker_url"] if _bd_docker else config["database"]["url"]
DATABASE_NAME = make_url(DATABASE_URL).database

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
WEBREPORT_RELOAD = config["webreport"].get("reload", True)
WEBREPORT_BACKEND_DEBUG_PORT = int(config["webreport"].get("backend_debug_port", 5678))
WEBREPORT_FRONTEND_DEBUG_PORT = int(config["webreport"].get("frontend_debug_port", 5679))
WEBREPORT_ALLOWED_ORIGINS = list(config["webreport"].get(
    "allowed_origins",
    [
        f"http://localhost:{WEBREPORT_FRONTEND_PORT}",
        f"http://127.0.0.1:{WEBREPORT_FRONTEND_PORT}",
    ],
))

# Report agent configuration
AGENT_RECURSION_LIMIT = int(config["webreport"].get("agent_recursion_limit", 8))
AGENT_TIMEOUT_SECONDS = int(config["webreport"].get("agent_timeout_seconds", 60))
AGENT_MAX_ROWS_PER_FETCH = int(config["webreport"].get("agent_max_rows_per_fetch", 256))
AGENT_MAX_ROWS_PER_RUN = int(config["webreport"].get("agent_max_rows_per_run", 1024))
CHECKPOINT_TTL_SECONDS = int(config["webreport"].get("checkpoint_ttl_seconds", 3600))
LITELLM_BASE_URL = config["webreport"].get("litellm_base_url", "http://litellm:4000")
AGENT_MODEL = config["webreport"].get("agent_model", "gpt-4o")

# Startup LiteLLM probe and LLM client retry policy
PROBE_RETRY_ATTEMPTS = int(config["webreport"].get("probe_retry_attempts", 5))
PROBE_RETRY_DELAY_SECONDS = int(config["webreport"].get("probe_retry_delay_seconds", 2))
PROBE_REQUEST_TIMEOUT_SECONDS = int(config["webreport"].get("probe_request_timeout_seconds", 10))
LLM_MAX_RETRIES = int(config["webreport"].get("llm_max_retries", 0))
LLM_REQUEST_TIMEOUT_SECONDS = int(config["webreport"].get("llm_request_timeout_seconds", 60))

KNOWLEDGE_MAX_TITLE_CHARS = int(config["webreport"].get("knowledge_max_title_chars", 80))
KNOWLEDGE_MAX_SUMMARY_CHARS = int(config["webreport"].get("knowledge_max_summary_chars", 200))
KNOWLEDGE_MAX_PERSONA_CHARS = int(config["webreport"].get("knowledge_max_persona_chars", 2000))
KNOWLEDGE_MAX_TOPICS = int(config["webreport"].get("knowledge_max_topics", 50))
KNOWLEDGE_MAX_DOC_BYTES = int(config["webreport"].get("knowledge_max_doc_bytes", 65536))
_knowledge_dir_value = config["webreport"].get("knowledge_dir") or None
if _knowledge_dir_value is None:
    _knowledge_dir_path = None
else:
    _knowledge_dir_path = Path(_knowledge_dir_value)
    _knowledge_dir_path = (
        _knowledge_dir_path
        if _knowledge_dir_path.is_absolute()
        else Path(config_directory) / _knowledge_dir_path
    )
KNOWLEDGE_DIR = _knowledge_dir_path

# Use BD_CHECKPOINT_DB_PATH environment variable to override the checkpoint store location
CHECKPOINT_DB_PATH = os.environ.get("BD_CHECKPOINT_DB_PATH") or config["webreport"].get(
    "checkpoint_db_path", "/data/checkpoints.db"
)
