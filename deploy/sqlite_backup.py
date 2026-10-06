"""In-image SQLite backup/restore helper. Output contains checksums, never data."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from typing import TypedDict


class FileInfo(TypedDict):
    present: bool
    sha256: str | None
    size: int


def describe(path: Path) -> FileInfo:
    if not path.exists():
        return {"present": False, "sha256": None, "size": 0}
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"present": True, "sha256": digest.hexdigest(), "size": path.stat().st_size}


def backup(src: Path, dst: Path) -> FileInfo:
    """Never create a missing source; quiesced first-install stores may be absent."""
    if not src.exists():
        return describe(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    # The context manager commits transactions but does not close a connection.
    source = sqlite3.connect(src.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
    target = sqlite3.connect(dst, timeout=30)
    try:
        source.backup(target, pages=256, sleep=0.01)
        if target.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise sqlite3.DatabaseError("SQLite integrity check failed")
    finally:
        target.close()
        source.close()
    os.chmod(dst, 0o600)
    return describe(dst)


def restore(src: Path, dst: Path) -> FileInfo:
    """Validate before replacement; remove stale WAL/SHM only after validation."""
    tmp: Path | None = None
    try:
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=dst.parent, delete=False) as handle:
                tmp = Path(handle.name)
            backup(src, tmp)
        for suffix in ("-wal", "-shm"):
            Path(str(dst) + suffix).unlink(missing_ok=True)
        if tmp is None:
            dst.unlink(missing_ok=True)
        else:
            os.replace(tmp, dst)
        return describe(dst)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("operation", choices=("backup", "restore", "describe"))
    cli.add_argument("src", type=Path)
    cli.add_argument("dst", type=Path, nargs="?")
    args = cli.parse_args()
    try:
        if args.operation == "describe":
            result = describe(args.src)
        else:
            if args.dst is None:
                cli.error("backup and restore require a destination")
            result = backup(args.src, args.dst) if args.operation == "backup" else restore(args.src, args.dst)
        print(json.dumps(result))
        return 0
    except (OSError, sqlite3.Error):
        print("SQLite backup/restore failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
