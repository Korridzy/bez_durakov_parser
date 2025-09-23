"""API-based fetcher for Google Drive files."""

from typing import List, Dict, Optional
import os
import re
import requests

from .base_fetcher import BaseFetcher


class ApiFetcher(BaseFetcher):
    """Fetcher that uses the Google Drive REST API.

    Operates in three optional modes:
    - access_token (OAuth2) provided to the constructor -> uses Authorization: Bearer header
    - api_key provided to the constructor -> uses the 'key' query parameter
    - no credentials provided -> attempts an unauthenticated request (may be rejected)

    Pagination: iterates through all pages using nextPageToken.
    """

    DRIVE_FILES_ENDPOINT = "https://www.googleapis.com/drive/v3/files"

    def __init__(self, folder_url: str, api_key: Optional[str] = None, access_token: Optional[str] = None, download_dir: Optional[str] = None):
        """Initialize with Google Drive folder URL and optional credentials.

        Args:
            folder_url: Google Drive folder URL or a raw folder id.
            api_key: optional API key for public requests.
            access_token: optional OAuth2 access token (Bearer) for authenticated requests.
            download_dir: optional download directory path.
        """
        super().__init__(folder_url, download_dir)
        self.api_key = api_key
        self.access_token = access_token

    def _extract_folder_id(self) -> Optional[str]:
        """Extract Google Drive folder id from the provided folder_url.

        Supports common URL patterns and returns the id if found, otherwise None.
        """
        if not self.folder_url:
            return None

        # common patterns
        patterns = [
            r"/folders/([a-zA-Z0-9_-]+)",
            r"[?&]id=([a-zA-Z0-9_-]+)",
            r"/file/d/([a-zA-Z0-9_-]+)"
        ]

        for pat in patterns:
            m = re.search(pat, self.folder_url)
            if m:
                return m.group(1)

        # fallback: maybe the entire URL is just an id
        if re.fullmatch(r"[a-zA-Z0-9_-]+", self.folder_url):
            return self.folder_url

        return None

    def fetch(self) -> List[Dict[str, str]]:
        """Fetch list of .xlsm files using the Google Drive API.

        Uses access_token (Bearer) if provided, otherwise api_key if provided, or an unauthenticated
        request as a last resort. Iterates through all pages and returns files matching '.xlsm'.

        Returns:
            List of dictionaries with file info: {'id': str, 'name': str, 'size': int}
        """
        self._log(f"Starting API fetch from: {self.folder_url}")

        folder_id = self._extract_folder_id()
        if not folder_id:
            self._log("Could not extract folder id from folder_url")
            return []

        params = {
            # list children of folder, skip trashed
            'q': f"'{folder_id}' in parents and trashed=false",
            'fields': 'nextPageToken, files(id, name, mimeType, size)',
            'pageSize': 1000,
        }

        headers = {}
        if self.access_token:
            headers['Authorization'] = f"Bearer {self.access_token}"
            self._log("Using provided access_token for Authorization: Bearer <token>")
        elif self.api_key:
            params['key'] = self.api_key
            self._log("Using provided api_key for requests")
        else:
            self._log("No credentials provided; attempting unauthenticated requests (may fail)")

        files: List[Dict[str, str]] = []
        next_token: Optional[str] = None

        try:
            while True:
                if next_token:
                    params['pageToken'] = next_token

                resp = requests.get(self.DRIVE_FILES_ENDPOINT, params=params, headers=headers or None, timeout=30)
                if resp.status_code != 200:
                    self._log(f"Drive API returned status {resp.status_code}: {resp.text}")
                    return files

                data = resp.json()
                page_files = data.get('files', [])

                for f in page_files:
                    name = f.get('name') or ''
                    if name.lower().endswith('.xlsm'):
                        size = 0
                        try:
                            size = int(f.get('size', 0) or 0)
                        except Exception:
                            size = 0

                        files.append({
                            'id': f.get('id'),
                            'name': name,
                            'size': size,
                        })

                next_token = data.get('nextPageToken')
                if not next_token:
                    break

            self._log(f"API fetch completed. Found {len(files)} .xlsm files")
            return files

        except requests.RequestException as e:
            self._log(f"Request error during API fetch: {e}")
            return files
        except Exception as e:
            self._log(f"Unexpected error during API fetch: {e}")
            return files
