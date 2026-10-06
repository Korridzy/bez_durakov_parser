"""Executor contract tests: subprocess and network boundaries never reach Docker or GitHub."""

import contextlib
import fcntl
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from typing import Any
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import deploy.deploy as d  # noqa: E402
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
        self.assertFailure(42, self.invoke(["rollback", TAG, "--restore-backup", "backup-id"]))

    def test_later_command_bodies_refuse_instead_of_claiming_success(self):
        for args in (["deploy", TAG], ["rollback", TAG], ["smoke"], ["status"]):
            with self.subTest(args=args):
                self.assertFailure(42, self.invoke(args))

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


if __name__ == "__main__":
    unittest.main()
