"""Gdown-based fetcher for Google Drive files."""

from typing import List, Optional

from .base_fetcher import BaseFetcher


class GdownFetcher(BaseFetcher):
    """Fetcher that uses gdown library to get files from Google Drive."""

    def __init__(self, folder_url: str, download_dir: Optional[str] = None):
        """Initialize with Google Drive folder URL and optional download directory."""
        super().__init__(folder_url, download_dir)

    def fetch(self) -> List[str]:
        """Fetch list of .xlsm files using gdown library.

        Returns:
            List[str] - list of file names that were downloaded/added
        """
        self._log(f"Gdown fetcher called for: {self.folder_url}")
        self._log("Gdown fetcher is not implemented yet - returning empty list")
        return []
