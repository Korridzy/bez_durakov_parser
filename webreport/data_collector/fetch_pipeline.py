"""Fetch pipeline for data_collector.

Adapted from root xlsm_fetch.py for use as an importable module
called by APScheduler. Exposes run_fetch() as the main entry point.
"""
import sys
sys.path.insert(0, '/')  # bd_shared is mounted at / in Docker

import logging
from datetime import datetime
from pathlib import Path

from xlsm_fetch import SeleniumFetcher, ApiFetcher, GdownFetcher
from bd_shared.config import XLSM_FETCH_CONFIG
from bd_shared.bd_game import BdGame
from bd_shared.db_helpers import initialize_database, save_game_to_database


logger = logging.getLogger(__name__)


def create_fetcher(mode: str, folder_url: str, cfg: dict | None = None, headless: bool = True):
    """Create appropriate fetcher based on mode.

    If cfg is provided and mode == 'public_api', read 'google_api_key' and
    'google_access_token' from it and pass to ApiFetcher.
    """
    # Extract download_dir from config (may be None)
    download_dir = cfg.get('download_dir') if cfg else None

    if mode == 'browser_selenium':
        return SeleniumFetcher(folder_url, download_dir, headless=headless)
    elif mode == 'public_api':
        api_key = cfg.get('google_api_key') if cfg else None
        access_token = cfg.get('google_access_token') if cfg else None
        return ApiFetcher(folder_url, download_dir, api_key, access_token)
    elif mode == 'gdown':
        return GdownFetcher(folder_url, download_dir)
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
        print("No files to process")
        return 0, 0

    # Initialize database connection
    db = initialize_database()
    if not db:
        print("❌ Failed to initialize database connection")
        return 0, 0

    print(f"\n{'='*60}")
    print(f"PROCESSING DOWNLOADED FILES")
    print(f"{'='*60}")

    successful_parses = 0
    successful_saves = 0

    for file_name in files:
        # Handle both string filenames and dict objects
        if isinstance(file_name, dict):
            file_name = file_name.get('name', 'unknown')

        file_path = Path(download_dir) / file_name

        print(f"\nProcessing: {file_name}")

        # Check if file exists locally
        if not file_path.exists():
            print(f"❌ File not found locally: {file_path}")
            continue

        # Create BdGame instance and parse file
        game = BdGame()

        if game.parse_from_file(str(file_path)):
            successful_parses += 1
            print(f"✅ Successfully parsed: {file_name}")

            # Save to database
            if save_game_to_database(game, db):
                successful_saves += 1
            else:
                print(f"⚠️ Failed to save to database: {file_name}")
        else:
            print(f"❌ Failed to parse: {file_name}")

    # Print summary
    print(f"\n{'='*60}")
    print(f"PROCESSING SUMMARY")
    print(f"{'='*60}")
    print(f"Files processed: {len(files)}")
    print(f"Successfully parsed: {successful_parses}")
    print(f"Successfully saved to database: {successful_saves}")

    if successful_parses < len(files):
        print(f"Failed to parse: {len(files) - successful_parses}")

    if successful_saves < successful_parses:
        print(f"Failed to save: {successful_parses - successful_saves}")

    return successful_parses, successful_saves


def run_fetch():
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

    # Get modes from config (no argparse override)
    modes_config = config.get('modes', ['browser_selenium'])
    if isinstance(modes_config, str):
        modes_to_try = [modes_config]
    else:
        modes_to_try = modes_config
    logger.info(f"Using mode: {modes_to_try[0] if len(modes_to_try) == 1 else modes_to_try}")

    folder_url = config['google_drive_folder_url']
    logger.info(f"Folder URL: {folder_url}")

    # Try each mode until one succeeds
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
                # If only one mode specified, re-raise the error
                raise
            # Otherwise continue to next mode
            continue

    if not files:
        logger.warning("All methods failed")
        return []

    # Process downloaded files (parse + save to DB)
    process_downloaded_files(files, download_dir)

    return files
