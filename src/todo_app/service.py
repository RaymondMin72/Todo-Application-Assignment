"""Todo business operations."""

import threading
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from uuid import UUID, uuid4

from todo_app.errors import TodoNotFound
from todo_app.models import Todo, TodoInput
from todo_app.repository import TodoRepository

Clock = Callable[[], datetime]
UUIDFactory = Callable[[], UUID]


def utc_now() -> datetime:
    """Return the current time as an aware UTC datetime."""
    return datetime.now(UTC)


class TodoService:
    """Implements the Todo operations on top of a repository.

    One re-entrant lock, owned by the service, is held for every complete read and every complete
    load-change-save sequence, so operations within one process never interleave. All methods are
    synchronous and never wait on anything else while holding the lock.

    Operations that target a Todo take the raw ID text; malformed and unmatched IDs both raise
    ``TodoNotFound``. Mutations return only after the repository has saved the new collection, so
    a persistence failure is never reported as success.
    """

    def __init__(
        self,
        repository: TodoRepository,
        clock: Clock = utc_now,
        uuid_factory: UUIDFactory = uuid4,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._uuid_factory = uuid_factory
        self._lock = threading.RLock()

    def list_todos(self) -> list[Todo]:
        """Return every Todo, newest first; equal creation times are ordered by ID ascending."""
        with self._lock:
            todos = self._repository.load_all()
        by_id = sorted(todos, key=lambda todo: str(todo.id))
        return sorted(by_id, key=lambda todo: todo.created_at, reverse=True)

    def get_todo(self, raw_id: str) -> Todo:
        """Return the Todo with the given ID or raise ``TodoNotFound``."""
        todo_id = _parse_id(raw_id)
        with self._lock:
            todos = self._repository.load_all()
        return todos[_index_of(todos, todo_id)]

    def create_todo(self, values: Mapping[str, str]) -> Todo:
        """Validate the editable values and store a new, incomplete Todo.

        Only ``title``, ``description``, and ``due_date`` are read from ``values``. Raises
        ``InputValidationError`` without touching the repository if any of them is invalid.
        """
        todo_input = TodoInput.from_mapping(values)
        with self._lock:
            todos = self._repository.load_all()
            todo = Todo(
                id=self._new_id(todos),
                title=todo_input.title,
                description=todo_input.description,
                due_date=todo_input.due_date,
                is_completed=False,
                created_at=self._now(),
            )
            self._repository.save_all([*todos, todo])
        return todo

    def update_todo(self, raw_id: str, values: Mapping[str, str]) -> Todo:
        """Replace the title, description, and due date of an existing Todo together.

        The target is resolved before the values are validated, so an unknown ID raises
        ``TodoNotFound`` even when the values are also invalid. ID, creation time, and completion
        state are preserved.
        """
        todo_id = _parse_id(raw_id)
        with self._lock:
            todos = self._repository.load_all()
            index = _index_of(todos, todo_id)
            todo_input = TodoInput.from_mapping(values)
            updated = todos[index].model_copy(
                update={
                    "title": todo_input.title,
                    "description": todo_input.description,
                    "due_date": todo_input.due_date,
                }
            )
            self._save_replacing(todos, index, updated)
        return updated

    def set_completed(self, raw_id: str, completed: bool) -> Todo:
        """Set only the completion state of a Todo; repeating the same state succeeds."""
        todo_id = _parse_id(raw_id)
        with self._lock:
            todos = self._repository.load_all()
            index = _index_of(todos, todo_id)
            updated = todos[index].model_copy(update={"is_completed": completed})
            self._save_replacing(todos, index, updated)
        return updated

    def delete_todo(self, raw_id: str) -> None:
        """Permanently remove exactly one Todo."""
        todo_id = _parse_id(raw_id)
        with self._lock:
            todos = self._repository.load_all()
            index = _index_of(todos, todo_id)
            self._repository.save_all([*todos[:index], *todos[index + 1 :]])

    def _save_replacing(self, todos: list[Todo], index: int, updated: Todo) -> None:
        self._repository.save_all([*todos[:index], updated, *todos[index + 1 :]])

    def _new_id(self, existing: list[Todo]) -> UUID:
        value = self._uuid_factory()
        # UUID.version is None for non-RFC 4122 variants, so this also rejects them.
        if not isinstance(value, UUID) or value.version != 4:
            raise RuntimeError("The UUID factory must return a UUID version 4.")
        if any(todo.id == value for todo in existing):
            raise RuntimeError("The UUID factory returned an ID that is already in use.")
        return value

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.utcoffset() is None:
            raise RuntimeError("The clock must return a timezone-aware datetime.")
        # Stored timestamps have whole-second precision in UTC.
        return value.astimezone(UTC).replace(microsecond=0)


def _parse_id(raw_id: str) -> UUID:
    # Only the canonical lowercase hyphenated form names a Todo; anything else is simply not
    # found, the same as a well-formed ID that matches nothing.
    try:
        todo_id = UUID(raw_id)
    except ValueError:
        raise TodoNotFound(raw_id) from None
    if str(todo_id) != raw_id:
        raise TodoNotFound(raw_id)
    return todo_id


def _index_of(todos: list[Todo], todo_id: UUID) -> int:
    for index, todo in enumerate(todos):
        if todo.id == todo_id:
            return index
    raise TodoNotFound(str(todo_id))
