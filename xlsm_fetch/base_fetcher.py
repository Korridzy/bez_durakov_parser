"""Base fetcher for xlsm_fetch package."""

from typing import List, Dict, Optional
from pathlib import Path


class BaseFetcher:
    """Abstract base class for all fetchers in xlsm_fetch.

    Provides common fields and helper methods used by concrete fetchers.
    """

    def __init__(self, folder_url: str, download_dir: Optional[str] = None):
        """Initialize with Google Drive folder URL and optional download directory.

        If download_dir is not provided, it is set to <project_root>/xlsm_archive.
        """
        self.folder_url = folder_url

        # Normalize: if download_dir not provided, use project_root/xlsm_archive
        project_root = Path(__file__).parent.parent.resolve()
        # expose project root to subclasses so they can inherit it instead of recomputing
        self.project_root = project_root
        if not download_dir:
            download_dir = str(project_root / 'xlsm_archive')

        p = Path(download_dir)
        if not p.is_absolute():
            p = project_root / p
        p.mkdir(parents=True, exist_ok=True)
        self.download_dir = p.resolve()

    def fetch(self) -> List[str]:
        """Perform the fetch. Must be implemented by subclasses.

        Returns:
            List[str] - list of file names that were downloaded/added
        """
        raise NotImplementedError

    def _log(self, msg: str) -> None:
        """Simple logging helper; subclasses can override if needed."""
        print(msg)
