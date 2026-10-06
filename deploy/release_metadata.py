"""Release metadata contract shared by the promotion workflow and the deploy executor.

Standard library only: the executor runs on a server that has no project environment.
"""

import dataclasses
import hashlib
import json
import os
import re

SCHEMA_VERSION = 1
ASSET_NAME = "release-metadata.json"
MARKER_RE = re.compile(r"^<!-- release-metadata\.json sha256=([0-9a-f]{64}) -->$", re.MULTILINE)
MAX_BYTES = 65536
MAX_CI_NUMBER = 2**63 - 1
DEFAULT_REPOSITORY = "Korridzy/bez_durakov_parser"

DEFAULT_IMAGE_PREFIX = "ghcr.io/korridzy/bez_durakov_parser"
IMAGE_PREFIX_ENV = "BD_RELEASE_IMAGE_PREFIX"
_COMPONENT_REPOSITORY_NAMES = {
    "backend": "backend",
    "data_collector": "data-collector",
    "frontend": "frontend",
}
IMAGE_REPOSITORIES = {
    component: f"{DEFAULT_IMAGE_PREFIX}/{name}" for component, name in _COMPONENT_REPOSITORY_NAMES.items()
}

_VERSION_RE = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
_COMMIT_RE = re.compile(r"[0-9a-f]{40}")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
_REVISION_RE = re.compile(r"[A-Za-z0-9_]{1,32}")
_REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_RESERVED_REVISIONS = {"head", "heads", "base"}


class MetadataError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class ReleaseMetadata:
    schema_version: int
    version: str
    source_commit: str
    ci_run_id: int
    ci_run_attempt: int
    built_from_candidate_tag: str
    images: dict[str, str]
    alembic_revision: str
    repository: str = dataclasses.field(default=DEFAULT_REPOSITORY, kw_only=True)


_FIELDS = tuple(field.name for field in dataclasses.fields(ReleaseMetadata))


def _image_repositories():
    prefix = os.environ.get(IMAGE_PREFIX_ENV) or DEFAULT_IMAGE_PREFIX
    return {component: f"{prefix}/{name}" for component, name in _COMPONENT_REPOSITORY_NAMES.items()}


def _match(pattern, value, field):
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise MetadataError(f"{field} is malformed")
    return value


def _positive_int(value, field):
    if type(value) is not int or not 1 <= value <= MAX_CI_NUMBER:
        raise MetadataError(f"{field} must be an integer between 1 and {MAX_CI_NUMBER}")
    return value


def _validate_images(images):
    if not isinstance(images, dict):
        raise MetadataError("images must be an object")
    if set(images) != set(_COMPONENT_REPOSITORY_NAMES):
        raise MetadataError(f"images must have exactly the keys {sorted(_COMPONENT_REPOSITORY_NAMES)}")
    for component, repository in _image_repositories().items():
        value = images[component]
        field = f"images.{component}"
        head, separator, digest = value.partition("@sha256:") if isinstance(value, str) else ("", "", "")
        if head != repository or not separator or _DIGEST_RE.fullmatch(digest) is None:
            raise MetadataError(f"{field} must be {repository}@sha256:<64 hex>")
    return dict(images)


def validate(obj):
    if not isinstance(obj, dict):
        raise MetadataError("document must be a JSON object")
    if "schema_version" in obj and (type(obj["schema_version"]) is not int or obj["schema_version"] != SCHEMA_VERSION):
        raise MetadataError(f"schema_version must be {SCHEMA_VERSION}")
    missing = [key for key in _FIELDS if key not in obj]
    if missing:
        raise MetadataError(f"missing keys: {', '.join(missing)}")
    unknown = sorted(str(key) for key in obj if key not in _FIELDS)
    if unknown:
        raise MetadataError(f"unknown keys: {', '.join(unknown)}")

    source_commit = _match(_COMMIT_RE, obj["source_commit"], "source_commit")
    if obj["built_from_candidate_tag"] != f"sha-{source_commit}":
        raise MetadataError("built_from_candidate_tag must be sha-<source_commit>")
    revision = _match(_REVISION_RE, obj["alembic_revision"], "alembic_revision")
    if revision.lower() in _RESERVED_REVISIONS:
        raise MetadataError("alembic_revision must be a concrete revision id, not head, heads or base")

    return ReleaseMetadata(
        schema_version=SCHEMA_VERSION,
        repository=_match(_REPOSITORY_RE, obj["repository"], "repository"),
        version=_match(_VERSION_RE, obj["version"], "version"),
        source_commit=source_commit,
        ci_run_id=_positive_int(obj["ci_run_id"], "ci_run_id"),
        ci_run_attempt=_positive_int(obj["ci_run_attempt"], "ci_run_attempt"),
        built_from_candidate_tag=obj["built_from_candidate_tag"],
        images=_validate_images(obj["images"]),
        alembic_revision=revision,
    )


def _reject_duplicates(pairs):
    seen = set()
    for key, _ in pairs:
        if key in seen:
            raise MetadataError(f"duplicate key {key!r}")
        seen.add(key)
    return dict(pairs)


def _reject_constant(name):
    raise MetadataError(f"non-finite number {name} is not allowed")


def loads(data):
    if not isinstance(data, (bytes, bytearray)):
        raise MetadataError("document must be bytes")
    if len(data) > MAX_BYTES:
        raise MetadataError(f"document exceeds {MAX_BYTES} bytes")
    try:
        text = bytes(data).decode("utf-8")
        obj = json.loads(text, object_pairs_hook=_reject_duplicates, parse_constant=_reject_constant)
    except MetadataError:
        raise
    except UnicodeDecodeError as error:
        raise MetadataError(f"document is not valid UTF-8: {error.reason}") from error
    except RecursionError as error:
        raise MetadataError("document is not valid JSON: nested too deeply") from error
    except ValueError as error:
        raise MetadataError(f"document is not valid JSON: {error}") from error
    return validate(obj)


def dumps(meta):
    if not isinstance(meta, ReleaseMetadata):
        raise MetadataError("meta must be a ReleaseMetadata")
    obj = dataclasses.asdict(validate(dataclasses.asdict(meta)))
    return (json.dumps(obj, sort_keys=True, indent=2) + "\n").encode("utf-8")


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def format_marker(digest):
    _match(_DIGEST_RE, digest, "digest")
    return f"<!-- {ASSET_NAME} sha256={digest} -->"


def parse_marker(body):
    if not isinstance(body, str):
        raise MetadataError("release body must be text")
    found = MARKER_RE.findall(body.replace("\r\n", "\n"))
    if len(found) != 1:
        raise MetadataError(f"release body must contain exactly one {ASSET_NAME} marker, found {len(found)}")
    return found[0]
