"""Immutable result files beside the workspace, never inside tracked source folders."""

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 4 * 1024 * 1024
MAX_CHAT_BYTES = 128 * 1024 * 1024
IDENTIFIER = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


class ResultStore:
    def __init__(self, root):
        self.root = Path(root)
        self.lock = threading.Lock()

    def folder(self, chat_id):
        if not IDENTIFIER.fullmatch(chat_id):
            raise ValueError("Invalid chat identifier")
        return self.root / chat_id

    def save(self, chat_id, value, *, kind="data", provenance=None, title=""):
        record = {"id": uuid.uuid4().hex, "kind": kind, "title": title,
                  "created_at": datetime.now(timezone.utc).isoformat(),
                  "provenance": provenance or {}, "value": value}
        content = json.dumps(record, ensure_ascii=False, allow_nan=False).encode()
        if len(content) > MAX_BYTES:
            raise ValueError("Result exceeds 4 MiB. Request fewer columns or aggregate the data.")
        with self.lock:
            folder = self.folder(chat_id)
            folder.mkdir(parents=True, exist_ok=True)
            if sum(p.stat().st_size for p in folder.glob("*.json")) + len(content) > MAX_CHAT_BYTES:
                raise ValueError("This chat has reached its 128 MiB analysis storage limit. Start a new chat.")
            with (folder / (record["id"] + ".json")).open("xb") as stream:
                stream.write(content)
        return record

    def get(self, chat_id, result_id):
        if not re.fullmatch(r"[a-f0-9]{32}", result_id):
            raise ValueError("Invalid result identifier")
        path = self.folder(chat_id) / (result_id + ".json")
        if path.is_symlink() or not path.is_file():
            raise ValueError("Result not found in this chat. Query the data again.")
        return json.loads(path.read_text(encoding="utf-8"))

    def delete_chat(self, chat_id):
        # Delete only our generated regular files, never arbitrary recursive paths.
        folder = self.folder(chat_id)
        if folder.is_dir() and not folder.is_symlink():
            with self.lock:
                for path in folder.glob("*.json"):
                    if re.fullmatch(r"[a-f0-9]{32}\.json", path.name) and not path.is_symlink():
                        path.unlink()
                if not any(folder.iterdir()):
                    folder.rmdir()


def preview(value, limit=5):
    """Bound nested JSON by both depth and total bytes, not just its outer row count."""
    def brief(item, depth=0):
        if depth > 4:
            return "…"
        if isinstance(item, list):
            return {"count": len(item), "preview": [brief(v, depth + 1) for v in item[:limit]]}
        if isinstance(item, dict):
            return {str(k): brief(v, depth + 1) for k, v in list(item.items())[:30]}
        return item[:700] + "…" if isinstance(item, str) and len(item) > 700 else item
    result = brief(value)
    if len(json.dumps(result, ensure_ascii=False)) > 10000:
        return {"structure": list(value)[:30] if isinstance(value, dict) else type(value).__name__,
                "note": "Preview is too wide; use read_result or run_python to select columns."}
    return result


def rows_at(value, table="rows"):
    if isinstance(value, list):
        rows = value
    elif isinstance(value, dict):
        rows = value.get(table)
    else:
        rows = None
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Select a table of row objects, or return a DataFrame from run_python.")
    return rows
