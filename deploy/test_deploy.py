"""Executor contract tests: subprocess and network boundaries never reach Docker or GitHub."""

import contextlib
from collections.abc import Callable
import datetime
from dataclasses import replace
import errno
import fcntl
import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import shlex
import subprocess
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import uuid
from email.message import Message
from pathlib import Path
from typing import Any
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import deploy.deploy as d  # noqa: E402
import deploy.sqlite_backup as sqlite_backup  # noqa: E402
from deploy import release_metadata as rm  # noqa: E402

COMMIT = "a" * 40
TAG = "v1.2.3"
REVISION = "b1c2d3e4f5g6"
API = f"https://api.github.com/repos/{rm.DEFAULT_REPOSITORY}/releases/tags/{TAG}"
ASSET = f"https://github.com/{rm.DEFAULT_REPOSITORY}/releases/download/{TAG}/{rm.ASSET_NAME}"
INFRA = {"mysql": "mysql@sha256:" + "4" * 64, "litellm": "ghcr.io/berriai/litellm@sha256:" + "5" * 64}


def metadata_bytes() -> bytes:
    return rm.dumps(rm.ReleaseMetadata(
        schema_version=1, version=TAG, source_commit=COMMIT, ci_run_id=7,
        ci_run_attempt=1, built_from_candidate_tag="sha-" + COMMIT,
        images={name: ref + "@sha256:" + str(i) * 64
                for i, (name, ref) in enumerate(rm.IMAGE_REPOSITORIES.items(), 1)},
        alembic_revision=REVISION,
    ))


def release(data: bytes) -> dict[str, Any]:
    return {"tag_name": TAG, "draft": False, "prerelease": False,
            "body": rm.format_marker(rm.sha256_hex(data)),
            "assets": [{"name": rm.ASSET_NAME, "browser_download_url": ASSET}]}


class FakeFetcher:
    def __init__(self, payload: dict[str, Any], data: bytes):
        self.responses: dict[str, bytes | Exception] = {API: json.dumps(payload).encode(), ASSET: data}
        self.calls = []

    def fetch(self, url, *, limit, timeout):
        self.calls.append((url, limit, timeout))
        result = self.responses[url]
        if isinstance(result, BaseException):
            raise result
        if len(result) > limit:
            raise d.DeployError(16, "response exceeds size limit")
        return result


class FakeRunner:
    def __init__(self):
        self.calls = []
        self.commit = COMMIT
        self.label = COMMIT
        self.heads = REVISION + " (head)\n"
        self.db = REVISION + "\n"
        self.db_error = ""
        self.fail_pull = False
        self.compose = json.dumps({"services": {name: {"image": ref} for name, ref in INFRA.items()}})

    def run(self, argv, *, cwd, env, input=None, timeout=120):
        self.calls.append((list(argv), cwd, dict(env), input, timeout))
        output = ""
        code = 0
        stderr = ""
        if argv[:2] == ["git", "rev-parse"]:
            output = self.commit
        elif argv[:2] == ["git", "show"]:
            output = "services:\n  mysql:\n    image: tag-file\n"
        elif argv[:3] == ["docker", "compose", "--project-directory"] and "config" in argv:
            output = self.compose
        elif argv[:3] == ["docker", "image", "inspect"]:
            output = json.dumps({"Config": {"Labels": {"org.opencontainers.image.revision": self.label}}})
        elif argv[:2] == ["docker", "pull"]:
            code = int(self.fail_pull)
            stderr = "sensitive-command-output"
        elif argv[0] == "make":
            output = self.heads
        elif "SELECT version_num FROM alembic_version" in argv:
            output, stderr = self.db, self.db_error
            code = int(bool(stderr))
        else:
            if argv[:2] != ["git", "fetch"]:
                raise AssertionError(f"Unexpected command: {argv}")
        return subprocess.CompletedProcess(argv, code, output, stderr)


class ExecutorTest(unittest.TestCase):
    def __init__(self, methodName="runTest"):
        super().__init__(methodName)
        self.temp = tempfile.TemporaryDirectory(prefix="bdvrd-t11-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "webreport").mkdir()
        self.env = {"BD_DEPLOY_STATE_DIR": str(self.root / "state"), "COMPOSE_PROJECT_NAME": "bdvrd-t11"}
        self.data = metadata_bytes()
        self.payload: dict[str, Any] = release(self.data)
        self.runner = FakeRunner()
        self.fetcher = FakeFetcher(self.payload, self.data)

    def invoke(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = d.main(args, root=self.root, env=self.env, runner=self.runner, fetcher=self.fetcher)
        return code, out.getvalue(), err.getvalue()

    def select(self):
        self.fetcher.responses[API] = json.dumps(self.payload).encode()
        return self.invoke(["select", TAG])

    def assertFailure(self, expected, result):
        code, out, err = result
        self.assertEqual(code, expected, (out, err))
        self.assertEqual(out, "")
        self.assertEqual(len(err.splitlines()), 1)
        obj = json.loads(err)
        self.assertEqual(set(obj), {"exit_code", "error", "message"})
        self.assertEqual(obj["exit_code"], expected)
        self.assertTrue(obj["error"].startswith("E_"))
        self.assertNotIn("sensitive-command-output", err)
        return obj

    def test_valid_release_renders_five_digest_pins_from_tag_not_worktree(self):
        # Given a hostile current file, selection must use git show of the release tag.
        (self.root / "webreport" / "docker-compose.yml").write_text("dirty current compose")
        code, out, err = self.select()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(rm.loads(out.encode()), rm.loads(self.data))
        target = self.root / "state" / "releases" / TAG
        pins = json.loads((target / "compose.release.yml").read_text())["services"]
        self.assertEqual({name: value["image"] for name, value in pins.items()}, INFRA | rm.loads(self.data).images)
        self.assertEqual((target / "metadata.json").read_bytes(), self.data)
        self.assertIn(["git", "show", f"{TAG}:webreport/docker-compose.yml"], [c[0] for c in self.runner.calls])
        config = next(c for c in self.runner.calls if "config" in c[0])
        self.assertIn("tag-file", config[3])
        self.assertEqual(config[2]["COMPOSE_PROJECT_NAME"], "bdvrd-t11")
        self.assertTrue(all(c[4] > 0 for c in self.runner.calls))
        self.assertEqual(len(list((self.root / "state" / "logs").glob("*.log"))), 1)

    def test_404_returns_release_not_found(self):
        self.fetcher.responses[API] = urllib.error.HTTPError(API, 404, "secret", Message(), None)
        self.assertFailure(10, self.invoke(["select", TAG]))

    def test_draft_and_prerelease_return_11(self):
        for field in ("draft", "prerelease"):
            with self.subTest(field=field):
                self.payload = release(self.data) | {field: True}
                self.assertFailure(11, self.select())

    def test_two_assets_return_12(self):
        self.payload["assets"] *= 2
        self.assertFailure(12, self.select())

    def test_marker_mismatch_returns_13(self):
        self.payload["body"] = rm.format_marker("0" * 64)
        self.assertFailure(13, self.select())

    def test_missing_or_duplicate_marker_returns_13(self):
        for body in ("", self.payload["body"] + "\n" + self.payload["body"]):
            with self.subTest(body=body):
                self.payload["body"] = body
                self.assertFailure(13, self.select())

    def test_schema_and_hostile_asset_bytes_return_14(self):
        for raw in (b'{"schema_version":2}', b'{"schema_version":1,"schema_version":1}', b"\xff",
                    b"[" * 2000, b'{"version":"\\ud800"}'):
            with self.subTest(raw=raw[:40]):
                self.payload = release(raw)
                self.fetcher.responses[ASSET] = raw
                self.assertFailure(14, self.select())

    def test_tag_commit_mismatch_returns_15_before_pull(self):
        self.runner.commit = "b" * 40
        self.assertFailure(15, self.select())
        self.assertFalse(any(c[0][:2] == ["docker", "pull"] for c in self.runner.calls))

    def test_metadata_version_and_repository_must_match_requested_release(self):
        for changes in ({"version": "v9.9.9"}, {"repository": "other/project"}):
            with self.subTest(changes=changes):
                raw = json.dumps(json.loads(self.data) | changes).encode()
                self.payload, self.fetcher.responses[ASSET] = release(raw), raw
                self.assertFailure(15, self.select())

    def test_cached_metadata_byte_difference_returns_22_without_overwriting(self):
        cache = self.root / "state" / "releases" / TAG / "metadata.json"
        cache.parent.mkdir(parents=True)
        previous = self.data + b" "
        cache.write_bytes(previous)
        self.assertFailure(22, self.select())
        self.assertEqual(cache.read_bytes(), previous)
        self.assertFalse(any(c[0][:2] == ["docker", "pull"] for c in self.runner.calls))

    def test_identical_cache_is_revalidated_successfully(self):
        self.assertEqual(self.select()[0], 0)
        self.assertEqual(self.select()[0], 0)
        self.assertEqual(len([c for c in self.runner.calls if c[0][:2] == ["docker", "pull"]]), 6)

    def test_label_mismatch_returns_19(self):
        self.runner.label = "b" * 40
        self.assertFailure(19, self.select())

    def test_pull_failure_returns_18_not_success_text(self):
        self.runner.fail_pull = True
        self.assertFailure(18, self.select())

    def test_wrong_multiple_or_misleading_heads_return_21(self):
        for heads in ("other (head)\n", REVISION + " (head)\nother (head)\n", "OK\n", "", REVISION + " (head)\nOK\n"):
            with self.subTest(heads=heads):
                self.runner.heads = heads
                self.assertFailure(21, self.select())
        self.assertFalse((self.root / "state" / "releases" / TAG / "metadata.json").exists())

    def test_compose_missing_or_floating_infra_digest_returns_17(self):
        for config in ("{}", '{"services":{"mysql":{"image":"mysql:8.0"}}}', "not-json"):
            with self.subTest(config=config):
                self.runner.compose = config
                self.assertFailure(17, self.select())

    def test_lock_held_returns_3_without_network_or_commands(self):
        state = self.root / "state"
        state.mkdir()
        with (state / "lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertFailure(3, self.select())
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(self.fetcher.calls, [])

    def test_inherited_lock_skips_reacquisition(self):
        state = self.root / "state"
        state.mkdir()
        with (state / "lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.env["BD_DEPLOY_LOCK_FD"] = str(lock.fileno())
            self.assertEqual(self.select()[0], 0)

    def test_local_release_file_allows_file_asset_and_announces_override(self):
        asset = self.root / "release-metadata.json"
        asset.write_bytes(self.data)
        self.payload["assets"][0]["browser_download_url"] = asset.as_uri()
        local = self.root / "release.json"
        local.write_text(json.dumps(self.payload))
        self.env["BD_DEPLOY_RELEASE_FILE"] = str(local)
        with mock.patch.dict(os.environ, self.env, clear=True):
            code, out, err = self.invoke_with_real_fetcher(["select", TAG])
        self.assertEqual(code, 0, err)
        self.assertEqual(rm.loads(out.encode()), rm.loads(self.data))
        self.assertIn("BD_DEPLOY_RELEASE_FILE", err)
        self.assertEqual(self.fetcher.calls, [])

    def invoke_with_real_fetcher(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = d.main(args, root=self.root, env=self.env, runner=self.runner)
        return code, out.getvalue(), err.getvalue()

    def test_invalid_tag_and_parser_errors_return_2_without_reflecting_secrets(self):
        for args in (["select", "not-a-tag"], ["select", "../../secret"], ["select"], ["unknown-secret"],
                     ["rollback", TAG, "--restore-backup"], ["deploy", "v01.0.0"]):
            with self.subTest(args=args):
                obj = self.assertFailure(2, self.invoke(args))
                self.assertNotIn("secret", obj["message"])
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(self.fetcher.calls, [])

    def test_help_lists_all_seven_subcommands(self):
        code, out, err = self.invoke(["--help"])
        self.assertEqual((code, err), (0, ""))
        for name in ("deploy", "rollback", "resolve-rollback-target", "status", "verify-db-isolation", "smoke", "select"):
            self.assertIn(name, out)

    def test_dataset_deploy_and_rollback_exit_2_before_network(self):
        self.env["DATASET"] = "ikar"
        for name in ("deploy", "rollback"):
            self.assertFailure(2, self.invoke([name, TAG]))
        self.assertEqual(self.fetcher.calls, [])
        self.assertEqual(self.runner.calls, [])

    def test_dirty_marker_refuses_deploy_and_image_only_rollback_first(self):
        state = d.State(self.root, self.env)
        state.initialize()
        state.write_current({"stage": "migration_started"})
        for args in (["deploy", TAG], ["rollback", TAG]):
            self.assertFailure(41, self.invoke(args))
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(self.fetcher.calls, [])
        self.assertFailure(40, self.invoke(["rollback", TAG, "--restore-backup", "backup-id"]))

    def test_resolve_explicit_tag_and_no_target(self):
        self.assertEqual(self.invoke(["resolve-rollback-target", TAG]), (0, TAG + "\n", ""))
        self.assertFailure(2, self.invoke(["resolve-rollback-target"]))

    def test_malformed_release_json_is_structured(self):
        for raw in (b"\xff", b"[]", b'{"draft":false,"draft":true}', b"[" * 2000, b'{"draft":NaN}'):
            with self.subTest(raw=raw[:40]):
                self.fetcher.responses[API] = raw
                self.assertFailure(24, self.invoke(["select", TAG]))

    def test_malformed_release_shape_is_structured(self):
        for changes in ({"draft": "false"}, {"prerelease": 0}, {"body": []}, {"assets": [None]},
                        {"assets": "huge"}, {"tag_name": "v9.9.9"}):
            with self.subTest(changes=changes):
                self.payload = release(self.data) | changes
                self.assertFailure(24, self.select())

    def test_network_timeouts_have_structured_errors(self):
        self.fetcher.responses[API] = TimeoutError("secret")
        self.assertFailure(16, self.invoke(["select", TAG]))

    def test_subprocess_timeout_is_structured_and_secret_free(self):
        with mock.patch.object(self.runner, "run", side_effect=subprocess.TimeoutExpired("secret", 120)):
            self.assertFailure(15, self.select())

    def test_huge_release_response_is_bounded(self):
        self.fetcher.responses[API] = b"x" * (1024 * 1024 + 1)
        self.assertFailure(16, self.invoke(["select", TAG]))
        self.assertEqual(self.fetcher.calls[-1][1], 1024 * 1024)

    def test_huge_metadata_asset_is_bounded_before_parsing(self):
        self.fetcher.responses[ASSET] = b"x" * 65537
        self.assertFailure(16, self.select())
        self.assertEqual(self.fetcher.calls[-1][1], 65536)

    def test_remote_release_cannot_read_local_files_or_credential_urls(self):
        for url in ("file:///secret", "http://127.0.0.1/secret", "https://user:secret@github.com/asset",
                    "https://untrusted.invalid/asset"):
            with self.subTest(url=url):
                self.payload["assets"][0]["browser_download_url"] = url
                self.assertFailure(16, self.select())

    def test_mysql_revision_names_database_and_never_emits_password(self):
        (self.root / "webreport" / ".env.mysql").write_text("MYSQL_ROOT_PASSWORD=test-password\nMYSQL_DATABASE=games\n")
        executor = d.Executor(self.root, self.env, self.runner, self.fetcher)
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(executor.live_db_revision(), REVISION)
        argv, _, child_env, _, _ = self.runner.calls[-1]
        self.assertTrue(all("test-password" not in arg for arg in argv))
        self.assertEqual(argv[argv.index("exec") + 1:argv.index("exec") + 4], ["-T", "-e", "MYSQL_PWD"])
        self.assertEqual(child_env["MYSQL_PWD"], "test-password")
        self.assertEqual(child_env["COMPOSE_PROJECT_NAME"], "bdvrd-t11")
        self.assertNotIn("MYSQL_PWD", executor.env)
        self.assertEqual(argv[-1], "games")
        self.assertIn("SELECT version_num FROM alembic_version", argv)
        self.assertNotIn("alembic", argv)
        self.assertEqual(out.getvalue() + err.getvalue(), "")

    def test_mysql_failure_and_timeout_keep_password_out_of_cli_output_and_logs(self):
        password = "failure-password-not-a-secret"
        (self.root / "webreport" / ".env.mysql").write_text(
            f"MYSQL_ROOT_PASSWORD={password}\nMYSQL_DATABASE=games\n")
        self.runner.db_error = f"ERROR 1045: {password}"
        self.runner.db = f"plausible-success {password}\n"
        cases = (contextlib.nullcontext(), mock.patch.object(
            self.runner, "run", side_effect=subprocess.TimeoutExpired(password, 120, output=password, stderr=password)))
        for case in cases:
            with self.subTest(case=type(case).__name__), case, mock.patch.object(
                d.Executor, "select", autospec=True, side_effect=lambda executor, tag: executor.live_db_revision()
            ):
                result = self.invoke(["select", TAG])
            self.assertFailure(31, result)
            self.assertNotIn(password, result[1] + result[2])
        for argv, _, child_env, _, _ in self.runner.calls:
            self.assertTrue(all(password not in arg for arg in argv))
            self.assertEqual(child_env["MYSQL_PWD"], password)
        logs = list((self.root / "state" / "logs").glob("*.log"))
        self.assertEqual(len(logs), 2)
        for path in logs:
            logged = path.read_text()
            self.assertNotIn(password, logged)
            self.assertEqual(json.loads(logged)["exit_code"], 31)

    def test_mysql_dump_and_restore_share_env_only_credentials_and_stdin(self):
        password = "helper-password-not-a-secret"
        (self.root / "webreport" / ".env.mysql").write_text(
            f"MYSQL_ROOT_PASSWORD={password}\nMYSQL_DATABASE=games\n")
        executor = d.Executor(self.root, self.env, self.runner, self.fetcher)
        for client, arguments, stdin in (("mysqldump", ["--single-transaction", "--databases"], None),
                                         ("mysql", [], "restore-fixture")):
            with self.subTest(client=client), mock.patch.object(
                self.runner, "run", return_value=subprocess.CompletedProcess([], 0, "", "")
            ) as run:
                executor.mysql_command(client, arguments, input=stdin, timeout=180)
                call = run.call_args
                argv = call.args[0]
                self.assertTrue(all(password not in arg for arg in argv))
                self.assertEqual(argv[argv.index("exec") + 1:],
                                 ["-T", "-e", "MYSQL_PWD", "mysql", client, "-uroot", *arguments, "games"])
                self.assertEqual(call.kwargs["env"]["MYSQL_PWD"], password)
                self.assertEqual(call.kwargs["env"]["COMPOSE_PROJECT_NAME"], "bdvrd-t11")
                self.assertEqual(call.kwargs["input"], stdin)
                self.assertEqual(call.kwargs["timeout"], 180)
        self.assertNotIn("MYSQL_PWD", executor.env)

    def test_unversioned_database_empty_and_missing_table_return_none(self):
        (self.root / "webreport" / ".env.mysql").write_text("MYSQL_ROOT_PASSWORD=test-password\nMYSQL_DATABASE=games\n")
        self.runner.db = ""
        executor = d.Executor(self.root, self.env, self.runner, self.fetcher)
        self.assertIsNone(executor.live_db_revision())
        self.runner.db_error = "ERROR 1146 (42S02): Table 'games.alembic_version' doesn't exist"
        self.assertIsNone(executor.live_db_revision())
        self.runner.db_error = "ERROR 1045: sensitive-command-output"
        with self.assertRaises(d.DeployError) as caught:
            executor.live_db_revision()
        self.assertEqual(caught.exception.exit_code, 31)
        self.assertNotIn("sensitive", caught.exception.message)

    def test_state_layout_atomic_current_and_append_only_history(self):
        state = d.State(self.root, {"BD_VM_DIR": str(self.root / "vm")})
        state.initialize()
        self.assertEqual(state.path, self.root / "vm" / "deploy")
        self.assertTrue((state.path / "backups").is_dir())
        state.write_current({"last_successful": {"tag": TAG}})
        state.append_history({"event": "started", "tag": TAG})
        before = (state.path / "history.jsonl").read_bytes()
        state.append_history({"event": "success", "tag": TAG})
        self.assertTrue((state.path / "history.jsonl").read_bytes().startswith(before))
        self.assertEqual(state.read_current(), {"last_successful": {"tag": TAG}})
        self.assertEqual(list(state.path.glob("*.tmp")), [])
        self.assertEqual((state.path / "current.json").stat().st_mode & 0o777, 0o600)


class StatusTest(unittest.TestCase):
    """Read-only report: no lock, no log, no directory creation, no secrets."""

    def __init__(self, methodName="runTest"):
        super().__init__(methodName)
        self.temp = tempfile.TemporaryDirectory(prefix="bdvrd-t20-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "state"
        self.env = {"BD_DEPLOY_STATE_DIR": str(self.state), "MYSQL_ROOT_PASSWORD": "env-secret-value"}

    def invoke(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = d.main(args, root=self.root, env=self.env)
        return code, out.getvalue(), err.getvalue()

    def snapshot(self):
        if not self.state.exists():
            return None
        return {p.relative_to(self.state).as_posix(): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
                for p in sorted(self.state.rglob("*"))}

    def assertStateError(self, result, message_part):
        code, out, err = result
        self.assertEqual((code, out), (23, ""), (out, err))
        self.assertEqual(len(err.splitlines()), 1)
        obj = json.loads(err)
        self.assertEqual(obj["exit_code"], 23)
        self.assertEqual(obj["error"], "E_STATE")
        self.assertIn(message_part, obj["message"])
        self.assertNotIn("Traceback", err)
        return obj

    def populate(self):
        self.state.mkdir()
        for name in ("releases", "backups", "logs"):
            (self.state / name).mkdir()
        outcome = {"attempt_id": "a-2", "tag": "v1.10.0", "commit": COMMIT, "kind": "deploy",
                   "finished_at": "2026-10-02T09:00:00+00:00"}
        (self.state / "current.json").write_text(json.dumps({
            "last_successful": {**outcome, "db_revision_after": REVISION, "future_key": "extra-secret"},
            "unaudited": [outcome], "future_top_level": {"token": "extra-secret"}}) + "\n")
        events: list[dict[str, Any]] = [{"event": "started" if i % 2 == 0 else "success", "tag": f"v1.0.{i}", "kind": "deploy",
                   "at": f"2026-09-{i + 1:02d}T10:00:00+00:00", "digests": {"backend": "x"}} for i in range(12)]
        events[11] = {"event": "failed", "tag": "v1.0.11", "kind": "rollback", "at": "2026-09-12T10:00:00+00:00",
                      "exit_code": 38, "step": "S3", "note": "extra-secret"}
        (self.state / "history.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
        for ident, revision, created in (("20261001T100000000000Z-v1.9.0", "aaa111", "2026-10-01T10:00:00+00:00"),
                                         ("20261002T090000000000Z-v1.10.0", None, "2026-10-02T09:00:00+00:00")):
            folder = self.state / "backups" / ident
            folder.mkdir()
            (folder / "manifest.json").write_text(json.dumps({
                "tag": ident.split("-")[-1], "created_at": created, "db_revision_before": revision,
                "files": {"mysql.sql": {"sha256": "0" * 64}}, "dataset": ""}))
        for tag in ("v1.9.0", "v1.10.0", "v1.2.3"):
            (self.state / "releases" / tag).mkdir()
        (self.state / "releases" / "not-a-tag").mkdir()

    def test_missing_state_dir_is_a_clean_first_install_and_creates_nothing(self):
        code, out, err = self.invoke(["status"])
        self.assertEqual((code, err), (0, ""))
        self.assertIn("first-install", out)
        self.assertFalse(self.state.exists())
        code, out, err = self.invoke(["status", "--json"])
        self.assertEqual((code, err), (0, ""))
        report = json.loads(out)
        self.assertEqual((report["initialized"], report["state_dir"]), (False, str(self.state)))
        self.assertEqual((report["last_successful"], report["history"], report["backups"], report["releases"]),
                         (None, [], [], []))
        self.assertFalse(self.state.exists())

    def test_empty_initialized_state_reports_nothing_deployed_yet(self):
        d.State(self.root, self.env).initialize()
        before = self.snapshot()
        code, out, err = self.invoke(["status", "--json"])
        self.assertEqual((code, err), (0, ""))
        report = json.loads(out)
        self.assertEqual((report["initialized"], report["last_successful"], report["attempt"], report["dirty"],
                          report["unaudited"], report["history_total"]), (True, None, None, False, 0, 0))
        self.assertEqual(self.snapshot(), before)

    def test_healthy_state_json_reports_every_section(self):
        self.populate()
        code, out, err = self.invoke(["status", "--json"])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.count("\n"), 1)
        report = json.loads(out)
        self.assertEqual(report["last_successful"], {
            "tag": "v1.10.0", "commit": COMMIT, "db_revision_after": REVISION,
            "finished_at": "2026-10-02T09:00:00+00:00"})
        self.assertEqual((report["attempt"], report["stage"], report["dirty"], report["unaudited"]),
                         (None, None, False, 1))
        self.assertEqual(report["history_total"], 12)
        self.assertEqual([e["tag"] for e in report["history"]], [f"v1.0.{i}" for i in range(2, 12)])
        self.assertEqual(report["history"][-1], {"tag": "v1.0.11", "kind": "rollback", "event": "failed",
                                                 "at": "2026-09-12T10:00:00+00:00", "exit_code": 38, "step": "S3"})
        self.assertEqual(report["history"][0]["exit_code"], None)
        self.assertEqual([b["id"] for b in report["backups"]],
                         ["20261002T090000000000Z-v1.10.0", "20261001T100000000000Z-v1.9.0"])
        self.assertEqual([b["db_revision_before"] for b in report["backups"]], [None, "aaa111"])
        self.assertTrue(all(isinstance(b["age_seconds"], int) and b["age_seconds"] >= 0 for b in report["backups"]))
        self.assertEqual(report["releases"], ["v1.10.0", "v1.9.0", "v1.2.3"])

    def test_text_report_is_readable_and_never_echoes_unknown_keys_or_environment(self):
        self.populate()
        code, out, err = self.invoke(["status"])
        self.assertEqual((code, err), (0, ""))
        for expected in (str(self.state), "Last successful: v1.10.0", COMMIT, REVISION, "Unaudited outcomes: 1",
                         "last 10 of 12", "v1.0.11 rollback failed exit_code=38 step=S3",
                         "20261001T100000000000Z-v1.9.0 db_revision_before=aaa111",
                         "20261002T090000000000Z-v1.10.0 db_revision_before=none",
                         "Cached releases: v1.10.0, v1.9.0, v1.2.3"):
            self.assertIn(expected, out)
        self.assertNotIn("v1.0.1 ", out)
        for secret in ("extra-secret", "env-secret-value"):
            self.assertNotIn(secret, out + err)

    def test_backup_age_is_computed_from_the_manifest_timestamp(self):
        self.populate()
        now = datetime.datetime(2026, 10, 3, 12, 30, tzinfo=datetime.timezone.utc)
        report = d.collect_status(d.State(self.root, self.env), now)
        self.assertEqual([b["age_seconds"] for b in report["backups"]], [86400 + 3 * 3600 + 1800, 2 * 86400 + 2 * 3600 + 1800])
        self.assertEqual(d.format_age(2 * 86400 + 2 * 3600 + 1800), "2d 2h")
        self.assertEqual(d.format_age(3 * 3600 + 120), "3h 2m")
        self.assertEqual(d.format_age(59), "0m")
        future = d.collect_status(d.State(self.root, self.env), now - datetime.timedelta(days=30))
        self.assertEqual([b["age_seconds"] for b in future["backups"]], [0, 0])

    def test_dirty_marker_and_current_attempt_are_visible(self):
        self.populate()
        current: dict[str, Any] = json.loads((self.state / "current.json").read_text())
        current["stage"] = "migration_started"
        current["attempt"] = {"tag": "v1.11.0", "commit": COMMIT, "attempt_id": "a-3",
                              "started_at": "2026-10-03T08:00:00+00:00"}
        (self.state / "current.json").write_text(json.dumps(current))
        report = json.loads(self.invoke(["status", "--json"])[1])
        self.assertEqual((report["stage"], report["dirty"]), ("migration_started", True))
        self.assertEqual(report["attempt"], {"tag": "v1.11.0", "commit": COMMIT, "attempt_id": "a-3",
                                             "started_at": "2026-10-03T08:00:00+00:00"})
        code, out, err = self.invoke(["status"])
        self.assertEqual((code, err), (0, ""))
        self.assertIn("DIRTY", out)
        self.assertIn("migration_started", out)
        self.assertIn("Current attempt: v1.11.0", out)

    def test_incomplete_backup_folder_is_listed_and_unrelated_names_are_ignored(self):
        self.populate()
        (self.state / "backups" / "20261003T000000000000Z-v1.11.0").mkdir()
        (self.state / "backups" / "stray").mkdir()
        (self.state / "backups" / "20261003T000000000000Z-v1.12.0").symlink_to(self.root)
        report = json.loads(self.invoke(["status", "--json"])[1])
        self.assertEqual(report["backups"][0]["id"], "20261003T000000000000Z-v1.11.0")
        self.assertEqual((report["backups"][0]["complete"], report["backups"][0]["age_seconds"]), (False, None))
        self.assertEqual(len(report["backups"]), 3)

    def test_corrupt_current_json_is_a_structured_state_error_without_mutation(self):
        self.populate()
        for raw in (b"{", b"[]", b'{"last_successful":{"tag":"nope"}}', b'{"stage":"other"}',
                    b'{"unaudited":"x"}', b'{"a":1,"a":2}', b"\xff", b"x" * (d.RELEASE_MAX_BYTES + 1)):
            with self.subTest(raw=raw[:30]):
                (self.state / "current.json").write_bytes(raw)
                before = self.snapshot()
                for args in (["status"], ["status", "--json"]):
                    self.assertStateError(self.invoke(args), "deployment")
                self.assertEqual(self.snapshot(), before)

    def test_corrupt_history_line_is_a_structured_state_error_without_mutation(self):
        self.populate()
        history = self.state / "history.jsonl"
        for line in (b"{broken\n", b"[]\n", b"\n", b'{"event":"success"'):
            with self.subTest(line=line):
                history.write_bytes(history.read_bytes().split(b"\n")[0] + b"\n" + line)
                before = self.snapshot()
                self.assertStateError(self.invoke(["status"]), "history")
                self.assertEqual(self.snapshot(), before)

    def test_corrupt_backup_manifest_is_a_structured_state_error_without_mutation(self):
        self.populate()
        manifest = self.state / "backups" / "20261001T100000000000Z-v1.9.0" / "manifest.json"
        for raw in (b"{", b"[]", b'{"created_at":"yesterday","db_revision_before":null}',
                    b'{"created_at":"2026-10-01T10:00:00","db_revision_before":null}',
                    b'{"created_at":"2026-10-01T10:00:00+00:00","db_revision_before":7}'):
            with self.subTest(raw=raw):
                manifest.write_bytes(raw)
                before = self.snapshot()
                obj = self.assertStateError(self.invoke(["status", "--json"]), "backup manifest")
                self.assertIn("20261001T100000000000Z-v1.9.0", obj["message"])
                self.assertEqual(self.snapshot(), before)

    def test_backup_manifest_header_follows_the_executor_rules_in_both_output_modes(self):
        self.populate()
        ident = "20261001T100000000000Z-v1.9.0"
        manifest = self.state / "backups" / ident / "manifest.json"
        good: dict[str, Any] = {"tag": "v1.9.0", "created_at": "2026-10-01T10:00:00+00:00", "db_revision_before": "aaa111"}
        bad = [{**good, "db_revision_before": "not a revision"}, {**good, "db_revision_before": ""},
               {**good, "db_revision_before": "r" * 33}, {**good, "db_revision_before": 7},
               {**good, "tag": "not-a-tag"}, {**good, "tag": "v01.0.0"}, {**good, "tag": 5}, {**good, "tag": None},
               {k: v for k, v in good.items() if k != "tag"}, {k: v for k, v in good.items() if k != "created_at"},
               {**good, "created_at": 5}, {**good, "created_at": "2026-10-01T10:00:00"},
               {**good, "created_at": "yesterday"}, {}]
        for obj in bad:
            for args in (["status"], ["status", "--json"]):
                with self.subTest(manifest=obj, args=args):
                    manifest.write_text(json.dumps(obj))
                    before = self.snapshot()
                    error = self.assertStateError(self.invoke(args), "backup manifest")
                    self.assertIn(ident, error["message"])
                    self.assertEqual(self.snapshot(), before)
        for obj in (good, {**good, "db_revision_before": None}, {**good, "extra": ["kept", "out"]}):
            with self.subTest(accepted=obj):
                manifest.write_text(json.dumps(obj))
                self.assertEqual(self.invoke(["status", "--json"])[0], 0)

    def test_every_manifest_header_the_status_accepts_is_accepted_by_the_executor(self):
        self.populate()
        executor = d.Executor(self.root, self.env, mock.Mock(), mock.Mock())
        manifest = self.state / "backups" / "20261001T100000000000Z-v1.9.0" / "manifest.json"
        for revision in ("aaa111", None, "b1c2d3e4f5g6", "not a revision", "r" * 33):
            with self.subTest(revision=revision):
                manifest.write_text(json.dumps({"tag": "v1.9.0", "created_at": "2026-10-01T10:00:00+00:00",
                                                "db_revision_before": revision, "dataset": ""}))
                status_ok = self.invoke(["status", "--json"])[0] == 0
                try:
                    executor.backup_manifest("20261001T100000000000Z-v1.9.0")
                    executor_ok = True
                except d.DeployError:
                    executor_ok = False
                self.assertEqual(status_ok, executor_ok)

    def test_backup_folder_name_with_an_invalid_label_is_a_state_error(self):
        self.populate()
        (self.state / "backups" / "20261003T000000000000Z-v01.0.0").mkdir()
        error = self.assertStateError(self.invoke(["status"]), "backup id")
        self.assertIn("20261003T000000000000Z-v01.0.0", error["message"])

    def test_success_history_events_need_a_valid_tag_like_rollback_target_selection(self):
        self.populate()
        history = self.state / "history.jsonl"
        for event in ({"event": "success", "tag": "not-a-tag"}, {"event": "success", "tag": None},
                      {"event": "success"}, {"event": "success", "tag": 5}):
            with self.subTest(event=event):
                history.write_text(json.dumps({"event": "started", "tag": "v1.0.0"}) + "\n" + json.dumps(event) + "\n")
                before = self.snapshot()
                for args in (["status"], ["status", "--json"]):
                    self.assertStateError(self.invoke(args), "history")
                self.assertEqual(self.snapshot(), before)
        # The executor never reads the tag of a started or failed event, so status does not either.
        history.write_text(json.dumps({"event": "started", "tag": "odd tag"}) + "\n")
        self.assertEqual(self.invoke(["status"])[0], 0)

    def test_status_never_writes_logs_takes_the_lock_or_waits_for_a_running_deploy(self):
        self.populate()
        before = self.snapshot()
        assert before is not None
        with (self.state / "lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            held = self.snapshot()
            for args in (["status"], ["status", "--json"]):
                code, _, err = self.invoke(args)
                self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.snapshot(), held)
        self.assertEqual(list((self.state / "logs").iterdir()), [])
        self.assertEqual(before, {k: v for k, v in (held or {}).items() if k != "lock"})

    def test_status_ignores_an_inherited_lock_descriptor_and_the_dataset_refusal(self):
        self.populate()
        self.env |= {"BD_DEPLOY_LOCK_FD": "9", "DATASET": "ikar"}
        code, out, err = self.invoke(["status", "--json"])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out)["last_successful"]["tag"], "v1.10.0")

    def test_usage_and_help_do_not_create_the_state_dir(self):
        code, out, err = self.invoke(["status", "--bogus-secret"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(err)["error"], "E_USAGE")
        self.assertNotIn("bogus-secret", err)
        code, out, err = self.invoke(["status", "--help"])
        self.assertEqual((code, err), (0, ""))
        self.assertIn("--json", out)
        self.assertFalse(self.state.exists())

    def test_state_path_that_is_a_file_is_a_structured_state_error(self):
        self.state.write_text("not a directory")
        self.assertStateError(self.invoke(["status"]), "not a directory")


class OperationalRunner(FakeRunner):
    """Docker fake with real backup files and configurable operational failures."""

    def __init__(self):
        super().__init__()
        self.containers = {name: name + "-id" for name in (*INFRA, "backend", "frontend", "data_collector")}
        self.image_ids = {name: "sha256:" + name for name in self.containers}
        self.running_ids = dict(self.image_ids)
        self.version = "2.24.4"
        self.history = f"old -> {REVISION} (head), change\n"
        self.tables = "game\n"
        self.fail = ""
        self.upgrade_revision = REVISION
        self.interrupt = ""
        self.config_hashes = {name: "hash-" + name for name in self.containers}
        self.running_hashes = dict(self.config_hashes)
        self.observer: Callable[[str], None] | None = None

    def run(self, argv, *, cwd, env, input=None, timeout=120):
        if argv[:2] == ["git", "fetch"] or argv[:2] == ["git", "rev-parse"] or argv[:2] == ["git", "show"]:
            return super().run(argv, cwd=cwd, env=env, input=input, timeout=timeout)
        if argv[:2] == ["docker", "pull"]:
            return super().run(argv, cwd=cwd, env=env, input=input, timeout=timeout)
        self.calls.append((list(argv), cwd, dict(env), input, timeout))
        text = " ".join(argv)
        if self.observer is not None:
            self.observer(text)
        if self.interrupt and self.interrupt in text:
            raise KeyboardInterrupt
        if self.fail and self.fail in text:
            return subprocess.CompletedProcess(argv, 1, "plausible-success", "password-must-not-leak")
        output = ""
        if "SELECT version_num FROM alembic_version" in argv:
            output = self.db
        elif "SHOW TABLES" in argv:
            output = self.tables
        elif "mysqldump" in argv:
            output = "-- fixture dump\nCREATE TABLE game(id INT);\n"
        elif "du -sb" in text:
            output = "100 /data\n"
        elif "version --short" in text:
            output = self.version
        elif "ps -a --format json" in text:
            output = json.dumps([{"Service": "backend" if k == "backend-two" else k, "ID": v, "State": "running"}
                                 for k, v in self.containers.items()])
        elif argv[:3] == ["docker", "container", "inspect"]:
            name = argv[3].removesuffix("-id")
            output = self.running_hashes[name] if "config-hash" in text else self.running_ids[name]
        elif argv[:3] == ["docker", "image", "inspect"]:
            if "{{json .}}" in argv:
                output = json.dumps({"Config": {"Labels": {"org.opencontainers.image.revision": COMMIT}}})
            else:
                name = next(k for k, v in (INFRA | rm.loads(metadata_bytes()).images).items() if v == argv[3])
                output = self.image_ids[name]
        elif "config --hash=" in text:
            name = text.split("config --hash=")[1].split()[0]
            output = name + " " + self.config_hashes[name]
        elif "config --format json" in text or ("config" in argv and "--format" in argv):
            output = self.compose
        elif "alembic" in text and "heads" in text:
            output = self.heads
        elif "alembic" in text and "history" in text:
            output = self.history
        elif "alembic" in text and "upgrade" in text:
            self.db = self.upgrade_revision + "\n"
        elif "/sqlite_backup.py backup" in text:
            import shlex
            cmd = next(a[4:] for a in argv if a.startswith("CMD="))
            args = shlex.split(cmd)
            mount = next(a[9:] for a in argv if a.startswith("RUN_ARGS="))
            mounts = shlex.split(mount)
            backup_dir = Path(next(v[:-8] for v in mounts if v.endswith(":/backup")))
            target = backup_dir / Path(args[-1]).name
            with sqlite3.connect(target) as connection:
                connection.execute("CREATE TABLE fixture(id INTEGER)")
                connection.execute("INSERT INTO fixture VALUES (7)")
            output = json.dumps({"present": True, "sha256": rm.sha256_hex(target.read_bytes()),
                                 "size": target.stat().st_size})
        return subprocess.CompletedProcess(argv, 0, output, "")


class OperationalCase(unittest.TestCase):
    def __init__(self, methodName="runTest"):
        super().__init__(methodName)
        self.temp = tempfile.TemporaryDirectory(prefix="bdvrd-t1314-unit-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "webreport").mkdir()
        (self.root / "bd_shared").mkdir()
        (self.root / "bd_shared" / "config.toml").write_text(
            '[webreport]\nagent_timeout_seconds=1\n[xlsm_fetch]\nstart_time="20:00"\ntimezone="Europe/Belgrade"\n')
        (self.root / "bd_shared" / "config.local.toml").write_text("[webreport]\n")
        (self.root / "webreport" / ".env.mysql").write_text("MYSQL_ROOT_PASSWORD=fixture-secret\nMYSQL_DATABASE=games\n")
        self.env = {"BD_VM_DIR": str(self.root / "vm"), "COMPOSE_PROJECT_NAME": "bdvrd-t1314"}
        self.runner = OperationalRunner()
        self.meta = rm.loads(metadata_bytes())
        self.executor = d.Executor(self.root, self.env, self.runner, FakeFetcher(release(metadata_bytes()), metadata_bytes()))
        self.executor.clock = FakeClock()
        self.executor.state.initialize()
        cache = self.executor.state.path / "releases" / TAG
        cache.mkdir()
        (cache / "compose.release.yml").write_text(
            json.dumps({"services": {k: {"image": v} for k, v in (INFRA | self.meta.images).items()}}))
        self.flags = d.parser().parse_args(["deploy", TAG, "--yes", "--approve-migration"])

    def assertCode(self, code, fn):
        with self.assertRaises(d.DeployError) as caught:
            fn()
        self.assertEqual(caught.exception.exit_code, code)
        self.assertNotIn("fixture-secret", caught.exception.message)
        return caught.exception

    def commands(self):
        return [" ".join(call[0]) for call in self.runner.calls]


class OperationsTest(OperationalCase):
    def test_shared_rollback_finish_publication_failure_is_terminal_failed(self):
        previous: dict[str, d.JSON] = {"tag": "v0.1.0"}
        self.executor.state.write_current({"last_successful": previous})
        self.executor.begin_attempt(self.meta, kind="rollback")
        output = []
        self.executor.emit = output.append
        with mock.patch.object(self.executor.state, "write_current",
                               side_effect=OSError(errno.ENOSPC, "fixture-secret")):
            error = self.assertCode(23, lambda: self.executor.finish_attempt(smoke_steps=["S1", "S2"]))
        self.assertIn("publish-state", error.message)
        events = self.executor.state.read_history()
        self.assertEqual([e["event"] for e in events], ["started", "failed"])
        self.assertEqual(events[-1]["kind"], "rollback")
        self.assertEqual(events[-1]["exit_code"], 23)
        self.assertEqual(events[-1]["step"], "publish-state")
        self.assertEqual(events[0]["started_at"], events[-1]["started_at"])
        self.assertEqual(self.executor.state.read_current()["last_successful"], previous)
        self.assertIn("Recovery: make rollback VERSION=v0.1.0", output)

    def test_shared_success_is_published_before_terminal_success_append(self):
        for kind in ("deploy", "rollback"):
            with self.subTest(kind=kind):
                self.executor.begin_attempt(self.meta, kind=kind)
                append = self.executor.state.append_history
                def observe(event):
                    self.assertEqual(self.executor.state.read_current()["last_successful"], event)
                    append(event)
                with mock.patch.object(self.executor.state, "append_history", side_effect=observe):
                    self.executor.finish_attempt(smoke_steps=["S1", "S2"])
                events = self.executor.state.read_history()
                self.assertEqual([e["event"] for e in events[-2:]], ["started", "success"])
                self.assertEqual(events[-1]["kind"], kind)

    def test_release_up_infrastructure_guard_issues_no_runner_command(self):
        for name in INFRA:
            with self.subTest(service=name):
                self.runner.calls.clear()
                self.assertCode(2, lambda: self.executor.release_make("release-up", services=[name]))
                self.assertEqual(self.runner.calls, [])

    def test_infrastructure_pin_drift_and_missing_container_refuse_mutation(self):
        for name in INFRA:
            for missing in (False, True):
                with self.subTest(service=name, missing=missing):
                    self.runner.calls.clear()
                    identifier = self.runner.containers[name]
                    if missing:
                        self.runner.containers.pop(name)
                    else:
                        self.runner.running_ids[name] = "different-image"
                    self.assertCode(4, lambda: self.executor.preflight(self.meta, self.flags))
                    self.assertFalse(any(any(stage in cmd for stage in
                                             ("release-stop", "release-start", "release-up", "upgrade"))
                                         for cmd in self.commands()))
                    if missing:
                        self.runner.containers[name] = identifier
                    self.runner.running_ids[name] = self.runner.image_ids[name]

    def test_disk_shortage_is_preflight_failure(self):
        with mock.patch("shutil.disk_usage", return_value=mock.Mock(free=399)):
            self.assertCode(4, lambda: self.executor.preflight(self.meta, self.flags))
        self.assertFalse(any("release-stop" in cmd for cmd in self.commands()))

    def test_preflight_checks_compose_version_and_release_commands(self):
        for fail in ("release-config", "agent.knowledge_cli", "agent.tools_cli"):
            with self.subTest(fail=fail):
                self.runner.fail = fail
                self.assertCode(4, lambda: self.executor.preflight(self.meta, self.flags))
        self.runner.fail = ""
        self.runner.version = "2.24.3"
        self.assertCode(4, lambda: self.executor.preflight(self.meta, self.flags))

    def test_missing_overlay_fails_before_generate_env(self):
        (self.root / "bd_shared" / "config.local.toml").unlink()
        self.assertCode(4, lambda: self.executor.preflight(self.meta, self.flags))
        self.assertFalse(any("generate-env" in cmd for cmd in self.commands()))

    def test_infra_mismatch_missing_and_multiple_backends_fail_before_stop(self):
        for field, value in (("image", "different"), ("missing", ""), ("backend", "")):
            with self.subTest(field=field):
                self.runner = OperationalRunner()
                self.executor.runner = self.runner
                if field == "image":
                    self.runner.running_ids["mysql"] = value
                elif field == "missing":
                    del self.runner.containers["litellm"]
                else:
                    self.runner.containers["backend-two"] = "backend-two-id"
                self.assertCode(4, lambda: self.executor.preflight(self.meta, self.flags))
                self.assertFalse(any("release-stop" in cmd for cmd in self.commands()))

    def test_zero_backend_is_valid_first_install(self):
        del self.runner.containers["backend"]
        self.executor.preflight(self.meta, self.flags)

    def test_collector_window_requires_yes_and_handles_midnight(self):
        import datetime
        (self.root / "bd_shared" / "config.local.toml").write_text('[xlsm_fetch]\nstart_time="00:05"\n')
        self.flags.yes = False
        now = datetime.datetime(2026, 1, 1, 22, 59, tzinfo=datetime.timezone.utc)
        with mock.patch.object(self.executor, "now", return_value=now):
            self.assertCode(4, lambda: self.executor.preflight(self.meta, self.flags))
            self.flags.yes = True
            self.executor.preflight(self.meta, self.flags)

    def test_current_target_has_no_prompt_but_takes_backup(self):
        with mock.patch("builtins.input", side_effect=AssertionError("unexpected prompt")):
            self.executor.prepare_deploy(self.meta, self.flags)
        self.assertTrue(any("mysqldump" in cmd for cmd in self.commands()))
        self.assertFalse(any("upgrade" in cmd for cmd in self.commands()))

    def test_pending_decline_and_noninteractive_refuse_before_stop(self):
        self.runner.db = "old\n"
        self.flags.approve_migration = False
        with mock.patch("sys.stdin.isatty", return_value=False):
            self.assertCode(32, lambda: self.executor.prepare_deploy(self.meta, self.flags))
        with mock.patch("sys.stdin.isatty", return_value=True), mock.patch("builtins.input", return_value="n"):
            self.assertCode(33, lambda: self.executor.prepare_deploy(self.meta, self.flags))
        self.assertFalse(any("release-stop" in cmd for cmd in self.commands()))

    def test_upgrade_uses_literal_revision_and_backup_manifest(self):
        self.runner.db = "old\n"
        result = self.executor.prepare_deploy(self.meta, self.flags)
        commands = self.commands()
        self.assertTrue(any(f"upgrade {REVISION}" in cmd for cmd in commands))
        self.assertFalse(any("upgrade head" in cmd for cmd in commands))
        self.assertLess(next(i for i, cmd in enumerate(commands) if "mysqldump" in cmd),
                        next(i for i, cmd in enumerate(commands) if "upgrade" in cmd))
        manifest = json.loads((self.executor.state.path / "backups" / result["backup_id"] / "manifest.json").read_text())
        self.assertEqual(manifest["db_revision_before"], "old")
        self.assertEqual(len(manifest["files"]), 4)
        self.assertNotIn("stage", self.executor.state.read_current())
        for argv, _, env, _, timeout in self.runner.calls:
            self.assertNotIn("fixture-secret", " ".join(argv))
            self.assertGreater(timeout, 0)
            if "mysqldump" in argv:
                self.assertEqual(env["MYSQL_PWD"], "fixture-secret")
                self.assertIn("--add-drop-database", argv)

    def test_upgrade_mismatch_and_interrupt_preserve_dirty_marker(self):
        self.runner.db = "old\n"
        self.runner.upgrade_revision = "wrong"
        self.assertCode(36, lambda: self.executor.prepare_deploy(self.meta, self.flags))
        self.assertEqual(self.executor.state.read_current()["stage"], "migration_started")
        self.executor.state.write_current({})
        self.runner.db = "old\n"
        self.runner.interrupt = "upgrade"
        with self.assertRaises(KeyboardInterrupt):
            self.executor.prepare_deploy(self.meta, self.flags)
        self.assertEqual(self.executor.state.read_current()["stage"], "migration_started")
        self.assertCode(41, lambda: self.executor.prepare_deploy(self.meta, self.flags))

    def test_backup_failure_restarts_quiesced_services_and_does_not_upgrade(self):
        self.runner.db = "old\n"
        self.runner.fail = "mysqldump"
        self.assertCode(35, lambda: self.executor.prepare_deploy(self.meta, self.flags))
        self.assertTrue(any("release-start" in cmd and "data_collector backend" in cmd for cmd in self.commands()))
        self.assertFalse(any("upgrade" in cmd for cmd in self.commands()))
        self.assertEqual(list((self.executor.state.path / "backups").iterdir()), [])

    def test_quiesce_failure_is_34(self):
        self.runner.fail = "release-stop"
        self.assertCode(34, lambda: self.executor.prepare_deploy(self.meta, self.flags))

    def test_unversioned_nonempty_database_and_nonancestor_refuse(self):
        self.runner.db = ""
        self.assertCode(31, lambda: self.executor.prepare_deploy(self.meta, self.flags))
        self.runner.tables = ""
        self.runner.history = f"<base> -> {REVISION} (head), initial\n"
        result = self.executor.prepare_deploy(self.meta, self.flags)
        self.assertIsNone(result["db_revision_before"])
        self.runner.db = "newer\n"
        self.runner.history = "not an ancestor"
        self.assertCode(31, lambda: self.executor.prepare_deploy(self.meta, self.flags))

    def test_prune_retains_five_newest_and_migrating_restore_point(self):
        backups = self.executor.state.path / "backups"
        for i in range(8):
            folder = backups / f"20260101T00000{i}Z-{TAG}"
            folder.mkdir()
            (folder / "manifest.json").write_text("{}")
        protected = f"20260101T000000Z-{TAG}"
        self.executor.state.append_history({"kind": "deploy", "event": "success", "backup_id": protected,
                                            "db_revision_before": "old", "db_revision_after": REVISION})
        self.executor.prune_backups()
        names = {p.name for p in backups.iterdir()}
        self.assertEqual(len(names), 6)
        self.assertIn(protected, names)
        self.assertNotIn(f"20260101T000001Z-{TAG}", names)

    def test_store_resolution_honours_env_and_rejects_escaping_mount(self):
        self.executor.env["BD_CHATS_DB_PATH"] = "/data/chats-ikar.db"
        stores = self.executor.store_paths()
        self.assertEqual(stores["chats"], self.root / "vm/backend/checkpoints/chats-ikar.db")
        for bad in ("/data/../secret.db", "/elsewhere/store.db", "/data/x$(touch bad).db"):
            self.executor.env["BD_CHATS_DB_PATH"] = bad
            self.assertCode(4, self.executor.store_paths)

    def test_corrupt_state_and_backup_traversal_are_refused(self):
        (self.executor.state.path / "current.json").write_text('{"stage":')
        self.assertCode(23, lambda: self.executor.prepare_deploy(self.meta, self.flags))
        for bad in ("../escape", "/absolute", "x/../../y"):
            self.assertCode(40, lambda: self.executor.restore_backup_set(bad))

    def test_make_calls_are_silent_and_services_allowlisted(self):
        self.executor.prepare_deploy(self.meta, self.flags)
        for argv, _, _, _, _ in self.runner.calls:
            if argv[0] == "make":
                self.assertIn("-s", argv)
                self.assertIn("--no-print-directory", argv)
        self.assertCode(2, lambda: self.executor.release_make("release-stop", services=["mysql;bad"]))


class SQLiteBackupTest(unittest.TestCase):
    def test_real_cli_restore_replaces_rows_and_removes_sidecars(self):
        with tempfile.TemporaryDirectory(prefix="bdvrd-t15-sqlite-cli-") as folder:
            src, snapshot = Path(folder) / "store.db", Path(folder) / "snapshot.db"
            with sqlite3.connect(src) as conn:
                conn.execute("CREATE TABLE records(id INTEGER)")
                conn.execute("INSERT INTO records VALUES (13)")
            helper = PROJECT_ROOT / "deploy/sqlite_backup.py"
            backup_cmd = [sys.executable, str(helper), "backup", str(src), str(snapshot)]
            saved = subprocess.run(backup_cmd, capture_output=True, text=True, timeout=30, check=False)
            self.assertEqual(saved.returncode, 0, saved.stderr)
            with sqlite3.connect(src) as conn:
                conn.execute("UPDATE records SET id = 99")
            for suffix in ("-wal", "-shm"):
                Path(str(src) + suffix).write_bytes(b"stale")
            restore_cmd = [sys.executable, str(helper), "restore", str(snapshot), str(src)]
            restored = subprocess.run(restore_cmd, capture_output=True, text=True, timeout=30, check=False)
            self.assertEqual(restored.returncode, 0, restored.stderr)
            self.assertTrue(json.loads(restored.stdout)["present"])
            with sqlite3.connect(src) as conn:
                self.assertEqual(conn.execute("SELECT id FROM records").fetchall(), [(13,)])
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone(), ("ok",))
            self.assertFalse(any(Path(str(src) + suffix).exists() for suffix in ("-wal", "-shm")))
            print("SQLite CLI QA: " + shlex.join(restore_cmd))
            print("SQLite CLI PASS: rows [(13,)] replaced [(99,)]; integrity ok; WAL/SHM absent")
        self.assertFalse(Path(folder).exists())
        print("SQLite CLI cleanup PASS: scratch directory removed; child processes exited")

    def test_real_backup_integrity_restore_and_sidecars(self):
        with tempfile.TemporaryDirectory(prefix="bdvrd-sqlite-") as folder:
            src, dst = Path(folder) / "store.db", Path(folder) / "copy.db"
            with sqlite3.connect(src) as conn:
                conn.execute("CREATE TABLE records(id INTEGER)")
                conn.execute("INSERT INTO records VALUES (13)")
            sqlite_backup.backup(src, dst)
            with sqlite3.connect(dst) as conn:
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(conn.execute("SELECT id FROM records").fetchall(), [(13,)])
            for suffix in ("-wal", "-shm"):
                Path(str(src) + suffix).write_bytes(b"stale")
            sqlite_backup.restore(dst, src)
            self.assertFalse(Path(str(src) + "-wal").exists())
            self.assertFalse(Path(str(src) + "-shm").exists())
            with sqlite3.connect(src) as conn:
                self.assertEqual(conn.execute("SELECT id FROM records").fetchall(), [(13,)])

    def test_absent_store_is_not_created_and_corrupt_backup_refuses_restore(self):
        with tempfile.TemporaryDirectory(prefix="bdvrd-sqlite-") as folder:
            src, dst = Path(folder) / "missing.db", Path(folder) / "copy.db"
            result = sqlite_backup.backup(src, dst)
            self.assertFalse(result["present"])
            self.assertFalse(src.exists())
            self.assertFalse(dst.exists())
            dst.write_bytes(b"not a database")
            src.write_bytes(b"original")
            with self.assertRaises(sqlite3.DatabaseError):
                sqlite_backup.restore(dst, src)
            self.assertEqual(src.read_bytes(), b"original")


class BackupFailureTest(OperationalCase):
    """Exercise the real CLI and filesystem boundary after services quiesce."""

    def invoke_failure(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = d.main(["deploy", TAG, "--yes", "--approve-migration"], root=self.root, env=self.env,
                          runner=self.runner, fetcher=self.executor.fetcher)
        return code, out.getvalue(), json.loads(err.getvalue())

    def assertBackupFailure(self, result):
        code, out, error = result
        self.assertEqual(code, 35, (out, error))
        self.assertEqual(error["error"], "E_BACKUP")
        self.assertEqual(error["exit_code"], 35)
        commands = self.commands()
        stop = next(i for i, cmd in enumerate(commands) if "release-stop" in cmd)
        start = next(i for i, cmd in enumerate(commands) if "release-start" in cmd)
        self.assertLess(stop, start)
        self.assertIn("SERVICES=data_collector backend", commands[start])
        self.assertFalse(any("upgrade" in cmd or "release-up" in cmd for cmd in commands))
        self.assertNotIn("fixture-secret", out + json.dumps(error))
        self.assertNotIn("Deploy " + TAG + " success", out)

    def test_mkdir_enospc_restarts_services_and_returns_35(self):
        original = Path.mkdir
        def full(path, *args, **kwargs):
            if path.parent == self.executor.state.path / "backups":
                raise OSError(errno.ENOSPC, "fixture-secret")
            return original(path, *args, **kwargs)
        with mock.patch.object(Path, "mkdir", full):
            result = self.invoke_failure()
        self.assertBackupFailure(result)
        self.assertEqual(list((self.executor.state.path / "backups").iterdir()), [])

    def test_existing_backup_collision_preserves_set_and_restarts_services(self):
        now = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        folder = self.executor.state.path / "backups" / (now.strftime("%Y%m%dT%H%M%S%fZ") + "-" + TAG)
        folder.mkdir()
        previous = b"existing snapshot must survive"
        (folder / "mysql.sql").write_bytes(previous)
        (folder / "manifest.json").write_bytes(b'{"existing":true}\n')
        with mock.patch.object(d.Executor, "now", return_value=now):
            result = self.invoke_failure()
        self.assertBackupFailure(result)
        self.assertEqual((folder / "mysql.sql").read_bytes(), previous)
        self.assertEqual((folder / "manifest.json").read_bytes(), b'{"existing":true}\n')
        self.assertFalse(any("mysqldump" in cmd for cmd in self.commands()))

    def test_manifest_enospc_restarts_services_and_removes_incomplete_set(self):
        original = d.State.write_atomic
        def full(state, path, data):
            if path.name == "manifest.json":
                raise OSError(errno.ENOSPC, "fixture-secret")
            return original(state, path, data)
        with mock.patch.object(d.State, "write_atomic", full):
            result = self.invoke_failure()
        self.assertBackupFailure(result)
        self.assertEqual(list((self.executor.state.path / "backups").iterdir()), [])

    def test_cleanup_failure_cannot_mask_backup_error_or_prevent_restart(self):
        original = d.State.write_atomic
        def full(state, path, data):
            if path.name == "manifest.json":
                raise OSError(errno.ENOSPC, "fixture-secret")
            return original(state, path, data)
        with mock.patch.object(d.State, "write_atomic", full), mock.patch(
                "shutil.rmtree", side_effect=PermissionError("fixture-secret")):
            result = self.invoke_failure()
        self.assertBackupFailure(result)
        folders = list((self.executor.state.path / "backups").iterdir())
        self.assertEqual(len(folders), 1)
        self.assertFalse((folders[0] / "manifest.json").exists())

    def test_restart_failure_is_best_effort_and_still_reports_35(self):
        original = Path.mkdir
        def full(path, *args, **kwargs):
            if path.parent == self.executor.state.path / "backups":
                raise OSError(errno.ENOSPC, "fixture-secret")
            return original(path, *args, **kwargs)
        self.runner.fail = "release-start"
        with mock.patch.object(Path, "mkdir", full):
            result = self.invoke_failure()
        self.assertBackupFailure(result)


class FailureBookkeepingTest(OperationalCase):
    def invoke(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = d.main(["deploy", TAG, "--yes", "--approve-migration"], root=self.root, env=self.env,
                          runner=self.runner, fetcher=self.executor.fetcher)
        return code, out.getvalue(), err.getvalue()

    def assertPrimary(self, expected, result):
        code, out, err = result
        self.assertEqual(code, expected, (out, err))
        primary = json.loads(next(line for line in err.splitlines() if line.startswith("{")))
        self.assertEqual(primary["exit_code"], expected)
        self.assertEqual(primary["error"], d.EXIT_CODES[expected])
        self.assertIn("secondary", err.lower())
        self.assertNotIn("fixture-secret", out + err)
        self.assertNotIn("Deploy " + TAG + " success", out)

    def test_persistent_backup_enospc_preserves_35_and_restarts(self):
        full = False
        mkdir, append, atomic = Path.mkdir, d.State.append_history, d.State.write_atomic
        def allocate(path, *args, **kwargs):
            nonlocal full
            if path.parent == self.executor.state.path / "backups":
                full = True
                raise OSError(errno.ENOSPC, "fixture-secret")
            return mkdir(path, *args, **kwargs)
        def history(state, event):
            if full:
                raise OSError(errno.ENOSPC, "fixture-secret")
            return append(state, event)
        def write(state, path, data):
            if full:
                raise OSError(errno.ENOSPC, "fixture-secret")
            return atomic(state, path, data)
        with mock.patch.object(Path, "mkdir", allocate), mock.patch.object(d.State, "append_history", history), \
                mock.patch.object(d.State, "write_atomic", write):
            result = self.invoke()
        self.assertPrimary(35, result)
        self.assertTrue(any("release-start" in cmd for cmd in self.commands()))
        self.assertEqual([e["event"] for e in self.executor.state.read_history()], ["started"])

    def test_migration_failure_with_failed_terminal_append_keeps_36(self):
        self.runner.db = "old\n"
        self.runner.fail = "upgrade"
        append = d.State.append_history
        def history(state, event):
            if event["event"] == "failed":
                raise OSError(errno.ENOSPC, "fixture-secret")
            return append(state, event)
        with mock.patch.object(d.State, "append_history", history):
            result = self.invoke()
        self.assertPrimary(36, result)
        self.assertEqual(self.executor.state.read_current()["stage"], "migration_started")

    def test_failed_current_publication_records_one_terminal_before_stop(self):
        previous: dict[str, d.JSON] = {"tag": "v0.1.0"}
        self.executor.state.write_current({"last_successful": previous})
        atomic = d.State.write_atomic
        def write(state, path, data):
            if path.name == "current.json":
                raise OSError(errno.ENOSPC, "fixture-secret")
            return atomic(state, path, data)
        with mock.patch.object(d.State, "write_atomic", write):
            code, out, err = self.invoke()
        self.assertEqual(code, 23, (out, err))
        events = self.executor.state.read_history()
        self.assertEqual([e["event"] for e in events], ["started", "failed"])
        self.assertEqual(events[0]["started_at"], events[1]["started_at"])
        self.assertEqual(events[1]["exit_code"], 23)
        self.assertEqual(self.executor.state.read_current()["last_successful"], previous)
        self.assertFalse(any("release-stop" in cmd for cmd in self.commands()))

    def test_failed_history_keeps_every_operational_error_family(self):
        append = d.State.append_history
        def history(state, event):
            if event["event"] == "failed":
                raise d.DeployError(23, "fixture-secret")
            return append(state, event)
        for expected in (34, 35, 36, 37, 38, 40, 41):
            with self.subTest(code=expected), mock.patch.object(d.State, "append_history", history), \
                    mock.patch.object(d.Executor, "quiesce_backup_migrate",
                                      side_effect=d.DeployError(expected, "primary operational failure")):
                self.assertPrimary(expected, self.invoke())

    def test_log_write_and_close_failure_cannot_mask_operational_errors(self):
        original = Path.open
        for expected in (35, 41):
            for boundary in ("write", "close"):
                broken = False
                def fail(*args, **kwargs):
                    nonlocal broken
                    broken = True
                    raise d.DeployError(expected, "primary operational failure")
                def opened(path, *args, **kwargs):
                    handle = original(path, *args, **kwargs)
                    if path.parent != self.executor.state.path / "logs":
                        return handle
                    self.addCleanup(handle.close)
                    proxy = mock.Mock(wraps=handle)
                    def write(text):
                        if broken and boundary == "write":
                            raise OSError(errno.ENOSPC, "fixture-secret")
                        return handle.write(text)
                    def close():
                        handle.close()
                        if broken and boundary == "close":
                            raise OSError(errno.ENOSPC, "fixture-secret")
                    proxy.write.side_effect = write
                    proxy.close.side_effect = close
                    return proxy
                with self.subTest(code=expected, boundary=boundary), mock.patch.object(Path, "open", opened), \
                        mock.patch.object(d.Executor, "quiesce_backup_migrate", side_effect=fail):
                    self.assertPrimary(expected, self.invoke())


class AuditReconciliationTest(OperationalCase):
    def test_successive_commits_retain_outcomes_when_reconciliation_cannot_write(self):
        audit = self.executor.state.path / "history.jsonl"
        self.addCleanup(audit.chmod, 0o600)
        self.executor.begin_attempt(self.meta)
        audit.chmod(0o400)
        with contextlib.redirect_stderr(io.StringIO()):
            self.executor.finish_attempt(smoke_steps=["S1", "S2"])
        first = self.executor.state.read_current()["last_successful"]
        assert isinstance(first, dict)
        warn = self.executor.warn_audit
        def repair(message):
            warn(message)
            audit.chmod(0o600)
        with mock.patch.object(self.executor, "warn_audit", side_effect=repair), \
                contextlib.redirect_stderr(io.StringIO()):
            self.executor.begin_attempt(replace(self.meta, version="v1.2.4"), kind="rollback")
        audit.chmod(0o400)
        with contextlib.redirect_stderr(io.StringIO()):
            self.executor.finish_attempt(smoke_steps=["S1", "S2"])
        second = self.executor.state.read_current()["last_successful"]
        assert isinstance(second, dict)
        audit.chmod(0o600)

        recovered = d.Executor(self.root, self.env, self.runner, self.executor.fetcher)
        recovered.begin_attempt(self.meta)
        recovered.finish_attempt(smoke_steps=["S1", "S2"])

        events = recovered.state.read_history()
        for committed in (first, second):
            same = [event for event in events if event["attempt_id"] == committed["attempt_id"]]
            self.assertEqual([event["event"] for event in same], ["started", "success"])
            self.assertEqual(same[-1], committed)
        self.assertEqual(first["kind"], "deploy")
        self.assertEqual(second["kind"], "rollback")
        self.assertEqual(recovered.state.read_current().get("unaudited"), [])
        before = audit.read_bytes()
        recovered.reconcile_attempts()
        self.assertEqual(audit.read_bytes(), before)

    def test_prune_failure_preserves_committed_record_without_changing_success(self):
        record = self.executor.begin_attempt(self.meta)
        write = self.executor.state.write_current
        def fail_prune(current):
            if current.get("unaudited") == []:
                raise OSError(errno.ENOSPC, "fixture-secret")
            write(current)
        err = io.StringIO()

        with mock.patch.object(self.executor.state, "write_current", side_effect=fail_prune), \
                contextlib.redirect_stderr(err):
            self.executor.finish_attempt(smoke_steps=["S1", "S2"])
            pending = self.executor.state.read_current().get("unaudited")
            self.executor.reconcile_attempts()

        assert isinstance(pending, list)
        self.assertEqual(len(pending), 1)
        assert isinstance(pending[0], dict)
        self.assertEqual(pending[0]["attempt_id"], record["attempt_id"])
        self.assertIn("WARNING", err.getvalue())
        self.assertNotIn("fixture-secret", err.getvalue())
        before = (self.executor.state.path / "history.jsonl").read_bytes()
        self.executor.reconcile_attempts()
        self.assertEqual((self.executor.state.path / "history.jsonl").read_bytes(), before)
        self.assertEqual(self.executor.state.read_current()["unaudited"], [])

    def test_pre_list_committed_outcome_survives_a_later_commit(self):
        first = self.executor.begin_attempt(self.meta)
        append = self.executor.state.append_history
        def fail_success(event):
            if event["event"] == "success":
                raise OSError(errno.ENOSPC, "fixture-secret")
            append(event)
        with mock.patch.object(self.executor.state, "append_history", side_effect=fail_success), \
                contextlib.redirect_stderr(io.StringIO()):
            self.executor.finish_attempt(smoke_steps=["S1", "S2"])
            current = self.executor.state.read_current()
            current.pop("unaudited", None)
            self.executor.state.write_current(current)
            self.executor.begin_attempt(replace(self.meta, version="v1.2.4"))
            self.executor.finish_attempt(smoke_steps=["S1", "S2"])

        self.executor.reconcile_attempts()

        events = self.executor.state.read_history()
        same = [event for event in events if event["attempt_id"] == first["attempt_id"]]
        self.assertEqual([event["event"] for event in same], ["started", "success"])
        self.assertEqual(self.executor.state.read_current()["unaudited"], [])

    def test_visible_success_is_not_pruned_until_audit_sync_succeeds(self):
        self.executor.begin_attempt(self.meta)
        append = self.executor.state.append_history
        def fail_sync(event):
            with mock.patch.object(d.os, "fsync", side_effect=OSError(errno.ENOSPC, "fixture-secret")):
                append(event)
        err = io.StringIO()
        with mock.patch.object(self.executor.state, "append_history", side_effect=fail_sync), \
                contextlib.redirect_stderr(err):
            self.executor.finish_attempt(smoke_steps=["S1", "S2"])
        self.assertEqual([e["event"] for e in self.executor.state.read_history()], ["started", "success"])
        pending = self.executor.state.read_current().get("unaudited")
        assert isinstance(pending, list)
        self.assertEqual(len(pending), 1)
        before = (self.executor.state.path / "history.jsonl").read_bytes()

        with mock.patch.object(d.os, "fsync", side_effect=OSError(errno.ENOSPC, "fixture-secret")), \
                contextlib.redirect_stderr(err):
            self.executor.reconcile_attempts()

        self.assertEqual(self.executor.state.read_current()["unaudited"], pending)
        self.assertIn("WARNING", err.getvalue())
        self.assertNotIn("fixture-secret", err.getvalue())
        self.executor.reconcile_attempts()
        self.assertEqual(self.executor.state.read_current()["unaudited"], [])
        self.assertEqual((self.executor.state.path / "history.jsonl").read_bytes(), before)

    def seed_open(self):
        record: dict[str, d.JSON] = {
            "event": "started", "kind": "deploy", "tag": TAG, "commit": COMMIT,
            "attempt_id": str(uuid.uuid4()), "started_at": self.executor.now().isoformat()}
        self.executor.state.append_history(record)
        self.executor.state.write_current({"attempt": {
            key: record[key] for key in ("attempt_id", "tag", "commit", "started_at")}})
        return record

    def test_committed_crash_is_reconciled_to_success_before_next_start(self):
        self.executor.begin_attempt(self.meta)
        append = self.executor.state.append_history
        def crash(event):
            if event["event"] == "success":
                raise SystemExit(97)
            append(event)
        with mock.patch.object(self.executor.state, "append_history", side_effect=crash), \
                self.assertRaises(SystemExit):
            self.executor.finish_attempt(smoke_steps=["S1", "S2"])
        committed = self.executor.state.read_current()["last_successful"]
        self.executor.begin_attempt(self.meta)
        events = self.executor.state.read_history()
        self.assertEqual([e["event"] for e in events], ["started", "success", "started"])
        self.assertEqual(events[1], committed)
        self.assertEqual(events[0]["attempt_id"], events[1]["attempt_id"])
        self.assertNotEqual(events[0]["attempt_id"], events[2]["attempt_id"])

    def test_started_crash_reconciles_before_dirty_check_for_deploy_and_rollback(self):
        record = self.seed_open()
        current = self.executor.state.read_current()
        current["stage"] = "migration_started"
        self.executor.state.write_current(current)
        for command in ("deploy", "rollback"):
            with self.subTest(command=command):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = d.main([command, TAG], root=self.root, env=self.env,
                                  runner=self.runner, fetcher=self.executor.fetcher)
                self.assertEqual(code, 41, (out.getvalue(), err.getvalue()))
                events = self.executor.state.read_history()
                self.assertEqual([e["event"] for e in events], ["started", "failed"])
                self.assertEqual(events[1]["attempt_id"], record["attempt_id"])
                self.assertEqual(events[1]["step"], "interrupted")
                self.assertIsNone(events[1]["exit_code"])
        self.assertEqual(self.runner.calls, [])
        assert isinstance(self.executor.fetcher, FakeFetcher)
        self.assertEqual(self.executor.fetcher.calls, [])

    def test_double_reconciliation_is_idempotent_for_all_open_attempts(self):
        records = [self.seed_open(), self.seed_open()]
        self.executor.reconcile_attempts()
        before = (self.executor.state.path / "history.jsonl").read_bytes()
        self.executor.reconcile_attempts()
        self.assertEqual((self.executor.state.path / "history.jsonl").read_bytes(), before)
        events = self.executor.state.read_history()
        for record in records:
            same = [e for e in events if e["attempt_id"] == record["attempt_id"]]
            self.assertEqual([e["event"] for e in same], ["started", "failed"])

    def test_success_reconciliation_requires_matching_attempt_id_tag_and_commit(self):
        record = self.seed_open()
        for field, value in (("attempt_id", str(uuid.uuid4())), ("tag", "v0.1.0"), ("commit", "b" * 40)):
            with self.subTest(field=field):
                (self.executor.state.path / "history.jsonl").write_text("")
                self.executor.state.append_history(record)
                self.executor.state.write_current({"last_successful": dict(record, event="success") | {field: value}})
                self.executor.reconcile_attempts()
                self.assertEqual(self.executor.state.read_history()[-1]["event"], "failed")

    def test_reconciliation_append_failure_warns_then_new_start_hard_stops(self):
        self.seed_open()
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(d.State, "append_history", side_effect=OSError(errno.ENOSPC, "fixture-secret")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = d.main(["deploy", TAG, "--yes", "--approve-migration"], root=self.root, env=self.env,
                          runner=self.runner, fetcher=self.executor.fetcher)
        self.assertEqual(code, 23)
        self.assertIn("WARNING", err.getvalue())
        self.assertIn("reconciliation", err.getvalue())
        self.assertNotIn("fixture-secret", out.getvalue() + err.getvalue())
        self.assertEqual([e["event"] for e in self.executor.state.read_history()], ["started"])
        self.assertFalse(any("release-stop" in cmd or "release-up" in cmd for cmd in self.commands()))

    def test_rollback_commit_survives_missing_success_audit_and_can_reconcile(self):
        record = self.executor.begin_attempt(self.meta, kind="rollback")
        identifier = record.get("attempt_id")
        self.assertIsInstance(identifier, str)
        assert isinstance(identifier, str)
        self.assertEqual(str(uuid.UUID(identifier)), identifier)
        attempt = self.executor.state.read_current()["attempt"]
        assert isinstance(attempt, dict)
        self.assertEqual(attempt["attempt_id"], identifier)
        err = io.StringIO()
        with mock.patch.object(self.executor.state, "append_history",
                               side_effect=OSError(errno.ENOSPC, "fixture-secret")), contextlib.redirect_stderr(err):
            self.executor.finish_attempt(smoke_steps=["S1", "S2"])
        committed = self.executor.state.read_current()["last_successful"]
        assert isinstance(committed, dict)
        self.assertEqual(committed["attempt_id"], identifier)
        self.assertEqual(committed["kind"], "rollback")
        self.assertIn("WARNING", err.getvalue())
        self.assertIn("success", err.getvalue())
        self.executor.reconcile_attempts()
        self.assertEqual(self.executor.state.read_history()[-1], committed)


class FakeClock:
    def __init__(self):
        self.elapsed = 0.0
        self.stamps = 0

    def monotonic(self):
        return self.elapsed

    def sleep(self, seconds):
        self.elapsed += seconds

    def now(self):
        import datetime
        self.stamps += 1
        return datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(
            seconds=self.elapsed, milliseconds=self.stamps)


class SmokeServer:
    """Real loopback HTTP server at the wire boundary; never calls a model."""

    def __init__(self):
        self.calls = []
        self.health_status = 200
        self.health = {"status": "healthy", "services": {"database": True, "agents": True, "llm_proxy": True}}
        self.chat_list = {"items": [], "next_cursor": None}
        self.run_state: str | None = "succeeded"
        self.has_run = True
        self.fail_path = ""
        self.fail_status = 200
        self.fail_body = b"misleading success"
        self.saved = False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def handle_api(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length)) if length else None
                owner.calls.append((self.command, self.path, body))
                status, response = 200, b""
                if self.path == owner.fail_path:
                    status, response = owner.fail_status, owner.fail_body
                elif self.path == "/health":
                    status = owner.health_status
                    assert isinstance(self.server, ThreadingHTTPServer)
                    response = json.dumps(owner.health).encode() if self.server.server_port == owner.backend_port else b"ok"
                elif self.path == "/":
                    response = b'<html><script src="/assets/app.js"></script><link href="/assets/app.css"></html>'
                elif self.path.startswith("/assets/"):
                    response = b"asset"
                elif self.path == "/api/chats?limit=1":
                    response = json.dumps(owner.chat_list).encode()
                elif self.path == "/api/chats" and self.command == "POST":
                    status, response = 201, b'{"id":"chat-1"}'
                elif self.path == "/api/chats/chat-1/messages":
                    status, response = 202, b'{"request_id":"request","state":"running"}'
                elif self.path == "/api/chats/chat-1/status":
                    response = json.dumps({"active_run": None, "last_run": {"state": owner.run_state}}).encode()
                elif self.path == "/api/chats/chat-1/reports":
                    response = b'[{"id":"report-1","chat_id":"chat-1","data":[{"games":7}]}]'
                elif self.path == "/api/reports/report-1/saved":
                    owner.saved = self.command == "PUT"
                    status = 200 if owner.saved else 204
                    response = b'{"id":"report-1","saved_at":"2026-01-01T00:00:00Z"}' if owner.saved else b""
                elif self.path == "/api/reports/report-1":
                    response = b'{"id":"report-1","data":[{"games":7}],"version":1}'
                elif self.path == "/api/reports/report-1/update":
                    response = b'{"id":"report-1","data":[{"games":8}],"version":2}'
                elif self.path == "/api/saved-reports":
                    response = b'[{"id":"report-1"}]' if owner.saved else b"[]"
                elif self.path == "/api/chats/chat-1" and self.command == "DELETE":
                    status = 409 if owner.run_state in ("running", "cancelling") else 204
                elif self.path == "/api/chats/chat-1/cancel":
                    if owner.has_run:
                        status, response = 202, b'{"state":"cancelled"}'
                        owner.run_state = "cancelled"
                    else:
                        status, response = 404, b'{"error":{"code":"not_found"}}'
                else:
                    status, response = 404, b"not found"
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

            do_GET = handle_api
            do_POST = handle_api
            do_PUT = handle_api
            do_DELETE = handle_api

        self.backend = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.frontend = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.backend_port = self.backend.server_port
        self.frontend_port = self.frontend.server_port
        self.threads = []
        for server in (self.backend, self.frontend):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.threads.append(thread)

    def close(self):
        for server in (self.backend, self.frontend):
            server.shutdown()
            server.server_close()
        for thread in self.threads:
            thread.join(timeout=3)
            if thread.is_alive():
                raise AssertionError("fake HTTP server did not stop")


class SmokeTest(OperationalCase):
    def __init__(self, methodName="runTest"):
        super().__init__(methodName)
        self.server = SmokeServer()
        self.addCleanup(self.server.close)
        self.clock = FakeClock()
        self.executor = d.Executor(self.root, self.env, self.runner, self.executor.fetcher)
        self.executor.clock = self.clock
        self.executor.metadata = self.meta
        self.executor.pin_file = self.executor.state.path / "releases" / TAG / "compose.release.yml"
        (self.root / "webreport" / ".env").write_text(
            f"WEBREPORT_BACKEND_PORT={self.server.backend_port}\nWEBREPORT_FRONTEND_PORT={self.server.frontend_port}\n")
        (self.root / "deploy").mkdir()
        (self.root / "deploy" / "smoke_question.txt").write_text("How many games were played?")
        self.before = {name: name + "-id" for name in INFRA}

    def test_unchanged_services_start_backend_collector_without_recreate(self):
        self.executor.recreate_and_smoke(self.meta, self.flags, before=self.before)
        commands = self.commands()
        self.assertTrue(any("release-start" in cmd and "SERVICES=backend" in cmd for cmd in commands))
        self.assertTrue(any("release-start" in cmd and "SERVICES=data_collector" in cmd for cmd in commands))
        self.assertFalse(any("release-up" in cmd or "release-pull" in cmd for cmd in commands))

    def test_changed_frontend_only_and_config_hash_change_are_detected(self):
        self.runner.running_ids["frontend"] = "old-image"
        self.executor.recreate_and_smoke(self.meta, self.flags, before=self.before)
        up = [cmd for cmd in self.commands() if "release-up" in cmd]
        self.assertEqual(len(up), 1)
        self.assertIn("SERVICES=frontend", up[0])
        self.runner.running_hashes["backend"] = "old-config"
        self.assertIn("backend", self.executor.affected_services(self.meta))
        del self.runner.containers["data_collector"]
        self.assertIn("data_collector", self.executor.affected_services(self.meta))

    def test_readiness_degraded_until_deadline_names_llm_proxy(self):
        self.server.health_status = 503
        self.server.health = {"status": "degraded", "services": {"database": True, "agents": False, "llm_proxy": False}}
        error = self.assertCode(38, lambda: self.executor.wait_ready())
        self.assertIn("llm_proxy", error.message)
        self.assertGreaterEqual(self.clock.elapsed, 180)
        self.assertLessEqual(self.clock.elapsed, 182)

    def test_smoke_checks_real_content_not_only_200(self):
        for path, body, step in (("/health", b'{"status":"healthy","services":{}}', "S1"),
                                 ("/", b"not html", "S3"), ("/health", b"wrong", "S4"),
                                 ("/api/chats?limit=1", b'{"items":[]}', "S5")):
            with self.subTest(step=step):
                # S1 and S4 share /health on different origins; S4 is handled
                # separately by the exact transport seam below.
                if step == "S4":
                    original = self.executor.http.request
                    def bad_frontend(method, url, **kwargs):
                        if url == f"http://127.0.0.1:{self.server.frontend_port}/health":
                            return 200, {}, b"wrong"
                        return original(method, url, **kwargs)
                    with mock.patch.object(self.executor.http, "request", side_effect=bad_frontend):
                        error = self.assertCode(38, lambda: self.executor.smoke(self.meta, before=self.before))
                else:
                    self.server.fail_path, self.server.fail_body = path, body
                    error = self.assertCode(38, lambda: self.executor.smoke(self.meta, before=self.before))
                self.assertIn(step, error.message)
                self.server.fail_path = ""

    def test_failed_asset_and_frontend_connection_name_S3(self):
        self.server.fail_path = "/assets/app.js"
        self.server.fail_status = 404
        self.assertIn("S3", self.assertCode(38, lambda: self.executor.smoke(self.meta, before=self.before)).message)
        self.server.fail_path = ""
        (self.root / "webreport" / ".env").write_text("WEBREPORT_BACKEND_PORT=1\nWEBREPORT_FRONTEND_PORT=1\n")
        self.assertIn("S3", self.assertCode(38, lambda: self.executor.smoke(self.meta, before=self.before, steps=["S3"])).message)

    def test_changed_infra_ids_db_revision_and_stopped_collector_fail(self):
        self.runner.db = "wrong\n"
        self.assertIn("S2", self.assertCode(38, lambda: self.executor.smoke(self.meta, before=self.before)).message)
        self.runner.db = REVISION
        self.runner.containers["mysql"] = "new-mysql-id"
        self.assertIn("S6", self.assertCode(38, lambda: self.executor.smoke(self.meta, before=self.before)).message)
        self.runner.containers["mysql"] = "mysql-id"
        del self.runner.containers["data_collector"]
        self.assertIn("S7", self.assertCode(38, lambda: self.executor.smoke(self.meta, before=self.before)).message)

    def test_llm_fake_http_server_exact_roundtrip_and_cleanup(self):
        steps = self.executor.smoke(self.meta, before=self.before, llm_smoke=True)
        self.assertEqual(steps, ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"])
        requests = [(method, path) for method, path, body in self.server.calls if path.startswith("/api/")]
        self.assertEqual(requests, [
            ("GET", "/api/chats?limit=1"), ("POST", "/api/chats"), ("POST", "/api/chats/chat-1/messages"),
            ("GET", "/api/chats/chat-1/status"), ("GET", "/api/chats/chat-1/reports"),
            ("PUT", "/api/reports/report-1/saved"), ("GET", "/api/reports/report-1"),
            ("POST", "/api/reports/report-1/update"), ("GET", "/api/saved-reports"),
            ("DELETE", "/api/reports/report-1/saved"), ("DELETE", "/api/chats/chat-1"),
        ])
        submission = next(body for method, path, body in self.server.calls if path.endswith("/messages"))
        self.assertEqual(submission["message"], "How many games were played?")
        self.assertRegex(submission["request_id"], r"^[0-9a-f-]{36}$")
        self.assertFalse(self.server.saved)

    def test_llm_failed_run_missing_report_and_poll_timeout_are_S8_and_cleanup(self):
        for state in ("failed", "interrupted", "running"):
            with self.subTest(state=state):
                self.server.calls.clear()
                self.server.run_state = state
                error = self.assertCode(38, lambda: self.executor.smoke(self.meta, before=self.before, llm_smoke=True))
                self.assertIn("S8", error.message)
                self.assertIn(("DELETE", "/api/chats/chat-1"), [(m, p) for m, p, b in self.server.calls])
        self.server.run_state = "succeeded"
        self.server.fail_path, self.server.fail_body = "/api/chats/chat-1/reports", b"[]"
        self.assertIn("S8", self.assertCode(38, lambda: self.executor.smoke(self.meta, before=self.before, llm_smoke=True)).message)

    def test_smoke_failure_with_failed_history_append_keeps_38(self):
        self.server.fail_path, self.server.fail_body = "/", b"not html"
        append = d.State.append_history
        def history(state, event):
            if event["event"] == "failed":
                raise OSError(errno.ENOSPC, "fixture-secret")
            return append(state, event)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(d.State, "append_history", history), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            code = d.main(["deploy", TAG, "--yes", "--approve-migration"], root=self.root, env=self.env,
                          runner=self.runner, fetcher=self.executor.fetcher)
        self.assertEqual(code, 38, (out.getvalue(), err.getvalue()))
        self.assertIn("S3", err.getvalue())
        self.assertIn("secondary", err.getvalue().lower())
        self.assertNotIn("fixture-secret", err.getvalue())
        self.assertNotIn("Deploy " + TAG + " success", out.getvalue())

    def test_unsave_failure_still_deletes_chat_and_keeps_primary_smoke_error(self):
        original = self.executor.http.request
        def unsave_fails(method, url, **kwargs):
            if method == "DELETE" and url.endswith("/report-1/saved"):
                self.server.calls.append((method, "/api/reports/report-1/saved", None))
                return 500, {}, b"fixture-secret"
            return original(method, url, **kwargs)
        with mock.patch.object(self.executor.http, "request", side_effect=unsave_fails):
            error = self.assertCode(38, lambda: self.executor.llm_smoke(
                f"http://127.0.0.1:{self.server.frontend_port}"))
        self.assertTrue(error.message.startswith("S8: unexpected HTTP status 500"))
        self.assertIn("cleanup", error.message)
        self.assertIn(("DELETE", "/api/chats/chat-1"), [(m, p) for m, p, b in self.server.calls])

    def test_multiple_cleanup_failures_are_collected_without_masking_smoke(self):
        self.server.fail_path, self.server.fail_body = "/api/reports/report-1/update", b"bad JSON"
        original = self.executor.http.request
        def cleanup_fails(method, url, **kwargs):
            if method == "DELETE":
                path = urllib.parse.urlsplit(url).path
                self.server.calls.append((method, path, None))
                return 500, {}, b"fixture-secret"
            return original(method, url, **kwargs)
        with mock.patch.object(self.executor.http, "request", side_effect=cleanup_fails):
            error = self.assertCode(38, lambda: self.executor.llm_smoke(
                f"http://127.0.0.1:{self.server.frontend_port}"))
        self.assertTrue(error.message.startswith("S8: invalid JSON response"))
        self.assertIn("unsave", error.message)
        self.assertIn("delete", error.message)
        self.assertEqual([p for m, p, b in self.server.calls if m == "DELETE"],
                         ["/api/reports/report-1/saved", "/api/chats/chat-1"])

    def test_late_terminal_status_is_rejected_and_request_budget_is_capped(self):
        original = self.executor.http.request
        polls = []
        def late_terminal(method, url, **kwargs):
            if url.endswith("/status"):
                self.clock.elapsed += 10
                polls.append((self.clock.elapsed, kwargs.get("timeout", 10)))
                self.server.run_state = "succeeded" if len(polls) >= 3 else "running"
            return original(method, url, **kwargs)
        with mock.patch.object(self.executor.http, "request", side_effect=late_terminal):
            error = self.assertCode(38, lambda: self.executor.llm_smoke(
                f"http://127.0.0.1:{self.server.frontend_port}"))
        self.assertIn("S8", error.message)
        self.assertIn("deadline", error.message)
        self.assertEqual(polls[:3], [(10, 10), (22, 10), (34, 7)])
        self.assertNotIn(("GET", "/api/chats/chat-1/reports"), [(m, p) for m, p, b in self.server.calls])
        self.assertIn(("DELETE", "/api/chats/chat-1"), [(m, p) for m, p, b in self.server.calls])

    def test_history_started_before_stop_and_success_only_after_smoke(self):
        def observe(cmd):
            if "release-stop" in cmd:
                events = self.executor.state.read_history()
                self.assertEqual(events[-1]["event"], "started")
        self.runner.observer = observe
        self.executor.deploy(self.meta, self.flags)
        events = self.executor.state.read_history()
        self.assertEqual([event["event"] for event in events], ["started", "success"])
        success = self.executor.state.read_current()["last_successful"]
        assert isinstance(success, dict)
        self.assertEqual(success["tag"], TAG)
        self.assertEqual(success["smoke_steps"], ["S1", "S2", "S3", "S4", "S5", "S6", "S7"])
        self.assertIn("backup_id", success)
        self.assertIn("digests", success)

    def test_final_state_publication_failure_reports_failed_and_rollback_hint(self):
        previous: dict[str, d.JSON] = {"tag": "v0.1.0"}
        self.executor.state.write_current({"last_successful": previous})
        write = d.State.write_current
        def fail_final(state, current):
            last = current.get("last_successful")
            if isinstance(last, dict) and last.get("tag") == TAG:
                raise OSError(errno.ENOSPC, "fixture-secret")
            return write(state, current)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(d.State, "write_current", fail_final), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            code = d.main(["deploy", TAG, "--yes", "--approve-migration"], root=self.root, env=self.env,
                          runner=self.runner, fetcher=self.executor.fetcher)
        self.assertEqual(code, 23, (out.getvalue(), err.getvalue()))
        self.assertEqual(json.loads(err.getvalue())["exit_code"], 23)
        events = self.executor.state.read_history()
        self.assertEqual([e["event"] for e in events], ["started", "failed"])
        self.assertEqual(events[-1]["exit_code"], 23)
        self.assertEqual(events[-1]["step"], "publish-state")
        self.assertEqual(events[-1]["smoke_steps"], ["S1", "S2", "S3", "S4", "S5", "S6", "S7"])
        self.assertEqual(self.executor.state.read_current()["last_successful"], previous)
        self.assertIn("S7 PASS", out.getvalue())
        self.assertEqual(out.getvalue().count("Recovery: make rollback VERSION=v0.1.0"), 1)
        self.assertNotIn("Deploy " + TAG + " success", out.getvalue())
        self.assertNotIn("fixture-secret", err.getvalue())

    def test_success_audit_failure_after_commit_still_returns_zero_with_warning(self):
        self.executor.state.write_current({"last_successful": {"tag": "v0.1.0"}})
        append = d.State.append_history
        def fail_success(state, event):
            if event["event"] == "success":
                raise OSError(errno.ENOSPC, "fixture-secret")
            append(state, event)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(d.State, "append_history", fail_success), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            code = d.main(["deploy", TAG, "--yes", "--approve-migration"], root=self.root, env=self.env,
                          runner=self.runner, fetcher=self.executor.fetcher)
        self.assertEqual(code, 0, (out.getvalue(), err.getvalue()))
        committed = self.executor.state.read_current()["last_successful"]
        assert isinstance(committed, dict)
        self.assertEqual(committed["tag"], TAG)
        events = self.executor.state.read_history()
        self.assertEqual([e["event"] for e in events], ["started"])
        self.assertEqual(events[0]["attempt_id"], committed["attempt_id"])
        self.assertIn("Deploy " + TAG + " success", out.getvalue())
        self.assertNotIn("make rollback", out.getvalue())
        self.assertIn("WARNING", err.getvalue())
        self.assertIn("success", err.getvalue())
        identifier = committed["attempt_id"]
        assert isinstance(identifier, str)
        self.assertIn(identifier, err.getvalue())
        self.assertNotIn("fixture-secret", out.getvalue() + err.getvalue())

    def test_failed_recreate_retains_last_successful_and_records_failure(self):
        previous: dict[str, d.JSON] = {"tag": "v0.1.0"}
        self.executor.state.write_current({"last_successful": previous})
        self.runner.running_ids["frontend"] = "old-image"
        self.runner.fail = "release-up"
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertCode(37, lambda: self.executor.deploy(self.meta, self.flags))
        self.assertNotIn("Deploy " + TAG + " success", out.getvalue())
        events = self.executor.state.read_history()
        self.assertEqual([e["event"] for e in events], ["started", "failed"])
        self.assertEqual(events[-1]["exit_code"], 37)
        self.assertIn("recreate", str(events[-1]["step"]))
        self.assertEqual(self.executor.state.read_current()["last_successful"], previous)
        attempt = self.executor.state.read_current()["attempt"]
        assert isinstance(attempt, dict)
        self.assertEqual(attempt["tag"], TAG)

    def test_interrupt_between_recreate_steps_records_terminal_failure(self):
        self.runner.running_ids["frontend"] = "old-image"
        self.runner.interrupt = "release-up"
        self.assertCode(37, lambda: self.executor.deploy(self.meta, self.flags))
        self.assertEqual([e["event"] for e in self.executor.state.read_history()], ["started", "failed"])
        self.assertNotIn("last_successful", self.executor.state.read_current())

    def test_corrupt_history_refuses_before_stop_and_dev_fallback_uses_own_head(self):
        (self.executor.state.path / "history.jsonl").write_text('{"event":')
        self.assertCode(23, lambda: self.executor.deploy(self.meta, self.flags))
        self.assertFalse(any("release-stop" in cmd for cmd in self.commands()))
        (self.executor.state.path / "history.jsonl").write_text("")
        self.executor.pin_file = None
        steps = self.executor.smoke(None, before=self.before)
        self.assertEqual(steps, ["S1", "S2", "S3", "S4", "S5", "S6", "S7"])
        self.assertTrue(any("ALLOW_DEV_COMPOSE=1" in cmd and "heads" in cmd for cmd in self.commands()))

    def test_stale_attempt_is_replaced_without_losing_last_successful(self):
        self.executor.state.write_current({"attempt": {"tag": "v9.0.0"}, "last_successful": {"tag": "v0.1.0"}})
        self.executor.begin_attempt(self.meta, db_revision_before=REVISION)
        current = self.executor.state.read_current()
        self.assertEqual(current["last_successful"], {"tag": "v0.1.0"})
        attempt = current["attempt"]
        assert isinstance(attempt, dict)
        self.assertEqual(attempt["tag"], TAG)
        for data in ('{"attempt":3}', '{"last_successful":{"tag":"../bad"}}', '{"stage":false}'):
            (self.executor.state.path / "current.json").write_text(data)
            self.assertCode(23, self.executor.state.read_current)

    def test_migration_interruption_records_backup_and_preserves_marker(self):
        self.runner.db = "old\n"
        self.runner.interrupt = "upgrade"
        self.assertCode(36, lambda: self.executor.deploy(self.meta, self.flags))
        events = self.executor.state.read_history()
        self.assertEqual([e["event"] for e in events], ["started", "failed"])
        self.assertEqual(events[-1]["exit_code"], 36)
        self.assertIsNotNone(events[-1]["backup_id"])
        self.assertEqual(self.executor.state.read_current()["stage"], "migration_started")
        calls = len(self.runner.calls)
        self.assertCode(41, lambda: self.executor.deploy(self.meta, self.flags))
        self.assertEqual(len(self.runner.calls), calls)

    def test_uncertain_message_response_cancels_accepted_run_before_delete(self):
        self.server.run_state = "running"
        self.server.fail_path = "/api/chats/chat-1/messages"
        self.server.fail_body = b"broken accepted response"
        self.assertCode(38, lambda: self.executor.smoke(self.meta, before=self.before, llm_smoke=True))
        calls = [(m, p) for m, p, b in self.server.calls]
        self.assertIn(("POST", "/api/chats/chat-1/cancel"), calls)
        self.assertLess(calls.index(("POST", "/api/chats/chat-1/cancel")),
                        calls.index(("DELETE", "/api/chats/chat-1")))
        self.assertEqual(self.server.run_state, "cancelled")

    def test_rejected_message_cleans_chat_when_cancel_reports_no_run(self):
        self.server.run_state = None
        self.server.has_run = False
        self.server.fail_path, self.server.fail_status = "/api/chats/chat-1/messages", 422
        self.assertCode(38, lambda: self.executor.smoke(self.meta, before=self.before, llm_smoke=True))
        calls = [(m, p) for m, p, b in self.server.calls]
        self.assertIn(("POST", "/api/chats/chat-1/cancel"), calls)
        self.assertEqual(calls[-1], ("DELETE", "/api/chats/chat-1"))
        self.assertNotIn(("GET", "/api/chats/chat-1/status"), calls)

    def test_llm_missing_question_and_invalid_config_name_S8(self):
        (self.root / "deploy/smoke_question.txt").unlink()
        error = self.assertCode(38, lambda: self.executor.smoke(self.meta, before=self.before, llm_smoke=True))
        self.assertIn("S8", error.message)
        (self.root / "bd_shared/config.local.toml").write_text("invalid toml [")
        error = self.assertCode(38, lambda: self.executor.smoke(self.meta, before=self.before, llm_smoke=True))
        self.assertIn("S8", error.message)
        self.assertFalse(any(m == "POST" for m, p, b in self.server.calls))


class RollbackRunner(OperationalRunner):
    """Restore fake uses real SQLite files; MySQL is the only simulated store."""

    def __init__(self):
        super().__init__()
        self.restore_revision = REVISION
        self.missing_images = set()
        self.restore_fault = ""

    def run(self, argv, *, cwd, env, input=None, timeout=120):
        if "mysql" in argv and input is not None and self.restore_fault:
            self.calls.append((list(argv), cwd, dict(env), input, timeout))
            if self.restore_fault == "interrupt":
                raise KeyboardInterrupt
            if self.restore_fault == "timeout":
                raise subprocess.TimeoutExpired(argv, timeout, output="fixture-secret")
            return subprocess.CompletedProcess(argv, 1, "plausible-success", "fixture-secret")
        result = super().run(argv, cwd=cwd, env=env, input=input, timeout=timeout)
        if result.returncode:
            return result
        if argv[:3] == ["docker", "image", "inspect"] and argv[3] in self.missing_images:
            return subprocess.CompletedProcess(argv, 1, "", "fixture-secret")
        if argv[:2] == ["docker", "pull"]:
            self.missing_images.discard(argv[2])
        if "mysql" in argv and input is not None:
            self.db = self.restore_revision + "\n"
        text = " ".join(argv)
        if "/sqlite_backup.py describe" in text or "/sqlite_backup.py restore" in text:
            args = shlex.split(next(a[4:] for a in argv if a.startswith("CMD=")))
            mounts = shlex.split(next(a[9:] for a in argv if a.startswith("RUN_ARGS=")))
            folder = Path(next(v[:-8] for v in mounts if v.endswith(":/backup")))
            source = folder / Path(args[3]).name
            if args[2] == "describe":
                info = sqlite_backup.describe(source)
            else:
                dest = Path(env["BD_VM_DIR"]) / "backend/checkpoints" / Path(args[4]).relative_to("/data")
                info = sqlite_backup.restore(source, dest)
            return subprocess.CompletedProcess(argv, 0, json.dumps(info), "")
        return result


class RollbackTest(OperationalCase):
    def __init__(self, methodName="runTest"):
        super().__init__(methodName)
        self.runner = RollbackRunner()
        self.env["COMPOSE_PROJECT_NAME"] = "bdvrd-t15"
        self.executor = d.Executor(self.root, self.env, self.runner, self.executor.fetcher)
        assert isinstance(self.executor.fetcher, FakeFetcher)
        self.fetcher = self.executor.fetcher
        self.executor.clock = FakeClock()
        self.executor.metadata = self.meta
        self.executor.pin_file = self.executor.state.path / "releases" / TAG / "compose.release.yml"
        (self.executor.pin_file.parent / "metadata.json").write_bytes(metadata_bytes())
        self.output = []
        self.executor.emit = self.output.append
        self.flags = d.parser().parse_args(["rollback", TAG, "--yes"])
        self.addCleanup(self.assert_safe_commands)

    def assert_safe_commands(self):
        for argv, _, env, _, timeout in self.runner.calls:
            self.assertNotIn("downgrade", " ".join(argv))
            self.assertFalse(any(v in argv for v in ("down", "--remove-orphans", "--force-recreate", "--build")))
            self.assertNotIn("fixture-secret", " ".join(argv))
            self.assertGreater(timeout, 0)
            if "mysql" in argv and ("mysqldump" in argv or "-uroot" in argv):
                self.assertEqual(env["MYSQL_PWD"], "fixture-secret")
            if argv[0] == "make":
                self.assertIn("-s", argv)
                self.assertIn("--no-print-directory", argv)
        self.assertNotIn("fixture-secret", "\n".join(self.output))

    def attach_http(self):
        server = SmokeServer()
        self.addCleanup(server.close)
        (self.root / "webreport" / ".env").write_text(
            f"WEBREPORT_BACKEND_PORT={server.backend_port}\nWEBREPORT_FRONTEND_PORT={server.frontend_port}\n")
        (self.root / "deploy").mkdir(exist_ok=True)
        (self.root / "deploy/smoke_question.txt").write_text("How many games were played?")
        return server

    def backup(self):
        identifier = self.executor.take_backup_set(TAG, db_revision_before=REVISION)
        self.runner.calls.clear()
        return identifier

    def restore_flags(self, identifier):
        return d.parser().parse_args(["rollback", TAG, "--restore-backup", identifier, "--yes"])

    def assert_backup_refused_before_mutation(self, identifier):
        self.runner.calls.clear()
        code, out, err = self.invoke(["rollback", TAG, "--restore-backup", identifier, "--yes"])
        self.assertEqual(code, 40, (out, err))
        self.assertEqual(json.loads(err)["error"], "E_RESTORE")
        for argv, _, _, stdin, _ in self.runner.calls:
            command = " ".join(argv)
            self.assertFalse(any(stage in command for stage in
                                 ("release-stop", "release-start", "release-up", "mysqldump",
                                  "/sqlite_backup.py backup", "/sqlite_backup.py restore", " upgrade ")),
                             command)
            self.assertFalse("mysql" in argv and stdin is not None, command)
        self.assertEqual(self.executor.state.read_history(), [])
        self.assertNotIn("success", out.lower())

    def invoke(self, args):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(d.Executor, "now", side_effect=self.executor.clock.now), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = d.main(args, root=self.root, env=self.env, runner=self.runner, fetcher=self.executor.fetcher)
        return code, out.getvalue(), err.getvalue()

    def test_default_target_prefers_last_successful_after_failed_attempt(self):
        self.executor.state.write_current({"attempt": {"tag": "v2.0.0"}, "last_successful": {"tag": TAG}})
        self.assertEqual(self.invoke(["resolve-rollback-target"]), (0, TAG + "\n", ""))
        self.assertEqual(self.runner.calls, [])

    def test_default_target_uses_latest_different_success_not_failed_event(self):
        self.executor.state.write_current({"attempt": {"tag": TAG}, "last_successful": {"tag": TAG}})
        for event, tag in (("success", "v0.1.0"), ("success", "v0.2.0"), ("failed", "v0.3.0"), ("success", TAG)):
            self.executor.state.append_history({"event": event, "tag": tag})
        self.assertEqual(self.invoke(["resolve-rollback-target"]), (0, "v0.2.0\n", ""))

    def test_explicit_target_wins_and_empty_history_has_no_target(self):
        self.assertEqual(self.invoke(["resolve-rollback-target", TAG]), (0, TAG + "\n", ""))
        code, out, err = self.invoke(["resolve-rollback-target"])
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(json.loads(err)["message"], "no rollback target")

    def test_hostile_current_or_success_history_cannot_select_path(self):
        for current in ('{"attempt":{"tag":"../x"}}', '{"last_successful":[]}', '{"stage":"healthy"}'):
            (self.executor.state.path / "current.json").write_text(current)
            self.assertEqual(self.invoke(["resolve-rollback-target"])[0], 23)
        self.executor.state.write_current({"last_successful": {"tag": TAG}})
        self.executor.state.append_history({"event": "success", "tag": "../x"})
        self.assertEqual(self.invoke(["resolve-rollback-target"])[0], 23)

    def test_equal_schema_uses_cached_digests_and_scoped_smoke(self):
        self.attach_http()
        self.runner.running_ids["frontend"] = "old-frontend"
        code, out, err = self.invoke(["rollback", TAG, "--yes"])
        self.assertEqual(code, 0, err)
        self.assertIn("Rollback " + TAG + " success", out)
        self.assertEqual(self.fetcher.calls, [])
        self.assertFalse(any(c[0][0] == "git" for c in self.runner.calls))
        up = [cmd for cmd in self.commands() if "release-up" in cmd]
        self.assertEqual(len(up), 1)
        self.assertIn("SERVICES=frontend", up[0])
        events = self.executor.state.read_history()
        self.assertEqual([e["event"] for e in events], ["started", "success"])
        self.assertEqual(events[-1]["kind"], "rollback")
        self.assertEqual(events[-1]["smoke_steps"], [f"S{i}" for i in range(1, 8)])
        self.assertEqual(self.executor.state.read_current()["last_successful"], events[-1])

    def test_default_rollback_cli_selects_last_successful_and_honours_llm_smoke(self):
        server = self.attach_http()
        self.executor.state.write_current({"last_successful": {"tag": TAG}, "attempt": {"tag": "v2.0.0"}})
        code, out, err = self.invoke(["rollback", "--yes", "--llm-smoke"])
        self.assertEqual(code, 0, err)
        self.assertIn("S8 PASS", out)
        self.assertIn(("DELETE", "/api/chats/chat-1", None), server.calls)

    def test_cached_missing_image_is_pulled_by_digest(self):
        self.attach_http()
        ref = self.meta.images["frontend"]
        self.runner.missing_images.add(ref)
        self.executor.rollback(TAG, self.flags)
        pulls = [c[0] for c in self.runner.calls if c[0][:2] == ["docker", "pull"]]
        self.assertIn(["docker", "pull", ref], pulls)
        self.assertFalse(any(["docker", "pull", self.meta.images[name]] in pulls for name in ("backend", "data_collector")))

    def test_absent_cache_runs_existing_selection(self):
        self.attach_http()
        assert self.executor.pin_file is not None
        (self.executor.pin_file.parent / "metadata.json").unlink()
        self.executor.rollback(TAG, self.flags)
        self.assertTrue(self.fetcher.calls)
        self.assertTrue(any(c[0] == ["git", "show", f"{TAG}:webreport/docker-compose.yml"] for c in self.runner.calls))

    def test_cached_pin_injection_and_wrong_metadata_refuse_before_stop(self):
        pin = self.executor.pin_file
        assert pin is not None
        original = pin.read_bytes()
        for changes in ({"backend": {"image": "backend:latest"}},
                        {"backend": {"image": self.meta.images["backend"], "volumes": ["/:/host"]}},
                        {"evil": {"image": "mysql:8"}}):
            pins = json.loads(original)
            pins["services"].update(changes)
            pin.write_text(json.dumps(pins))
            self.assertCode(23, lambda: self.executor.rollback(TAG, self.flags))
        pin.write_bytes(original)
        (pin.parent / "metadata.json").write_bytes(rm.dumps(replace(self.meta, version="v9.9.9")))
        self.assertCode(23, lambda: self.executor.rollback(TAG, self.flags))
        self.assertFalse(any("release-stop" in cmd for cmd in self.commands()))

    def test_schema_refusal_suggests_newest_matching_backup(self):
        first, newest = self.backup(), self.backup()
        self.runner.db = "newer\n"
        error = self.assertCode(39, lambda: self.executor.rollback(TAG, self.flags))
        self.assertIn("--restore-backup " + newest, error.message)
        self.assertNotIn("--restore-backup " + first, error.message)
        self.assertFalse(any("release-stop" in cmd for cmd in self.commands()))

    def test_dirty_image_only_refuses_before_images_or_network(self):
        self.executor.state.write_current({"stage": "migration_started"})
        self.assertCode(41, lambda: self.executor.rollback(TAG, self.flags))
        self.assertEqual(self.runner.calls, [])

    def test_hostile_backup_ids_refuse_before_any_commands(self):
        for identifier in ("", "../x", "/tmp/x", "x\n", "20260101T000000Z-" + TAG + "\n",
                           "20260101T000000Z-v01.0.0",
                           "20260101T000000Z-v" + "1" * 300 + ".0.0"):
            self.assertCode(40, lambda: self.executor.rollback(TAG, self.restore_flags(identifier)))
        self.assertEqual(self.runner.calls, [])

    def test_manifest_checksum_revision_dataset_and_timestamp_refuse_before_quiesce(self):
        identifier = self.backup()
        folder = self.executor.backup_path(identifier)
        path = folder / "manifest.json"
        original = json.loads(path.read_bytes())
        for changes in ({"db_revision_before": "older"}, {"dataset": "other"}, {"created_at": "not-time"},
                        {"files": {"mysql.sql": {}}}):
            path.write_text(json.dumps(original | changes))
            self.assertCode(40, lambda: self.executor.rollback(TAG, self.restore_flags(identifier)))
        path.write_text(json.dumps(original))
        (folder / "mysql.sql").write_text("corrupted")
        self.assertCode(40, lambda: self.executor.rollback(TAG, self.restore_flags(identifier)))
        self.assertFalse(any("release-stop" in cmd for cmd in self.commands()))
        self.assertFalse(any(c[3] is not None and "mysql" in c[0] for c in self.runner.calls))

    def test_same_size_backup_corruption_refuses_before_mutation(self):
        identifier = self.backup()
        folder = self.executor.backup_path(identifier)
        for name in ("mysql.sql", "checkpoint.db", "archive.db", "chats.db"):
            with self.subTest(file=name):
                path = folder / name
                original = path.read_bytes()
                corrupted = original[:-1] + bytes([original[-1] ^ 1])
                self.assertEqual(len(corrupted), len(original))
                self.assertNotEqual(corrupted, original)
                try:
                    path.write_bytes(corrupted)
                    self.assert_backup_refused_before_mutation(identifier)
                finally:
                    path.write_bytes(original)

    def test_wrong_manifest_digest_refuses_intact_backup_before_mutation(self):
        identifier = self.backup()
        folder = self.executor.backup_path(identifier)
        path = folder / "manifest.json"
        original = path.read_bytes()
        for name in ("mysql.sql", "checkpoint.db", "archive.db", "chats.db"):
            with self.subTest(file=name):
                manifest = json.loads(original)
                record = manifest["files"][name]
                digest = record["sha256"]
                record["sha256"] = ("1" if digest[0] == "0" else "0") + digest[1:]
                try:
                    path.write_text(json.dumps(manifest))
                    self.assert_backup_refused_before_mutation(identifier)
                finally:
                    path.write_bytes(original)

    def test_missing_listed_backup_file_refuses_before_mutation(self):
        identifier = self.backup()
        folder = self.executor.backup_path(identifier)
        for name in ("mysql.sql", "checkpoint.db", "archive.db", "chats.db"):
            with self.subTest(file=name):
                path = folder / name
                original = path.read_bytes()
                try:
                    path.unlink()
                    self.assert_backup_refused_before_mutation(identifier)
                finally:
                    path.write_bytes(original)

    def test_extra_unlisted_backup_file_refuses_before_mutation(self):
        identifier = self.backup()
        folder = self.executor.backup_path(identifier)
        (folder / "unlisted.sql").write_bytes(b"unlisted backup content")
        self.assert_backup_refused_before_mutation(identifier)

    def test_recorded_absent_sqlite_store_validates_without_creating_file(self):
        identifier = self.backup()
        folder = self.executor.backup_path(identifier)
        manifest_path = folder / "manifest.json"
        original = manifest_path.read_bytes()
        for name in ("checkpoint.db", "archive.db", "chats.db"):
            with self.subTest(file=name):
                path = folder / name
                data = path.read_bytes()
                manifest = json.loads(original)
                manifest["files"][name].update({"present": False, "size": 0, "sha256": None})
                try:
                    path.unlink()
                    manifest_path.write_text(json.dumps(manifest))
                    validated = self.executor.validate_backup_set(identifier)
                    records = validated["files"]
                    assert isinstance(records, dict)
                    record = records[name]
                    assert isinstance(record, dict)
                    self.assertIs(record["present"], False)
                    self.assertFalse(path.exists())
                finally:
                    path.write_bytes(data)
                    manifest_path.write_bytes(original)

    def test_explicit_restore_orders_safety_mysql_sqlite_verify_then_recreate(self):
        self.attach_http()
        identifier = self.backup()
        self.runner.db = "newer\n"
        seen = []
        def observe(command):
            if "release-stop" in command:
                self.assertEqual(self.executor.state.read_history()[-1]["event"], "started")
            if "/sqlite_backup.py restore" in command:
                self.assertEqual(self.executor.state.read_current()["stage"], "migration_started")
            if "release-start" in command or "release-up" in command:
                self.assertNotIn("stage", self.executor.state.read_current())
            seen.append(command)
        self.runner.observer = observe
        self.executor.rollback(TAG, self.restore_flags(identifier))
        calls = self.runner.calls
        mysql = next(i for i, c in enumerate(calls) if "mysql" in c[0] and c[3] is not None)
        safety = next(i for i, c in enumerate(calls) if "mysqldump" in c[0])
        sqlite = [i for i, c in enumerate(calls) if "/sqlite_backup.py restore" in " ".join(c[0])]
        self.assertLess(safety, mysql)
        self.assertEqual(len(sqlite), 3)
        self.assertLess(mysql, min(sqlite))
        self.assertTrue(any("heads" in " ".join(c[0]) for c in calls[max(sqlite) + 1:]))
        event = self.executor.state.read_history()[-1]
        self.assertEqual(event["backup_id"], identifier)
        safety_id = event["safety_backup_id"]
        assert isinstance(safety_id, str)
        self.assertTrue(safety_id.endswith("-pre-restore"))
        self.assertEqual(event["db_revision_before"], "newer")
        self.assertEqual(event["db_revision_after"], REVISION)
        self.assertIn("all MySQL and SQLite writes after this time will be discarded; a safety copy is kept at ",
                      "\n".join(self.output))
        for name in ("checkpoints.db", "conversations.db", "chats.db"):
            with sqlite3.connect(self.root / "vm/backend/checkpoints" / name) as conn:
                self.assertEqual(conn.execute("SELECT id FROM fixture").fetchall(), [(7,)])

    def test_dirty_restore_clears_marker_after_proof_and_records_recovery_kind(self):
        self.attach_http()
        identifier = self.backup()
        self.runner.db = "newer\n"
        self.executor.state.write_current({"stage": "migration_started", "migration_backup_id": "old-marker"})
        self.executor.rollback(TAG, self.restore_flags(identifier))
        state = self.executor.state.read_current()
        self.assertNotIn("stage", state)
        self.assertNotIn("migration_backup_id", state)
        last = state["last_successful"]
        assert isinstance(last, dict)
        self.assertEqual(last["kind"], "rollback-restore-after-dirty")
        self.assertEqual(state["unaudited"], [])

    def test_mysql_failure_or_interrupt_retains_guard_and_never_reports_success(self):
        identifier = self.backup()
        for fault in ("failure", "interrupt", "timeout"):
            with self.subTest(fault=fault):
                self.runner.restore_fault = fault
                code, out, err = self.invoke(["rollback", TAG, "--restore-backup", identifier, "--yes"])
                self.assertEqual(code, 40, err)
                self.assertNotIn("success", out.lower())
                self.assertNotIn("fixture-secret", out + err)
                self.assertEqual(self.executor.state.read_current()["stage"], "migration_started")
                self.assertFalse(any("release-up" in cmd for cmd in self.commands()))
                self.assertEqual(self.executor.state.read_history()[-1]["exit_code"], 40)
        self.runner.restore_fault = ""
        self.assertEqual(self.invoke(["rollback", TAG, "--yes"])[0], 41)

    def test_live_or_image_head_mismatch_keeps_services_stopped_and_marker(self):
        identifier = self.backup()
        for boundary in ("live", "heads"):
            with self.subTest(boundary=boundary):
                self.runner.restore_revision = "wrong" if boundary == "live" else REVISION
                self.runner.heads = "wrong (head)" if boundary == "heads" else REVISION + " (head)"
                self.assertCode(40, lambda: self.executor.rollback(TAG, self.restore_flags(identifier)))
                self.assertEqual(self.executor.state.read_current()["stage"], "migration_started")
                self.assertFalse(any("release-start" in cmd or "release-up" in cmd for cmd in self.commands()))

    def test_restore_decline_or_no_tty_cannot_write_databases(self):
        identifier = self.backup()
        flags = d.parser().parse_args(["rollback", TAG, "--restore-backup", identifier])
        for tty, answer in ((False, "yes"), (True, "y"), (True, "no")):
            with self.subTest(tty=tty, answer=answer), mock.patch("sys.stdin.isatty", return_value=tty), \
                    mock.patch("builtins.input", return_value=answer):
                self.assertCode(40, lambda: self.executor.rollback(TAG, flags))
        self.assertFalse(any("mysqldump" in cmd or "/sqlite_backup.py restore" in cmd for cmd in self.commands()))
        self.assertFalse(any(c[3] is not None and "mysql" in c[0] for c in self.runner.calls))

    def test_safety_backup_failure_never_restores_and_preserves_dirty_marker(self):
        identifier = self.backup()
        self.executor.state.write_current({"stage": "migration_started"})
        self.runner.fail = "mysqldump"
        self.assertCode(35, lambda: self.executor.rollback(TAG, self.restore_flags(identifier)))
        self.assertEqual(self.executor.state.read_current()["stage"], "migration_started")
        self.assertFalse(any("/sqlite_backup.py restore" in cmd for cmd in self.commands()))

    def test_terminal_audit_failure_preserves_restore_error(self):
        identifier = self.backup()
        self.runner.restore_fault = "failure"
        append = self.executor.state.append_history
        def failed(event):
            if event["event"] == "failed":
                raise OSError(errno.ENOSPC, "fixture-secret")
            append(event)
        with mock.patch.object(self.executor.state, "append_history", side_effect=failed):
            error = self.assertCode(40, lambda: self.executor.rollback(TAG, self.restore_flags(identifier)))
        self.assertIn("secondary", error.message)
        self.assertEqual(self.executor.state.read_current()["stage"], "migration_started")

    def test_failed_recovery_output_cannot_mask_primary_restore_failure(self):
        identifier = self.backup()
        self.runner.restore_fault = "failure"
        def broken_output(message):
            if message.startswith("Recovery:"):
                raise OSError(errno.ENOSPC, "fixture-secret")
            self.output.append(message)
        self.executor.emit = broken_output
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertCode(40, lambda: self.executor.rollback(TAG, self.restore_flags(identifier)))
        self.assertEqual(self.executor.state.read_current()["stage"], "migration_started")

    def test_interrupted_quiesce_has_no_restore_and_can_be_retried(self):
        identifier = self.backup()
        self.runner.interrupt = "release-stop"
        self.assertCode(34, lambda: self.executor.rollback(TAG, self.restore_flags(identifier)))
        self.assertNotIn("stage", self.executor.state.read_current())
        self.assertFalse(any(c[3] is not None and "mysql" in c[0] for c in self.runner.calls))
        self.runner.interrupt = ""
        self.attach_http()
        self.executor.rollback(TAG, self.restore_flags(identifier))
        self.assertEqual(self.executor.state.read_history()[-1]["event"], "success")

    def test_interrupted_sqlite_restore_retains_dirty_guard_until_explicit_retry(self):
        identifier = self.backup()
        self.runner.db = "newer\n"
        self.runner.interrupt = "/sqlite_backup.py restore /backup/archive.db"
        self.assertCode(40, lambda: self.executor.rollback(TAG, self.restore_flags(identifier)))
        self.assertEqual(self.executor.state.read_current()["stage"], "migration_started")
        self.assertCode(41, lambda: self.executor.rollback(TAG, self.flags))
        self.runner.interrupt = ""
        self.attach_http()
        self.executor.rollback(TAG, self.restore_flags(identifier))
        last = self.executor.state.read_history()[-1]
        self.assertEqual(last["event"], "success")
        self.assertEqual(last["kind"], "rollback-restore-after-dirty")

    def test_dirty_recovery_commit_survives_failed_audit_then_reconciles(self):
        self.attach_http()
        identifier = self.backup()
        self.executor.state.write_current({"stage": "migration_started"})
        append = self.executor.state.append_history
        def failed(event):
            if event["event"] == "success":
                raise OSError(errno.ENOSPC, "fixture-secret")
            append(event)
        err = io.StringIO()
        with mock.patch.object(self.executor.state, "append_history", side_effect=failed), \
                contextlib.redirect_stderr(err):
            self.executor.rollback(TAG, self.restore_flags(identifier))
        state = self.executor.state.read_current()
        committed = state["last_successful"]
        self.assertEqual(state["unaudited"], [committed])
        self.assertNotIn("stage", state)
        self.assertIn("success", "\n".join(self.output))
        self.assertIn("WARNING", err.getvalue())
        self.executor.reconcile_attempts()
        self.assertEqual(self.executor.state.read_history()[-1], committed)
        self.assertEqual(self.executor.state.read_current()["unaudited"], [])

    def test_safety_pruning_keeps_explicit_older_restore_set(self):
        self.attach_http()
        identifier = self.backup()
        backups = self.executor.state.path / "backups"
        for i in range(6):
            folder = backups / f"20260201T00000{i}Z-{TAG}"
            folder.mkdir()
            (folder / "manifest.json").write_text("{}")
        self.executor.rollback(TAG, self.restore_flags(identifier))
        self.assertTrue((backups / identifier / "mysql.sql").is_file())
        event = self.executor.state.read_history()[-1]
        self.assertEqual(event["event"], "success")
        safety_id = event["safety_backup_id"]
        assert isinstance(safety_id, str)
        self.assertTrue((backups / safety_id / "mysql.sql").is_file())

    def test_missing_duplicate_or_symlink_manifest_fails_before_stop(self):
        identifier = self.backup()
        folder = self.executor.backup_path(identifier)
        path = folder / "manifest.json"
        for content in (None, b'{"tag":"v1.2.3","tag":"v1.2.3"}', b"[]" ,
                        b"x" * (d.RELEASE_MAX_BYTES + 1)):
            with self.subTest(content=None if content is None else len(content)):
                path.unlink(missing_ok=True)
                if content is not None:
                    path.write_bytes(content)
                self.assertCode(40, lambda: self.executor.rollback(TAG, self.restore_flags(identifier)))
        path.unlink()
        path.symlink_to(folder / "mysql.sql")
        self.assertCode(40, lambda: self.executor.rollback(TAG, self.restore_flags(identifier)))
        self.assertFalse(any("release-stop" in cmd for cmd in self.commands()))

    def test_interactive_exact_yes_permits_restore(self):
        self.attach_http()
        identifier = self.backup()
        flags = d.parser().parse_args(["rollback", TAG, "--restore-backup", identifier])
        with mock.patch("sys.stdin.isatty", return_value=True), mock.patch("builtins.input", return_value="yes"):
            self.executor.rollback(TAG, flags)
        self.assertEqual(self.executor.state.read_history()[-1]["event"], "success")

    def test_failed_smoke_does_not_publish_rollback_success(self):
        server = self.attach_http()
        previous: dict[str, d.JSON] = {"tag": "v0.1.0"}
        self.executor.state.write_current({"last_successful": previous})
        server.chat_list.pop("next_cursor")
        self.assertCode(38, lambda: self.executor.rollback(TAG, self.flags))
        self.assertEqual(self.executor.state.read_current()["last_successful"], previous)
        self.assertEqual(self.executor.state.read_history()[-1]["event"], "failed")
        self.assertNotIn("success", "\n".join(self.output))


class Response(io.BytesIO):
    def __init__(self, data, *, length=None):
        super().__init__(data)
        self.headers = {} if length is None else {"Content-Length": str(length)}
        self.read_sizes = []

    def read(self, size: int | None = -1):
        self.read_sizes.append(size)
        return super().read(-1 if size is None else size)


def redirect_error(url: str) -> urllib.error.HTTPError:
    headers = Message()
    headers["Location"] = url
    return urllib.error.HTTPError(ASSET, 302, "redirect", headers, None)


class TransportTest(unittest.TestCase):
    def fetch_with_response(self, response):
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch("urllib.request.build_opener", return_value=opener):
            result = d.URLFetcher().fetch(ASSET, limit=65536, timeout=30)
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 30)
        return result

    def test_content_length_limit_rejected_before_body_read(self):
        response = Response(b"small", length=65537)
        with self.assertRaises(d.DeployError):
            self.fetch_with_response(response)
        self.assertEqual(response.read_sizes, [])

    def test_missing_content_length_uses_bounded_read(self):
        response = Response(b"x" * 200000)
        with self.assertRaises(d.DeployError):
            self.fetch_with_response(response)
        self.assertEqual(response.read_sizes, [65537])

    def test_exact_asset_limit_is_accepted(self):
        self.assertEqual(self.fetch_with_response(Response(b"x" * 65536)), b"x" * 65536)

    def test_redirect_to_local_or_plain_http_is_rejected_before_following(self):
        for url in ("file:///secret", "http://127.0.0.1/secret", "https://untrusted.invalid/secret"):
            with self.subTest(url=url):
                opener = mock.Mock()
                opener.open.side_effect = redirect_error(url)
                with mock.patch("urllib.request.build_opener", return_value=opener):
                    with self.assertRaises(d.DeployError):
                        d.URLFetcher().fetch(ASSET, limit=65536, timeout=30)
                self.assertEqual(opener.open.call_count, 1)

    def test_github_asset_redirect_is_followed_with_bounded_timeout(self):
        opener = mock.Mock()
        redirected = "https://release-assets.githubusercontent.com/asset"
        opener.open.side_effect = [
            redirect_error(redirected), Response(b"data")]
        with mock.patch("urllib.request.build_opener", return_value=opener):
            self.assertEqual(d.URLFetcher().fetch(ASSET, limit=65536, timeout=30), b"data")
        self.assertEqual(opener.open.call_count, 2)
        self.assertTrue(all(call.kwargs["timeout"] > 0 for call in opener.open.call_args_list))

    def test_redirect_loop_is_bounded(self):
        opener = mock.Mock()
        opener.open.side_effect = redirect_error(ASSET)
        with mock.patch("urllib.request.build_opener", return_value=opener):
            with self.assertRaises(d.DeployError):
                d.URLFetcher().fetch(ASSET, limit=65536, timeout=30)
        self.assertLessEqual(opener.open.call_count, 6)


class GeneratedEnvDecodingTest(unittest.TestCase):
    """The executor reads back exactly what webreport/generate_env.py wrote."""

    # Each value is a valid configured password; together they cover the generator's quoting.
    PASSWORDS = (
        "has'quote",
        '"edge"',
        "'",
        "back\\slash a\\'b",
        "tail\\",
        "  #hash # $HOME ${X} k=v==  ",
        "\u0443\u043d\u0438 \u043a\u043e\u0434 \u00fc\u2028line",
        "mix '\"\\ #$= \u00fc ",
    )

    def generate(self, password: str) -> Path:
        """Run the real generator over a copied tree whose MySQL URL carries the password."""
        temp = tempfile.TemporaryDirectory(prefix="bdvrd-f2-env-test-")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for relative in ("webreport/generate_env.py", "bd_shared/config.py"):
            (root / relative).parent.mkdir(exist_ok=True)
            (root / relative).write_bytes((PROJECT_ROOT / relative).read_bytes())
        url = "mysql+pymysql://durak:" + urllib.parse.quote(password, safe="") + "@mysql:3306/games"
        config = (PROJECT_ROOT / "bd_shared" / "config.toml").read_text(encoding="utf-8").splitlines(keepends=True)
        (root / "bd_shared" / "config.toml").write_text(
            "".join(f'docker_url = "{url}"\n' if line.startswith("docker_url = ") else line for line in config),
            encoding="utf-8")
        env = {key: value for key, value in os.environ.items() if key not in ("BD_CONFIG_FILE", "BD_CONFIG_LOCAL_FILE")}
        env["PYTHONPATH"] = str(root)
        completed = subprocess.run([sys.executable, str(root / "webreport" / "generate_env.py")], cwd=root, env=env,
                                   capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(completed.returncode, 0, "environment generator failed")
        return root

    def executor(self, root: Path, runner: FakeRunner) -> d.Executor:
        data = metadata_bytes()
        return d.Executor(root, {"BD_DEPLOY_STATE_DIR": str(root / "state")}, runner,
                          FakeFetcher(release(data), data))

    def test_generated_mysql_password_reaches_the_client_unchanged(self):
        for password in self.PASSWORDS:
            with self.subTest(password=ascii(password)):
                runner = FakeRunner()
                executor = self.executor(self.generate(password), runner)
                with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
                    self.assertEqual(executor.live_db_revision(), REVISION)
                argv, _, child_env, _, _ = runner.calls[-1]
                self.assertEqual(child_env["MYSQL_PWD"], password)
                self.assertEqual(argv[-1], "games")
                self.assertTrue(all(password not in arg for arg in argv))
                self.assertNotIn("MYSQL_PWD", executor.env)
                self.assertEqual(out.getvalue() + err.getvalue(), "")

    def test_generated_http_ports_are_read_from_the_unquoted_form(self):
        executor = self.executor(self.generate("plain"), FakeRunner())
        self.assertEqual(executor.ports(), ("http://127.0.0.1:28000", "http://127.0.0.1:28501"))

    def test_undecodable_mysql_environment_is_a_clean_executor_failure(self):
        root = self.generate("plain")
        (root / "webreport" / ".env.mysql").write_bytes(b"MYSQL_DATABASE='games'\nMYSQL_ROOT_PASSWORD='\xff\xfe'\n")
        runner = FakeRunner()
        with self.assertRaises(d.DeployError) as caught:
            self.executor(root, runner).live_db_revision()
        self.assertEqual(caught.exception.exit_code, 31)
        self.assertEqual(runner.calls, [])


if __name__ == "__main__":
    unittest.main()
