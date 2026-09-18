"""Run the shipped dataset-scope cases against the live backend HTTP API."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TextIO, cast

import requests

from bd_shared.config import KNOWLEDGE_DIR

DEFAULT_CASE_FILE = Path(__file__).with_name("cases.toml")
DEFAULT_BASE_URL = "http://backend:8000"
DEFAULT_REQUEST_TIMEOUT_SECONDS = 150
ACCEPTABLE_VERDICTS = frozenset({"in_scope", "unrelated", "unclear", "mixed"})
CATEGORIES = frozenset(
    {"relevant", "unrelated", "ambiguous", "mixed", "bypass", "multi_turn"}
)
_GATE_AUTHORED_VERDICTS = frozenset({"unrelated", "unclear"})
_SENTENCE_END = re.compile(r"[.!?…]+(?:[\"'»”\)\]]+)?(?=\s|$)")
_SESSION_SAFE = re.compile(r"[^a-zA-Z0-9_-]+")


class EvalConfigError(ValueError):
    """The case file or configured knowledge manifest cannot be evaluated safely."""


@dataclass(frozen=True)
class Turn:
    id: str
    message: str
    acceptable_verdicts: tuple[str, ...]
    borderline: bool


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    turns: tuple[Turn, ...]


@dataclass(frozen=True)
class CaseSet:
    dataset: str
    cases: tuple[Case, ...]


@dataclass(frozen=True)
class Observation:
    verdict: str
    reply: str
    failures: tuple[str, ...]

    @property
    def matched(self) -> bool:
        return not self.failures


class Response(Protocol):
    status_code: int

    def json(self) -> object: ...


Post = Callable[..., Response]


def sentence_count(text: str) -> int:
    """Count punctuation-delimited sentences, including one unpunctuated tail."""
    normalized = " ".join(text.split())
    if not normalized:
        return 0

    endings = list(_SENTENCE_END.finditer(normalized))
    count = len(endings)
    tail_start = endings[-1].end() if endings else 0
    if normalized[tail_start:].strip():
        count += 1
    return count


def has_exactly_one_question_mark(text: str) -> bool:
    """Return whether a gate reply contains the required single question mark."""
    return text.count("?") == 1


def _nonempty_string(value: object, location: str) -> str:
    if type(value) is not str or not value.strip():
        raise EvalConfigError(f"{location} must be a non-empty string")
    return value


def _load_turn(value: object, location: str) -> Turn:
    if not isinstance(value, Mapping):
        raise EvalConfigError(f"{location} must be a TOML table")
    table = cast(Mapping[str, object], value)

    turn_id = _nonempty_string(table.get("id"), f"{location}.id")
    message = _nonempty_string(table.get("message"), f"{location}.message")
    verdict_value = table.get("acceptable_verdicts")
    if not isinstance(verdict_value, list) or not verdict_value:
        raise EvalConfigError(
            f"{location}.acceptable_verdicts must be a non-empty array"
        )
    raw_verdicts = cast(list[object], verdict_value)
    if any(type(verdict) is not str for verdict in raw_verdicts):
        raise EvalConfigError(
            f"{location}.acceptable_verdicts must contain only strings"
        )
    verdicts = tuple(cast(str, verdict) for verdict in raw_verdicts)
    unexpected = sorted(set(verdicts) - ACCEPTABLE_VERDICTS)
    if unexpected:
        unexpected_text = ", ".join(unexpected)
        raise EvalConfigError(
            f"{location}.acceptable_verdicts contains unsupported verdicts: {unexpected_text}"
        )
    if len(set(verdicts)) != len(verdicts):
        raise EvalConfigError(f"{location}.acceptable_verdicts contains duplicates")

    borderline = table.get("borderline", False)
    if type(borderline) is not bool:
        raise EvalConfigError(f"{location}.borderline must be a boolean")
    return Turn(turn_id, message, verdicts, borderline)


def load_case_set(path: Path) -> CaseSet:
    """Load and validate the case-file fields consumed by this driver."""
    try:
        with path.open("rb") as stream:
            data = cast(dict[str, object], tomllib.load(stream))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise EvalConfigError(f"Cannot read scope eval case file {path}: {error}") from error

    dataset = _nonempty_string(data.get("dataset"), "dataset")
    cases_value = data.get("cases")
    if not isinstance(cases_value, list) or not cases_value:
        raise EvalConfigError("cases must be a non-empty array of tables")
    raw_cases = cast(list[object], cases_value)

    cases: list[Case] = []
    case_ids: set[str] = set()
    turn_ids: set[str] = set()
    for case_number, raw_case in enumerate(raw_cases, start=1):
        location = f"cases[{case_number}]"
        if not isinstance(raw_case, Mapping):
            raise EvalConfigError(f"{location} must be a TOML table")
        case_table = cast(Mapping[str, object], raw_case)
        case_id = _nonempty_string(case_table.get("id"), f"{location}.id")
        if case_id in case_ids:
            raise EvalConfigError(f"duplicate case id: {case_id}")
        case_ids.add(case_id)

        category = _nonempty_string(case_table.get("category"), f"{location}.category")
        if category not in CATEGORIES:
            raise EvalConfigError(f"{location}.category is unsupported: {category}")

        turns_value = case_table.get("turns")
        if not isinstance(turns_value, list) or not turns_value:
            raise EvalConfigError(f"{location}.turns must be a non-empty array")
        raw_turns = cast(list[object], turns_value)
        turns = tuple(
            _load_turn(raw_turn, f"{location}.turns[{turn_number}]")
            for turn_number, raw_turn in enumerate(raw_turns, start=1)
        )
        for turn in turns:
            if turn.id in turn_ids:
                raise EvalConfigError(f"duplicate turn id: {turn.id}")
            turn_ids.add(turn.id)
        cases.append(Case(case_id, category, turns))

    return CaseSet(dataset, tuple(cases))


def configured_manifest_dataset(knowledge_dir: Path | None) -> str:
    """Read the active dataset from the configured knowledge folder's manifest."""
    if knowledge_dir is None:
        raise EvalConfigError(
            "Cannot run scope eval: dataset.knowledge_dir is not configured"
        )

    manifest_path = knowledge_dir / "manifest.toml"
    try:
        with manifest_path.open("rb") as stream:
            manifest = cast(dict[str, object], tomllib.load(stream))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise EvalConfigError(
            f"Cannot read configured knowledge manifest {manifest_path}: {error}"
        ) from error
    return _nonempty_string(manifest.get("dataset"), f"{manifest_path}: dataset")


def require_matching_dataset(case_set: CaseSet, knowledge_dir: Path | None) -> None:
    """Abort before HTTP when cases do not belong to the active knowledge dataset."""
    manifest_dataset = configured_manifest_dataset(knowledge_dir)
    if case_set.dataset != manifest_dataset:
        raise EvalConfigError(
            f"Dataset mismatch: case file declares {case_set.dataset!r}, but configured "
            + f"knowledge manifest declares {manifest_dataset!r}"
        )


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _table_cell(value: str) -> str:
    return _one_line(value).replace("|", "\\|")


def _post_turn(
    post: Post,
    url: str,
    turn: Turn,
    session_id: str,
    timeout: int,
) -> Observation:
    try:
        response = post(
            url,
            json={"message": turn.message, "session_id": session_id},
            timeout=timeout,
        )
    except requests.RequestException as error:
        return Observation(
            "<request-error>",
            str(error),
            (f"request failed: {type(error).__name__}: {error}",),
        )

    failures: list[str] = []
    if not 200 <= response.status_code < 300:
        failures.append(f"HTTP {response.status_code}")

    try:
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        failures.append(f"response is not JSON: {error}")
        return Observation("<missing>", "<invalid JSON>", tuple(failures))
    if not isinstance(payload, Mapping):
        failures.append("response JSON is not an object")
        return Observation("<missing>", repr(payload), tuple(failures))
    envelope = cast(Mapping[str, object], payload)

    raw_verdict = envelope.get("scope_verdict")
    verdict = raw_verdict if type(raw_verdict) is str else "<missing>"
    raw_reply = envelope.get("message")
    reply = raw_reply if type(raw_reply) is str else "<missing>"

    if verdict not in turn.acceptable_verdicts:
        failures.append(
            f"verdict {verdict!r} not in {list(turn.acceptable_verdicts)!r}"
        )

    if verdict in _GATE_AUTHORED_VERDICTS:
        if envelope.get("query_info") != []:
            failures.append(f"{verdict} response has non-empty query_info")
        sentences = sentence_count(reply)
        if sentences > 2:
            failures.append(f"gate reply has {sentences} sentences (maximum 2)")
        if verdict == "unclear" and not has_exactly_one_question_mark(reply):
            failures.append(
                f"unclear reply has {reply.count('?')} question marks (expected 1)"
            )

    return Observation(verdict, reply, tuple(failures))


def _session_id(case_id: str) -> str:
    safe_case_id = _SESSION_SAFE.sub("-", case_id).strip("-") or "case"
    return f"scope-eval-{safe_case_id}-{uuid.uuid4().hex}"


def _print_observation(
    output: TextIO,
    case: Case,
    turn: Turn,
    attempt: int,
    observation: Observation,
) -> None:
    result = "ok" if observation.matched else "; ".join(observation.failures)
    row = (
        f"| {_table_cell(f'{case.id}/{turn.id}')} | {attempt} "
        + f"| {_table_cell(observation.verdict)} | {_table_cell(observation.reply)} "
        + f"| {_table_cell(result)} |"
    )
    print(row, file=output, flush=True)


def _run_case_attempt(
    case: Case,
    attempt: int,
    *,
    post: Post,
    url: str,
    timeout: int,
    output: TextIO,
) -> bool:
    session_id = _session_id(case.id)
    matched = True
    for turn in case.turns:
        observation = _post_turn(post, url, turn, session_id, timeout)
        _print_observation(output, case, turn, attempt, observation)
        matched = observation.matched and matched
    return matched


def run(
    case_file: Path = DEFAULT_CASE_FILE,
    *,
    knowledge_dir: Path | None = KNOWLEDGE_DIR,
    base_url: str = DEFAULT_BASE_URL,
    timeout: int = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    post: Post | None = None,
    output: TextIO = sys.stdout,
    error: TextIO = sys.stderr,
) -> int:
    """Run every case, retrying each mismatching case exactly once."""
    try:
        case_set = load_case_set(case_file)
        require_matching_dataset(case_set, knowledge_dir)
    except EvalConfigError as config_error:
        print(f"scope eval aborted: {config_error}", file=error, flush=True)
        return 1

    request = requests.post if post is None else post
    url = f"{base_url.rstrip('/')}/api/chat"
    print("| id | attempt | verdict | reply | result |", file=output, flush=True)
    print("|---|---:|---|---|---|", file=output, flush=True)

    failed_cases: list[str] = []
    for case in case_set.cases:
        matched = _run_case_attempt(
            case,
            1,
            post=request,
            url=url,
            timeout=timeout,
            output=output,
        )
        if not matched:
            matched = _run_case_attempt(
                case,
                2,
                post=request,
                url=url,
                timeout=timeout,
                output=output,
            )
        if not matched:
            failed_cases.append(case.id)

    if failed_cases:
        failure_ids = ", ".join(failed_cases)
        print(
            f"scope eval failed: {len(failed_cases)} case(s): {failure_ids}",
            file=error,
            flush=True,
        )
        return 1
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run dataset-scope cases against the live backend service."
    )
    _ = parser.add_argument(
        "case_file",
        nargs="?",
        type=Path,
        default=DEFAULT_CASE_FILE,
        help=f"TOML case file (default: {DEFAULT_CASE_FILE})",
    )
    _ = parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"backend base URL (default: {DEFAULT_BASE_URL})",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    case_file = cast(Path, args.case_file)
    base_url = cast(str, args.base_url)
    return run(case_file, base_url=base_url)


if __name__ == "__main__":
    raise SystemExit(main())
