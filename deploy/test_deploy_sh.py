"""Bootstrap tests for deploy/deploy.sh: rollback resolves its target under the deployment lock.

Each test copies the wrapper into a scratch Git checkout whose origin is a local bare
repository with two release tags. A fake `poetry` on PATH records every executor call and
whether the deployment lock was held at that moment. Nothing reaches Docker or GitHub.
"""

import fcntl
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

WRAPPER = Path(__file__).resolve().with_name("deploy.sh")
TIMEOUT = 60

# One tab-separated line per call: lock held by someone, inherited lock fd, file behind that
# fd, the exact tag checked out, and the arguments.
FAKE_POETRY = """#!/usr/bin/env bash
set -u
if [[ ! -e $BD_DEPLOY_STATE_DIR/lock ]]; then held=absent
elif flock -n "$BD_DEPLOY_STATE_DIR/lock" true; then held=no
else held=yes; fi
fd=${BD_DEPLOY_LOCK_FD:-}
target=''
[[ -n $fd ]] && target=$(readlink "/proc/$$/fd/$fd" || true)
tag=$(git describe --tags --exact-match 2>/dev/null || echo none)
printf '%s\\t%s\\t%s\\t%s\\t%s\\n' "$held" "$fd" "$target" "$tag" "$*" >>"$FAKE_POETRY_LOG"
if [[ ${4:-} == resolve-rollback-target ]]; then
    if [[ -n ${FAKE_RESOLVE_EXIT:-} ]]; then
        exit "$FAKE_RESOLVE_EXIT"
    fi
    printf '%s\\n' "${5:-${FAKE_RESOLVE_TARGET:-v1.0.0}}"
fi
"""


class RollbackLockTest(unittest.TestCase):
    def __init__(self, methodName="runTest"):
        super().__init__(methodName)
        self.temp = tempfile.TemporaryDirectory(prefix="bdvrd-deploy-sh-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo, self.state, self.log = self.base / "repo", self.base / "state", self.base / "poetry.log"
        self.env: dict[str, str] = {}

    def setUp(self):
        base = self.base
        origin, bin_dir = base / "origin.git", base / "bin"
        (self.repo / "deploy").mkdir(parents=True)
        (self.repo / "deploy" / "deploy.sh").write_bytes(WRAPPER.read_bytes())
        (self.repo / "deploy" / "deploy.sh").chmod(0o755)
        bin_dir.mkdir()
        (bin_dir / "poetry").write_text(FAKE_POETRY)
        (bin_dir / "poetry").chmod(0o755)
        self.env = {key: value for key, value in os.environ.items()
                    if key not in ("DATASET", "BD_DEPLOY_LOCK_FD", "BD_VM_DIR") and not key.startswith("GIT_")}
        self.env.update(PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}", BD_DEPLOY_STATE_DIR=str(self.state),
                        FAKE_POETRY_LOG=str(self.log), GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_AUTHOR_NAME="test", GIT_AUTHOR_EMAIL="test@example.invalid",
                        GIT_COMMITTER_NAME="test", GIT_COMMITTER_EMAIL="test@example.invalid")
        self.git("init", "--quiet", "--bare", str(origin), cwd=base)
        self.git("init", "--quiet")
        self.git("remote", "add", "origin", str(origin))
        for tag in ("v1.0.0", "v2.0.0", "v3.0.0"):
            (self.repo / "release.txt").write_text(tag)
            self.git("add", "--all")
            self.git("commit", "--quiet", "-m", tag)
            self.git("tag", tag)
        self.git("push", "--quiet", "--tags", "origin", "HEAD:refs/heads/main")

    def git(self, *args, cwd=None):
        subprocess.run(["git", *args], cwd=cwd or self.repo, env=self.env, check=True,
                       capture_output=True, timeout=TIMEOUT)

    def rollback(self, *args, **extra_env):
        return subprocess.run(["bash", str(self.repo / "deploy" / "deploy.sh"), "rollback", *args],
                              cwd=self.repo, env={**self.env, **extra_env}, capture_output=True,
                              text=True, timeout=TIMEOUT)

    def calls(self):
        if not self.log.exists():
            return []
        return [line.split("\t") for line in self.log.read_text().splitlines()]

    def head_tag(self):
        return subprocess.run(["git", "describe", "--tags", "--exact-match"], cwd=self.repo, env=self.env,
                              capture_output=True, text=True, timeout=TIMEOUT).stdout.strip()

    def test_target_is_resolved_and_executed_under_one_held_lock(self):
        lock = str(self.state / "lock")
        for args, resolve, execute in (
                (["--yes"], "run python deploy/deploy.py resolve-rollback-target",
                 "run python deploy/deploy.py rollback v1.0.0 --yes"),
                (["v2.0.0", "--restore-backup"], "run python deploy/deploy.py resolve-rollback-target v2.0.0",
                 "run python deploy/deploy.py rollback v2.0.0 --restore-backup")):
            with self.subTest(args=args):
                self.log.unlink(missing_ok=True)
                self.git("checkout", "--quiet", "--detach", "v3.0.0")
                result = self.rollback(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                tag = execute.split()[4]
                self.assertEqual(self.calls(), [["yes", "9", lock, "v3.0.0", resolve],
                                                ["yes", "9", lock, tag, execute]])
                self.assertEqual(self.head_tag(), tag)

    def test_a_held_lock_refuses_rollback_before_any_target_resolution(self):
        self.state.mkdir(mode=0o700)
        with open(self.state / "lock", "a") as holder:
            fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for args in ([], ["v2.0.0"]):
                with self.subTest(args=args):
                    self.log.unlink(missing_ok=True)
                    result = self.rollback(*args)
                    self.assertEqual(result.returncode, 3)
                    self.assertIn('"error":"E_LOCKED"', result.stderr)
                    self.assertEqual(self.calls(), [])
                    self.assertEqual(self.head_tag(), "v3.0.0")

    def test_resolver_failure_passes_its_code_through_without_checkout(self):
        for extra, expected in (({"FAKE_RESOLVE_EXIT": "23"}, 23), ({"FAKE_RESOLVE_TARGET": "not-a-tag"}, 2)):
            with self.subTest(extra=extra):
                self.log.unlink(missing_ok=True)
                result = self.rollback(**extra)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual([call[4] for call in self.calls()],
                                 ["run python deploy/deploy.py resolve-rollback-target"])
                self.assertEqual(self.head_tag(), "v3.0.0")
                with open(self.state / "lock", "a") as probe:
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_usage_errors_exit_2_without_taking_the_lock(self):
        for args in (["--bogus"], ["1.0.0"]):
            with self.subTest(args=args):
                result = self.rollback(*args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(self.calls(), [])
                self.assertFalse(self.state.exists())

    def test_make_fetch_dispatches_without_checkout_and_refuses_dataset(self):
        # Given the real root target in the isolated checkout.
        root_makefile = WRAPPER.parent.parent / "Makefile"
        (self.repo / "Makefile").write_bytes(root_makefile.read_bytes())
        # When invoked through Make, the wrapper must reach the fetch subcommand.
        result = subprocess.run(["make", "deploy-fetch-data"], cwd=self.repo, env=self.env,
                                capture_output=True, text=True, timeout=TIMEOUT)
        # Then no checkout happened and only the production subcommand was dispatched.
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([call[4] for call in self.calls()], ["run python deploy/deploy.py fetch-data"])
        self.assertEqual(self.head_tag(), "v3.0.0")
        self.log.unlink()
        result = subprocess.run(["make", "deploy-fetch-data", "DATASET=foreign"], cwd=self.repo, env=self.env,
                                capture_output=True, text=True, timeout=TIMEOUT)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
