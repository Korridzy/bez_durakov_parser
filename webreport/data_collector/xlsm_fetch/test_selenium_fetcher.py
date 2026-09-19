"""Regression tests for Google Drive browser controls."""

import io
import json
import logging
import tempfile
import unittest

from bd_shared import logging_setup
from selenium.webdriver.common.keys import Keys

from .selenium_fetcher import SeleniumFetcher


class FakeMenuItem:
    def __init__(self):
        self.clicked = False

    def is_displayed(self) -> bool:
        return True

    def get_attribute(self, name: str) -> str | None:
        if name == "textContent":
            return "Download"
        return None


class FakeSelectedRow:
    def __init__(self, driver: "FakeDriver"):
        self.driver = driver
        self.keys: tuple[str, ...] = ()

    def send_keys(self, *keys: str) -> None:
        self.keys = keys
        self.driver.menu_open = True


class FakeDriver:
    def __init__(self):
        self.menu_open = False
        self.menu_item = FakeMenuItem()
        self.row = FakeSelectedRow(self)

    def find_elements(
        self,
        by: str,
        selector: str,
    ) -> list[FakeMenuItem | FakeSelectedRow]:
        if selector == "[role='row'][aria-selected='true']":
            return [self.row]
        if selector == "[role='menuitem']" and self.menu_open:
            return [self.menu_item]
        return []

    def execute_script(
        self,
        script: str,
        menu_item: FakeMenuItem | None = None,
    ):
        if menu_item is not None:
            menu_item.clicked = True
            return None
        return {"width": 1920, "height": 1080}


class SeleniumFetcherTests(unittest.TestCase):
    def test_download_uses_selected_items_menu(self):
        with tempfile.TemporaryDirectory() as download_dir:
            driver = FakeDriver()
            fetcher = SeleniumFetcher(
                "https://drive.google.com/drive/folders/example",
                download_dir,
            )

            clicked = fetcher._find_download_button_by_properties(driver)

            self.assertTrue(clicked)
            self.assertEqual(driver.row.keys, (Keys.SHIFT, Keys.F10))
            self.assertTrue(driver.menu_item.clicked)

    def test_log_redacts_folder_url_and_preserves_other_messages(self):
        folder_url = "https://drive.google.com/drive/folders/TESTFOLDERID999"
        with tempfile.TemporaryDirectory() as download_dir:
            fetcher = SeleniumFetcher(folder_url, download_dir)

            with self.assertLogs(
                "webreport.data_collector.xlsm_fetch.base_fetcher",
                level=logging.INFO,
            ) as captured:
                fetcher._log(
                    f"Error: boom at {fetcher.folder_url}",
                    level=logging.ERROR,
                )
                fetcher._log("A message without the folder URL")

        output = "\n".join(captured.output)
        self.assertNotIn(folder_url, output)
        self.assertIn("[REDACTED_FOLDER_URL]", output)
        self.assertEqual(
            captured.records[0].getMessage(),
            "Error: boom at [REDACTED_FOLDER_URL]",
        )
        self.assertEqual(
            captured.records[1].getMessage(),
            "A message without the folder URL",
        )

    def test_log_redacts_exception_value_and_preserves_safe_exception(self):
        folder_url = "https://drive.google.com/drive/folders/EXCEPTIONFOLDERID999"
        with tempfile.TemporaryDirectory() as download_dir:
            fetcher = SeleniumFetcher(folder_url, download_dir)
            logging_setup._reset_for_tests()
            stream = io.StringIO()
            try:
                logging_setup.configure_logging(
                    "selenium-fetcher-test",
                    log_format="json",
                    stream=stream,
                )

                try:
                    raise RuntimeError(f"navigation failed at {folder_url}")
                except RuntimeError:
                    fetcher._log(
                        "navigation failed",
                        level=logging.ERROR,
                        exc_info=True,
                    )

                records = [
                    json.loads(line)
                    for line in stream.getvalue().splitlines()
                    if line.strip()
                ]
                sanitized_value = records[0]["exception"][0]["exc_value"]
                self.assertNotIn(folder_url, sanitized_value)
                self.assertIn("[REDACTED_FOLDER_URL]", sanitized_value)

                try:
                    raise RuntimeError("safe failure")
                except RuntimeError:
                    fetcher._log(
                        "safe failure",
                        level=logging.ERROR,
                        exc_info=True,
                    )

                records = [
                    json.loads(line)
                    for line in stream.getvalue().splitlines()
                    if line.strip()
                ]
                self.assertEqual(
                    records[1]["exception"][0]["exc_value"],
                    "safe failure",
                )
            finally:
                logging_setup._reset_for_tests()


if __name__ == "__main__":
    _ = unittest.main()
