"""Fetch pipeline for data_collector.

Adapted from root xlsm_fetch.py for use as an importable module
called by APScheduler. Exposes run_fetch() as the main entry point.
"""

import time
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from bd_shared.bd_game import BdGame
from bd_shared.config import LOG_LEVEL, SQLALCHEMY_LOGGING, XLSM_FETCH_CONFIG
from bd_shared.db_helpers import initialize_database, save_game_to_database
from bd_shared.logging_setup import configure_logging, get_logger

if TYPE_CHECKING:
    from .xlsm_fetch import SeleniumFetcher
else:
    SeleniumFetcher = import_module(
        f"{__package__}.xlsm_fetch" if __package__ else "xlsm_fetch"
    ).SeleniumFetcher


logger = get_logger(__name__)


def create_fetcher(
    mode: str,
    folder_url: str,
    cfg: dict[str, str | list[str] | int] | None = None,
    headless: bool = True,
) -> SeleniumFetcher:
    download_dir = None
    if cfg is not None:
        configured_download_dir = cfg.get("download_dir")
        if configured_download_dir is not None:
            download_dir = str(configured_download_dir)

    if mode == "browser_selenium":
        return SeleniumFetcher(folder_url, download_dir, headless=headless)
    elif mode == "public_api":
        raise NotImplementedError(
            "Fetch mode 'public_api' is not supported yet. Use 'browser_selenium'."
        )
    elif mode == "gdown":
        raise NotImplementedError(
            "Fetch mode 'gdown' is not supported yet. Use 'browser_selenium'."
        )
    else:
        raise ValueError(f"Unknown mode: {mode}")


def process_downloaded_files(files, download_dir):
    """Process downloaded .xlsm files by parsing and saving to database.

    Args:
        files: List of file names (strings) from fetcher
        download_dir: Directory where files were downloaded

    Returns:
        tuple: (successful_parses, successful_saves)
    """
    if not files:
        logger.info("no_files_to_process")
        return 0, 0

    if download_dir is None:
        logger.error("download_dir_missing")
        return 0, 0

    # Initialize database connection
    db = initialize_database()
    if not db:
        logger.error("database_unavailable")
        return 0, 0

    successful_parses = 0
    successful_saves = 0

    normalized_files: list[str] = []
    for file_entry in files:
        if isinstance(file_entry, dict):
            normalized_files.append(file_entry.get("name", "unknown"))
        else:
            normalized_files.append(file_entry)

    for file_name in normalized_files:
        file_path = Path(download_dir) / file_name
        parsed = False
        saved = False

        if not file_path.exists():
            logger.warning("downloaded_file_missing", file_name=file_name)
        else:
            game = BdGame()
            parsed = bool(game.parse_from_file(str(file_path)))
            if parsed:
                successful_parses += 1
                saved = bool(save_game_to_database(game, db))
                if saved:
                    successful_saves += 1

        logger.info(
            "downloaded_file_processed",
            file_name=file_name,
            parsed=parsed,
            saved=saved,
        )

    logger.info(
        "downloaded_files_processed",
        files=len(normalized_files),
        parsed=successful_parses,
        saved=successful_saves,
    )

    if successful_parses < len(normalized_files):
        logger.warning(
            "downloaded_files_parse_failures",
            count=len(normalized_files) - successful_parses,
        )

    if successful_saves < successful_parses:
        logger.warning(
            "downloaded_files_save_failures",
            count=successful_parses - successful_saves,
        )

    return successful_parses, successful_saves


def _run_fetch() -> list[str]:
    config = XLSM_FETCH_CONFIG

    if not config.get("google_drive_folder_url"):
        raise ValueError(
            "google_drive_folder_url is required in config.toml [xlsm_fetch] section"
        )

    # Always headless in scheduled mode
    headless = True

    modes_config = config.get("modes", ["browser_selenium"])
    if isinstance(modes_config, str):
        modes_to_try = [modes_config]
    elif isinstance(modes_config, Iterable):
        modes_to_try = [str(mode) for mode in modes_config]
    else:
        raise TypeError("xlsm_fetch.modes must be a string or iterable of strings")
    logger.info("fetch_modes_selected", modes=modes_to_try)

    folder_url = config["google_drive_folder_url"]

    files = []
    download_dir = None
    fetch_succeeded = False

    for mode in modes_to_try:
        logger.info("fetch_method_attempted", mode=mode)

        try:
            fetcher = create_fetcher(mode, folder_url, config, headless=headless)
            files = fetcher.fetch()
            download_dir = fetcher.download_dir
            fetch_succeeded = True
            logger.info("files_fetched", count=len(files), mode=mode)
            break

        except Exception:
            logger.error("fetch_method_failed", mode=mode, exc_info=True)
            if len(modes_to_try) == 1:
                raise
            continue

    if not fetch_succeeded:
        logger.warning("fetch_all_methods_failed")
        return []

    if not files:
        logger.info("no_new_files")
        return []

    _ = process_downloaded_files(files, download_dir)

    return files


def run_fetch() -> list[str]:
    """Fetch XLSM files with a correlation id bound for the full job run."""
    with structlog.contextvars.bound_contextvars(
        job_id=uuid.uuid4().hex, job_name="xlsm_fetch"
    ):
        started = time.perf_counter()
        logger.info(
            "fetch_started",
            marker="Fetch started at",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        try:
            files = _run_fetch()
        except Exception:
            logger.error(
                "fetch_failed",
                duration_ms=(time.perf_counter() - started) * 1000,
                exc_info=True,
            )
            raise

        logger.info(
            "fetch_completed",
            file_count=len(files),
            duration_ms=(time.perf_counter() - started) * 1000,
        )
        return files


if __name__ == "__main__":
    configure_logging(
        "webreport-data-collector",
        level=LOG_LEVEL,
        logger_levels={"sqlalchemy.engine": LOG_LEVEL}
        if SQLALCHEMY_LOGGING
        else None,
    )
    _ = run_fetch()
