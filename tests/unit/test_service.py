from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta, timezone
from uuid import UUID

import pytest

from todo_app.errors import (
    InputValidationError,
    PersistenceReadError,
    PersistenceWriteError,
    TodoNotFound,
)
from todo_app.models import Todo
from todo_app.repository import TodoRepository
from todo_app.service import TodoService

FIRST_ID = UUID("11111111-1111-4111-8111-111111111111")
SECOND_ID = UUID("22222222-2222-4222-8222-222222222222")
THIRD_ID = UUID("33333333-3333-4333-8333-333333333333")
UNMATCHED_ID = UUID("44444444-4444-4444-8444-444444444444")
FIRST_TIME = datetime(2026, 9, 25, 14, 30, tzinfo=UTC)
LATER_TIME = datetime(2026, 9, 25, 14, 31, tzinfo=UTC)

MISSING_OR_MALFORMED_IDS = [
    str(UNMATCHED_ID),
    "abc",
    FIRST_ID.hex,
    f"{{{FIRST_ID}}}",
    f" {FIRST_ID} ",
    "",
]
MISSING_OR_MALFORMED_ID_NAMES = [
    "unmatched-uuid",
    "abc",
    "no-hyphens",
    "braces",
    "padded",
    "empty",
]


def make_todo(todo_id: UUID = FIRST_ID, **overrides: object) -> Todo:
    fields: dict[str, object] = {
        "id": todo_id,
        "title": "Submit assignment",
        "description": "Review the final implementation.",
        "due_date": date(2026, 9, 30),
        "is_completed": False,
        "created_at": FIRST_TIME,
    }
    fields.update(overrides)
    return Todo(**fields)  # type: ignore[arg-type]


class FakeRepository:
    """In-memory repository that records every call and can fail loads or saves on request."""

    def __init__(self, todos: Iterable[Todo] = ()) -> None:
        self.todos = list(todos)
        self.calls: list[str] = []
        self.saved: list[list[Todo]] = []
        self.load_error: Exception | None = None
        self.save_error: Exception | None = None

    def load_all(self) -> list[Todo]:
        self.calls.append("load")
        if self.load_error is not None:
            raise self.load_error
        return list(self.todos)

    def save_all(self, todos: Sequence[Todo]) -> None:
        self.calls.append("save")
        if self.save_error is not None:
            raise self.save_error
        self.saved.append(list(todos))
        self.todos = list(todos)


class FixedSequence:
    """Returns the given values in order and records how many were consumed."""

    def __init__(self, *values: object) -> None:
        self._values = list(values)
        self.calls = 0

    def __call__(self) -> object:
        value = self._values[self.calls]
        self.calls += 1
        return value


def make_service(
    repository: FakeRepository,
    clock: FixedSequence | None = None,
    uuids: FixedSequence | None = None,
) -> TodoService:
    return TodoService(
        repository,
        clock=clock or FixedSequence(FIRST_TIME, LATER_TIME),  # type: ignore[arg-type]
        uuid_factory=uuids or FixedSequence(FIRST_ID, SECOND_ID),  # type: ignore[arg-type]
    )


def test_fake_repository_satisfies_the_protocol() -> None:
    repository: TodoRepository = FakeRepository()

    assert repository.load_all() == []


# SVC-001: Create


def test_create_stores_normalized_values_with_system_managed_defaults() -> None:
    repository = FakeRepository()
    service = make_service(repository)

    todo = service.create_todo(
        {"title": "  Buy milk  ", "description": " two\r\nlines ", "due_date": " 2026-09-30 "}
    )

    assert todo == Todo(
        id=FIRST_ID,
        title="Buy milk",
        description="two\nlines",
        due_date=date(2026, 9, 30),
        is_completed=False,
        created_at=FIRST_TIME,
    )
    assert repository.saved == [[todo]]


def test_create_accepts_absent_optional_values() -> None:
    repository = FakeRepository()

    todo = make_service(repository).create_todo({"title": "Buy milk"})

    assert todo.description is None
    assert todo.due_date is None


def test_create_appends_to_the_existing_collection() -> None:
    existing = make_todo(THIRD_ID)
    repository = FakeRepository([existing])

    todo = make_service(repository).create_todo({"title": "Buy milk"})

    assert repository.saved == [[existing, todo]]


def test_create_allows_duplicate_titles() -> None:
    repository = FakeRepository()
    service = make_service(repository)

    first = service.create_todo({"title": "Same"})
    second = service.create_todo({"title": "Same"})

    assert (first.id, second.id) == (FIRST_ID, SECOND_ID)
    assert repository.todos == [first, second]


def test_create_stores_the_clock_value_in_utc_without_microseconds() -> None:
    eastern = timezone(timedelta(hours=-4))
    clock = FixedSequence(datetime(2026, 9, 25, 10, 30, 0, 999_999, tzinfo=eastern))
    repository = FakeRepository()

    todo = make_service(repository, clock=clock).create_todo({"title": "Buy milk"})

    assert todo.created_at == FIRST_TIME
    assert todo.created_at.utcoffset() == timedelta(0)
    assert todo.created_at.microsecond == 0


def test_create_reports_success_only_after_the_save_succeeds() -> None:
    repository = FakeRepository()
    repository.save_error = PersistenceWriteError("disk full")

    with pytest.raises(PersistenceWriteError):
        make_service(repository).create_todo({"title": "Buy milk"})

    assert repository.calls == ["load", "save"]
    assert repository.todos == []


# SVC-002: generated values are checked


@pytest.mark.parametrize(
    "generated",
    [
        UUID("11111111-1111-1111-8111-111111111111"),
        UUID("11111111-1111-4111-c111-111111111111"),
        str(FIRST_ID),
        None,
    ],
    ids=["version-1", "non-rfc-variant", "string", "none"],
)
def test_create_rejects_an_invalid_generated_uuid(generated: object) -> None:
    repository = FakeRepository([make_todo(THIRD_ID)])

    with pytest.raises(RuntimeError, match="UUID version 4"):
        make_service(repository, uuids=FixedSequence(generated)).create_todo({"title": "Buy milk"})

    assert "save" not in repository.calls
    assert repository.todos == [make_todo(THIRD_ID)]


def test_create_rejects_a_duplicate_generated_uuid() -> None:
    existing = make_todo(FIRST_ID)
    repository = FakeRepository([existing])

    with pytest.raises(RuntimeError, match="already in use"):
        make_service(repository, uuids=FixedSequence(FIRST_ID)).create_todo({"title": "Buy milk"})

    assert "save" not in repository.calls
    assert repository.todos == [existing]


@pytest.mark.parametrize(
    "clock_value",
    [datetime(2026, 9, 25, 14, 30), date(2026, 9, 25), "2026-09-25T14:30:00Z"],
    ids=["naive-datetime", "date", "string"],
)
def test_create_rejects_an_invalid_clock_value(clock_value: object) -> None:
    repository = FakeRepository()

    with pytest.raises(RuntimeError, match="timezone-aware"):
        make_service(repository, clock=FixedSequence(clock_value)).create_todo(
            {"title": "Buy milk"}
        )

    assert "save" not in repository.calls
    assert repository.todos == []


# SVC-003: List ordering


def test_list_returns_every_todo_newest_first_with_id_ascending_for_ties() -> None:
    tie_high_id = make_todo(SECOND_ID, created_at=FIRST_TIME)
    tie_low_id = make_todo(FIRST_ID, created_at=FIRST_TIME)
    newest = make_todo(THIRD_ID, created_at=LATER_TIME)
    repository = FakeRepository([tie_high_id, newest, tie_low_id])

    assert make_service(repository).list_todos() == [newest, tie_low_id, tie_high_id]


def test_list_orders_ties_by_canonical_id_text() -> None:
    letters = make_todo(UUID("aaaaaaaa-0000-4000-8000-000000000000"))
    digits = make_todo(UUID("99999999-0000-4000-8000-000000000000"))
    repository = FakeRepository([letters, digits])

    assert make_service(repository).list_todos() == [digits, letters]


def test_list_of_an_empty_collection_is_empty() -> None:
    assert make_service(FakeRepository()).list_todos() == []


def test_list_does_not_reorder_the_stored_collection() -> None:
    stored = [make_todo(FIRST_ID), make_todo(SECOND_ID, created_at=LATER_TIME)]
    repository = FakeRepository(stored)

    make_service(repository).list_todos()

    assert repository.todos == stored


# SVC-004: Get and ID handling


def test_get_returns_the_matching_todo() -> None:
    target = make_todo(SECOND_ID, title="Target")
    repository = FakeRepository([make_todo(FIRST_ID), target])

    assert make_service(repository).get_todo(str(SECOND_ID)) == target


@pytest.mark.parametrize("raw_id", MISSING_OR_MALFORMED_IDS, ids=MISSING_OR_MALFORMED_ID_NAMES)
def test_get_raises_not_found_for_missing_or_malformed_ids(raw_id: str) -> None:
    repository = FakeRepository([make_todo(FIRST_ID)])

    with pytest.raises(TodoNotFound):
        make_service(repository).get_todo(raw_id)

    assert "save" not in repository.calls


# SVC-005: Update replaces all editable fields


def test_update_replaces_editable_fields_and_preserves_protected_fields() -> None:
    original = make_todo(FIRST_ID, is_completed=True)
    other = make_todo(SECOND_ID)
    repository = FakeRepository([original, other])

    updated = make_service(repository).update_todo(
        str(FIRST_ID),
        {"title": " New title ", "description": "New\r\ntext", "due_date": "2027-01-15"},
    )

    assert updated == Todo(
        id=FIRST_ID,
        title="New title",
        description="New\ntext",
        due_date=date(2027, 1, 15),
        is_completed=True,
        created_at=FIRST_TIME,
    )
    assert repository.saved == [[updated, other]]


@pytest.mark.parametrize(
    "values",
    [
        {"title": "Only title", "description": "", "due_date": ""},
        {"title": "Only title", "description": "  \r\n ", "due_date": "   "},
        {"title": "Only title"},
    ],
    ids=["empty", "whitespace", "missing"],
)
def test_update_with_blank_optional_fields_removes_them(values: dict[str, str]) -> None:
    repository = FakeRepository([make_todo(FIRST_ID)])

    updated = make_service(repository).update_todo(str(FIRST_ID), values)

    assert updated.description is None
    assert updated.due_date is None
    assert repository.todos == [updated]


def test_update_does_not_consume_the_clock_or_uuid_source() -> None:
    clock = FixedSequence(LATER_TIME)
    uuids = FixedSequence(SECOND_ID)
    repository = FakeRepository([make_todo(FIRST_ID)])

    make_service(repository, clock=clock, uuids=uuids).update_todo(
        str(FIRST_ID), {"title": "Changed"}
    )

    assert (clock.calls, uuids.calls) == (0, 0)


# SVC-006: unchanged Update


def test_unchanged_update_succeeds_and_still_saves() -> None:
    original = make_todo(FIRST_ID)
    repository = FakeRepository([original])

    updated = make_service(repository).update_todo(
        str(FIRST_ID),
        {
            "title": original.title,
            "description": original.description or "",
            "due_date": "2026-09-30",
        },
    )

    assert updated == original
    assert repository.saved == [[original]]


def test_unchanged_update_fails_when_the_save_fails() -> None:
    original = make_todo(FIRST_ID)
    repository = FakeRepository([original])
    repository.save_error = PersistenceWriteError("disk full")

    with pytest.raises(PersistenceWriteError):
        make_service(repository).update_todo(
            str(FIRST_ID),
            {"title": original.title, "description": "Review the final implementation."},
        )


# SVC-007: Complete and Incomplete


@pytest.mark.parametrize(
    ("initial", "requested"),
    [(False, True), (True, True), (True, False), (False, False)],
    ids=["complete", "complete-again", "incomplete", "incomplete-again"],
)
def test_set_completed_changes_only_the_completion_state(initial: bool, requested: bool) -> None:
    original = make_todo(FIRST_ID, is_completed=initial)
    other = make_todo(SECOND_ID, is_completed=not requested)
    repository = FakeRepository([original, other])

    updated = make_service(repository).set_completed(str(FIRST_ID), requested)

    assert updated == original.model_copy(update={"is_completed": requested})
    assert updated.model_dump(exclude={"is_completed"}) == original.model_dump(
        exclude={"is_completed"}
    )
    assert repository.saved == [[updated, other]]


def test_repeated_status_requests_keep_succeeding_and_saving() -> None:
    repository = FakeRepository([make_todo(FIRST_ID)])
    service = make_service(repository)

    first = service.set_completed(str(FIRST_ID), True)
    second = service.set_completed(str(FIRST_ID), True)

    assert first == second
    assert second.is_completed is True
    assert repository.calls == ["load", "save", "load", "save"]


@pytest.mark.parametrize("raw_id", MISSING_OR_MALFORMED_IDS, ids=MISSING_OR_MALFORMED_ID_NAMES)
@pytest.mark.parametrize("completed", [True, False], ids=["complete", "incomplete"])
def test_set_completed_raises_not_found_without_saving(raw_id: str, completed: bool) -> None:
    repository = FakeRepository([make_todo(FIRST_ID)])

    with pytest.raises(TodoNotFound):
        make_service(repository).set_completed(raw_id, completed)

    assert "save" not in repository.calls


# SVC-008: Delete


def test_delete_removes_only_the_target() -> None:
    first = make_todo(FIRST_ID)
    second = make_todo(SECOND_ID)
    third = make_todo(THIRD_ID)
    repository = FakeRepository([first, second, third])

    result = make_service(repository).delete_todo(str(SECOND_ID))

    assert result is None
    assert repository.saved == [[first, third]]


def test_deleting_the_same_todo_twice_is_not_found_the_second_time() -> None:
    repository = FakeRepository([make_todo(FIRST_ID)])
    service = make_service(repository)

    service.delete_todo(str(FIRST_ID))

    with pytest.raises(TodoNotFound):
        service.delete_todo(str(FIRST_ID))
    assert repository.todos == []
    assert len(repository.saved) == 1


@pytest.mark.parametrize("raw_id", MISSING_OR_MALFORMED_IDS, ids=MISSING_OR_MALFORMED_ID_NAMES)
def test_delete_raises_not_found_without_saving(raw_id: str) -> None:
    existing = make_todo(FIRST_ID)
    repository = FakeRepository([existing])

    with pytest.raises(TodoNotFound):
        make_service(repository).delete_todo(raw_id)

    assert "save" not in repository.calls
    assert repository.todos == [existing]


# SVC-009: invalid input never saves


def test_invalid_create_reports_all_errors_without_touching_state() -> None:
    clock = FixedSequence(FIRST_TIME)
    uuids = FixedSequence(FIRST_ID)
    repository = FakeRepository([make_todo(THIRD_ID)])

    with pytest.raises(InputValidationError) as exc_info:
        make_service(repository, clock=clock, uuids=uuids).create_todo(
            {"title": " ", "description": "x" * 2001, "due_date": "2026-02-30"}
        )

    assert set(exc_info.value.errors) == {"title", "description", "due_date"}
    assert "save" not in repository.calls
    assert repository.todos == [make_todo(THIRD_ID)]
    assert (clock.calls, uuids.calls) == (0, 0)


def test_invalid_update_reports_errors_without_saving() -> None:
    original = make_todo(FIRST_ID)
    repository = FakeRepository([original])

    with pytest.raises(InputValidationError) as exc_info:
        make_service(repository).update_todo(
            str(FIRST_ID), {"title": "x" * 201, "due_date": "2026/09/24"}
        )

    assert set(exc_info.value.errors) == {"title", "due_date"}
    assert "save" not in repository.calls
    assert repository.todos == [original]


@pytest.mark.parametrize("raw_id", MISSING_OR_MALFORMED_IDS, ids=MISSING_OR_MALFORMED_ID_NAMES)
def test_update_resolves_the_target_before_validating_values(raw_id: str) -> None:
    repository = FakeRepository([make_todo(FIRST_ID)])

    with pytest.raises(TodoNotFound):
        make_service(repository).update_todo(raw_id, {"title": ""})

    assert "save" not in repository.calls


# SVC-010: system-managed and unexpected fields are ignored

SYSTEM_FIELDS = {
    "id": str(THIRD_ID),
    "is_completed": "true",
    "isCompleted": "true",
    "created_at": "2000-01-01T00:00:00Z",
    "createdAt": "2000-01-01T00:00:00Z",
    "priority": "high",
}


def test_create_ignores_submitted_system_managed_fields() -> None:
    repository = FakeRepository()

    todo = make_service(repository).create_todo({"title": "Buy milk", **SYSTEM_FIELDS})

    assert (todo.id, todo.is_completed, todo.created_at) == (FIRST_ID, False, FIRST_TIME)


def test_update_ignores_submitted_system_managed_fields() -> None:
    original = make_todo(FIRST_ID)
    repository = FakeRepository([original])

    updated = make_service(repository).update_todo(
        str(FIRST_ID), {"title": "Changed", **SYSTEM_FIELDS}
    )

    assert (updated.id, updated.is_completed, updated.created_at) == (
        FIRST_ID,
        False,
        FIRST_TIME,
    )
    assert repository.todos == [updated]


# SVC-011: persistence failures propagate


def run_each_operation(service: TodoService) -> list[tuple[str, Exception | None]]:
    operations = {
        "list": lambda: service.list_todos(),
        "get": lambda: service.get_todo(str(FIRST_ID)),
        "create": lambda: service.create_todo({"title": "New"}),
        "update": lambda: service.update_todo(str(FIRST_ID), {"title": "Changed"}),
        "complete": lambda: service.set_completed(str(FIRST_ID), True),
        "incomplete": lambda: service.set_completed(str(FIRST_ID), False),
        "delete": lambda: service.delete_todo(str(FIRST_ID)),
    }
    outcomes: list[tuple[str, Exception | None]] = []
    for name, operation in operations.items():
        try:
            operation()
        except Exception as exc:
            outcomes.append((name, exc))
        else:
            outcomes.append((name, None))
    return outcomes


def test_read_failure_propagates_from_every_operation_without_saving() -> None:
    repository = FakeRepository([make_todo(FIRST_ID)])
    failure = PersistenceReadError("corrupt data")
    repository.load_error = failure

    outcomes = run_each_operation(make_service(repository, uuids=FixedSequence(SECOND_ID)))

    assert all(error is failure for _, error in outcomes), outcomes
    assert "save" not in repository.calls


def test_write_failure_propagates_from_every_mutation() -> None:
    original = make_todo(FIRST_ID)
    repository = FakeRepository([original])
    failure = PersistenceWriteError("disk full")
    repository.save_error = failure

    outcomes = dict(run_each_operation(make_service(repository, uuids=FixedSequence(SECOND_ID))))

    assert outcomes.pop("list") is None
    assert outcomes.pop("get") is None
    assert all(error is failure for error in outcomes.values()), outcomes
    assert repository.todos == [original]


# SVC-012: repository interaction sequence


def test_reads_load_once_and_never_save() -> None:
    repository = FakeRepository([make_todo(FIRST_ID)])
    service = make_service(repository)

    service.list_todos()
    service.get_todo(str(FIRST_ID))

    assert repository.calls == ["load", "load"]


@pytest.mark.parametrize(
    "operation",
    ["create", "update", "complete", "incomplete", "delete"],
)
def test_each_mutation_loads_then_saves_the_complete_collection(operation: str) -> None:
    first = make_todo(FIRST_ID)
    third = make_todo(THIRD_ID)
    repository = FakeRepository([first, third])
    service = make_service(repository, uuids=FixedSequence(SECOND_ID))

    actions = {
        "create": lambda: service.create_todo({"title": "New"}),
        "update": lambda: service.update_todo(str(FIRST_ID), {"title": "Changed"}),
        "complete": lambda: service.set_completed(str(FIRST_ID), True),
        "incomplete": lambda: service.set_completed(str(FIRST_ID), False),
        "delete": lambda: service.delete_todo(str(FIRST_ID)),
    }
    actions[operation]()

    assert repository.calls == ["load", "save"]
    saved_ids = [todo.id for todo in repository.saved[0]]
    expected_ids = {
        "create": [FIRST_ID, THIRD_ID, SECOND_ID],
        "delete": [THIRD_ID],
    }.get(operation, [FIRST_ID, THIRD_ID])
    assert saved_ids == expected_ids
