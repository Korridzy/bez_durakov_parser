from typing import final

from .base_fetcher import BaseFetcher


@final
class ApiFetcher(BaseFetcher):
    def __init__(self, folder_url: str, download_dir: str | None = None, api_key: str | None = None, access_token: str | None = None):
        super().__init__(folder_url, download_dir)
        self.api_key: str | None = api_key
        self.access_token: str | None = access_token

    def fetch(self) -> list[str]:
        raise NotImplementedError("ApiFetcher is a stub and does not download files. Use browser_selenium instead.")
