"""UTC timestamps for the HTTP contract and legacy store reads."""

from datetime import datetime, timezone
from typing import overload


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@overload
def normalize_timestamp(value: str, *, timespec: str = "auto") -> str: ...


@overload
def normalize_timestamp(value: None, *, timespec: str = "auto") -> None: ...


def normalize_timestamp(value: str | None, *, timespec: str = "auto") -> str | None:
    """Treat legacy naive values as UTC; retain corrupt values without inventing dates.

    A fixed microsecond precision is used for SQL ordering and keyset comparison,
    so equivalent naive, Z and offset values share the same sort key.
    """
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec=timespec).replace("+00:00", "Z")
