"""Types for the operator knowledge folder subsystem.

Deliberately takes no dependency on bd_shared.config: limits and the
database name are passed in as arguments by the caller, keeping this
module pure and independently testable (AC-16 requires no config or
DB coupling here).

Containment uses resolve-then-open and therefore has an accepted TOCTOU
gap. The knowledge folder is operator-owned, writable only by the operator,
and read once at startup with no concurrent writer or hot reload. An attacker
able to win that race already has deployment write access, so this is a
deliberate scope boundary rather than a missed case.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
)


class KnowledgeError(Exception):
    """Raised when a knowledge folder, manifest, or document fails validation."""

    def __init__(self, message, *, path, key=None, rule=None):
        super().__init__(message)
        self.path = path
        self.key = key
        self.rule = rule


@dataclass(frozen=True)
class KnowledgeLimits:
    max_title_chars: int
    max_summary_chars: int
    max_persona_chars: int
    max_topics: int
    max_doc_bytes: int
    max_bytes_per_turn: int


@dataclass(frozen=True)
class KnowledgeTopic:
    id: str
    title: str
    summary: str
    text: str


@dataclass(frozen=True)
class Knowledge:
    manifest: object
    topics: tuple[KnowledgeTopic, ...]


class KnowledgeManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: str = Field(pattern=r"^[a-z0-9_-]{1,64}$")
    persona: str = Field(min_length=1)

    @field_validator("persona")
    @classmethod
    def validate_persona_length(cls, value: str, info: ValidationInfo) -> str:
        max_persona_chars = (info.context or {}).get("max_persona_chars")
        if max_persona_chars is not None and len(value) > max_persona_chars:
            raise ValueError("persona exceeds max_persona_chars")
        return value


def _safe_read_bytes(folder: Path, name: str) -> bytes:
    """Read one regular top-level file without escaping its resolved folder."""
    candidate_path = folder / name
    try:
        resolved_folder = folder.resolve()
        resolved_candidate = candidate_path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise KnowledgeError(
            f"Knowledge file is missing or invalid: {candidate_path}: {error}",
            path=candidate_path,
        ) from error

    if resolved_candidate.parent != resolved_folder or not resolved_candidate.is_file():
        raise KnowledgeError(
            f"Knowledge file is not a regular file inside its folder: {candidate_path}",
            path=candidate_path,
        )

    try:
        return resolved_candidate.read_bytes()
    except OSError as error:
        raise KnowledgeError(
            f"Unable to read knowledge file {candidate_path}: {error}",
            path=candidate_path,
        ) from error


def load_knowledge(
    path: Path,
    database_name: str,
    limits: KnowledgeLimits,
) -> Knowledge:
    """Load and validate the manifest for an operator knowledge folder."""
    try:
        folder = path.resolve()
    except (OSError, RuntimeError) as error:
        raise KnowledgeError(
            f"Knowledge folder is invalid: {path}: {error}",
            path=path,
        ) from error

    if not folder.is_dir():
        raise KnowledgeError(f"Knowledge folder is not a directory: {path}", path=path)

    manifest_path = folder / "manifest.toml"
    manifest_bytes = _safe_read_bytes(folder, "manifest.toml")
    try:
        manifest_data = tomllib.loads(manifest_bytes.decode("utf-8"))
    except UnicodeDecodeError as error:
        raise KnowledgeError(
            f"Knowledge manifest is not UTF-8: {manifest_path}: {error}",
            path=manifest_path,
        ) from error
    except tomllib.TOMLDecodeError as error:
        raise KnowledgeError(
            f"Invalid TOML in knowledge manifest {manifest_path}: {error}",
            path=manifest_path,
        ) from error

    try:
        manifest = KnowledgeManifest.model_validate(
            manifest_data,
            context={"max_persona_chars": limits.max_persona_chars},
        )
    except ValidationError as error:
        raise KnowledgeError(
            f"Invalid knowledge manifest {manifest_path}: {error}",
            path=manifest_path,
        ) from error

    if manifest.dataset != database_name:
        mismatch_message = f"dataset {manifest.dataset!r} does not match configured database {database_name!r}"
        raise KnowledgeError(
            mismatch_message,
            path=manifest_path,
        )

    return Knowledge(manifest=manifest, topics=())
