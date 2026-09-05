"""Fetch pipeline for data_collector.

Adapted from root xlsm_fetch.py for use as an importable module
called by APScheduler. Exposes run_fetch() as the main entry point.
"""
import logging
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from bd_shared.bd_game import BdGame
from bd_shared.config import XLSM_FETCH_CONFIG
from bd_shared.db_helpers import initialize_database, save_game_to_database
from xlsm_fetch import SeleniumFetcher


logger = logging.getLogger(__name__)


def create_fetcher(mode: str, folder_url: str, cfg: dict | None = None, headless: bool = True) -> SeleniumFetcher:
    download_dir = None
    if cfg is not None:
        configured_download_dir = cfg.get('download_dir')
        if configured_download_dir is not None:
            download_dir = str(configured_download_dir)

    if mode == 'browser_selenium':
        return SeleniumFetcher(folder_url, download_dir, headless=headless)
    elif mode == 'public_api':
        raise NotImplementedError("Fetch mode 'public_api' is not supported yet. Use 'browser_selenium'.")
    elif mode == 'gdown':
        raise NotImplementedError("Fetch mode 'gdown' is not supported yet. Use 'browser_selenium'.")
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
        logger.info("No files to process")
        return 0, 0

    if download_dir is None:
        logger.error("Download directory is not configured")
        return 0, 0

    # Initialize database connection
    db = initialize_database()
    if not db:
        logger.error("Failed to initialize database connection")
        return 0, 0

    logger.info("Processing downloaded files")

    successful_parses = 0
    successful_saves = 0

    normalized_files: list[str] = []
    for file_entry in files:
        if isinstance(file_entry, dict):
            normalized_files.append(file_entry.get('name', 'unknown'))
        else:
            normalized_files.append(file_entry)

    for file_name in normalized_files:

        file_path = Path(download_dir) / file_name

        logger.info("Processing downloaded file: %s", file_name)

        if not file_path.exists():
            logger.warning("Downloaded file not found locally: %s", file_path)
            continue

        game = BdGame()

        if game.parse_from_file(str(file_path)):
            successful_parses += 1
            logger.info("Successfully parsed downloaded file: %s", file_name)

            if save_game_to_database(game, db):
                successful_saves += 1
            else:
                logger.warning("Failed to save downloaded file to database: %s", file_name)
        else:
            logger.error("Failed to parse downloaded file: %s", file_name)

    logger.info(
        "Downloaded file processing completed: files=%d parsed=%d saved=%d",
        len(normalized_files),
        successful_parses,
        successful_saves,
    )

    if successful_parses < len(normalized_files):
        logger.warning(
            "Downloaded files failed to parse: %d",
            len(normalized_files) - successful_parses,
        )

    if successful_saves < successful_parses:
        logger.warning(
            "Parsed files failed to save: %d",
            successful_parses - successful_saves,
        )

    return successful_parses, successful_saves


def run_fetch() -> list[str]:
    """Main entry point for the fetch pipeline.

    Called by APScheduler to fetch XLSM files from Google Drive,
    parse them, and save to database.

    Returns:
        list: List of downloaded files.

    Raises:
        ValueError: If google_drive_folder_url is missing from config.
    """
    logging.info(f"Fetch started at {datetime.now()}")

    config = XLSM_FETCH_CONFIG

    if not config.get('google_drive_folder_url'):
        raise ValueError("google_drive_folder_url is required in config.toml [xlsm_fetch] section")

    # Always headless in scheduled mode
    headless = True

    modes_config = config.get('modes', ['browser_selenium'])
    if isinstance(modes_config, str):
        modes_to_try = [modes_config]
    elif isinstance(modes_config, Iterable):
        modes_to_try = [str(mode) for mode in modes_config]
    else:
        raise TypeError("xlsm_fetch.modes must be a string or iterable of strings")
    logger.info(f"Using mode: {modes_to_try[0] if len(modes_to_try) == 1 else modes_to_try}")

    folder_url = config['google_drive_folder_url']
    logger.info(f"Folder URL: {folder_url}")

    files = []
    download_dir = None

    for mode in modes_to_try:
        logger.info(f"Trying mode: {mode}")

        try:
            fetcher = create_fetcher(mode, folder_url, config, headless=headless)
            files = fetcher.fetch()
            download_dir = fetcher.download_dir

            if files:
                logger.info(f"Successfully fetched {len(files)} files using {mode}")
                break
            else:
                logger.warning(f"No files found using {mode}")

        except Exception as e:
            logger.error(f"Error with {mode}: {e}")
            if len(modes_to_try) == 1:
                raise
            continue

    if not files:
        logger.warning("All methods failed")
        return []

    _ = process_downloaded_files(files, download_dir)

    return files


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    _ = run_fetch()
