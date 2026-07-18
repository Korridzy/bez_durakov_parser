from typing import final

from .base_fetcher import BaseFetcher


@final
class GdownFetcher(BaseFetcher):
    def __init__(self, folder_url: str, download_dir: str | None = None):
        """Initialize with Google Drive folder URL and optional download directory."""
        super().__init__(folder_url, download_dir)

    def fetch(self) -> list[str]:
        raise NotImplementedError("GdownFetcher is a stub and does not download files. Use browser_selenium instead.")
