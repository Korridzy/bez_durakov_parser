"""Server-local release selection and shared deployment plumbing (standard library only).

Runner and Fetcher are the two external boundaries. Operational stages are owned by
the subsequent deployment todos; they must not report success before implementation.
history.jsonl is an append-only event log; current.json holds attempt, last_successful
and the durable migration stage. Selection never publishes a successful deployment.
"""

import argparse
import contextlib
import datetime
import fcntl
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import NoReturn, Protocol, TextIO, TypeAlias

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from deploy import release_metadata as rm  # noqa: E402

JSON: TypeAlias = None | bool | int | float | str | list["JSON"] | dict[str, "JSON"]
TAG_RE = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
DIGEST_REF_RE = re.compile(r"[A-Za-z0-9./:_-]+@sha256:[0-9a-f]{64}")
REVISION_RE = re.compile(r"[A-Za-z0-9_]{1,32}")
RELEASE_MAX_BYTES = 1024 * 1024
NETWORK_TIMEOUT = 30
COMMAND_TIMEOUT = 120
PULL_TIMEOUT = 1800

# Codes are stable across the bootstrap, executor and later operational stages.
EXIT_CODES = {
    2: "E_USAGE", 3: "E_LOCKED", 4: "E_PREFLIGHT",
    10: "E_RELEASE_NOT_FOUND", 11: "E_RELEASE_NOT_STABLE", 12: "E_RELEASE_ASSET",
    13: "E_METADATA_MARKER", 14: "E_METADATA_SCHEMA", 15: "E_TAG_COMMIT",
    16: "E_RELEASE_FETCH", 17: "E_RELEASE_COMPOSE", 18: "E_IMAGE_PULL",
    19: "E_IMAGE_REVISION", 20: "E_IMAGE_INSPECT", 21: "E_ALEMBIC_HEAD",
    22: "E_METADATA_CHANGED", 23: "E_STATE", 24: "E_RELEASE_RESPONSE",
    30: "E_DEPLOY_FAILED", 31: "E_MIGRATION_PLAN", 32: "E_MIGRATION_APPROVAL_REQUIRED",
    33: "E_MIGRATION_DECLINED", 34: "E_QUIESCE", 35: "E_BACKUP",
    36: "E_MIGRATION_FAILED", 37: "E_RECREATE", 38: "E_SMOKE",
    39: "E_ROLLBACK_SCHEMA", 40: "E_RESTORE", 41: "E_DEPLOYMENT_DIRTY",
    42: "E_NOT_IMPLEMENTED",
}


class DeployError(Exception):
    def __init__(self, exit_code: int, message: str):
        super().__init__(message)
        self.exit_code = exit_code
        self.error = EXIT_CODES[exit_code]
        self.message = message


class Runner(Protocol):
    def run(self, argv: Sequence[str], *, cwd: Path, env: Mapping[str, str],
            input: str | None = None, timeout: int = COMMAND_TIMEOUT) -> subprocess.CompletedProcess[str]: ...


class Fetcher(Protocol):
    def fetch(self, url: str, *, limit: int, timeout: int) -> bytes: ...


class SubprocessRunner:
    def run(self, argv: Sequence[str], *, cwd: Path, env: Mapping[str, str],
            input: str | None = None, timeout: int = COMMAND_TIMEOUT) -> subprocess.CompletedProcess[str]:
        # Capture, never echo raw subprocess output: it may contain generated credentials.
        return subprocess.run(argv, cwd=cwd, env=env, input=input, timeout=timeout,
                              text=True, capture_output=True, check=False)


def check_url(url: str, *, allow_file: bool = False) -> None:
    parsed = urllib.parse.urlsplit(url)
    if allow_file and parsed.scheme == "file" and not parsed.netloc:
        return
    if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.hostname not in {"api.github.com", "github.com", "objects.githubusercontent.com",
                                       "release-assets.githubusercontent.com"}):
        raise DeployError(16, "release URL or redirect is not an allowed GitHub HTTPS URL")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class URLFetcher:
    def __init__(self, *, allow_file: bool = False):
        self.allow_file = allow_file

    def fetch(self, url: str, *, limit: int, timeout: int) -> bytes:
        # urllib's automatic redirect following could open a local file or an arbitrary
        # network target before we inspect the final URL. Validate every hop instead.
        opener = urllib.request.build_opener(NoRedirect())
        for _ in range(6):
            check_url(url, allow_file=self.allow_file and _ == 0)
            request = urllib.request.Request(url, headers={
                "Accept": "application/vnd.github+json", "User-Agent": "webreport-deploy"})
            try:
                with opener.open(request, timeout=timeout) as response:
                    length = response.headers.get("Content-Length")
                    if length is not None and (not length.isdecimal() or int(length) > limit):
                        raise DeployError(16, "release response exceeds size limit or has an invalid length")
                    data = response.read(limit + 1)
                    if len(data) > limit:
                        raise DeployError(16, "release response exceeds size limit")
                    return data
            except urllib.error.HTTPError as error:
                if error.code not in (301, 302, 303, 307, 308):
                    raise
                location = error.headers.get("Location")
                error.close()
                if not location:
                    raise DeployError(16, "release redirect has no location") from None
                url = urllib.parse.urljoin(url, location)
        raise DeployError(16, "release redirect limit exceeded")


def _pairs(pairs: list[tuple[str, JSON]]) -> dict[str, JSON]:
    result: dict[str, JSON] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ValueError("non-finite JSON number")


def json_object(data: bytes, code: int, message: str) -> dict[str, JSON]:
    try:
        obj = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, RecursionError):
        raise DeployError(code, message) from None
    if not isinstance(obj, dict):
        raise DeployError(code, message)
    return obj


def valid_tag(tag: str) -> str:
    if len(tag) > 128 or not TAG_RE.fullmatch(tag):
        raise DeployError(2, "tag must be vMAJOR.MINOR.PATCH")
    return tag


class State:
    def __init__(self, root: Path, env: Mapping[str, str]):
        vm = Path(env.get("BD_VM_DIR") or str(root / "vm"))
        self.path = Path(env.get("BD_DEPLOY_STATE_DIR") or str(vm / "deploy")).resolve()
        self.env = env

    def initialize(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name in ("releases", "backups", "logs"):
            (self.path / name).mkdir(exist_ok=True, mode=0o700)
        (self.path / "history.jsonl").touch(mode=0o600, exist_ok=True)

    @contextlib.contextmanager
    def lock(self) -> Iterator[None]:
        if "BD_DEPLOY_LOCK_FD" in self.env:
            yield
            return
        with (self.path / "lock").open("a") as handle:
            os.chmod(handle.name, 0o600)
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise DeployError(3, "deployment lock is held") from None
            yield

    def read_current(self) -> dict[str, JSON]:
        path = self.path / "current.json"
        if not path.exists():
            return {}
        with path.open("rb") as handle:
            data = handle.read(RELEASE_MAX_BYTES + 1)
        if len(data) > RELEASE_MAX_BYTES:
            raise DeployError(23, "current deployment state exceeds size limit")
        return json_object(data, 23, "current deployment state is invalid")

    def write_current(self, current: dict[str, JSON]) -> None:
        self.write_atomic(self.path / "current.json", (json.dumps(current, sort_keys=True) + "\n").encode())

    def append_history(self, event: dict[str, JSON]) -> None:
        with (self.path / "history.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def write_atomic(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as handle:
                tmp = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
            # Migration markers must survive a crash after rename.
            fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)


class Executor:
    def __init__(self, root: Path, env: Mapping[str, str], runner: Runner, fetcher: Fetcher):
        self.root, self.env, self.runner, self.fetcher = root, dict(env), runner, fetcher
        self.state = State(root, env)

    def command(self, argv: Sequence[str], code: int, message: str, *,
                input: str | None = None, timeout: int = COMMAND_TIMEOUT) -> str:
        try:
            result = self.runner.run(argv, cwd=self.root, env=self.env, input=input, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            raise DeployError(code, message) from None
        if result.returncode:
            raise DeployError(code, message)
        return result.stdout

    def fetch(self, url: str, limit: int, *, release_request: bool = False) -> bytes:
        try:
            check_url(url, allow_file=bool(self.env.get("BD_DEPLOY_RELEASE_FILE")))
            return self.fetcher.fetch(url, limit=limit, timeout=NETWORK_TIMEOUT)
        except urllib.error.HTTPError as error:
            missing = release_request and error.code == 404
            error.close()
            raise DeployError(10 if missing else 16,
                              "release not found" if missing else "release request failed") from None
        except (OSError, ValueError, urllib.error.URLError):
            raise DeployError(16, "release request failed or timed out") from None

    def select(self, tag: str) -> rm.ReleaseMetadata:
        tag = valid_tag(tag)
        repo = self.env.get("BD_DEPLOY_REPO") or rm.DEFAULT_REPOSITORY
        if not REPO_RE.fullmatch(repo):
            raise DeployError(2, "BD_DEPLOY_REPO must be owner/repository")
        local = self.env.get("BD_DEPLOY_RELEASE_FILE")
        if local:
            with Path(local).open("rb") as handle:
                raw = handle.read(RELEASE_MAX_BYTES + 1)
            if len(raw) > RELEASE_MAX_BYTES:
                raise DeployError(24, "local release response exceeds size limit")
        else:
            raw = self.fetch(f"https://api.github.com/repos/{repo}/releases/tags/{tag}",
                             RELEASE_MAX_BYTES, release_request=True)
        payload = json_object(raw, 24, "release response is invalid JSON")
        if (type(payload.get("draft")) is not bool or type(payload.get("prerelease")) is not bool
                or payload.get("tag_name") != tag or not isinstance(payload.get("body"), str)):
            raise DeployError(24, "release response fields are invalid")
        if payload["draft"] or payload["prerelease"]:
            raise DeployError(11, "draft and prerelease deployments are not supported")
        assets = payload.get("assets")
        if not isinstance(assets, list) or any(not isinstance(asset, dict) for asset in assets):
            raise DeployError(24, "release assets are invalid")
        matches = [asset for asset in assets if isinstance(asset, dict) and asset.get("name") == rm.ASSET_NAME]
        if len(matches) != 1:
            raise DeployError(12, "release must have exactly one metadata asset")
        url = matches[0].get("browser_download_url")
        if not isinstance(url, str):
            raise DeployError(24, "release metadata asset URL is invalid")
        data = self.fetch(url, rm.MAX_BYTES)
        try:
            digest = rm.parse_marker(payload["body"])
        except rm.MetadataError:
            raise DeployError(13, "release must have exactly one metadata checksum marker") from None
        if rm.sha256_hex(data) != digest:
            raise DeployError(13, "metadata asset checksum does not match release body")
        try:
            metadata = rm.loads(data)
        except rm.MetadataError:
            raise DeployError(14, "release metadata schema is invalid") from None
        if metadata.version != tag or metadata.repository != repo:
            raise DeployError(15, "metadata version or repository does not match release")
        self.command(["git", "fetch", "--tags"], 15, "could not fetch release tags")
        commit = self.command(["git", "rev-parse", f"{tag}^{{commit}}"], 15, "could not resolve release tag").strip()
        if commit != metadata.source_commit or metadata.built_from_candidate_tag != "sha-" + commit:
            raise DeployError(15, "release tag commit differs from metadata")
        release_dir = self.state.path / "releases" / tag
        cached = release_dir / "metadata.json"
        if cached.exists():
            with cached.open("rb") as handle:
                old = handle.read(rm.MAX_BYTES + 1)
            if old != data:
                raise DeployError(22, "cached release metadata differs from the asset")
        compose = self.command(["git", "show", f"{tag}:webreport/docker-compose.yml"], 17,
                               "could not read release compose file")
        # Rendering is read-only. Safe defaults fill the two ports when selection
        # runs before generate-env; the source file is from the tag, not this checkout.
        original_env = self.env
        self.env = {"WEBREPORT_BACKEND_PORT": "28000", "WEBREPORT_FRONTEND_PORT": "28501", **original_env}
        try:
            config = self.command(["docker", "compose", "--project-directory", str(self.root / "webreport"),
                                   "-f", "-", "config", "--format", "json"], 17,
                                  "could not render release compose configuration", input=compose)
        finally:
            self.env = original_env
        rendered = json_object(config.encode(), 17, "release compose configuration is invalid")
        services = rendered.get("services")
        pins: dict[str, JSON] = {}
        for name in ("mysql", "litellm"):
            service = services.get(name) if isinstance(services, dict) else None
            ref = service.get("image") if isinstance(service, dict) else None
            if not isinstance(ref, str) or not DIGEST_REF_RE.fullmatch(ref):
                raise DeployError(17, "release infrastructure images must be digest-pinned")
            pins[name] = {"image": ref}
        for name, ref in metadata.images.items():
            self.command(["docker", "pull", ref], 18, "release image pull failed", timeout=PULL_TIMEOUT)
            inspection = self.command(["docker", "image", "inspect", ref, "--format", "{{json .}}"],
                                      20, "release image inspection failed")
            inspected = json_object(inspection.encode(), 19, "release image inspection is invalid")
            image_config = inspected.get("Config")
            labels = image_config.get("Labels") if isinstance(image_config, dict) else None
            label = labels.get("org.opencontainers.image.revision") if isinstance(labels, dict) else None
            if label != commit:
                raise DeployError(19, "release image revision label differs from source commit")
            pins[name] = {"image": ref}
        pin_file = release_dir / "compose.release.yml"
        self.state.write_atomic(pin_file, (json.dumps({"services": pins}, indent=2) + "\n").encode())
        heads = self.command(["make", "-s", "-C", str(self.root / "webreport"), "release-run",
                              f"RELEASE_COMPOSE={pin_file}", "SERVICE=backend",
                              "CMD=alembic -c /alembic/alembic.ini heads"], 21, "release Alembic heads failed")
        if not re.fullmatch(re.escape(metadata.alembic_revision) + r" \(head\)\s*", heads.strip()):
            raise DeployError(21, "release image must have exactly the metadata Alembic head")
        self.state.write_atomic(cached, data)
        return metadata

    def mysql_command(self, client: str, arguments: Sequence[str], *, input: str | None = None,
                      timeout: int = COMMAND_TIMEOUT, code: int = 31) -> subprocess.CompletedProcess[str]:
        """Run mysql/mysqldump with env-only credentials, database and optional restore input."""
        values: dict[str, str] = {}
        try:
            for line in (self.root / "webreport" / ".env.mysql").read_text().splitlines():
                key, sep, value = line.partition("=")
                if sep:
                    values[key.strip()] = value.strip().strip("'\"")
        except OSError:
            raise DeployError(code, "generated MySQL environment is unavailable") from None
        database, password = values.get("MYSQL_DATABASE"), values.get("MYSQL_ROOT_PASSWORD")
        if not database or password is None:
            raise DeployError(code, "generated MySQL database name or root password is missing")
        argv = ["docker", "compose", "--project-directory", str(self.root / "webreport"),
                "-f", str(self.root / "webreport" / "docker-compose.yml"), "exec", "-T",
                "-e", "MYSQL_PWD", "mysql", client, "-uroot", *arguments, database]
        try:
            return self.runner.run(argv, cwd=self.root, env={**self.env, "MYSQL_PWD": password},
                                   input=input, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            raise DeployError(code, "MySQL command failed or timed out") from None

    def live_db_revision(self) -> str | None:
        """Query the live database, independently of target-image migration files."""
        result = self.mysql_command("mysql", ["-N", "-e", "SELECT version_num FROM alembic_version"])
        if result.returncode:
            if re.search(r"\bERROR 1146\b", result.stderr):
                return None
            raise DeployError(31, "live database revision query failed")
        revision = result.stdout.strip()
        if not revision:
            return None
        if not REVISION_RE.fullmatch(revision):
            raise DeployError(31, "live database has an invalid or multiple revision result")
        return revision


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # argparse's default error echoes arbitrary arguments. Keep secrets out.
        raise DeployError(2, "invalid command or arguments; use --help")


def parser() -> Parser:
    cli = Parser(description="Server-local deployment executor")
    commands = cli.add_subparsers(dest="command", required=True)
    deploy = commands.add_parser("deploy")
    deploy.add_argument("tag", type=valid_tag)
    deploy.add_argument("--approve-migration", action="store_true")
    deploy.add_argument("--llm-smoke", action="store_true")
    deploy.add_argument("--yes", action="store_true")
    rollback = commands.add_parser("rollback")
    rollback.add_argument("tag", type=valid_tag)
    rollback.add_argument("--restore-backup")
    rollback.add_argument("--yes", action="store_true")
    rollback.add_argument("--llm-smoke", action="store_true")
    resolve = commands.add_parser("resolve-rollback-target")
    resolve.add_argument("tag", nargs="?", type=valid_tag)
    commands.add_parser("status")
    isolation = commands.add_parser("verify-db-isolation")
    isolation.add_argument("--container-probe", action="store_true")
    smoke = commands.add_parser("smoke")
    smoke.add_argument("--llm-smoke", action="store_true")
    commands.add_parser("select").add_argument("tag", type=valid_tag)
    return cli


def main(argv: Sequence[str] | None = None, *, root: Path = ROOT, env: Mapping[str, str] | None = None,
         runner: Runner | None = None, fetcher: Fetcher | None = None) -> int:
    environment = dict(os.environ if env is None else env)
    state = State(root, environment)
    log: TextIO | None = None
    help_output = io.StringIO()

    def emit(text: str, *, error: bool = False) -> None:
        print(text, file=sys.stderr if error else sys.stdout)
        if log is not None:
            log.write(text + "\n")
            log.flush()

    try:
        state.initialize()
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        # Only a validated tag may enter a log filename; invalid argv is never logged.
        args = list(sys.argv[1:] if argv is None else argv)
        tag = args[1] if len(args) > 1 and TAG_RE.fullmatch(args[1]) and len(args[1]) <= 128 else "cli"
        log_path = state.path / "logs" / f"{stamp}-{tag}.log"
        log = log_path.open("x", encoding="utf-8")
        os.chmod(log_path, 0o600)
        with contextlib.redirect_stdout(help_output):
            options = parser().parse_args(args)
        if options.command in ("deploy", "rollback") and environment.get("DATASET"):
            raise DeployError(2, "DATASET deployments are not supported by the executor")
        with state.lock():
            executor = Executor(root, environment, runner or SubprocessRunner(),
                                fetcher or URLFetcher(allow_file=bool(environment.get("BD_DEPLOY_RELEASE_FILE"))))
            if (options.command in ("deploy", "rollback") and state.read_current().get("stage") == "migration_started"
                    and not (options.command == "rollback" and options.restore_backup)):
                raise DeployError(41, "migration_started marker exists; explicit backup restore is required")
            match options.command:
                case "select":
                    metadata = executor.select(options.tag)
                    if environment.get("BD_DEPLOY_RELEASE_FILE"):
                        emit("WARNING: BD_DEPLOY_RELEASE_FILE rehearsal override bypassed GitHub", error=True)
                    emit(rm.dumps(metadata).decode().rstrip())
                case "resolve-rollback-target":
                    if not options.tag:
                        raise DeployError(2, "no rollback target")
                    emit(options.tag)
                case _:
                    raise DeployError(42, "not implemented in this todo; operational stages belong to todos 12-16")
        return 0
    except DeployError as error:
        emit(json.dumps({"exit_code": error.exit_code, "error": error.error, "message": error.message}), error=True)
        return error.exit_code
    except (OSError, UnicodeError):
        emit(json.dumps({"exit_code": 23, "error": EXIT_CODES[23], "message": "deployment state or local file I/O failed"}),
             error=True)
        return 23
    except SystemExit as exit:
        if help_output.getvalue():
            emit(help_output.getvalue().rstrip())
        return int(exit.code or 0)
    finally:
        if log is not None:
            log.close()


if __name__ == "__main__":
    sys.exit(main())
