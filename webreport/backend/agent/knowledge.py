"""Types for the operator knowledge folder subsystem.

Deliberately takes no dependency on bd_shared.config: limits and the
database name are passed in as arguments by the caller, keeping this
module pure and independently testable (AC-16 requires no config or
DB coupling here).
"""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


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
