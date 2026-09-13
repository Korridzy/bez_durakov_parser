"""Atomic local metadata store. Secrets are encrypted outside the tracked source tree."""

import copy
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet
from connectors.catalog import public_config


def identifier():
    return uuid.uuid4().hex


def now():
    return datetime.now(timezone.utc).isoformat()


class WorkspaceStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        self.temporary_secrets = {}
        path.parent.mkdir(parents=True, exist_ok=True)
        key_path = path.with_suffix(".key")
        if not key_path.exists():
            # Exclusive create prevents silently replacing a key during startup.
            try:
                with key_path.open("xb") as stream:
                    stream.write(Fernet.generate_key())
                os.chmod(key_path, 0o600)
            except FileExistsError:
                pass
        self.cipher = Fernet(key_path.read_bytes())
        if path.exists():
            self.state = json.loads(path.read_text(encoding="utf-8"))
        else:
            self.state = {
                "version": 1,
                "projects": [],
                "chats": [],
                "sources": [],
                "models": [],
                "jobs": [],
            }
        for job in self.state["jobs"]:
            if job["status"] == "running":
                job.update(
                    status="interrupted",
                    error="Сервер перезапустился. Можно повторить запрос.",
                )
                for chat in self.state["chats"]:
                    if chat["id"] == job.get("chat_id"):
                        chat.setdefault("messages", []).append(
                            {
                                "id": identifier(),
                                "role": "error",
                                "content": job["error"],
                                "created_at": now(),
                                "request_id": job["id"],
                            }
                        )
        self._save()

    def _save(self):
        temp = self.path.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as stream:
            json.dump(self.state, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, self.path)
        os.chmod(self.path, 0o600)

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def get(self, collection, item_id):
        with self.lock:
            for item in self.state[collection]:
                if item["id"] == item_id:
                    return copy.deepcopy(item)
        raise KeyError(item_id)

    def add(self, collection, item):
        with self.lock:
            item = {"id": identifier(), "created_at": now(), **item}
            self.state[collection].append(item)
            self._save()
            return copy.deepcopy(item)

    def update(self, collection, item_id, **changes):
        with self.lock:
            for item in self.state[collection]:
                if item["id"] == item_id:
                    item.update(changes)
                    self._save()
                    return copy.deepcopy(item)
        raise KeyError(item_id)

    def delete(self, collection, item_id):
        with self.lock:
            self.state[collection] = [
                i for i in self.state[collection] if i["id"] != item_id
            ]
            self.temporary_secrets.pop(item_id, None)
            self._save()

    def secret_payload(self, secret, remember):
        return (
            self.cipher.encrypt(json.dumps(secret).encode()).decode()
            if remember
            else None
        )

    def save_secret(self, collection, item_id, secret, remember):
        with self.lock:
            changes = {}
            if collection == "sources":
                changes = {
                    "config": public_config(
                        self.get(collection, item_id).get("provider"), secret
                    ),
                    "connection_error": None,
                    "connection_error_status": None,
                }
            self.temporary_secrets[item_id] = secret
            self.update(
                collection,
                item_id,
                encrypted=self.secret_payload(secret, remember),
                remembered=remember,
                **changes,
            )

    def secret(self, item):
        with self.lock:
            if item["id"] in self.temporary_secrets:
                return copy.deepcopy(self.temporary_secrets[item["id"]])
            if item.get("encrypted"):
                return json.loads(self.cipher.decrypt(item["encrypted"].encode()))
        return None

    def public(self, item):
        secret = self.secret(item)
        result = {
            k: v
            for k, v in item.items()
            if k not in {"encrypted", "messages", "result", "events", "config"}
        } | {"connected": secret is not None}
        if item.get("provider") and "project_id" in item:
            needs_key = secret is None or item.get("connection_error_status") in (
                401,
                403,
            )
            result.update(
                config=public_config(
                    item["provider"],
                    {
                        **item.get("metadata", {}),
                        **(secret or {}),
                        **item.get("config", {}),
                    },
                ),
                has_credentials=secret is not None,
                connected=not needs_key,
                connection_status=(
                    "reconnect"
                    if needs_key
                    else "error"
                    if item.get("connection_error")
                    else "ready"
                ),
            )
        return result

    def append_message(self, chat_id, message):
        with self.lock:
            chat = self.get("chats", chat_id)
            self.update(
                "chats",
                chat_id,
                messages=[*chat.get("messages", []), message],
                updated_at=now(),
            )

    def event(self, job_id, event):
        with self.lock:
            job = self.get("jobs", job_id)
            events = job.get("events", [])
            event = {"at": now(), **event}
            # Consecutive token chunks are folded into a single entry to bound disk growth.
            if (
                event.get("type") in {"text_delta", "reasoning_delta"}
                and events
                and events[-1].get("type") == event["type"]
            ):
                events[-1]["text"] = (
                    events[-1].get("text", "") + event.get("text", "")
                )[-100000:]
            else:
                events.append(event)
            self.update("jobs", job_id, events=events[-150:])
