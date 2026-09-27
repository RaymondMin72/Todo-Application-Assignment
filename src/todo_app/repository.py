"""JSON file persistence for Todos.

This module is the only place that knows the persisted format: a UTF-8 JSON array whose records
carry exactly the six camel-case keys ``id``, ``title``, ``description``, ``dueDate``,
``isCompleted``, and ``createdAt``. Optional values are JSON ``null``; ``id`` is a canonical
lowercase UUID string, ``dueDate`` is ``YYYY-MM-DD``, and ``createdAt`` is ``YYYY-MM-DDTHH:MM:SSZ``.
"""

import contextlib
import json
import os
import tempfile
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError

from todo_app.errors import PersistenceReadError, PersistenceWriteError
from todo_app.models import Todo

_RECORD_KEYS = ("id", "title", "description", "dueDate", "isCompleted", "createdAt")
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class TodoRepository(Protocol):
    """Persistence boundary: loads and replaces the complete Todo collection."""

    def load_all(self) -> list[Todo]:
        """Return every stored Todo, or raise ``PersistenceReadError`` if the data is invalid."""
        ...

    def save_all(self, todos: Sequence[Todo]) -> None:
        """Replace the stored collection, or raise ``PersistenceWriteError`` without changing it."""
        ...


class JsonTodoRepository:
    """Stores the complete Todo collection in one JSON file with atomic replacement.

    Only the configured primary file is ever read. A missing file is an empty collection; any
    existing file that is not a completely valid collection raises ``PersistenceReadError`` and
    is left untouched. Writes go to a temporary file in the same directory and are published
    with ``os.replace``, so the primary file always holds either the previous or the new
    complete collection.
    """

    def __init__(self, data_path: Path) -> None:
        self._path = data_path

    def load_all(self) -> list[Todo]:
        try:
            raw = self._path.read_bytes()
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise PersistenceReadError(f"Cannot read {self._path}: {exc}") from exc

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PersistenceReadError(f"{self._path} is not valid UTF-8: {exc}") from exc
        if not text.strip():
            raise PersistenceReadError(f"{self._path} exists but contains no data")
        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PersistenceReadError(f"{self._path} is not valid JSON: {exc}") from exc
        if not isinstance(document, list):
            raise PersistenceReadError(f"{self._path} must contain a JSON array at the top level")

        todos: list[Todo] = []
        seen: set[UUID] = set()
        for index, item in enumerate(document):
            try:
                todo = _decode_record(item)
            except ValueError as exc:
                raise PersistenceReadError(
                    f"{self._path} record {index} is invalid: {exc}"
                ) from exc
            if todo.id in seen:
                raise PersistenceReadError(f"{self._path} contains duplicate id {todo.id}")
            seen.add(todo.id)
            todos.append(todo)
        return todos

    def save_all(self, todos: Sequence[Todo]) -> None:
        records = _encode_all(todos)
        directory = self._path.parent
        try:
            directory.mkdir(parents=True, exist_ok=True)
            # The temporary file must share the destination directory so os.replace() is an
            # atomic rename on the same filesystem.
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{self._path.name}.", suffix=".tmp", dir=directory
            )
        except OSError as exc:
            raise PersistenceWriteError(f"Cannot prepare to write {self._path}: {exc}") from exc

        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(records, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                # Force the data to disk before publishing so a crash cannot leave the primary
                # path pointing at an incompletely written file.
                os.fsync(handle.fileno())
            os.replace(temp_path, self._path)
        except OSError as exc:
            _discard(temp_path)
            raise PersistenceWriteError(f"Cannot write {self._path}: {exc}") from exc


def _discard(temp_path: Path) -> None:
    # Best effort only: the original failure is what the caller needs to see. A leftover
    # temporary file is harmless because load_all() reads only the primary path.
    with contextlib.suppress(OSError):
        os.unlink(temp_path)


def _decode_record(item: object) -> Todo:
    if not isinstance(item, dict):
        raise ValueError("record must be a JSON object")
    if set(item) != set(_RECORD_KEYS):
        raise ValueError(f"record must have exactly the keys {', '.join(_RECORD_KEYS)}")
    fields = {
        "id": _decode_uuid(item["id"]),
        "title": item["title"],
        "description": item["description"],
        "due_date": _decode_optional_date(item["dueDate"]),
        "is_completed": item["isCompleted"],
        "created_at": _decode_timestamp(item["createdAt"]),
    }
    # Todo runs in strict mode, so remaining type and field-rule violations fail here as
    # ValidationError, which is a ValueError.
    return Todo.model_validate(fields)


def _decode_uuid(value: object) -> UUID:
    if not isinstance(value, str):
        raise ValueError("id must be a string")
    try:
        parsed = UUID(value)
    except ValueError:
        raise ValueError(f"id {value!r} is not a UUID") from None
    if str(parsed) != value:
        raise ValueError(f"id {value!r} is not a canonical lowercase hyphenated UUID")
    return parsed


def _decode_optional_date(value: object) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("dueDate must be a string or null")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"dueDate {value!r} is not a YYYY-MM-DD date") from None
    # fromisoformat() also accepts other ISO 8601 forms; require the exact canonical text.
    if parsed.isoformat() != value:
        raise ValueError(f"dueDate {value!r} is not in canonical YYYY-MM-DD form")
    return parsed


def _decode_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("createdAt must be a string")
    try:
        parsed = datetime.strptime(value, _TIMESTAMP_FORMAT)
    except ValueError:
        raise ValueError(f"createdAt {value!r} is not a YYYY-MM-DDTHH:MM:SSZ timestamp") from None
    # strptime() tolerates unpadded fields; only the exact canonical text is valid.
    if parsed.strftime(_TIMESTAMP_FORMAT) != value:
        raise ValueError(f"createdAt {value!r} is not in canonical YYYY-MM-DDTHH:MM:SSZ form")
    return parsed.replace(tzinfo=UTC)


def _encode_all(todos: Sequence[Todo]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    seen: set[UUID] = set()
    for index, todo in enumerate(todos):
        # model_copy(update=...) bypasses validation, so re-check every field before writing.
        try:
            valid = Todo.model_validate(todo.model_dump())
        except ValidationError as exc:
            raise PersistenceWriteError(f"Todo {index} is invalid: {exc}") from exc
        if valid.created_at.microsecond:
            raise PersistenceWriteError(
                f"Todo {index} createdAt must have whole-second precision to be stored"
            )
        if valid.id in seen:
            raise PersistenceWriteError(f"Todo collection contains duplicate id {valid.id}")
        seen.add(valid.id)
        records.append(_encode_record(valid))
    return records


def _encode_record(todo: Todo) -> dict[str, object]:
    return {
        "id": str(todo.id),
        "title": todo.title,
        "description": todo.description,
        "dueDate": None if todo.due_date is None else todo.due_date.isoformat(),
        "isCompleted": todo.is_completed,
        "createdAt": todo.created_at.astimezone(UTC).strftime(_TIMESTAMP_FORMAT),
    }
