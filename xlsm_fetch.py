#!/usr/bin/env python3
"""Fetch .xlsm files from Google Drive using different methods.

This script reads configuration from config.toml and supports three modes:
1. 'browser_selenium' - uses browser automation to access files
2. 'public_api' - uses public Google Drive API (not implemented yet)
3. 'gdown' - uses gdown library (not implemented yet)

Usage:
    python xlsm_fetch.py              # normal run
    python xlsm_fetch.py --mode browser_selenium  # force specific mode
"""

import argparse
import sys
from pathlib import Path
from xlsm_fetch import SeleniumFetcher, ApiFetcher, GdownFetcher
from config import XLSM_FETCH_CONFIG
from bd_game import BdGame
from db_helpers import initialize_database, save_game_to_database

# Constants
PROJECT_ROOT = Path(__file__).parent.resolve()

def load_config() -> dict:
    """Load configuration from config.toml via config module."""
    if not XLSM_FETCH_CONFIG.get('google_drive_folder_url'):
        print("ERROR: google_drive_folder_url is required in config.toml [xlsm_fetch] section")
        sys.exit(1)

    return XLSM_FETCH_CONFIG

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

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Fetch .xlsm files from Google Drive and process them")
    parser.add_argument(
        '--mode',
        choices=['browser_selenium', 'public_api', 'gdown'],
        help='Force specific fetching mode (overrides config)'
    )
    parser.add_argument('--no-headless', action='store_true', help='Disable headless mode for browser_selenium')
    parser.add_argument('--fetch-only', action='store_true', help='Only fetch files, do not parse and save to database')
    args = parser.parse_args()

    # Load configuration
    config = load_config()

    # Determine headless preference
    headless = not args.no_headless

    # Determine which modes to try
    if args.mode:
        modes_to_try = [args.mode]
        print(f"Using forced mode: {args.mode}")
    else:
        modes_config = config.get('modes', ['browser_selenium'])
        if isinstance(modes_config, str):
            modes_to_try = [modes_config]
        else:
            modes_to_try = modes_config
        print(f"Using mode: {modes_to_try[0] if len(modes_to_try) == 1 else modes_to_try}")

    folder_url = config['google_drive_folder_url']
    print(f"Folder URL: {folder_url}")

    # Try each mode until one succeeds
    files = []
    download_dir = None

    for mode in modes_to_try:
        print(f"\nTrying mode: {mode}")

        try:
            fetcher = create_fetcher(mode, folder_url, config, headless=headless)
            files = fetcher.fetch()
            download_dir = fetcher.download_dir

            if files:
                print(f"✅ Successfully fetched {len(files)} files using {mode}")
                break
            else:
                print(f"⚠️ No files found using {mode}")

        except Exception as e:
            print(f"❌ Error with {mode}: {e}")
            if len(modes_to_try) == 1:
                # If only one mode specified, re-raise the error
                raise
            # Otherwise continue to next mode
            continue

    if not files:
        print("❌ All methods failed")
        return []

    # Process files unless --fetch-only is specified
    if not args.fetch_only:
        process_downloaded_files(files, download_dir)
    else:
        print(f"Fetch complete. Files available in: {download_dir}")

    return files

if __name__ == "__main__":
    main()
