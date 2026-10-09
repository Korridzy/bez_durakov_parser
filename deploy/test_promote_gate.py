"""Gate tests for deploy/promote.sh: the default main gate and the first-rollout bootstrap opt-in.

BOOTSTRAP: this whole file belongs to the one-time first-rollout bootstrap; remove it with the
opt-in in promote.sh.

Each test builds a scratch bare origin with `main` and a diverged branch, tags both tips and
clones it. promote.sh runs from the clone, checked out at a tag, with the rehearsal gh shim
serving local release, CI run and job fixtures. A fake `docker` exits 1, so a gate that passes
fails later with E_CANDIDATE_MISSING, which tells it apart from a refused gate. Nothing reaches
GitHub, a registry or Docker.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

DEPLOY = Path(__file__).resolve().parent
PROMOTE = DEPLOY / "promote.sh"
SHIM = DEPLOY / "rehearsal" / "gh_shim.py"
TIMEOUT = 60
BRANCH = "issue-42-first-rollout"
API = "http://" + ".".join(str(part) for part in (127, 0, 0, 1)) + ":9"
PASSED = "E_CANDIDATE_MISSING: backend candidate is missing or unreadable\n"
NOT_ON_MAIN = "E_CI_NOT_APPROVED: tag commit is not on main\n"
NOT_APPROVED_COMMIT = "E_CI_NOT_APPROVED: tag commit is not the approved bootstrap commit\n"
NO_MAIN_RUN = "E_CI_NOT_APPROVED: no successful main push CI run\n"
NO_APPROVED_RUN = "E_CI_NOT_APPROVED: no successful approved push CI run\n"
BAD_COMMIT = "E_USAGE: BD_PROMOTE_BOOTSTRAP_COMMIT must be a 40-hex commit\n"
BAD_BRANCH = "E_USAGE: BD_PROMOTE_BOOTSTRAP_BRANCH must name the approved branch\n"


class PromoteGateTest(unittest.TestCase):
    def __init__(self, methodName="runTest"):
        super().__init__(methodName)
        self.temp = tempfile.TemporaryDirectory(prefix="bdvrd-promote-gate-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.clone, self.state = self.base / "clone", self.base / "state"
        self.env: dict[str, str] = {}
        self.commits: dict[str, str] = {}

    def setUp(self):
        base, work, origin, bin_dir = self.base, self.base / "work", self.base / "origin.git", self.base / "bin"
        bin_dir.mkdir()
        (bin_dir / "docker").write_text("#!/bin/sh\nexit 1\n")
        (bin_dir / "gh").write_text(f'#!/bin/sh\nexec "{sys.executable}" "{SHIM}" "$@"\n')
        for name in ("docker", "gh"):
            (bin_dir / name).chmod(0o755)
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(("GIT_", "GITHUB_", "BD_"))}
        self.env.update(PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}", SHIM_STATE=str(self.state),
                        GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_AUTHOR_NAME="test", GIT_AUTHOR_EMAIL="test@example.invalid",
                        GIT_COMMITTER_NAME="test", GIT_COMMITTER_EMAIL="test@example.invalid")
        (work / "deploy").mkdir(parents=True)
        (work / "deploy" / "promote.sh").write_bytes(PROMOTE.read_bytes())
        self.git(base, "init", "--quiet", "--bare", str(origin))
        self.git(work, "init", "--quiet", "--initial-branch=main")
        self.git(work, "add", "--all")
        self.git(work, "commit", "--quiet", "-m", "base")
        self.git(work, "tag", "v1.0.0")
        self.git(work, "checkout", "--quiet", "-b", BRANCH)
        (work / "branch.txt").write_text("only on the branch\n")
        self.git(work, "add", "--all")
        self.git(work, "commit", "--quiet", "-m", "branch only")
        self.git(work, "tag", "v2.0.0")
        self.git(work, "checkout", "--quiet", "main")
        (work / "main.txt").write_text("only on main\n")
        self.git(work, "add", "--all")
        self.git(work, "commit", "--quiet", "-m", "main only")
        self.git(work, "push", "--quiet", "--tags", str(origin), "main", BRANCH)
        self.git(base, "clone", "--quiet", str(origin), str(self.clone))
        for ref in ("v1.0.0", "v2.0.0", "origin/main"):
            self.commits[ref] = self.git(self.clone, "rev-parse", ref + "^{commit}")

    def git(self, cwd, *args):
        return subprocess.run(["git", *args], cwd=cwd, env=self.env, check=True, capture_output=True,
                              text=True, timeout=TIMEOUT).stdout.strip()

    def promote(self, tag, run_branch, **extra_env):
        self.git(self.clone, "checkout", "--quiet", "--detach", tag)
        self.state.mkdir(exist_ok=True)
        (self.state / "calls.jsonl").unlink(missing_ok=True)
        (self.state / "release.json").write_text(json.dumps(
            {"tag_name": tag, "draft": False, "prerelease": False, "body": "", "assets": []}))
        (self.state / "runs.json").write_text(json.dumps({"workflow_runs": [
            {"id": 77, "run_attempt": 1, "head_sha": self.commits[tag], "head_branch": run_branch,
             "event": "push", "status": "completed", "conclusion": "success",
             "created_at": "2026-10-06T00:00:00Z"}]}))
        (self.state / "jobs.json").write_text(json.dumps({"jobs": [
            {"name": "suite", "conclusion": "success",
             "steps": [{"name": "Push candidate images", "conclusion": "success"}]}]}))
        return subprocess.run(["bash", str(self.clone / "deploy" / "promote.sh"), "--tag", tag,
                               "--api-base", API, "--gh-bin", str(self.base / "bin" / "gh")],
                              cwd=self.base, env={**self.env, **extra_env}, capture_output=True,
                              text=True, timeout=TIMEOUT)

    def api_paths(self):
        calls = self.state / "calls.jsonl"
        lines = calls.read_text().splitlines() if calls.exists() else []
        return [next(arg for arg in json.loads(line) if arg.startswith("http"))[len(API):] for line in lines]

    def runs_path(self, tag, branch_query):
        return (f"/repos/Korridzy/bez_durakov_parser/actions/workflows/ci.yml/runs?head_sha="
                f"{self.commits[tag]}{branch_query}&event=push&status=success&per_page=10")

    def assert_refused(self, result, message, paths):
        self.assertEqual((result.returncode, result.stderr), (1, message))
        self.assertNotIn("BOOTSTRAP", result.stdout)
        self.assertEqual(self.api_paths(), paths)

    def test_default_gate_refuses_a_branch_only_commit(self):
        for extra in ({}, {"BD_PROMOTE_BOOTSTRAP_COMMIT": "", "BD_PROMOTE_BOOTSTRAP_BRANCH": BRANCH}):
            with self.subTest(extra=extra):
                result = self.promote("v2.0.0", BRANCH, **extra)
                self.assert_refused(result, NOT_ON_MAIN, ["/repos/Korridzy/bez_durakov_parser/releases/tags/v2.0.0"])

    def test_default_gate_still_accepts_a_main_commit_unchanged(self):
        release = "/repos/Korridzy/bez_durakov_parser/releases/tags/v1.0.0"
        runs = self.runs_path("v1.0.0", "&branch=main")
        jobs = "/repos/Korridzy/bez_durakov_parser/actions/runs/77/attempts/1/jobs?per_page=100"
        # The release workflow always sets the branch; an empty commit keeps the default gate.
        for extra in ({}, {"BD_PROMOTE_BOOTSTRAP_COMMIT": "", "BD_PROMOTE_BOOTSTRAP_BRANCH": BRANCH}):
            with self.subTest(extra=extra):
                result = self.promote("v1.0.0", "main", **extra)
                self.assertEqual((result.returncode, result.stderr, result.stdout), (1, PASSED, ""))
                self.assertEqual(self.api_paths(), [release, runs, jobs])
        with self.subTest("a run from another branch is not main CI evidence"):
            result = self.promote("v1.0.0", BRANCH)
            self.assert_refused(result, NO_MAIN_RUN, [release, runs])

    def test_bootstrap_refuses_any_other_commit(self):
        for approved in (self.commits["v1.0.0"], self.commits["origin/main"], "0" * 40):
            with self.subTest(approved=approved):
                result = self.promote("v2.0.0", BRANCH, BD_PROMOTE_BOOTSTRAP_COMMIT=approved,
                                      BD_PROMOTE_BOOTSTRAP_BRANCH=BRANCH)
                self.assert_refused(result, NOT_APPROVED_COMMIT,
                                    ["/repos/Korridzy/bez_durakov_parser/releases/tags/v2.0.0"])

    def test_malformed_bootstrap_settings_are_usage_errors_before_any_api_call(self):
        commit = self.commits["v2.0.0"]
        for value in ("1", commit[:39], commit + "0", commit.upper(), commit + "\n", " " + commit, "HEAD"):
            with self.subTest(commit=value):
                result = self.promote("v2.0.0", BRANCH, BD_PROMOTE_BOOTSTRAP_COMMIT=value,
                                      BD_PROMOTE_BOOTSTRAP_BRANCH=BRANCH)
                self.assert_refused(result, BAD_COMMIT, [])
        for value in (None, "", "-x", "a b", "a..b", "x/", "/x", "a//b", BRANCH + "\n", 'x" or true',
                      "x$(id)", "refs/heads/.x"):
            with self.subTest(branch=value):
                extra = {"BD_PROMOTE_BOOTSTRAP_COMMIT": commit}
                if value is not None:
                    extra["BD_PROMOTE_BOOTSTRAP_BRANCH"] = value
                result = self.promote("v2.0.0", BRANCH, **extra)
                self.assert_refused(result, BAD_BRANCH, [])

    def test_bootstrap_requires_a_push_run_from_the_exact_branch(self):
        commit = self.commits["v2.0.0"]
        for run_branch in ("main", "other", BRANCH + "-x", BRANCH.upper(), "issue-42"):
            with self.subTest(run_branch=run_branch):
                result = self.promote("v2.0.0", run_branch, BD_PROMOTE_BOOTSTRAP_COMMIT=commit,
                                      BD_PROMOTE_BOOTSTRAP_BRANCH=BRANCH)
                self.assertEqual((result.returncode, result.stderr), (1, NO_APPROVED_RUN))
                self.assertEqual(self.api_paths(), ["/repos/Korridzy/bez_durakov_parser/releases/tags/v2.0.0",
                                                    self.runs_path("v2.0.0", "")])

    def test_bootstrap_passes_the_gate_for_the_approved_commit_and_branch(self):
        commit = self.commits["v2.0.0"]
        result = self.promote("v2.0.0", BRANCH, BD_PROMOTE_BOOTSTRAP_COMMIT=commit,
                              BD_PROMOTE_BOOTSTRAP_BRANCH=BRANCH)
        self.assertEqual((result.returncode, result.stderr), (1, PASSED))
        self.assertEqual(result.stdout, f"BOOTSTRAP: promoting non-main commit {commit} "
                                        f"from branch {BRANCH} approved by BD_PROMOTE_BOOTSTRAP_COMMIT\n")
        self.assertEqual(self.api_paths(), [
            "/repos/Korridzy/bez_durakov_parser/releases/tags/v2.0.0", self.runs_path("v2.0.0", ""),
            "/repos/Korridzy/bez_durakov_parser/actions/runs/77/attempts/1/jobs?per_page=100"])


if __name__ == "__main__":
    unittest.main()
