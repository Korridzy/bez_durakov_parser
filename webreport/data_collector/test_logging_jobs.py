"""Structured logging tests for correlated data collector jobs."""

import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import structlog

from bd_shared import logging_setup

if TYPE_CHECKING:
    from webreport.data_collector import fetch_pipeline
else:
    import fetch_pipeline


class StubFetcher:
    def __init__(self, files: list[str], download_dir: str = "/tmp/downloads"):
        self.files: list[str] = files
        self.download_dir: str = download_dir

    def fetch(self) -> list[str]:
        return self.files


class RaisingFetcher:
    download_dir: str = "/tmp/downloads"

    def fetch(self) -> list[str]:
        raise RuntimeError("fetch broke")


class LoggingJobTests(unittest.TestCase):
    def __init__(self, methodName: str = "runTest") -> None:
        super().__init__(methodName)
        self.stream = io.StringIO()
        self.folder_url = ""
        self.config: dict[str, str | list[str]] = {}

    def setUp(self):
        logging_setup._reset_for_tests()
        self.stream = io.StringIO()
        logging_setup.configure_logging(
            "test-data-collector", log_format="json", stream=self.stream
        )
        self.folder_url = "https://drive.example.invalid/folders/private-folder"
        self.config = {
            "google_drive_folder_url": self.folder_url,
            "modes": ["browser_selenium"],
        }

    def tearDown(self):
        logging_setup._reset_for_tests()

    def records(self) -> list[dict[str, object]]:
        return [
            json.loads(line)
            for line in self.stream.getvalue().splitlines()
            if line.strip()
        ]

    def run_successfully(self, files: list[str] | None = None) -> list[str]:
        fetched_files = ["a.xlsm"] if files is None else files
        fetcher = StubFetcher(fetched_files)
        with (
            patch.object(fetch_pipeline, "XLSM_FETCH_CONFIG", self.config),
            patch.object(fetch_pipeline, "create_fetcher", return_value=fetcher),
            patch.object(
                fetch_pipeline, "process_downloaded_files", return_value=(1, 1)
            ),
        ):
            return fetch_pipeline.run_fetch()

    def test_run_fetch_emits_correlated_start_and_completion(self):
        self.assertEqual(self.run_successfully(), ["a.xlsm"])

        records = self.records()
        started = [record for record in records if record["event"] == "fetch_started"]
        completed = [
            record for record in records if record["event"] == "fetch_completed"
        ]
        self.assertEqual(len(started), 1)
        self.assertEqual(len(completed), 1)
        self.assertEqual(started[0]["marker"], "Fetch started at")
        self.assertEqual(started[0]["job_name"], "xlsm_fetch")
        self.assertIsNotNone(
            re.fullmatch(r"[0-9a-f]{32}", str(started[0]["job_id"]))
        )
        self.assertEqual(completed[0]["job_id"], started[0]["job_id"])
        self.assertEqual(completed[0]["file_count"], 1)

        start_index = records.index(started[0])
        completion_index = records.index(completed[0])
        for record in records[start_index : completion_index + 1]:
            self.assertEqual(record["job_id"], started[0]["job_id"])

    def test_sequential_runs_use_distinct_ids_and_clear_context(self):
        _ = self.run_successfully()
        _ = self.run_successfully()

        started = [
            record
            for record in self.records()
            if record["event"] == "fetch_started"
        ]
        self.assertEqual(len(started), 2)
        self.assertNotEqual(started[0]["job_id"], started[1]["job_id"])
        self.assertNotIn("job_id", structlog.contextvars.get_contextvars())

    def test_run_fetch_restores_preexisting_context(self):
        with structlog.contextvars.bound_contextvars(
            job_id="outer-job", job_name="outer-name"
        ):
            _ = self.run_successfully()
            context = structlog.contextvars.get_contextvars()
            self.assertEqual(context["job_id"], "outer-job")
            self.assertEqual(context["job_name"], "outer-name")

        self.assertNotIn("job_id", structlog.contextvars.get_contextvars())

    def test_failure_is_logged_twice_and_context_is_cleared(self):
        with (
            patch.object(fetch_pipeline, "XLSM_FETCH_CONFIG", self.config),
            patch.object(
                fetch_pipeline, "create_fetcher", return_value=RaisingFetcher()
            ),
            self.assertRaisesRegex(RuntimeError, "fetch broke"),
        ):
            _ = fetch_pipeline.run_fetch()

        records = self.records()
        started = next(record for record in records if record["event"] == "fetch_started")
        for event in ("fetch_method_failed", "fetch_failed"):
            record = next(record for record in records if record["event"] == event)
            self.assertEqual(record["level"], "error")
            self.assertIn("exception", record)
            self.assertEqual(record["job_id"], started["job_id"])
        self.assertNotIn("job_id", structlog.contextvars.get_contextvars())

    def test_folder_url_is_never_logged(self):
        _ = self.run_successfully()
        self.assertNotIn(self.folder_url, json.dumps(self.records()))

    def test_process_downloaded_files_emits_per_file_results_and_totals(self):
        with tempfile.TemporaryDirectory() as directory:
            file_names = ["saved.xlsm", "unsaved.xlsm", "unparsed.xlsm"]
            for file_name in file_names:
                (Path(directory) / file_name).touch()

            with (
                patch.object(fetch_pipeline, "initialize_database", return_value=object()),
                patch.object(
                    fetch_pipeline.BdGame,
                    "parse_from_file",
                    side_effect=[True, True, False],
                ),
                patch.object(
                    fetch_pipeline,
                    "save_game_to_database",
                    side_effect=[True, False],
                ),
            ):
                result = fetch_pipeline.process_downloaded_files(file_names, directory)

        self.assertEqual(result, (2, 1))
        records = self.records()
        processed = [
            record
            for record in records
            if record["event"] == "downloaded_file_processed"
        ]
        self.assertEqual(
            [
                (record["file_name"], record["parsed"], record["saved"])
                for record in processed
            ],
            [
                ("saved.xlsm", True, True),
                ("unsaved.xlsm", True, False),
                ("unparsed.xlsm", False, False),
            ],
        )
        summary = next(
            record
            for record in records
            if record["event"] == "downloaded_files_processed"
        )
        self.assertEqual(
            (summary["files"], summary["parsed"], summary["saved"]), (3, 2, 1)
        )
        parse_failures = next(
            record
            for record in records
            if record["event"] == "downloaded_files_parse_failures"
        )
        save_failures = next(
            record
            for record in records
            if record["event"] == "downloaded_files_save_failures"
        )
        self.assertEqual(parse_failures["count"], 1)
        self.assertEqual(save_failures["count"], 1)

    def test_empty_fetch_is_successful_and_not_processed(self):
        fetcher = StubFetcher([])
        with (
            patch.object(fetch_pipeline, "XLSM_FETCH_CONFIG", self.config),
            patch.object(fetch_pipeline, "create_fetcher", return_value=fetcher),
            patch.object(fetch_pipeline, "process_downloaded_files") as process_files,
        ):
            self.assertEqual(fetch_pipeline.run_fetch(), [])

        process_files.assert_not_called()
        records = self.records()
        self.assertEqual(
            len([record for record in records if record["event"] == "no_new_files"]),
            1,
        )
        completed = next(
            record for record in records if record["event"] == "fetch_completed"
        )
        self.assertEqual(completed["file_count"], 0)

    def test_no_files_to_process_emits_event(self):
        self.assertEqual(fetch_pipeline.process_downloaded_files([], "/tmp"), (0, 0))
        self.assertEqual([record["event"] for record in self.records()], ["no_files_to_process"])

    def test_missing_download_directory_emits_event(self):
        self.assertEqual(fetch_pipeline.process_downloaded_files(["a.xlsm"], None), (0, 0))
        records = self.records()
        self.assertEqual([record["event"] for record in records], ["download_dir_missing"])
        self.assertEqual(records[0]["level"], "error")

    def test_unavailable_database_emits_event(self):
        with patch.object(fetch_pipeline, "initialize_database", return_value=None):
            self.assertEqual(
                fetch_pipeline.process_downloaded_files(["a.xlsm"], "/tmp"),
                (0, 0),
            )
        records = self.records()
        self.assertEqual([record["event"] for record in records], ["database_unavailable"])
        self.assertEqual(records[0]["level"], "error")

    def test_missing_file_emits_missing_and_processed_events(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(fetch_pipeline, "initialize_database", return_value=object()),
        ):
            self.assertEqual(
                fetch_pipeline.process_downloaded_files(["missing.xlsm"], directory),
                (0, 0),
            )

        records = self.records()
        missing = next(
            record
            for record in records
            if record["event"] == "downloaded_file_missing"
        )
        processed = next(
            record
            for record in records
            if record["event"] == "downloaded_file_processed"
        )
        self.assertEqual(missing["file_name"], "missing.xlsm")
        self.assertEqual(
            (processed["file_name"], processed["parsed"], processed["saved"]),
            ("missing.xlsm", False, False),
        )


if __name__ == "__main__":
    _ = unittest.main(verbosity=2)
