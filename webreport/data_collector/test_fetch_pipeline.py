"""Regression tests for fetch mode orchestration."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from . import fetch_pipeline


class EmptyFetcher:
    def __init__(self, download_dir: Path):
        self.download_dir = download_dir

    def fetch(self) -> list[str]:
        return []


class RunFetchTests(unittest.TestCase):
    def test_empty_success_is_not_reported_as_failure(self):
        with tempfile.TemporaryDirectory() as download_dir:
            fetcher = EmptyFetcher(Path(download_dir))
            config = {
                "google_drive_folder_url": (
                    "https://drive.google.com/drive/folders/example"
                ),
                "modes": ["browser_selenium", "gdown"],
            }

            with (
                patch.object(fetch_pipeline, "XLSM_FETCH_CONFIG", config),
                patch.object(
                    fetch_pipeline,
                    "create_fetcher",
                    return_value=fetcher,
                ) as create_fetcher,
                patch.object(fetch_pipeline.logger, "warning") as warning,
            ):
                files = fetch_pipeline.run_fetch()

            self.assertEqual(files, [])
            create_fetcher.assert_called_once()
            warning.assert_not_called()


if __name__ == "__main__":
    _ = unittest.main()
