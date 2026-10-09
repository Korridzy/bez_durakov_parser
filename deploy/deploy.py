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
import ipaddress
from html.parser import HTMLParser
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, NoReturn, Protocol, TextIO, TypeAlias, TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
APPLICATION_SERVICES = ("backend", "frontend", "data_collector")
INFRA_NAMES = ("mysql", "litellm")
SERVICES = (*INFRA_NAMES, *APPLICATION_SERVICES)
BACKUP_ID_RE = re.compile(r"[0-9]{8}T[0-9]{6,12}Z-(?:v[0-9]+\.[0-9]+\.[0-9]+|pre-restore)")


class Preparation(TypedDict):
    backup_id: str
    db_revision_before: str | None
    db_revision_after: str
    pending: list[str]

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


class Clock(Protocol):
    def monotonic(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...
    def now(self) -> datetime.datetime: ...


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def now(self) -> datetime.datetime:
        return datetime.datetime.now(datetime.timezone.utc)


class LocalHTTP:
    """Bounded, loopback-only transport, with no redirects or environment proxies."""

    def request(self, method: str, url: str, *, body: dict[str, JSON] | None = None,
                timeout: float = 10) -> tuple[int, dict[str, str], bytes]:
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
                or parsed.username or parsed.password or parsed.fragment):
            raise DeployError(38, "smoke request must stay on the loopback origin")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        request = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"}, method=method)
        try:
            response = opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            data = response.read(RELEASE_MAX_BYTES + 1)
            if len(data) > RELEASE_MAX_BYTES:
                raise DeployError(38, "smoke response exceeds size limit")
            return response.code, dict(response.headers), data


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls: list[str] = []
        self.html = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "html":
            self.html = True
        key = "src" if tag == "script" else "href" if tag == "link" else None
        if key is not None:
            self.urls.extend(value for name, value in attrs if name == key and value is not None)


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


def backup_id_valid(identifier: str) -> bool:
    if len(identifier) > 160 or not BACKUP_ID_RE.fullmatch(identifier):
        return False
    label = identifier.split("-", 1)[1]
    return label == "pre-restore" or (len(label) <= 128 and bool(TAG_RE.fullmatch(label)))


def manifest_timestamp(manifest: Mapping[str, JSON], code: int) -> datetime.datetime:
    """Backup manifest header contract shared by the executor (code 40) and status (code 23)."""
    tag, revision, stamp = (manifest.get(key) for key in ("tag", "db_revision_before", "created_at"))
    if (not isinstance(tag, str) or not TAG_RE.fullmatch(tag) or
            not (revision is None or isinstance(revision, str) and REVISION_RE.fullmatch(revision)) or
            not isinstance(stamp, str)):
        raise DeployError(code, "backup manifest header is invalid")
    try:
        timestamp = datetime.datetime.fromisoformat(stamp)
    except ValueError:
        raise DeployError(code, "backup manifest header is invalid") from None
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise DeployError(code, "backup timestamp must have a timezone")
    return timestamp


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
        current = json_object(data, 23, "current deployment state is invalid")
        for key in ("attempt", "last_successful"):
            if key in current:
                record = current[key]
                tag = record.get("tag") if isinstance(record, dict) else None
                if not isinstance(tag, str) or not TAG_RE.fullmatch(tag):
                    raise DeployError(23, "current deployment record is invalid")
        if "stage" in current and current["stage"] != "migration_started":
            raise DeployError(23, "current deployment stage is invalid")
        if "unaudited" in current:
            pending = current["unaudited"]
            if not isinstance(pending, list):
                raise DeployError(23, "unaudited deployment outcomes are invalid")
            for outcome in pending:
                if (not isinstance(outcome, dict) or
                        any(not isinstance(outcome.get(key), str)
                            for key in ("attempt_id", "tag", "commit", "kind", "finished_at")) or
                        outcome["kind"] not in ("deploy", "rollback", "rollback-restore-after-dirty")):
                    raise DeployError(23, "unaudited deployment outcome is invalid")
        return current

    def write_current(self, current: dict[str, JSON]) -> None:
        self.write_atomic(self.path / "current.json", (json.dumps(current, sort_keys=True) + "\n").encode())

    def append_history(self, event: dict[str, JSON]) -> None:
        with (self.path / "history.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def read_history(self) -> list[dict[str, JSON]]:
        events = []
        with (self.path / "history.jsonl").open("rb") as handle:
            for line in handle:
                if len(line) > RELEASE_MAX_BYTES:
                    raise DeployError(23, "deployment history event exceeds size limit")
                events.append(json_object(line, 23, "deployment history is invalid"))
        return events

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


def read_generated_env(path: Path) -> dict[str, str]:
    """Read a webreport/generate_env.py file back into the values it was generated from.

    The generator writes KEY='value' with each ' escaped as \\' and nothing else changed, or
    a plain KEY=value. Lines end only at \\n, since a value may hold other line separators.
    """
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").split("\n"):
        key, separator, value = line.partition("=")
        if not separator or key.startswith("#"):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == "'":
            value = value[1:-1].replace("\\'", "'")
        values[key.strip()] = value
    return values


class Executor:
    def __init__(self, root: Path, env: Mapping[str, str], runner: Runner, fetcher: Fetcher, *,
                 clock: Clock | None = None, output: Callable[[str], None] = print):
        self.root, self.env, self.runner, self.fetcher = root, dict(env), runner, fetcher
        self.state = State(root, env)
        self.pin_file: Path | None = None
        self.metadata: rm.ReleaseMetadata | None = None
        self.step = "preflight"
        self.clock = clock or SystemClock()
        self.http = LocalHTTP()
        self.emit = output
        self.attempt_record: dict[str, JSON] = {}

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
        heads = self.command(["make", "-s", "--no-print-directory", "-C", str(self.root / "webreport"), "release-run",
                              f"RELEASE_COMPOSE={pin_file}", "SERVICE=backend",
                              "CMD=alembic -c /alembic/alembic.ini heads"], 21, "release Alembic heads failed")
        if not re.fullmatch(re.escape(metadata.alembic_revision) + r" \(head\)\s*", heads.strip()):
            raise DeployError(21, "release image must have exactly the metadata Alembic head")
        self.state.write_atomic(cached, data)
        self.pin_file, self.metadata = pin_file, metadata
        return metadata

    def mysql_command(self, client: str, arguments: Sequence[str], *, input: str | None = None,
                      timeout: int = COMMAND_TIMEOUT, code: int = 31) -> subprocess.CompletedProcess[str]:
        """Run mysql/mysqldump with env-only credentials, database and optional restore input."""
        try:
            values = read_generated_env(self.root / "webreport" / ".env.mysql")
        except (OSError, UnicodeError):
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

    def now(self) -> datetime.datetime:
        return self.clock.now()

    def release_make(self, target: str, *, services: Sequence[str] = (), cmd: Sequence[str] = (),
                     run_args: Sequence[str] = (), compose_args: Sequence[str] = (),
                     code: int = 4, timeout: int = COMMAND_TIMEOUT) -> str:
        """Use Make's allowlisted wrapper, without directory chatter in parsed output."""
        if any(name not in SERVICES for name in services):
            raise DeployError(2, "service is not allowlisted")
        if target == "release-up" and any(name not in APPLICATION_SERVICES for name in services):
            raise DeployError(2, "application release cannot recreate infrastructure")
        argv = ["make", "-s", "--no-print-directory", "-C", str(self.root / "webreport"), target]
        if self.pin_file is not None:
            argv.append(f"RELEASE_COMPOSE={self.pin_file}")
        elif target == "release-run":
            argv.append("ALLOW_DEV_COMPOSE=1")
        if services:
            key = "SERVICE" if target == "release-run" else "SERVICES"
            if key == "SERVICE" and len(services) != 1:
                raise DeployError(2, "release-run requires one service")
            argv.append(f"{key}={' '.join(services)}")
        if cmd:
            argv.append("CMD=" + shlex.join(cmd))
        if run_args:
            argv.append("RUN_ARGS=" + shlex.join(run_args))
        if compose_args:
            key = "CONFIG_ARGS" if target == "release-config" else "ARGS"
            argv.append(key + "=" + shlex.join(compose_args))
        return self.command(argv, code, f"{self.step}: {target} failed or timed out", timeout=timeout)

    def config(self) -> dict[str, JSON]:
        """Read only operational settings; never print private overlay contents."""
        try:
            with (self.root / "bd_shared" / "config.toml").open("rb") as handle:
                config = tomllib.load(handle)
            overlay = self.root / "bd_shared" / "config.local.toml"
            if overlay.is_file():
                with overlay.open("rb") as handle:
                    local = tomllib.load(handle)
                for key, value in local.items():
                    if isinstance(value, dict) and isinstance(config.get(key), dict):
                        config[key].update(value)
                    else:
                        config[key] = value
            return config
        except (OSError, ValueError):
            raise DeployError(4, "deployment configuration is unreadable or invalid") from None

    def store_paths(self) -> dict[str, Path]:
        vm = Path(self.env.get("BD_VM_DIR") or str(self.root / "vm")).resolve()
        web = self.config().get("webreport", {})
        if not isinstance(web, dict):
            raise DeployError(4, "webreport configuration must be a table")
        paths = {}
        for name, default in (("checkpoint", "checkpoints.db"), ("archive", "conversations.db"), ("chats", "chats.db")):
            value = self.env.get(f"BD_{name.upper()}_DB_PATH") or web.get(f"{name}_db_path", "/data/" + default)
            if not isinstance(value, str) or re.search(r"[$`\n\r\x00]", value):
                raise DeployError(4, "SQLite store path is invalid")
            path = Path(value)
            if not path.is_absolute() or ".." in path.parts or not path.is_relative_to("/data") or path == Path("/data"):
                raise DeployError(4, "SQLite store must be inside the /data bind mount")
            paths[name] = vm / "backend" / "checkpoints" / path.relative_to("/data")
        if len(set(paths.values())) != 3:
            raise DeployError(4, "SQLite stores must use distinct files")
        return paths

    def containers(self, *, code: int = 4) -> list[dict[str, JSON]]:
        raw = self.release_make("compose", compose_args=["ps", "-a", "--format", "json"], code=code).strip()
        try:
            values = json.loads(raw) if raw.startswith("[") else [json.loads(line) for line in raw.splitlines()]
        except (ValueError, RecursionError):
            raise DeployError(code, f"{self.step}: invalid container listing") from None
        if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
            raise DeployError(code, f"{self.step}: invalid container listing")
        return values

    def container_ids(self, *, code: int = 4) -> dict[str, str]:
        ids: dict[str, str] = {}
        for item in self.containers(code=code):
            name, identifier = item.get("Service"), item.get("ID")
            if name in SERVICES and isinstance(name, str) and isinstance(identifier, str) and identifier:
                if name in ids:
                    raise DeployError(code, "one backend/container per service is required")
                ids[name] = identifier
        return ids

    def preflight(self, meta: rm.ReleaseMetadata, flags: argparse.Namespace) -> dict[str, str]:
        self.step = "preflight"
        self.metadata = meta
        self.pin_file = self.state.path / "releases" / meta.version / "compose.release.yml"
        if not (self.root / "bd_shared" / "config.local.toml").is_file():
            raise DeployError(4, "bd_shared/config.local.toml must exist as a file")
        version = self.command(["docker", "compose", "version", "--short"], 4, "Docker Compose version unavailable").strip()
        match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?", version)
        if match is None or tuple(int(part) for part in match.groups()) < (2, 24, 4):
            raise DeployError(4, "Docker Compose >= 2.24.4 is required")
        self.release_make("generate-env")
        self.release_make("release-config", compose_args=["-q"])
        ids = self.container_ids()
        pins = json_object(self.pin_file.read_bytes(), 4, "release pins are invalid").get("services")
        for name in ("mysql", "litellm"):
            if name not in ids:
                raise DeployError(4, "mysql/litellm image differs from the release pin or is missing; run the documented infra procedure")
            pin = pins.get(name) if isinstance(pins, dict) else None
            ref = pin.get("image") if isinstance(pin, dict) else None
            if not isinstance(ref, str) or not DIGEST_REF_RE.fullmatch(ref):
                raise DeployError(4, "infrastructure pin is invalid")
            self.command(["docker", "pull", ref], 4, "infrastructure pin pull failed", timeout=PULL_TIMEOUT)
            running = self.command(["docker", "container", "inspect", ids[name], "--format", "{{.Image}}"],
                                   4, "infrastructure container inspection failed").strip()
            pinned = self.command(["docker", "image", "inspect", ref, "--format", "{{.Id}}"],
                                  4, "infrastructure image inspection failed").strip()
            if not running or running != pinned:
                raise DeployError(4, "mysql/litellm image differs from the release pin or is missing; run the documented infra procedure")
        if "backend" not in ids:
            self.emit("First install: no backend container")
        self.store_paths()
        vm = Path(self.env.get("BD_VM_DIR") or str(self.root / "vm"))
        try:
            if vm.exists() and not os.access(vm, os.R_OK | os.X_OK):
                raise DeployError(4, "BD_VM_DIR is unreadable")
            used = 0
            for output in (
                self.release_make("release-run", services=["backend"], cmd=["du", "-sb", "/data"]),
                self.command(["docker", "compose", "--project-directory", str(self.root / "webreport"),
                              "-f", str(self.root / "webreport/docker-compose.yml"), "exec", "-T",
                              "mysql", "du", "-sb", "/var/lib/mysql"], 4, "BD_VM_DIR mysql data size is unreadable"),
            ):
                used += int(output.split()[0])
            if shutil.disk_usage(self.state.path).free < 2 * used:
                raise DeployError(4, "free disk must be at least twice the MySQL and SQLite data size")
        except (OSError, ValueError, IndexError):
            raise DeployError(4, "BD_VM_DIR data size or free disk is unreadable") from None
        for module in ("agent.knowledge_cli", "agent.tools_cli"):
            self.release_make("release-run", services=["backend"], cmd=["python", "-m", module])
        fetch = self.config().get("xlsm_fetch", {})
        if not isinstance(fetch, dict):
            raise DeployError(4, "collector configuration must be a table")
        try:
            time_value, timezone_value = fetch.get("start_time", "20:00"), fetch.get("timezone", "Europe/Belgrade")
            if not isinstance(time_value, str) or not isinstance(timezone_value, str):
                raise DeployError(4, "collector schedule must contain strings")
            hour, minute = (int(part) for part in time_value.split(":"))
            now = self.now().astimezone(ZoneInfo(timezone_value))
            start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            window = any(-600 <= (now - (start + datetime.timedelta(days=offset))).total_seconds() <= 1800
                         for offset in (-1, 0, 1))
        except (ValueError, TypeError, AttributeError, ZoneInfoNotFoundError):
            raise DeployError(4, "collector schedule is invalid") from None
        if window:
            self.emit("WARNING: near the collector fetch window; --yes is required")
            if not flags.yes:
                raise DeployError(4, "collector fetch window requires --yes")
        return {name: ids[name] for name in ("mysql", "litellm")}

    def migration_plan(self, meta: rm.ReleaseMetadata) -> tuple[str | None, list[str]]:
        self.step = "migration_plan"
        current = self.live_db_revision()
        if current == meta.alembic_revision:
            return current, []
        if current is None:
            tables = self.mysql_command("mysql", ["-N", "-e", "SHOW TABLES"])
            if tables.returncode or tables.stdout.strip():
                raise DeployError(31, "unversioned nonempty database requires an explicit baseline")
            self.emit("First install: empty database; full upgrade")
        history = self.release_make("release-run", services=["backend"],
                                    cmd=["alembic", "-c", "/alembic/alembic.ini", "history",
                                         "-r", f"{current or 'base'}:{meta.alembic_revision}"], code=31)
        edges = re.findall(r"^\s*(<base>|[A-Za-z0-9_]+)\s*->\s*([A-Za-z0-9_]+)\b", history, re.MULTILINE)
        # Alembic prints newest first. Trace the ancestry rather than trusting
        # success exit status or assuming a nonempty history means compatibility.
        ancestor = meta.alembic_revision
        pending = []
        while ancestor != (current or "<base>"):
            parents = [parent for parent, child in edges if child == ancestor]
            if len(parents) != 1 or ancestor in pending:
                raise DeployError(31, "live revision is not an ancestor of the release revision")
            pending.append(ancestor)
            ancestor = parents[0]
        return current, list(reversed(pending))

    def approve_migrations(self, pending: Sequence[str], flags: argparse.Namespace) -> None:
        self.step = "migration_approval"
        if not pending:
            return
        self.emit("Pending migrations: " + ", ".join(pending))
        if flags.approve_migration:
            return
        if not sys.stdin.isatty():
            raise DeployError(32, "pending migrations require --approve-migration without a TTY")
        if input("Apply these migrations? [y/N] ").strip().lower() != "y":
            raise DeployError(33, "migration declined")

    def backup_path(self, identifier: str) -> Path:
        if not backup_id_valid(identifier):
            raise DeployError(40, "invalid backup id")
        path = self.state.path / "backups" / identifier
        if path.is_symlink() or path.resolve().parent != (self.state.path / "backups").resolve():
            raise DeployError(40, "backup id escapes backup directory")
        return path

    def sqlite_command(self, operation: str, src: str, dst: str | None, folder: Path, *,
                       code: int = 35) -> dict[str, JSON]:
        cmd = ["python", "/sqlite_backup.py", operation, src]
        if dst is not None:
            cmd.append(dst)
        raw = self.release_make("release-run", services=["backend"], cmd=cmd,
                                run_args=["-v", f"{self.root}/deploy/sqlite_backup.py:/sqlite_backup.py:ro",
                                          "-v", f"{folder}:/backup"], code=code, timeout=PULL_TIMEOUT)
        result = json_object(raw.encode(), code, "SQLite helper returned invalid file information")
        size = result.get("size")
        if type(result.get("present")) is not bool or type(size) is not int or size < 0:
            raise DeployError(code, "SQLite helper returned invalid file information")
        digest = result.get("sha256")
        if result["present"] and (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise DeployError(code, "SQLite helper returned invalid checksum")
        if not result["present"] and (result["size"] != 0 or digest is not None):
            raise DeployError(code, "SQLite helper returned invalid absent-store information")
        return result

    def take_backup_set(self, label: str, *, db_revision_before: str | None = None,
                        identifier: str | None = None, protected_backup_id: str | None = None) -> str:
        """Quiesced snapshot, reusable by rollback's pre-restore safety copy."""
        self.step = "backup"
        folder: Path | None = None
        created = False
        try:
            if label != "pre-restore":
                valid_tag(label)
            identifier = identifier or self.now().strftime("%Y%m%dT%H%M%S%fZ") + "-" + label
            folder = self.backup_path(identifier)
            folder.mkdir(mode=0o700)
            created = True
            result = self.mysql_command("mysqldump", [
                "--single-transaction", "--quick", "--routines", "--triggers", "--events", "--hex-blob",
                "--no-tablespaces", "--set-gtid-purged=OFF", "--add-drop-database", "--databases",
            ], code=35, timeout=PULL_TIMEOUT)
            if result.returncode or not result.stdout.strip():
                raise DeployError(35, "MySQL backup failed")
            data = result.stdout.encode()
            self.state.write_atomic(folder / "mysql.sql", data)
            files: dict[str, JSON] = {"mysql.sql": {"present": True, "sha256": rm.sha256_hex(data),
                                                  "size": len(data), "store": "mysql"}}
            vm_data = Path(self.env.get("BD_VM_DIR") or str(self.root / "vm")).resolve() / "backend/checkpoints"
            for name, path in self.store_paths().items():
                relative = path.relative_to(vm_data)
                dest = name + ".db"
                info = self.sqlite_command("backup", "/data/" + relative.as_posix(), "/backup/" + dest, folder)
                files[dest] = {**info, "store": name, "source": "/data/" + relative.as_posix()}
            manifest: dict[str, JSON] = {
                "tag": self.metadata.version if self.metadata is not None else label,
                "label": label, "created_at": self.now().isoformat(),
                "db_revision_before": db_revision_before, "files": files,
                "dataset": self.env.get("DATASET", ""),
            }
            self.state.write_atomic(folder / "manifest.json", (json.dumps(manifest, sort_keys=True) + "\n").encode())
            if self.attempt_record:
                self.attempt_record["backup_id"] = identifier
            self.prune_backups(protected_backup_ids=[identifier, *([protected_backup_id] if protected_backup_id else [])])
            return identifier
        except (DeployError, OSError, KeyboardInterrupt):
            message = "consistent backup failed"
            # A collision belongs to an existing snapshot, not this attempt.
            if created and folder is not None:
                try:
                    shutil.rmtree(folder)
                except OSError:
                    message += "; partial backup cleanup failed"
            raise DeployError(35, message) from None

    def prune_backups(self, *, protected_backup_ids: Sequence[str] = ()) -> None:
        protected = None
        for event in reversed(self.state.read_history()):
            if (event.get("kind") == "deploy" and event.get("backup_id")
                    and event.get("db_revision_before") != event.get("db_revision_after")):
                protected = event["backup_id"]
                break
        folders = sorted((p for p in (self.state.path / "backups").iterdir()
                          if p.is_dir() and not p.is_symlink() and BACKUP_ID_RE.fullmatch(p.name)
                          and (p / "manifest.json").is_file()), reverse=True)
        for folder in folders[5:]:
            if folder.name not in (protected, *protected_backup_ids):
                shutil.rmtree(folder)

    def backup_manifest(self, identifier: str) -> dict[str, JSON]:
        """Bounded manifest parsing, including the dataset and timestamp boundary."""
        folder = self.backup_path(identifier)
        try:
            path = folder / "manifest.json"
            if path.is_symlink():
                raise DeployError(40, "backup manifest must not be a symlink")
            with path.open("rb") as handle:
                data = handle.read(RELEASE_MAX_BYTES + 1)
            if len(data) > RELEASE_MAX_BYTES:
                raise DeployError(40, "backup manifest exceeds size limit")
            manifest = json_object(data, 40, "backup manifest is invalid")
            if manifest.get("dataset", "") != self.env.get("DATASET", ""):
                raise DeployError(40, "backup dataset differs from the configured dataset")
            timestamp = manifest_timestamp(manifest, 40)
            # Emit a normalized timestamp, never arbitrary manifest text.
            manifest["created_at"] = timestamp.isoformat()
            return manifest
        except (OSError, ValueError):
            raise DeployError(40, "backup manifest is unavailable or invalid") from None

    def validate_backup_set(self, identifier: str) -> dict[str, JSON]:
        """Validate every checksum before any restore; caller checks target revision."""
        folder = self.backup_path(identifier)
        manifest = self.backup_manifest(identifier)
        files = manifest.get("files")
        if not isinstance(files, dict) or set(files) != {"mysql.sql", "checkpoint.db", "archive.db", "chats.db"}:
            raise DeployError(40, "backup manifest file set is invalid")
        try:
            names = {path.name for path in folder.iterdir()}
        except OSError:
            raise DeployError(40, "backup directory is unavailable") from None
        expected_names = {"manifest.json"} | {
            name for name, record in files.items() if isinstance(record, dict) and record.get("present") is True
        }
        if names != expected_names:
            raise DeployError(40, "backup directory files differ from the manifest")
        expected_paths = self.store_paths()
        vm_data = Path(self.env.get("BD_VM_DIR") or str(self.root / "vm")).resolve() / "backend/checkpoints"
        for name, record in files.items():
            if (not isinstance(record, dict) or (folder / name).is_symlink() or
                    type(record.get("present")) is not bool or type(record.get("size")) is not int):
                raise DeployError(40, "backup file record is invalid")
            if name == "mysql.sql":
                try:
                    data = (folder / name).read_bytes()
                except OSError:
                    raise DeployError(40, "MySQL backup is unavailable") from None
                if not data.strip() or record.get("store") != "mysql":
                    raise DeployError(40, "MySQL backup record is invalid")
                actual: dict[str, JSON] = {"present": True, "size": len(data), "sha256": rm.sha256_hex(data)}
            else:
                store = name[:-3]
                source = "/data/" + expected_paths[store].relative_to(vm_data).as_posix()
                if record.get("source") != source or record.get("store") != store:
                    raise DeployError(40, "backup store paths differ from configured stores")
                actual = self.sqlite_command("describe", "/backup/" + name, None, folder, code=40)
            if any(record.get(key) != actual[key] for key in ("present", "size", "sha256")):
                raise DeployError(40, "backup checksum or size mismatch")
        return manifest

    def restore_backup_set(self, identifier: str) -> dict[str, JSON]:
        """Restore only an explicitly named, validated set. Caller owns approval."""
        manifest = self.validate_backup_set(identifier)
        folder = self.backup_path(identifier)
        result = self.mysql_command("mysql", [], input=(folder / "mysql.sql").read_text(),
                                    code=40, timeout=PULL_TIMEOUT)
        if result.returncode:
            raise DeployError(40, "MySQL backup restore failed")
        files = manifest["files"]
        assert isinstance(files, dict)
        for name in ("checkpoint.db", "archive.db", "chats.db"):
            record = files[name]
            assert isinstance(record, dict)
            source = record["source"]
            assert isinstance(source, str)
            self.sqlite_command("restore", "/backup/" + name, source, folder, code=40)
        return manifest

    def quiesce_backup_migrate(self, meta: rm.ReleaseMetadata, current: str | None,
                              pending: list[str]) -> Preparation:
        self.step = "quiesce"
        self.release_make("release-stop", services=["data_collector", "backend"], code=34, timeout=1500)
        try:
            backup_id = self.take_backup_set(meta.version, db_revision_before=current)
        except (DeployError, OSError, KeyboardInterrupt) as failure:
            message = failure.message if isinstance(failure, DeployError) else "consistent backup failed"
            try:
                self.release_make("release-start", services=["data_collector", "backend"], code=35)
            except (DeployError, OSError, KeyboardInterrupt):
                message += "; application services could not be restarted"
            raise DeployError(35, message) from None
        if pending:
            self.step = "migration"
            state = self.state.read_current()
            state["stage"] = "migration_started"
            state["migration_backup_id"] = backup_id
            self.state.write_current(state)
            if self.attempt_record:
                self.attempt_record["db_revision_after"] = None
            try:
                self.release_make("release-run", services=["backend"],
                                  cmd=["alembic", "-c", "/alembic/alembic.ini", "upgrade", meta.alembic_revision],
                                  code=36, timeout=PULL_TIMEOUT)
                actual_revision = self.live_db_revision()
                if self.attempt_record:
                    self.attempt_record["db_revision_after"] = actual_revision
                if actual_revision != meta.alembic_revision:
                    raise DeployError(36, "post-upgrade database revision differs from target")
            except DeployError:
                raise DeployError(36, "migration failed; marker retained, services stopped; explicitly restore the backup") from None
            state.pop("stage", None)
            state.pop("migration_backup_id", None)
            self.state.write_current(state)
        return {"backup_id": backup_id, "db_revision_before": current,
                "db_revision_after": meta.alembic_revision, "pending": pending}

    def prepare_deploy(self, meta: rm.ReleaseMetadata, flags: argparse.Namespace) -> Preparation:
        if self.state.read_current().get("stage") == "migration_started":
            raise DeployError(41, "migration_started marker exists; explicit backup restore is required")
        self.preflight(meta, flags)
        current, pending = self.migration_plan(meta)
        self.approve_migrations(pending, flags)
        return self.quiesce_backup_migrate(meta, current, pending)

    def affected_services(self, meta: rm.ReleaseMetadata) -> list[str]:
        self.step = "recreate_detection"
        ids = self.container_ids(code=37)
        affected = []
        for name in APPLICATION_SERVICES:
            if name not in ids:
                affected.append(name)
                continue
            running = self.command(["docker", "container", "inspect", ids[name], "--format", "{{.Image}}"],
                                   37, "recreate: container image inspection failed").strip()
            pinned = self.command(["docker", "image", "inspect", meta.images[name], "--format", "{{.Id}}"],
                                  37, "recreate: pinned image inspection failed").strip()
            label = self.command(["docker", "container", "inspect", ids[name], "--format",
                                  '{{index .Config.Labels "com.docker.compose.config-hash"}}'],
                                 37, "recreate: container configuration inspection failed").strip()
            expected = self.release_make("compose", compose_args=["config", "--hash=" + name], code=37).strip()
            pieces = expected.split()
            if len(pieces) != 2 or pieces[0] != name:
                raise DeployError(37, "recreate: invalid Compose service configuration hash")
            if not pinned or running != pinned or not label or label != pieces[1]:
                affected.append(name)
        return affected

    def ports(self) -> tuple[str, str]:
        try:
            values = read_generated_env(self.root / "webreport/.env")
            result = []
            for key in ("WEBREPORT_BACKEND_PORT", "WEBREPORT_FRONTEND_PORT"):
                value = self.env.get(key) or values.get(key)
                if value is None or not value.isdecimal() or not 1 <= int(value) <= 65535:
                    raise DeployError(38, f"{self.step}: generated HTTP port is invalid")
                result.append("http://127.0.0.1:" + value)
            return result[0], result[1]
        except (OSError, UnicodeError):
            raise DeployError(38, f"{self.step}: generated HTTP ports unavailable") from None

    def request(self, method: str, url: str, *, statuses: Sequence[int] = (200,),
                body: dict[str, JSON] | None = None, timeout: float = 10) -> bytes:
        try:
            status, _, data = self.http.request(method, url, body=body, timeout=timeout)
        except (OSError, ValueError, urllib.error.URLError, DeployError):
            raise DeployError(38, f"{self.step}: HTTP request failed or timed out") from None
        if status not in statuses:
            raise DeployError(38, f"{self.step}: unexpected HTTP status {status}")
        return data

    def request_json(self, method: str, url: str, *, statuses: Sequence[int] = (200,),
                     body: dict[str, JSON] | None = None, timeout: float = 10) -> JSON:
        data = self.request(method, url, statuses=statuses, body=body, timeout=timeout)
        try:
            return json.loads(data, object_pairs_hook=_pairs, parse_constant=_constant)
        except (ValueError, RecursionError):
            raise DeployError(38, f"{self.step}: invalid JSON response") from None

    def health(self, *, timeout: float = 10) -> tuple[bool, str]:
        backend, _ = self.ports()
        try:
            status, _, data = self.http.request("GET", backend + "/health", timeout=timeout)
            health = json_object(data, 38, "invalid health response")
        except (OSError, ValueError, urllib.error.URLError, DeployError):
            return False, "database/agents/llm_proxy health response unavailable"
        components = health.get("services")
        if not isinstance(components, dict):
            return False, "database/agents/llm_proxy component booleans missing"
        failed = [key for key in ("database", "agents", "llm_proxy") if components.get(key) is not True]
        good = status == 200 and health.get("status") == "healthy" and not failed
        # Do not echo response text or attacker-controlled component keys.
        return good, "database/agents/llm_proxy: " + (", ".join(failed) or "unexpected health status")

    def wait_ready(self) -> None:
        self.step = "readiness"
        deadline = self.clock.monotonic() + 180
        detail = "database/agents/llm_proxy unavailable"
        while self.clock.monotonic() < deadline:
            ready, detail = self.health(timeout=min(10, deadline - self.clock.monotonic()))
            if ready:
                return
            remaining = deadline - self.clock.monotonic()
            if remaining > 0:
                self.clock.sleep(min(2, remaining))
        raise DeployError(38, "readiness: backend not healthy within 180s; " + detail)

    def recreate_and_smoke(self, meta: rm.ReleaseMetadata, flags: argparse.Namespace, *,
                           before: Mapping[str, str] | None = None) -> list[str]:
        if before is None:
            before = {name: identifier for name, identifier in self.container_ids(code=37).items() if name in INFRA_NAMES}
        affected = self.affected_services(meta)
        self.step = "recreate_pull"
        if affected:
            self.release_make("release-pull", services=affected, code=37, timeout=PULL_TIMEOUT)
        self.step = "recreate_backend"
        self.release_make("release-up" if "backend" in affected else "release-start",
                          services=["backend"], code=37)
        self.wait_ready()
        self.step = "recreate_frontend"
        if "frontend" in affected:
            self.release_make("release-up", services=["frontend"], code=37)
        self.step = "recreate_collector"
        self.release_make("release-up" if "data_collector" in affected else "release-start",
                          services=["data_collector"], code=37)
        return self.smoke(meta, before=before, llm_smoke=flags.llm_smoke)

    def smoke(self, meta: rm.ReleaseMetadata | None, *, before: Mapping[str, str] | None = None,
              llm_smoke: bool = False, steps: Sequence[str] | None = None) -> list[str]:
        """Shared deploy/rollback/manual sequence. A subset is for explicit zero-spend QA."""
        self.step = "smoke"
        backend, frontend = self.ports()
        if meta is None:
            self.emit("dev smoke: no successful release state; using dev Compose")
            self.pin_file = None
        if before is None:
            ids = self.container_ids(code=38)
            before = {name: ids[name] for name in INFRA_NAMES if name in ids}
        requested = list(steps) if steps is not None else [f"S{i}" for i in range(1, 8 + int(llm_smoke))]
        if any(step not in {f"S{i}" for i in range(1, 9)} for step in requested):
            raise DeployError(2, "invalid smoke step")
        passed = []
        for step in requested:
            self.step = step
            match step:
                case "S1":
                    ready, detail = self.health()
                    if not ready:
                        raise DeployError(38, "S1: backend health failed; " + detail)
                case "S2":
                    if meta is None:
                        heads = self.release_make("release-run", services=["backend"],
                                                  cmd=["alembic", "-c", "/alembic/alembic.ini", "heads"], code=38)
                        match = re.fullmatch(r"([A-Za-z0-9_]{1,32}) \(head\)\s*", heads.strip())
                        if match is None:
                            raise DeployError(38, "S2: running backend must have one Alembic head")
                        target = match[1]
                    else:
                        target = meta.alembic_revision
                    try:
                        revision = self.live_db_revision()
                    except DeployError:
                        raise DeployError(38, "S2: database revision unavailable") from None
                    if revision != target:
                        raise DeployError(38, "S2: live database revision differs from backend head")
                case "S3":
                    data = self.request("GET", frontend + "/")
                    parser = Assets()
                    try:
                        parser.feed(data.decode("utf-8"))
                    except UnicodeError:
                        raise DeployError(38, "S3: frontend is not UTF-8 HTML") from None
                    if not parser.html or not parser.urls:
                        raise DeployError(38, "S3: frontend HTML or assets are missing")
                    for asset in parser.urls:
                        url = urllib.parse.urljoin(frontend + "/", asset)
                        if urllib.parse.urlsplit(url).netloc != urllib.parse.urlsplit(frontend).netloc:
                            raise DeployError(38, "S3: frontend asset leaves the frontend origin")
                        self.request("GET", url)
                case "S4":
                    if self.request("GET", frontend + "/health").strip() != b"ok":
                        raise DeployError(38, "S4: frontend health body is not ok")
                case "S5":
                    obj = self.request_json("GET", frontend + "/api/chats?limit=1")
                    if (not isinstance(obj, dict) or not isinstance(obj.get("items"), list)
                            or "next_cursor" not in obj
                            or not (obj["next_cursor"] is None or isinstance(obj["next_cursor"], str))):
                        raise DeployError(38, "S5: chat listing requires items and next_cursor")
                case "S6":
                    ids = self.container_ids(code=38)
                    if any(name not in before or name not in ids or before[name] != ids[name] for name in INFRA_NAMES):
                        raise DeployError(38, "S6: mysql/litellm container ids changed or are missing")
                case "S7":
                    if not any(item.get("Service") == "data_collector" and item.get("State") == "running"
                               for item in self.containers(code=38)):
                        raise DeployError(38, "S7: collector is not running")
                case "S8":
                    self.llm_smoke(frontend)
            passed.append(step)
            self.emit(step + " PASS")
        return passed

    def llm_smoke(self, frontend: str) -> None:
        self.step = "S8"
        try:
            timeout_value = self.config().get("webreport", {})
            question = (self.root / "deploy/smoke_question.txt").read_text(encoding="utf-8").strip()
        except (DeployError, OSError, UnicodeError):
            raise DeployError(38, "S8: smoke configuration or canned question unavailable") from None
        if not isinstance(timeout_value, dict):
            raise DeployError(38, "S8: agent timeout configuration invalid")
        timeout = timeout_value.get("agent_timeout_seconds", 120)
        if type(timeout) is not int or not 1 <= timeout <= 3600:
            raise DeployError(38, "S8: agent timeout configuration invalid")
        if not question:
            raise DeployError(38, "S8: canned smoke question missing")
        chat_id: str | None = None
        report_id: str | None = None
        saved = False
        active = False
        failure: DeployError | None = None
        request_id = uuid.uuid4().hex
        try:
            chat = self.request_json("POST", frontend + "/api/chats", statuses=[201], body={"title": "Deployment smoke"})
            chat_id = self.response_id(chat, "chat")
            chat_url = frontend + "/api/chats/" + chat_id
            # A lost/malformed response does not prove the server rejected the
            # request. The generated request id lets cleanup cancel either case.
            active = True
            self.request_json("POST", chat_url + "/messages", statuses=[202],
                              body={"request_id": request_id, "message": question})
            deadline = self.clock.monotonic() + timeout + 30
            while True:
                remaining = deadline - self.clock.monotonic()
                if remaining <= 0:
                    raise DeployError(38, "S8: canned chat deadline expired")
                obj = self.request_json("GET", chat_url + "/status", timeout=min(10, remaining))
                run = obj.get("last_run") if isinstance(obj, dict) else None
                state = run.get("state") if isinstance(run, dict) else None
                if state in ("succeeded", "failed", "cancelled", "interrupted"):
                    active = False
                if self.clock.monotonic() > deadline:
                    raise DeployError(38, "S8: canned chat deadline expired")
                if not active:
                    if state != "succeeded":
                        raise DeployError(38, "S8: canned chat run did not succeed")
                    break
                if state not in ("running", "cancelling"):
                    raise DeployError(38, "S8: run status response is invalid")
                remaining = deadline - self.clock.monotonic()
                if remaining <= 0:
                    raise DeployError(38, "S8: canned chat deadline expired")
                self.clock.sleep(min(2, remaining))
            reports = self.request_json("GET", chat_url + "/reports")
            if not isinstance(reports, list) or not reports:
                raise DeployError(38, "S8: canned chat produced no report")
            report_id = self.response_id(reports[0], "report")
            report_url = frontend + "/api/reports/" + report_id
            saved_report = self.request_json("PUT", report_url + "/saved")
            if self.response_id(saved_report, "saved report") != report_id:
                raise DeployError(38, "S8: saved report id differs")
            saved = True
            report = self.request_json("GET", report_url)
            if self.response_id(report, "report") != report_id or not isinstance(report, dict) or "data" not in report:
                raise DeployError(38, "S8: report content is missing")
            updated = self.request_json("POST", report_url + "/update", statuses=range(200, 300))
            if self.response_id(updated, "updated report") != report_id or not isinstance(updated, dict) or "data" not in updated:
                raise DeployError(38, "S8: updated report content is missing")
            old_version, new_version = report.get("version"), updated.get("version")
            if type(old_version) is not int or type(new_version) is not int or new_version <= old_version:
                raise DeployError(38, "S8: report Update did not advance its version")
            saved_reports = self.request_json("GET", frontend + "/api/saved-reports")
            if not isinstance(saved_reports, list) or not any(isinstance(item, dict) and item.get("id") == report_id
                                                            for item in saved_reports):
                raise DeployError(38, "S8: saved report listing does not contain smoke report")
            self.request("DELETE", report_url + "/saved", statuses=[204])
            saved = False
        except DeployError as error:
            failure = error
            raise
        finally:
            self.step = "S8 cleanup"
            cleanup_errors: list[str] = []
            if chat_id is not None:
                chat_url = frontend + "/api/chats/" + chat_id
                if active:
                    try:
                        cancel_status, _, _ = self.http.request(
                            "POST", chat_url + "/cancel", body={"request_id": request_id})
                        if cancel_status not in (200, 202, 404):
                            raise DeployError(38, "cancellation was not accepted")
                        deadline = self.clock.monotonic() + 30
                        while cancel_status != 404:
                            remaining = deadline - self.clock.monotonic()
                            if remaining <= 0:
                                raise DeployError(38, "cancelled run did not terminate")
                            obj = self.request_json("GET", chat_url + "/status", timeout=min(10, remaining))
                            if self.clock.monotonic() > deadline:
                                raise DeployError(38, "cancelled run did not terminate")
                            run = obj.get("last_run") if isinstance(obj, dict) else None
                            state = run.get("state") if isinstance(run, dict) else None
                            if state in ("succeeded", "failed", "cancelled", "interrupted"):
                                break
                            self.clock.sleep(min(2, max(0, deadline - self.clock.monotonic())))
                    except (OSError, ValueError, urllib.error.URLError, DeployError):
                        cleanup_errors.append("cancel failed")
                if saved and report_id is not None:
                    try:
                        self.request("DELETE", frontend + "/api/reports/" + report_id + "/saved", statuses=[204])
                    except DeployError:
                        cleanup_errors.append("unsave failed")
                try:
                    self.request("DELETE", chat_url, statuses=[204])
                except DeployError:
                    cleanup_errors.append("chat delete failed")
                if not cleanup_errors:
                    self.emit("S8 cleanup: smoke chat removed; report unsaved")
            self.step = "S8"
            if cleanup_errors:
                message = "S8 cleanup: " + "; ".join(cleanup_errors)
                if failure is not None:
                    failure.message += "; secondary error: " + message
                else:
                    raise DeployError(38, message) from None

    def response_id(self, obj: JSON, label: str) -> str:
        identifier = obj.get("id") if isinstance(obj, dict) else None
        if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", identifier):
            raise DeployError(38, "S8: invalid " + label + " id")
        return identifier

    def reconcile_attempts(self, *, new_attempt_id: str | None = None) -> None:
        """Called under the deployment lock before a new attempt or dirty check."""
        events = self.state.read_history()
        current = self.state.read_current()
        committed = current.get("last_successful")
        starts: dict[str, dict[str, JSON]] = {}
        terminal: set[str] = set()
        successful: set[str] = set()
        for event in events:
            identifier = event.get("attempt_id")
            if not isinstance(identifier, str) or identifier == new_attempt_id:
                continue
            if event.get("event") == "started":
                starts[identifier] = event
            elif event.get("event") in ("success", "failed"):
                terminal.add(identifier)
                if event.get("event") == "success":
                    successful.add(identifier)
        pending = current.get("unaudited", [])
        assert isinstance(pending, list)
        outcomes: dict[str, dict[str, JSON]] = {}
        for outcome in pending:
            assert isinstance(outcome, dict)
            identifier = outcome["attempt_id"]
            assert isinstance(identifier, str)
            outcomes[identifier] = outcome
        # Recover attempts committed before the unaudited list was introduced.
        if isinstance(committed, dict):
            identifier = committed.get("attempt_id")
            if (isinstance(identifier, str) and identifier in starts and
                    all(committed.get(key) == starts[identifier].get(key)
                        for key in ("attempt_id", "tag", "commit"))):
                outcomes.setdefault(identifier, committed)
        for identifier, outcome in outcomes.items():
            if identifier in terminal:
                continue
            record = dict(outcome)
            record["event"] = "success"
            try:
                self.state.append_history(record)
            except (DeployError, OSError, UnicodeError):
                self.warn_audit("reconciliation could not append terminal success event")
            else:
                terminal.add(identifier)
                successful.add(identifier)
        self.prune_unaudited(successful)
        for identifier, started in starts.items():
            if identifier in terminal or identifier in outcomes:
                continue
            stamp = self.now().isoformat()
            record = {**started, "event": "failed", "at": stamp, "finished_at": stamp,
                      "step": "interrupted", "exit_code": None}
            try:
                self.state.append_history(record)
            except (DeployError, OSError, UnicodeError):
                self.warn_audit("reconciliation could not append terminal " + str(record["event"]) + " event")

    def prune_unaudited(self, successful: set[str]) -> None:
        """Remove recovery records only after their success audit is durable."""
        try:
            current = self.state.read_current()
            pending = current.get("unaudited", [])
            assert isinstance(pending, list)
            retained: list[JSON] = []
            for outcome in pending:
                assert isinstance(outcome, dict)
                identifier = outcome["attempt_id"]
                assert isinstance(identifier, str)
                if identifier not in successful:
                    retained.append(outcome)
            if retained == pending:
                return
            # A prior append may have written a visible line but failed its fsync.
            with (self.state.path / "history.jsonl").open("rb") as handle:
                os.fsync(handle.fileno())
            current["unaudited"] = retained
            self.state.write_current(current)
        except (DeployError, OSError, UnicodeError):
            self.warn_audit("could not prune durably audited committed outcomes")

    def warn_audit(self, message: str) -> None:
        try:
            print("WARNING: secondary audit error: " + message, file=sys.stderr)
        except OSError:
            # A closed/full diagnostic destination cannot change the outcome.
            pass

    def begin_attempt(self, meta: rm.ReleaseMetadata, *, kind: str = "deploy",
                      db_revision_before: str | None = None) -> dict[str, JSON]:
        """Shared history contract for deploy/rollback; first service mutation follows."""
        identifier = str(uuid.uuid4())
        self.reconcile_attempts(new_attempt_id=identifier)
        current = self.state.read_current()
        stamp = self.now().isoformat()
        digests: dict[str, JSON] = dict(meta.images)
        record: dict[str, JSON] = {
            "kind": kind, "tag": meta.version, "commit": meta.source_commit, "digests": digests,
            "attempt_id": identifier,
            "event": "started", "at": stamp, "started_at": stamp,
            "db_revision_before": db_revision_before, "db_revision_after": db_revision_before,
            "backup_id": None,
        }
        self.state.append_history(record)
        self.attempt_record = record
        current["attempt"] = {"tag": meta.version, "commit": meta.source_commit,
                              "attempt_id": identifier, "started_at": stamp}
        self.step = "attempt publication"
        try:
            self.state.write_current(current)
        except (DeployError, OSError, UnicodeError, KeyboardInterrupt):
            error = DeployError(23, "deployment attempt state publication failed")
            self.finish_attempt(error=error)
            raise error from None
        return record

    def finish_attempt(self, *, error: DeployError | None = None, smoke_steps: Sequence[str] = ()) -> None:
        """Publication failure records its own failed terminal event, then raises 23."""
        stamp = self.now().isoformat()
        steps: list[JSON] = list(smoke_steps)
        record: dict[str, JSON] = {
            **self.attempt_record, "event": "failed" if error else "success", "at": stamp,
            "finished_at": stamp, "smoke_steps": steps,
        }
        publication_error: DeployError | None = None
        previous_tag: JSON = None
        if error is None:
            self.step = "publish-state"
            try:
                current = self.state.read_current()
                previous = current.get("last_successful")
                previous_tag = previous.get("tag") if isinstance(previous, dict) else None
                current["last_successful"] = record
                pending = current.get("unaudited", [])
                assert isinstance(pending, list)
                if ("unaudited" not in current and isinstance(previous, dict) and
                        previous.get("kind") in ("deploy", "rollback", "rollback-restore-after-dirty") and
                        all(isinstance(previous.get(key), str)
                            for key in ("attempt_id", "tag", "commit", "kind", "finished_at"))):
                    # The first new-format commit must retain the older recovery source.
                    pending = [dict(previous)]
                current["unaudited"] = [*pending, dict(record)]
                self.state.write_current(current)
            except (DeployError, OSError, UnicodeError, KeyboardInterrupt):
                publication_error = DeployError(23, "publish-state: successful deployment state publication failed")
                error = publication_error
                record["event"] = "failed"
        if error is not None:
            record.update({"exit_code": error.exit_code, "step": self.step})
        try:
            self.state.append_history(record)
        except (DeployError, OSError, UnicodeError):
            if error is None:
                self.warn_audit("missing terminal success event for committed attempt " +
                                str(record["attempt_id"]))
            else:
                error.message += "; secondary error: failed to persist terminal failed history"
        else:
            if error is None:
                identifier = record["attempt_id"]
                assert isinstance(identifier, str)
                self.prune_unaudited({identifier})
        if publication_error is not None:
            if isinstance(previous_tag, str):
                self.emit("Recovery: make rollback VERSION=" + previous_tag)
            raise publication_error from None

    def deploy(self, meta: rm.ReleaseMetadata, flags: argparse.Namespace) -> None:
        self.reconcile_attempts()
        if self.state.read_current().get("stage") == "migration_started":
            raise DeployError(41, "migration_started marker exists; explicit backup restore is required")
        self.state.read_history()
        before = self.preflight(meta, flags)
        current, pending = self.migration_plan(meta)
        self.approve_migrations(pending, flags)
        previous = self.state.read_current().get("last_successful")
        previous_tag = previous.get("tag") if isinstance(previous, dict) else None
        self.begin_attempt(meta, db_revision_before=current)
        try:
            self.quiesce_backup_migrate(meta, current, pending)
            steps = self.recreate_and_smoke(meta, flags, before=before)
        except (DeployError, OSError, KeyboardInterrupt) as cause:
            if isinstance(cause, DeployError):
                error = cause
            else:
                code = 36 if self.step == "migration" else 37
                error = DeployError(code, f"{self.step}: deployment interrupted or local I/O failed")
            self.finish_attempt(error=error)
            if self.step.startswith(("recreate", "readiness", "S")) and isinstance(previous_tag, str):
                self.emit("Recovery: make rollback VERSION=" + previous_tag)
            raise error from None
        self.finish_attempt(smoke_steps=steps)
        self.emit("Deploy " + meta.version + " success")

    def smoke_metadata(self) -> rm.ReleaseMetadata | None:
        current = self.state.read_current()
        record = current.get("attempt") or current.get("last_successful")
        if record is None:
            return None
        if not isinstance(record, dict) or not isinstance(record.get("tag"), str):
            raise DeployError(23, "current deployment record cannot select smoke metadata")
        tag = record["tag"]
        assert isinstance(tag, str)
        folder = self.state.path / "releases" / valid_tag(tag)
        try:
            meta = rm.loads((folder / "metadata.json").read_bytes())
        except (OSError, rm.MetadataError):
            raise DeployError(23, "cached smoke metadata is missing or invalid") from None
        if meta.version != tag:
            raise DeployError(23, "cached smoke metadata tag differs from current state")
        self.metadata, self.pin_file = meta, folder / "compose.release.yml"
        return meta

    def resolve_rollback_target(self, tag: str | None = None) -> str:
        if tag is not None:
            return valid_tag(tag)
        current = self.state.read_current()
        last, attempt = current.get("last_successful"), current.get("attempt")
        if not isinstance(last, dict):
            raise DeployError(2, "no rollback target")
        last_tag = last["tag"]
        assert isinstance(last_tag, str)
        if isinstance(attempt, dict) and attempt["tag"] != last_tag:
            return last_tag
        for event in reversed(self.state.read_history()):
            if event.get("event") == "success" and event.get("tag") != last_tag:
                target = event.get("tag")
                if not isinstance(target, str) or not TAG_RE.fullmatch(target):
                    raise DeployError(23, "rollback history target is invalid")
                return target
        raise DeployError(2, "no rollback target")

    def rollback_metadata(self, tag: str) -> rm.ReleaseMetadata:
        """Cached metadata and exact five-image pins require no GitHub access."""
        folder = self.state.path / "releases" / valid_tag(tag)
        cached, pins = folder / "metadata.json", folder / "compose.release.yml"
        if folder.is_symlink() or cached.is_symlink() or pins.is_symlink():
            raise DeployError(23, "cached rollback release must not use symlinks")
        if not cached.exists() or not pins.exists():
            return self.select(tag)
        try:
            with cached.open("rb") as handle:
                meta = rm.loads(handle.read(rm.MAX_BYTES + 1))
            with pins.open("rb") as handle:
                data = handle.read(RELEASE_MAX_BYTES + 1)
            if len(data) > RELEASE_MAX_BYTES:
                raise DeployError(23, "cached rollback pins exceed size limit")
            obj = json_object(data, 23, "cached rollback pins are invalid")
        except (OSError, rm.MetadataError):
            raise DeployError(23, "cached rollback metadata is unavailable or invalid") from None
        if meta.version != tag or meta.repository != (self.env.get("BD_DEPLOY_REPO") or rm.DEFAULT_REPOSITORY):
            raise DeployError(23, "cached rollback metadata differs from target")
        services = obj.get("services")
        if set(obj) != {"services"} or not isinstance(services, dict) or set(services) != set(SERVICES):
            raise DeployError(23, "cached rollback pin service set is invalid")
        for name, pin in services.items():
            ref = pin.get("image") if isinstance(pin, dict) else None
            if (not isinstance(pin, dict) or set(pin) != {"image"} or
                    not isinstance(ref, str) or not DIGEST_REF_RE.fullmatch(ref) or
                    name in APPLICATION_SERVICES and ref != meta.images[name]):
                raise DeployError(23, "cached rollback image pin is invalid")
        self.metadata, self.pin_file = meta, pins
        for ref in meta.images.values():
            try:
                inspection = self.command(["docker", "image", "inspect", ref, "--format", "{{json .}}"],
                                          20, "rollback image inspection failed")
            except DeployError:
                self.command(["docker", "pull", ref], 18, "rollback image pull failed", timeout=PULL_TIMEOUT)
                inspection = self.command(["docker", "image", "inspect", ref, "--format", "{{json .}}"],
                                          20, "rollback image inspection failed")
            inspected = json_object(inspection.encode(), 19, "rollback image inspection is invalid")
            config = inspected.get("Config")
            labels = config.get("Labels") if isinstance(config, dict) else None
            if not isinstance(labels, dict) or labels.get("org.opencontainers.image.revision") != meta.source_commit:
                raise DeployError(19, "rollback image revision label differs from source commit")
        return meta

    def suggested_backup(self, revision: str) -> str | None:
        for folder in sorted((self.state.path / "backups").iterdir(), reverse=True):
            if not BACKUP_ID_RE.fullmatch(folder.name):
                continue
            try:
                manifest = self.backup_manifest(folder.name)
            except DeployError:
                continue
            if manifest["db_revision_before"] == revision:
                return folder.name
        return None

    def rollback(self, tag: str | None, flags: argparse.Namespace) -> None:
        """Explicit restore is the only path through a different or dirty schema."""
        if self.env.get("DATASET"):
            raise DeployError(2, "DATASET deployments are not supported by the executor")
        self.reconcile_attempts()
        dirty = self.state.read_current().get("stage") == "migration_started"
        identifier = flags.restore_backup
        if identifier is not None:
            self.backup_path(identifier)
        if dirty and not identifier:
            raise DeployError(41, "migration_started marker exists; explicit backup restore is required")
        target = self.resolve_rollback_target(tag)
        meta = self.rollback_metadata(target)
        manifest = self.validate_backup_set(identifier) if identifier else None
        if manifest is not None and manifest["db_revision_before"] != meta.alembic_revision:
            raise DeployError(40, "backup revision differs from rollback target")
        current = self.live_db_revision()
        if not identifier and current != meta.alembic_revision:
            suggested = self.suggested_backup(meta.alembic_revision)
            message = "rollback schema differs from live database; explicit backup restore is required"
            if suggested:
                message += "; use --restore-backup " + suggested
            raise DeployError(39, message)
        before = self.preflight(meta, flags)
        kind = "rollback-restore-after-dirty" if dirty and identifier else "rollback"
        self.begin_attempt(meta, kind=kind, db_revision_before=current)
        try:
            if identifier:
                assert manifest is not None
                self.step = "restore_quiesce"
                self.release_make("release-stop", services=["data_collector", "backend"], code=34, timeout=1500)
                self.step = "restore_approval"
                safety_id = self.now().strftime("%Y%m%dT%H%M%S%fZ") + "-pre-restore"
                safety_path = self.backup_path(safety_id)
                self.emit("Backup timestamp: " + str(manifest["created_at"]))
                self.emit("all MySQL and SQLite writes after this time will be discarded; a safety copy is kept at " +
                          str(safety_path))
                if not flags.yes:
                    if not sys.stdin.isatty() or input("Restore this backup? Type yes: ").strip() != "yes":
                        raise DeployError(40, "backup restore requires --yes or interactive yes; services remain stopped")
                self.take_backup_set("pre-restore", db_revision_before=current, identifier=safety_id,
                                     protected_backup_id=identifier)
                self.attempt_record.update({"backup_id": identifier, "safety_backup_id": safety_id,
                                            "db_revision_after": None})
                self.step = "restore"
                state = self.state.read_current()
                state["stage"] = "migration_started"
                state["migration_backup_id"] = identifier
                self.state.write_current(state)
                self.restore_backup_set(identifier)
                self.step = "restore_verification"
                try:
                    actual = self.live_db_revision()
                except DeployError:
                    raise DeployError(40, "restored database revision is unavailable") from None
                self.attempt_record["db_revision_after"] = actual
                heads = self.release_make("release-run", services=["backend"],
                                          cmd=["alembic", "-c", "/alembic/alembic.ini", "heads"], code=40)
                if (actual != meta.alembic_revision or not re.fullmatch(
                        re.escape(meta.alembic_revision) + r" \(head\)\s*", heads.strip())):
                    raise DeployError(40, "restored database or release image head differs from target")
                state.pop("stage", None)
                state.pop("migration_backup_id", None)
                self.state.write_current(state)
            steps = self.recreate_and_smoke(meta, flags, before=before)
        except (DeployError, OSError, UnicodeError, KeyboardInterrupt, EOFError) as cause:
            if isinstance(cause, DeployError):
                error = cause
            else:
                code = 34 if self.step == "restore_quiesce" else 40 if self.step.startswith("restore") else 37
                error = DeployError(code, f"{self.step}: rollback interrupted or local I/O failed")
            self.finish_attempt(error=error)
            try:
                if identifier and self.step.startswith(("restore", "backup")):
                    status = ("quiesce was incomplete; inspect application services"
                              if self.step == "restore_quiesce" else "application services remain stopped")
                    self.emit("Recovery: " + status + "; retry rollback with --restore-backup " + identifier + " --yes")
                elif self.step.startswith(("recreate", "readiness", "S")):
                    self.emit("Recovery: make rollback VERSION=" + target)
            except (OSError, UnicodeError):
                self.warn_audit("recovery output could not be written")
            raise error from None
        self.finish_attempt(smoke_steps=steps)
        self.emit("Rollback " + meta.version + " success")


# --- status (todo 20) ---
# Read-only view of the state dir. Only known scalar fields are copied out, so extra keys in
# the state files are tolerated and never echoed.
STATUS_HISTORY_EVENTS = 10
LAST_SUCCESSFUL_FIELDS = ("tag", "commit", "db_revision_after", "finished_at")
ATTEMPT_FIELDS = ("tag", "commit", "attempt_id", "started_at")
HISTORY_FIELDS = ("tag", "kind", "event", "at", "exit_code", "step")


def scalar(value: JSON) -> str | int | None:
    return value if isinstance(value, (str, int)) and not isinstance(value, bool) else None


def project(record: JSON, fields: Sequence[str]) -> dict[str, JSON] | None:
    if not isinstance(record, dict):
        return None
    return {name: scalar(record.get(name)) for name in fields}


def format_age(seconds: int) -> str:
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    if days:
        return f"{days}d {hours}h"
    return f"{hours}h {rest // 60}m" if hours else f"{rest // 60}m"


def status_backup(folder: Path, now: datetime.datetime) -> dict[str, JSON]:
    entry: dict[str, JSON] = {"id": folder.name, "tag": None, "db_revision_before": None,
                              "created_at": None, "age_seconds": None, "complete": False}
    manifest = folder / "manifest.json"
    message = "backup manifest is invalid: " + folder.name
    if manifest.is_symlink():
        raise DeployError(23, message)
    if not manifest.is_file():
        # A backup in progress has no manifest yet; the manifest is written last.
        return entry
    with manifest.open("rb") as handle:
        data = handle.read(RELEASE_MAX_BYTES + 1)
    if len(data) > RELEASE_MAX_BYTES:
        raise DeployError(23, message)
    obj = json_object(data, 23, message)
    try:
        created = manifest_timestamp(obj, 23)
    except DeployError as error:
        raise DeployError(23, f"{message} ({error.message})") from None
    entry.update({"tag": scalar(obj.get("tag")), "db_revision_before": scalar(obj.get("db_revision_before")),
                  "created_at": created.isoformat(),
                  "age_seconds": max(0, int((now - created).total_seconds())), "complete": True})
    return entry


def collect_status(state: State, now: datetime.datetime) -> dict[str, Any]:
    report: dict[str, Any] = {
        "state_dir": str(state.path), "initialized": False, "last_successful": None, "attempt": None,
        "stage": None, "dirty": False, "unaudited": 0, "history_total": 0, "history": [],
        "backups": [], "releases": [],
    }
    if not state.path.exists():
        return report
    if not state.path.is_dir():
        raise DeployError(23, "deployment state path is not a directory")
    current = state.read_current()
    history = state.read_history() if (state.path / "history.jsonl").exists() else []
    shown = history[-STATUS_HISTORY_EVENTS:]
    for event in shown:
        # Rollback target selection refuses a success event without a valid tag, so status does too.
        tag = event.get("tag")
        if event.get("event") == "success" and (not isinstance(tag, str) or not TAG_RE.fullmatch(tag)):
            raise DeployError(23, "deployment history success event has an invalid tag")
    unaudited = current.get("unaudited")
    stage = current.get("stage")
    report.update({
        "initialized": True,
        "last_successful": project(current.get("last_successful"), LAST_SUCCESSFUL_FIELDS),
        "attempt": project(current.get("attempt"), ATTEMPT_FIELDS),
        "stage": stage, "dirty": stage == "migration_started",
        "unaudited": len(unaudited) if isinstance(unaudited, list) else 0,
        "history_total": len(history),
        "history": [project(event, HISTORY_FIELDS) for event in shown],
    })
    backups, releases = state.path / "backups", state.path / "releases"
    if backups.is_dir():
        folders = sorted((p for p in backups.iterdir()
                          if BACKUP_ID_RE.fullmatch(p.name) and p.is_dir() and not p.is_symlink()), reverse=True)
        for folder in folders:
            if not backup_id_valid(folder.name):
                raise DeployError(23, "backup id is invalid: " + folder.name)
        report["backups"] = [status_backup(folder, now) for folder in folders]
    if releases.is_dir():
        tags = [p.name for p in releases.iterdir() if TAG_RE.fullmatch(p.name) and p.is_dir()]
        report["releases"] = sorted(tags, key=lambda tag: tuple(map(int, tag[1:].split("."))), reverse=True)
    return report


def format_status(report: dict[str, Any]) -> list[str]:
    def text(value: object) -> str:
        return "-" if value is None else str(value)

    lines = ["Deployment state: " + report["state_dir"]]
    if not report["initialized"]:
        lines.append("No deployment state yet. This is a normal first-install state; the first deploy creates it.")
        return lines
    last, attempt = report["last_successful"], report["attempt"]
    lines.append("Last successful: none" if last is None else
                 f"Last successful: {text(last['tag'])} commit {text(last['commit'])} "
                 f"db_revision_after={text(last['db_revision_after'])} finished {text(last['finished_at'])}")
    lines.append("Current attempt: none" if attempt is None else
                 f"Current attempt: {text(attempt['tag'])} started {text(attempt['started_at'])} "
                 f"attempt_id={text(attempt['attempt_id'])}")
    lines.append("Migration marker: " + ("none" if report["stage"] is None else str(report["stage"])
                 + (" (DIRTY: restore a backup with rollback --restore-backup before deploying)"
                    if report["dirty"] else "")))
    lines.append(f"Unaudited outcomes: {report['unaudited']}")
    lines.append(f"History (last {STATUS_HISTORY_EVENTS} of {report['history_total']}):")
    for event in report["history"]:
        extra = "".join(f" {name}={event[name]}" for name in ("exit_code", "step") if event[name] is not None)
        lines.append("  " + " ".join(text(event[name]) for name in ("at", "tag", "kind", "event")) + extra)
    lines.append(f"Backups ({len(report['backups'])}):")
    for backup in report["backups"]:
        detail = (f"db_revision_before={backup['db_revision_before'] or 'none'} age {format_age(backup['age_seconds'])}"
                  if backup["complete"] else "incomplete (no manifest)")
        lines.append(f"  {backup['id']} {detail}")
    lines.append("Cached releases: " + (", ".join(report["releases"]) or "none"))
    return lines


def show_status(state: State, as_json: bool, emit: Callable[[str], None],
                now: datetime.datetime | None = None) -> None:
    report = collect_status(state, now or datetime.datetime.now(datetime.timezone.utc))
    emit(json.dumps(report, sort_keys=True) if as_json else "\n".join(format_status(report)))


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
    rollback.add_argument("tag", nargs="?", type=valid_tag)
    rollback.add_argument("--restore-backup")
    rollback.add_argument("--yes", action="store_true")
    rollback.add_argument("--llm-smoke", action="store_true")
    resolve = commands.add_parser("resolve-rollback-target")
    resolve.add_argument("tag", nargs="?", type=valid_tag)
    commands.add_parser("status").add_argument("--json", action="store_true")
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
            try:
                log.write(text + "\n")
                log.flush()
            except (OSError, UnicodeError):
                print("Secondary error: deployment log write failed", file=sys.stderr)

    try:
        args = list(sys.argv[1:] if argv is None else argv)
        if args[:1] == ["status"]:
            # Read-only report: it never initializes the state dir, takes the lock or writes a log.
            with contextlib.redirect_stdout(help_output):
                options = parser().parse_args(args)
            show_status(state, options.json, emit)
            return 0
        state.initialize()
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        # Only a validated tag may enter a log filename; invalid argv is never logged.
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
                                fetcher or URLFetcher(allow_file=bool(environment.get("BD_DEPLOY_RELEASE_FILE"))),
                                output=emit)
            if options.command in ("deploy", "rollback"):
                executor.reconcile_attempts()
            if (options.command in ("deploy", "rollback") and state.read_current().get("stage") == "migration_started"
                    and not (options.command == "rollback" and options.restore_backup is not None)):
                raise DeployError(41, "migration_started marker exists; explicit backup restore is required")
            match options.command:
                case "deploy":
                    metadata = executor.select(options.tag)
                    executor.deploy(metadata, options)
                case "rollback":
                    executor.rollback(options.tag, options)
                case "smoke":
                    executor.smoke(executor.smoke_metadata(), llm_smoke=options.llm_smoke)
                case "select":
                    metadata = executor.select(options.tag)
                    if environment.get("BD_DEPLOY_RELEASE_FILE"):
                        emit("WARNING: BD_DEPLOY_RELEASE_FILE rehearsal override bypassed GitHub", error=True)
                    emit(rm.dumps(metadata).decode().rstrip())
                case "resolve-rollback-target":
                    emit(executor.resolve_rollback_target(options.tag))
                case "verify-db-isolation":
                    return verify_db_isolation(executor, options.container_probe, emit)
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
            try:
                log.close()
            except (OSError, UnicodeError):
                print("Secondary error: deployment log close failed", file=sys.stderr)


# --- verify-db-isolation (todo 16) ---
# Read-only checks that the database and the application ports are reachable from this
# host's loopback only. Rows never print an address other than 127.0.0.1: a binding that
# is not loopback is described by kind, not by value.
ISOLATION_SERVICES = ("mysql", "backend", "frontend")
ISOLATION_TIMEOUT = 30
PROBE_TIMEOUT = 60
LISTEN_STATE = "0A"
PROBE_MARKER_RE = re.compile(r"^probe-exit=([0-9]+)$", re.MULTILINE)
HOST_KINDS = {"wildcard": "a wildcard address", "loopback": "a loopback address other than 127.0.0.1",
              "other": "a non-loopback address", "invalid": "an unparsable address"}
OFF_HOST_RECIPE = """\
Off-host probe: run these from ANOTHER machine, never from this host.
  nc -4 -z -w 3 <public-ipv4> {port}    expected: refused
  nc -6 -z -w 3 <public-ipv6> {port}    expected: refused
  nc -4 -z -w 3 <public-ipv4> 443       control, expected: connect (proves the path is open)
Reading the result: connect = FAIL (the port is exposed), refused = PASS,
timeout = filtered or inconclusive (confirm the control port connects, then retry)."""


def classify_host(host: object) -> str:
    """loopback, wildcard, other or invalid; an absent or empty host means every interface."""
    if host is None:
        return "wildcard"
    if not isinstance(host, str):
        return "invalid"
    text = host.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    text = text.partition("%")[0]
    if text in ("", "*"):
        return "wildcard"
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return "invalid"
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    if address.is_unspecified:
        return "wildcard"
    return "loopback" if address.is_loopback else "other"


def describe_host(host: object) -> str:
    if host == "127.0.0.1":
        return "127.0.0.1"
    return HOST_KINDS[classify_host(host)]


def parse_ss(text: str) -> list[tuple[str, int]]:
    """Local (host, port) of every row of `ss -ltnH`; a row that cannot be read is an error."""
    listeners = []
    for line in text.splitlines():
        fields = line.split()
        if not fields:
            continue
        if len(fields) < 4:
            raise ValueError("short ss row")
        host, sep, port = fields[3].rpartition(":")
        if not sep or not host or not (port.isascii() and port.isdecimal()) or not 0 < int(port) <= 65535:
            raise ValueError("invalid ss local address")
        listeners.append((host[1:-1] if host.startswith("[") and host.endswith("]") else host, int(port)))
    return listeners


def parse_proc_tcp(text: str, *, v6: bool) -> list[tuple[str, int]]:
    """Listening (host, port) pairs of /proc/net/tcp or tcp6; addresses are little-endian words."""
    listeners = []
    for line in text.splitlines():
        fields = line.split()
        if not fields or fields[0] == "sl":
            continue
        if len(fields) < 4:
            raise ValueError("short proc row")
        address, _, port = fields[1].partition(":")
        if fields[3].upper() != LISTEN_STATE:
            continue
        if v6:
            if len(address) != 32:
                raise ValueError("invalid proc address")
            raw = b"".join(bytes.fromhex(address[i:i + 8])[::-1] for i in range(0, 32, 8))
            host = str(ipaddress.IPv6Address(raw))
        else:
            if len(address) != 8:
                raise ValueError("invalid proc address")
            host = str(ipaddress.IPv4Address(bytes.fromhex(address)[::-1]))
        listeners.append((host, int(port, 16)))
    return listeners


def read_proc_tcp(name: str) -> str:
    return Path("/proc/net", name).read_text()


def parse_port_bindings(text: str) -> list[tuple[str, str | None]]:
    """(container port, HostIp) per published binding; a missing HostIp is None (all interfaces)."""
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        raise ValueError("port bindings are not JSON") from None
    if data is None:
        return []
    if not isinstance(data, dict):
        raise ValueError("port bindings are not an object")
    bindings: list[tuple[str, str | None]] = []
    for port, entries in data.items():
        if entries is None:
            continue
        if not isinstance(entries, list):
            raise ValueError("port binding entries are not a list")
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("port binding entry is not an object")
            host = entry.get("HostIp")
            if not (host is None or isinstance(host, str)):
                raise ValueError("port binding host is not a string")
            bindings.append((port, host))
    return bindings


def service_ports(config: dict[str, JSON], name: str) -> list[dict[str, JSON]] | None:
    """Published port entries of one rendered service, or None when the service is absent."""
    services = config.get("services")
    if not isinstance(services, dict):
        raise ValueError("services are not an object")
    service = services.get(name)
    if service is None:
        return None
    if not isinstance(service, dict):
        raise ValueError("service is not an object")
    ports = service.get("ports") or []
    entries = [port for port in ports if isinstance(port, dict)] if isinstance(ports, list) else []
    if not isinstance(ports, list) or len(entries) != len(ports):
        raise ValueError("ports are malformed")
    return entries


class IsolationCheck:
    def __init__(self, executor: Executor, container_probe: bool):
        self.executor = executor
        self.container_probe = container_probe
        self.rows: list[tuple[str, str, str]] = []
        self.required: tuple[str, ...] = ("mysql",)
        self.published: list[tuple[str, int]] = []
        self.image: str | None = None
        port = executor.env.get("BD_MYSQL_HOST_PORT") or "3306"
        self.mysql_port = int(port) if port.isascii() and port.isdecimal() else 3306

    def add(self, status: str, check: str, detail: str) -> None:
        self.rows.append((status, check, detail))

    def run_command(self, argv: Sequence[str], timeout: int = ISOLATION_TIMEOUT) -> subprocess.CompletedProcess[str] | None:
        try:
            return self.executor.runner.run(argv, cwd=self.executor.root, env=self.executor.env, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            return None

    def compose_prefix(self) -> list[str] | None:
        webreport = self.executor.root / "webreport"
        files = [webreport / "docker-compose.yml"]
        # An existing state file means release mode even when it is empty or corrupt: only
        # its absence selects the dev files, so a damaged state can never approve dev mode.
        release = (self.executor.state.path / "current.json").exists()
        if release:
            self.required = ISOLATION_SERVICES
        try:
            current = self.executor.state.read_current()
        except (DeployError, OSError):
            self.add("FAIL", "compose-config", "deployment state is unreadable; cannot choose the release files")
            return None
        if release:
            last = current.get("last_successful")
            tag = last.get("tag") if isinstance(last, dict) else None
            pin = (self.executor.state.path / "releases" / tag / "compose.release.yml"
                   if isinstance(tag, str) and TAG_RE.fullmatch(tag) else None)
            if pin is None or not pin.is_file():
                self.add("FAIL", "compose-config", "no recorded release pin file; cannot verify the release configuration")
                return None
            files += [webreport / "docker-compose.prod.yml", pin]
        prefix = ["docker", "compose", "--project-directory", str(webreport)]
        for file in files:
            prefix += ["-f", str(file)]
        return prefix

    def check_config(self, prefix: list[str]) -> None:
        result = self.run_command([*prefix, "config", "--format", "json"])
        try:
            if result is None or result.returncode:
                raise DeployError(17, "unrendered")
            config = json_object(result.stdout.encode(), 17, "invalid")
        except DeployError:
            self.add("FAIL", "compose-config",
                     "could not render the compose configuration (run make -C webreport generate-env first)")
            return
        for name in ISOLATION_SERVICES:
            required = name in self.required
            try:
                ports = service_ports(config, name)
            except ValueError:
                self.add("FAIL" if required else "INFO", "compose-config", f"{name} ports are malformed")
                continue
            if ports is None:
                self.add("FAIL" if required else "INFO", "compose-config", f"{name} is not in the configuration")
                continue
            if not ports:
                self.add("PASS" if required else "INFO", "compose-config", f"{name} publishes no host port")
            for port in ports:
                host, published = port.get("host_ip"), port.get("published")
                digits = str(published)
                number = int(digits) if digits.isascii() and digits.isdecimal() else None
                status = "PASS" if host == "127.0.0.1" else "FAIL"
                if not required:
                    status = "INFO"
                note = "" if required else " (not required in dev mode)"
                self.add(status, "compose-config", f"{name} port {published} binds {describe_host(host)}{note}")
                if required and number is not None:
                    self.published.append((name, number))
        services = config.get("services")
        mysql = services.get("mysql") if isinstance(services, dict) else None
        image = mysql.get("image") if isinstance(mysql, dict) else None
        self.image = image if isinstance(image, str) and DIGEST_REF_RE.fullmatch(image) else None

    def check_containers(self, prefix: list[str] | None) -> None:
        for name in ISOLATION_SERVICES:
            required = name in self.required
            bad, skip = ("FAIL" if required else "INFO"), ("SKIP" if required else "INFO")
            if prefix is None:
                self.add("SKIP", "container-bindings", f"{name} not checked without the compose configuration")
                continue
            listing = self.run_command([*prefix, "ps", "-q", name])
            if listing is None or listing.returncode:
                self.add(bad, "container-bindings", f"{name} containers could not be listed")
                continue
            ids = listing.stdout.split()
            if not ids:
                self.add(skip, "container-bindings", f"{name} has no running container")
            for container in ids:
                result = self.run_command(["docker", "container", "inspect", container,
                                           "--format", "{{json .HostConfig.PortBindings}}"])
                try:
                    if result is None or result.returncode:
                        raise ValueError("inspect failed")
                    bindings = parse_port_bindings(result.stdout)
                except ValueError:
                    self.add(bad, "container-bindings", f"{name} port bindings could not be read")
                    continue
                if not bindings:
                    self.add("PASS" if required else "INFO", "container-bindings", f"{name} publishes no host port")
                for port, host in bindings:
                    status = ("PASS" if host == "127.0.0.1" else "FAIL") if required else "INFO"
                    self.add(status, "container-bindings", f"{name} {port} binds {describe_host(host)}")

    def listeners(self) -> list[tuple[str, int]] | None:
        result = self.run_command(["ss", "-ltnH"])
        if result is not None and result.returncode == 0 and result.stdout.strip():
            try:
                return parse_ss(result.stdout)
            except ValueError:
                pass
        try:
            found = parse_proc_tcp(read_proc_tcp("tcp"), v6=False)
            try:
                found += parse_proc_tcp(read_proc_tcp("tcp6"), v6=True)
            except FileNotFoundError:
                pass
            return found
        except (OSError, ValueError):
            return None

    def check_sockets(self) -> None:
        ports = {port for _, port in self.published}
        if "mysql" not in {name for name, _ in self.published}:
            ports.add(self.mysql_port)
        listeners = self.listeners()
        if not listeners:
            self.add("FAIL", "listening-sockets", "cannot enumerate listening TCP sockets, so isolation is not proven")
            return
        for port in sorted(ports):
            kinds = [classify_host(host) for host, number in listeners if number == port]
            if not kinds:
                self.add("PASS", "listening-sockets", f"port {port} is not listening")
            elif all(kind == "loopback" for kind in kinds):
                self.add("PASS", "listening-sockets", f"port {port} listens on loopback only")
            else:
                worst = next(kind for kind in kinds if kind != "loopback")
                self.add("FAIL", "listening-sockets", f"port {port} listens on {HOST_KINDS[worst]}")

    def check_probe(self) -> None:
        if self.image is None:
            self.add("FAIL", "container-probe", "no digest-pinned mysql image in the configuration; cannot run the probe")
            return
        for name, port in self.published:
            script = f'timeout 3 bash -c "</dev/tcp/host.docker.internal/{port}" 2>&1; echo probe-exit=$?'
            result = self.run_command(["docker", "run", "--rm", "--pull", "never", "--network", "bridge",
                                       "--add-host", "host.docker.internal:host-gateway", self.image,
                                       "sh", "-c", script], PROBE_TIMEOUT)
            output = result.stdout if result is not None and result.returncode == 0 else ""
            marker = PROBE_MARKER_RE.search(output)
            label = f"{name} port {port} through the host gateway"
            if marker is None:
                self.add("FAIL", "container-probe", f"{label}: the probe did not run to completion")
                continue
            code = int(marker.group(1))
            if code == 0:
                self.add("FAIL", "container-probe", f"{label}: connected, so the port is exposed")
            elif code == 124:
                self.add("FAIL", "container-probe", f"{label}: inconclusive, the connection timed out")
            elif code == 1 and "Connection refused" in output:
                self.add("PASS", "container-probe", f"{label}: refused")
            else:
                self.add("FAIL", "container-probe", f"{label}: the probe failed with exit {code}")

    def run(self, emit: Callable[[str], None]) -> int:
        prefix = self.compose_prefix()
        if prefix is not None:
            self.check_config(prefix)
        self.check_containers(prefix)
        self.check_sockets()
        if self.container_probe:
            self.check_probe()
        for status, check, detail in self.rows:
            emit(f"{status:<4} {check:<18} {detail}")
        mysql_ports = [port for name, port in self.published if name == "mysql"]
        emit(OFF_HOST_RECIPE.format(port=mysql_ports[0] if mysql_ports else self.mysql_port))
        failed = sum(status == "FAIL" for status, _, _ in self.rows)
        emit("RESULT: PASS" if not failed else f"RESULT: FAIL ({failed} failed)")
        return 1 if failed else 0


def verify_db_isolation(executor: Executor, container_probe: bool, emit: Callable[[str], None]) -> int:
    return IsolationCheck(executor, container_probe).run(emit)


# --- end verify-db-isolation ---


if __name__ == "__main__":
    sys.exit(main())
