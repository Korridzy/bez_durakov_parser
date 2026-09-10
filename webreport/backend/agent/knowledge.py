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

import re
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

    def __init__(
        self,
        message,
        *,
        path,
        key=None,
        rule=None,
        observed=None,
        permitted=None,
    ):
        super().__init__(message)
        self.path = path
        self.key = key
        self.rule = rule
        self.observed = observed
        self.permitted = permitted


@dataclass(frozen=True)
class KnowledgeLimits:
    max_title_chars: int
    max_summary_chars: int
    max_persona_chars: int
    max_topics: int
    max_doc_bytes: int
    max_bytes_per_turn: int


def validate_limits(limits: KnowledgeLimits) -> None:
    limit_values = (
        ("knowledge_max_title_chars", limits.max_title_chars),
        ("knowledge_max_summary_chars", limits.max_summary_chars),
        ("knowledge_max_persona_chars", limits.max_persona_chars),
        ("knowledge_max_topics", limits.max_topics),
        ("knowledge_max_doc_bytes", limits.max_doc_bytes),
    )
    for config_key, value in limit_values:
        if type(value) is not int or value < 1:
            raise KnowledgeError(
                f"Invalid knowledge limit {config_key}: must be an integer greater than or equal to 1",
                path=None,
                key=config_key,
            )


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
            raise ValueError(
                f"persona exceeds max_persona_chars: persona is {len(value)} characters, "
                f"limit is {max_persona_chars}"
            )
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


_HEADING_LINE_RE = re.compile(r"^#{1,6}\s+\S")
_HEADING_STRIP_RE = re.compile(r"^#{1,6}\s+")

_DISQUALIFYING_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("bullet list", re.compile(r"^[-*+]\s")),
    ("ordered list", re.compile(r"^\d+\.")),
    ("fenced code block", re.compile(r"^(```|~~~)")),
    ("heading", re.compile(r"^#")),
    ("blockquote", re.compile(r"^>")),
    ("table", re.compile(r"^\|")),
    ("HTML block", re.compile(r"^<")),
)


def _derive_title_and_summary(
    text: str,
    entry: Path,
    limits: KnowledgeLimits,
) -> tuple[str, str]:
    """Derive a strict title and summary per decisions C3/C4.

    Title = the first line matching ^#{1,6}\\s+\\S, with only the leading
    hashes and surrounding whitespace stripped - nothing else (decision C4).
    Summary = the first non-blank block (consecutive non-blank lines) after
    that heading, joined by single spaces. If that block's first line opens
    with one of seven disqualifying markers, this raises instead of treating
    it as a paragraph (decision C3). Nothing is ever truncated.
    """
    lines = text.splitlines()

    heading_index = None
    for index, line in enumerate(lines):
        if _HEADING_LINE_RE.match(line):
            heading_index = index
            break

    if heading_index is None:
        raise KnowledgeError(
            f"Knowledge document has no heading: {entry}",
            path=entry,
        )

    title = _HEADING_STRIP_RE.sub("", lines[heading_index], count=1).strip()
    if len(title) > limits.max_title_chars:
        raise KnowledgeError(
            f"Knowledge document title exceeds {limits.max_title_chars} characters: {entry}; "
            f"title is {len(title)} characters, limit is {limits.max_title_chars}",
            path=entry,
            observed=len(title),
            permitted=limits.max_title_chars,
        )

    remaining_lines = lines[heading_index + 1:]
    block_start = None
    for index, line in enumerate(remaining_lines):
        if line.strip():
            block_start = index
            break

    if block_start is None:
        raise KnowledgeError(
            f"Knowledge document heading has no following paragraph: {entry}",
            path=entry,
        )

    block_lines: list[str] = []
    for line in remaining_lines[block_start:]:
        if not line.strip():
            break
        block_lines.append(line.strip())

    first_block_line = block_lines[0]
    for marker_name, pattern in _DISQUALIFYING_MARKERS:
        if pattern.match(first_block_line):
            raise KnowledgeError(
                f"Knowledge document paragraph after the heading is a {marker_name}, not plain text: {entry}",
                path=entry,
                rule=marker_name,
            )

    summary = " ".join(block_lines)
    if len(summary) > limits.max_summary_chars:
        raise KnowledgeError(
            f"Knowledge document summary exceeds {limits.max_summary_chars} characters: {entry}; "
            f"summary is {len(summary)} characters, limit is {limits.max_summary_chars}",
            path=entry,
            observed=len(summary),
            permitted=limits.max_summary_chars,
        )

    return title, summary


def load_knowledge(
    path: Path,
    database_name: str,
    limits: KnowledgeLimits,
) -> Knowledge:
    """Load and validate the manifest for an operator knowledge folder."""
    validate_limits(limits)
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
        persona = manifest_data.get("persona")
        if isinstance(persona, str) and len(persona) > limits.max_persona_chars:
            detail = str(error).replace("\n", " ")
            raise KnowledgeError(
                f"Invalid knowledge manifest {manifest_path}: {detail}",
                path=manifest_path,
                observed=len(persona),
                permitted=limits.max_persona_chars,
            ) from error
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

    topics: list[KnowledgeTopic] = []
    for entry in sorted(folder.iterdir(), key=lambda candidate: candidate.name.encode("utf-8")):
        if entry.name == "manifest.toml":
            continue
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            raise KnowledgeError(
                f"Knowledge folder contains a subdirectory: {entry}",
                path=entry,
            )
        if not entry.name.endswith(".md"):
            continue

        raw_bytes = _safe_read_bytes(folder, entry.name)
        if len(raw_bytes) > limits.max_doc_bytes:
            raise KnowledgeError(
                f"Knowledge document exceeds {limits.max_doc_bytes} bytes: {entry}; "
                f"document is {len(raw_bytes)} bytes, limit is {limits.max_doc_bytes}",
                path=entry,
                observed=len(raw_bytes),
                permitted=limits.max_doc_bytes,
            )
        topic_id = entry.stem
        if re.fullmatch(r"[a-z0-9_-]{1,40}", topic_id) is None:
            raise KnowledgeError(
                f"Topic filename stem is invalid: {entry.name}",
                path=entry,
            )

        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise KnowledgeError(
                f"Knowledge document is not UTF-8: {entry}: {error}",
                path=entry,
            ) from error
        title, summary = _derive_title_and_summary(text, entry, limits)
        topics.append(KnowledgeTopic(id=topic_id, title=title, summary=summary, text=text))

    topic_count = len(topics)
    if topic_count == 0 or topic_count > limits.max_topics:
        raise KnowledgeError(
            f"Knowledge folder {folder} has {topic_count} topic documents; "
            f"must be between 1 and {limits.max_topics}; "
            f"topic count is {topic_count}, limit is {limits.max_topics}",
            path=folder,
            observed=topic_count,
            permitted=limits.max_topics,
        )

    return Knowledge(manifest=manifest, topics=tuple(topics))


def compose_system_prompt(knowledge: Knowledge | None) -> str:
    rules = (
        "Get data ONLY through the tools.",
        "The tools return a summary, not the rows themselves. If you need rows, call read_rows.",
        "Row budgets are bounded per call and per request. When a budget is exhausted, answer with what you have.",
        "Once you have received data, call mark_report(handle).",
        "If there is nothing, say so plainly and do not mark a report.",
        "Do not invent numbers or names.",
    )

    if knowledge is None:
        persona = "You are a data analyst for the connected database. Answer in the language of the user's question."
        return f"{persona}\n\n" + "\n".join(f"- {rule}" for rule in rules)

    persona = knowledge.manifest.persona
    rules += (
        "Before answering a question covered by a listed topic, call read_knowledge with that topic id.",
    )
    topic_lines = "\n".join(
        f"{topic.id}: {topic.title}{'' if topic.title.endswith(('.', '!', '?', '…', ':')) else '.'} {topic.summary}"
        for topic in knowledge.topics
    )
    return (
        f"{persona}\n\n"
        + "\n".join(f"- {rule}" for rule in rules)
        + f"\n\n## Knowledge topics\n\n{topic_lines}"
    )
