"""Administer the durable conversation archive without exposing HTTP routes."""

import argparse
import asyncio
from datetime import datetime, timezone
import json
import sys

import requests

from archive import ArchiveSettings, ConversationArchive
from bd_shared.config import (
    ARCHIVE_DB_PATH,
    LANGFUSE_ENABLED,
    LANGFUSE_HOST,
    LANGFUSE_PUBLIC_KEY,
    LANGFUSE_SECRET_KEY,
)


_LIST_COLUMNS = (
    "id",
    "created_at",
    "status",
    "error",
    "session_id",
    "request_id",
    "trace_id",
)
_LANGFUSE_BATCH_SIZE = 30
_ALL_ROWS_LIMIT = 2**63 - 1
_CLI_SETTINGS = ArchiveSettings(
    enabled=False,
    retention_days=0,
    store_reasoning=False,
    reasoning_retention_days=0,
    sweep_interval_seconds=0,
)


def _before(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "must be an ISO-8601 date or timestamp"
        ) from error
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Administer the conversation archive")
    commands = parser.add_subparsers(dest="command", required=True)

    list_parser = commands.add_parser("list", help="list archived turns")
    list_parser.add_argument("--session")
    list_parser.add_argument("--user")
    list_parser.add_argument("--limit", type=int, default=50)

    show_parser = commands.add_parser("show", help="show one complete archived turn")
    show_parser.add_argument("--id", type=int, required=True)

    delete_parser = commands.add_parser("delete", help="delete archived turns")
    selector = delete_parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--session")
    selector.add_argument("--user")
    selector.add_argument("--before", type=_before)
    return parser


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


async def _rows_selected_for_delete(
    archive: ConversationArchive, arguments: argparse.Namespace
) -> list[dict[str, object]]:
    if arguments.session is not None:
        return await archive.list_turns(
            session_id=arguments.session, limit=_ALL_ROWS_LIMIT
        )
    if arguments.user is not None:
        return await archive.list_turns(user_id=arguments.user, limit=_ALL_ROWS_LIMIT)

    rows = await archive.list_turns(limit=_ALL_ROWS_LIMIT)
    cutoff = _timestamp(arguments.before)
    return [row for row in rows if str(row["created_at"]) < cutoff]


async def _delete_local(
    archive: ConversationArchive, arguments: argparse.Namespace
) -> tuple[int, list[str]]:
    rows = await _rows_selected_for_delete(archive, arguments)
    trace_ids = list(dict.fromkeys(str(row["trace_id"]) for row in rows))
    if arguments.session is not None:
        count = await archive.delete_session(arguments.session)
    elif arguments.user is not None:
        count = await archive.delete_user(arguments.user)
    else:
        count = await archive.delete_before(arguments.before)
    return count, trace_ids


def _delete_langfuse(trace_ids: list[str]) -> bool:
    endpoint = f"{LANGFUSE_HOST.rstrip('/')}/api/public/traces"
    try:
        for offset in range(0, len(trace_ids), _LANGFUSE_BATCH_SIZE):
            batch = trace_ids[offset : offset + _LANGFUSE_BATCH_SIZE]
            response = requests.delete(
                endpoint,
                auth=(LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY),
                json={"traceIds": batch},
                timeout=60,
            )
            if response.status_code >= 400:
                raise requests.HTTPError(
                    f"DELETE {endpoint} returned HTTP {response.status_code}"
                )
    except Exception as error:
        print(f"Langfuse deletion failed: {error}")
        return False

    print(
        f"Submitted {len(trace_ids)} traces for deletion in Langfuse (asynchronous)"
    )
    return True


async def _run(arguments: argparse.Namespace) -> int:
    archive = ConversationArchive(ARCHIVE_DB_PATH, settings=_CLI_SETTINGS)
    try:
        await archive.setup()
        if arguments.command == "list":
            rows = await archive.list_turns(
                session_id=arguments.session,
                user_id=arguments.user,
                limit=arguments.limit,
            )
            print("\t".join(_LIST_COLUMNS))
            for row in rows:
                print(
                    "\t".join(
                        "" if row[column] is None else str(row[column])
                        for column in _LIST_COLUMNS
                    )
                )
            return 0

        if arguments.command == "show":
            row = await archive.get_turn(arguments.id)
            if row is None:
                print(f"Archive row {arguments.id} was not found", file=sys.stderr)
                return 1
            print(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True))
            return 0

        count, trace_ids = await _delete_local(archive, arguments)
    except Exception as error:
        print(f"Archive operation failed: {error}", file=sys.stderr)
        return 1
    finally:
        await archive.close()

    print(f"Deleted {count} local rows")
    if LANGFUSE_ENABLED and not _delete_langfuse(trace_ids):
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run one archive administration command and return its process status."""
    return asyncio.run(_run(_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
