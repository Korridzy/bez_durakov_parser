"""Regression tests for Google Drive browser controls."""

import io
import json
import logging
import tempfile
import unittest

from bd_shared import logging_setup
from selenium.webdriver.common.keys import Keys

from .selenium_fetcher import SeleniumFetcher, _sanitize_exception_tree


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
        self.assertIn(
            "[REDACTED_FOLDER_URL]",
            captured.records[0].getMessage(),
        )
        self.assertNotIn(folder_url, captured.records[0].getMessage())
        self.assertNotIn(
            "[REDACTED_FOLDER_URL]",
            captured.records[1].getMessage(),
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

    def test_log_redacts_exception_cause_without_mutating_original_chain(self):
        folder_url = "https://drive.google.com/drive/folders/CAUSEFOLDERID999"
        with tempfile.TemporaryDirectory() as download_dir:
            fetcher = SeleniumFetcher(folder_url, download_dir)
            logging_setup._reset_for_tests()
            stream = io.StringIO()
            try:
                logging_setup.configure_logging(
                    "selenium-fetcher-cause-test",
                    log_format="json",
                    stream=stream,
                )

                inner = ValueError(f"transport rejected sensitive source {folder_url}")
                try:
                    try:
                        raise inner
                    except ValueError as cause:
                        raise OSError("webdriver navigation failed") from cause
                except OSError as caught:
                    outer = caught
                    fetcher._log(
                        "cause-bearing failure",
                        level=logging.ERROR,
                        exc_info=True,
                    )

                records = [
                    json.loads(line)
                    for line in stream.getvalue().splitlines()
                    if line.strip()
                ]
                serialized = json.dumps(records)
                self.assertNotIn(folder_url, serialized)
                self.assertIn("[REDACTED_FOLDER_URL]", serialized)
                self.assertIs(outer.__cause__, inner)
                self.assertIn(folder_url, str(outer.__cause__))
                self.assertTrue(outer.__suppress_context__)
            finally:
                logging_setup._reset_for_tests()

    def test_log_redacts_exception_context_without_mutating_original_chain(self):
        folder_url = "https://drive.google.com/drive/folders/CONTEXTFOLDERID999"
        with tempfile.TemporaryDirectory() as download_dir:
            fetcher = SeleniumFetcher(folder_url, download_dir)
            logging_setup._reset_for_tests()
            stream = io.StringIO()
            try:
                logging_setup.configure_logging(
                    "selenium-fetcher-context-test",
                    log_format="json",
                    stream=stream,
                )

                inner = ValueError(f"transport rejected sensitive source {folder_url}")
                try:
                    try:
                        raise inner
                    except ValueError:
                        raise OSError("webdriver navigation failed")
                except OSError as caught:
                    outer = caught
                    fetcher._log(
                        "context-bearing failure",
                        level=logging.ERROR,
                        exc_info=True,
                    )

                records = [
                    json.loads(line)
                    for line in stream.getvalue().splitlines()
                    if line.strip()
                ]
                serialized = json.dumps(records)
                self.assertNotIn(folder_url, serialized)
                self.assertIn("[REDACTED_FOLDER_URL]", serialized)
                self.assertIsNone(outer.__cause__)
                self.assertIs(outer.__context__, inner)
                self.assertIn(folder_url, str(outer.__context__))
                self.assertFalse(outer.__suppress_context__)
            finally:
                logging_setup._reset_for_tests()

    def test_log_redacts_exception_notes_without_mutating_original_notes(self):
        folder_url = "https://drive.google.com/drive/folders/NOTEFOLDERID999"
        with tempfile.TemporaryDirectory() as download_dir:
            fetcher = SeleniumFetcher(folder_url, download_dir)
            logging_setup._reset_for_tests()
            stream = io.StringIO()
            try:
                logging_setup.configure_logging(
                    "selenium-fetcher-note-test",
                    log_format="json",
                    stream=stream,
                )

                original = RuntimeError("safe failure")
                original_notes = ["safe note", f"source folder: {folder_url}"]
                for note in original_notes:
                    original.add_note(note)
                try:
                    raise original
                except RuntimeError:
                    fetcher._log(
                        "note-bearing failure",
                        level=logging.ERROR,
                        exc_info=True,
                    )

                records = [
                    json.loads(line)
                    for line in stream.getvalue().splitlines()
                    if line.strip()
                ]
                serialized = json.dumps(records)
                self.assertNotIn(folder_url, serialized)
                self.assertIn("[REDACTED_FOLDER_URL]", serialized)
                self.assertEqual(original.__notes__, original_notes)
                self.assertIn(folder_url, original.__notes__[1])
            finally:
                logging_setup._reset_for_tests()

    def test_log_redacts_syntax_error_metadata_without_mutating_original(self):
        folder_url = "https://drive.google.com/drive/folders/SYNTAXFOLDERID999"
        with tempfile.TemporaryDirectory() as download_dir:
            fetcher = SeleniumFetcher(folder_url, download_dir)
            logging_setup._reset_for_tests()
            stream = io.StringIO()
            try:
                logging_setup.configure_logging(
                    "selenium-fetcher-syntax-error-test",
                    log_format="json",
                    stream=stream,
                )

                source_text = f"load_source({folder_url!r})"
                original = SyntaxError(
                    "invalid source",
                    ("safe_source.py", 3, 2, source_text, 3, 8),
                )
                try:
                    raise original
                except SyntaxError:
                    fetcher._log(
                        "syntax failure",
                        level=logging.ERROR,
                        exc_info=True,
                    )

                records = [
                    json.loads(line)
                    for line in stream.getvalue().splitlines()
                    if line.strip()
                ]
                serialized = json.dumps(records)
                self.assertNotIn(folder_url, serialized)
                syntax_error = records[0]["exception"][0]["syntax_error"]
                self.assertIn("[REDACTED_FOLDER_URL]", syntax_error["line"])
                self.assertEqual(original.text, source_text)
                assert original.text is not None
                self.assertIn(folder_url, original.text)
            finally:
                logging_setup._reset_for_tests()

    def test_log_redacts_exception_group_child_and_preserves_safe_group(self):
        folder_url = "https://drive.google.com/drive/folders/GROUPFOLDERID999"
        replacement = "[REDACTED_FOLDER_URL]"
        with tempfile.TemporaryDirectory() as download_dir:
            fetcher = SeleniumFetcher(folder_url, download_dir)
            logging_setup._reset_for_tests()
            stream = io.StringIO()
            try:
                logging_setup.configure_logging(
                    "selenium-fetcher-group-test",
                    log_format="json",
                    stream=stream,
                )

                safe_child = KeyError("safe child")
                leaking_child = ValueError(f"child source: {folder_url}")
                original_group = ExceptionGroup(
                    "safe group",
                    [safe_child, leaking_child],
                )
                sanitized_group = _sanitize_exception_tree(
                    original_group,
                    folder_url,
                    replacement,
                )
                self.assertIs(type(sanitized_group), ExceptionGroup)
                assert isinstance(sanitized_group, BaseExceptionGroup)
                self.assertEqual(sanitized_group.message, "safe group")
                self.assertIs(sanitized_group.exceptions[0], safe_child)
                self.assertIsNot(sanitized_group.exceptions[1], leaking_child)

                try:
                    raise original_group
                except ExceptionGroup:
                    fetcher._log(
                        "grouped failure",
                        level=logging.ERROR,
                        exc_info=True,
                    )

                control_children = (ValueError("safe one"), OSError("safe two"))
                control_group = ExceptionGroup("safe control", control_children)
                sanitized_control = _sanitize_exception_tree(
                    control_group,
                    folder_url,
                    replacement,
                )
                self.assertIs(sanitized_control, control_group)
                assert isinstance(sanitized_control, BaseExceptionGroup)
                self.assertIs(sanitized_control.exceptions[0], control_children[0])
                self.assertIs(sanitized_control.exceptions[1], control_children[1])
                try:
                    raise control_group
                except ExceptionGroup:
                    fetcher._log(
                        "safe grouped failure",
                        level=logging.ERROR,
                        exc_info=True,
                    )

                records = [
                    json.loads(line)
                    for line in stream.getvalue().splitlines()
                    if line.strip()
                ]
                serialized = json.dumps(records)
                self.assertNotIn(folder_url, serialized)
                self.assertIn(replacement, serialized)
                group_stack = records[0]["exception"][0]
                self.assertEqual(group_stack["exc_type"], "ExceptionGroup")
                self.assertEqual(
                    group_stack["exc_value"],
                    "safe group (2 sub-exceptions)",
                )
                self.assertEqual(
                    group_stack["exceptions"][0][0]["exc_value"],
                    "'safe child'",
                )
                self.assertIn(
                    replacement,
                    group_stack["exceptions"][1][0]["exc_value"],
                )
                self.assertIs(original_group.exceptions[0], safe_child)
                self.assertIs(original_group.exceptions[1], leaking_child)
                self.assertIn(folder_url, str(original_group.exceptions[1]))
            finally:
                logging_setup._reset_for_tests()


if __name__ == "__main__":
    _ = unittest.main()
