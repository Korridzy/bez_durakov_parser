#!/usr/bin/env python3
"""Fetch .xlsm files from Google Drive using different methods.

This script reads configuration from secret/xlsm_data.json and supports three modes:
1. 'browser_selenium' - uses browser automation to access files
2. 'public_api' - uses public Google Drive API (not implemented yet)
3. 'gdown' - uses gdown library (not implemented yet)

Usage:
    python xlsm_fetch.py              # normal run
    python xlsm_fetch.py --mode browser_selenium  # force specific mode
"""

import argparse
import json
import sys
from pathlib import Path
from xlsm_fetch import SeleniumFetcher, ApiFetcher, GdownFetcher

# Constants
PROJECT_ROOT = Path(__file__).parent.resolve()
CONFIG_FILE = PROJECT_ROOT / "secret" / "xlsm_data.json"

def load_config() -> dict:
    """Load configuration from JSON file."""
    if not CONFIG_FILE.exists():
        print(f"ERROR: Configuration file not found: {CONFIG_FILE}")
        print("Please create the file with Google Drive folder URL and settings.")
        sys.exit(1)

    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)

        if not config.get('google_drive_folder_url'):
            print("ERROR: google_drive_folder_url is required in config")
            sys.exit(1)

        return config
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in {CONFIG_FILE}: {e}")
        sys.exit(1)

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

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Fetch .xlsm files from Google Drive")
    parser.add_argument(
        '--mode',
        choices=['browser_selenium', 'public_api', 'gdown'],
        help='Force specific fetching mode (overrides config)'
    )
    parser.add_argument('--no-headless', action='store_true', help='Disable headless mode for browser_selenium')
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
    for mode in modes_to_try:
        print(f"\nTrying mode: {mode}")

        try:
            fetcher = create_fetcher(mode, folder_url, config, headless=headless)
            files = fetcher.fetch()

            if files:
                return files
            else:
                print(f"⚠️ No files found using {mode}")

        except Exception as e:
            print(f"❌ Error with {mode}: {e}")
            if len(modes_to_try) == 1:
                # If only one mode specified, re-raise the error
                raise
            # Otherwise continue to next mode
            continue

    print("❌ All methods failed")
    return []

if __name__ == "__main__":
    main()
