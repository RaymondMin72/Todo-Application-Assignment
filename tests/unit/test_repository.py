import json
import os
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import IO, Any
from uuid import UUID

import pytest

from todo_app.errors import PersistenceReadError, PersistenceWriteError
from todo_app.models import Todo
from todo_app.repository import JsonTodoRepository, TodoRepository

FIRST_ID = UUID("11111111-1111-4111-8111-111111111111")
SECOND_ID = UUID("22222222-2222-4222-8222-222222222222")
FIRST_TIME = datetime(2026, 9, 25, 14, 30, tzinfo=UTC)
LATER_TIME = datetime(2026, 9, 25, 14, 31, tzinfo=UTC)

FIRST_TODO = Todo(
    id=FIRST_ID,
    title="Submit assignment",
    description="Review the final implementation.\nThen submit.",
    due_date=date(2026, 9, 30),
    is_completed=False,
    created_at=FIRST_TIME,
)
SECOND_TODO = Todo(
    id=SECOND_ID,
    title="Café 日本語 😀",
    description=None,
    due_date=None,
    is_completed=True,
    created_at=LATER_TIME,
)

CANONICAL_TEXT = """[
  {
    "id": "11111111-1111-4111-8111-111111111111",
    "title": "Submit assignment",
    "description": "Review the final implementation.\\nThen submit.",
    "dueDate": "2026-09-30",
    "isCompleted": false,
    "createdAt": "2026-09-25T14:30:00Z"
  },
  {
    "id": "22222222-2222-4222-8222-222222222222",
    "title": "Café 日本語 😀",
    "description": null,
    "dueDate": null,
    "isCompleted": true,
    "createdAt": "2026-09-25T14:31:00Z"
  }
]
"""

VALID_RECORD: dict[str, object] = {
    "id": "11111111-1111-4111-8111-111111111111",
    "title": "Submit assignment",
    "description": None,
    "dueDate": None,
    "isCompleted": False,
    "createdAt": "2026-09-25T14:30:00Z",
}


@pytest.fixture
def data_path(tmp_path: Path) -> Path:
    return tmp_path / "data" / "todos.json"


@pytest.fixture
def repository(data_path: Path) -> JsonTodoRepository:
    return JsonTodoRepository(data_path)


def write_text(path: Path, text: str) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path.read_bytes()


def write_records(path: Path, *records: object) -> bytes:
    return write_text(path, json.dumps(list(records)))


def record_with(**changes: object) -> dict[str, object]:
    return {**VALID_RECORD, **changes}


def record_without(key: str) -> dict[str, object]:
    return {name: value for name, value in VALID_RECORD.items() if name != key}


def temp_files(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.tmp"))


class RecordingHandle:
    """Wraps the temporary file handle to record the write sequence or inject one failure."""

    def __init__(self, inner: IO[str], events: list[str], fail_on: str | None) -> None:
        self._inner = inner
        self._events = events
        self._fail_on = fail_on

    def _step(self, name: str) -> None:
        if self._fail_on == name:
            if name == "close":
                self._inner.close()
            raise OSError(f"injected {name} failure")
        self._events.append(name)

    def write(self, text: str) -> int:
        self._step("write")
        return self._inner.write(text)

    def flush(self) -> None:
        self._step("flush")
        self._inner.flush()

    def fileno(self) -> int:
        return self._inner.fileno()

    def close(self) -> None:
        self._step("close")
        self._inner.close()

    def __enter__(self) -> "RecordingHandle":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


@pytest.fixture
def instrument(monkeypatch: pytest.MonkeyPatch) -> Callable[[str | None], list[str]]:
    """Return a function that instruments fdopen, fsync, and replace and can fail one step."""

    def install(fail_on: str | None = None) -> list[str]:
        events: list[str] = []
        real_fdopen = os.fdopen
        real_fsync = os.fsync
        real_replace = os.replace

        def fake_fdopen(fd: int, *args: Any, **kwargs: Any) -> RecordingHandle:
            return RecordingHandle(real_fdopen(fd, *args, **kwargs), events, fail_on)

        def fake_fsync(fd: int) -> None:
            if fail_on == "fsync":
                raise OSError("injected fsync failure")
            events.append("fsync")
            real_fsync(fd)

        def fake_replace(src: Any, dst: Any) -> None:
            if fail_on == "replace":
                raise OSError("injected replace failure")
            events.append(f"replace {Path(src).name} -> {Path(dst).name}")
            real_replace(src, dst)

        monkeypatch.setattr(os, "fdopen", fake_fdopen)
        monkeypatch.setattr(os, "fsync", fake_fsync)
        monkeypatch.setattr(os, "replace", fake_replace)
        return events

    return install


# REP-001: missing file


def test_missing_file_loads_as_empty_collection_without_creating_anything(
    repository: JsonTodoRepository, data_path: Path
) -> None:
    assert repository.load_all() == []
    assert not data_path.exists()
    assert not data_path.parent.exists()


def test_json_repository_satisfies_the_protocol(repository: JsonTodoRepository) -> None:
    protocol_instance: TodoRepository = repository

    assert protocol_instance.load_all() == []


# REP-002: empty and whitespace-only files


@pytest.mark.parametrize(
    "content",
    ["", " ", " \n\t\r\n ", "\u3000\n"],
    ids=["zero-byte", "space", "mixed", "unicode-space"],
)
def test_existing_blank_file_is_corrupt_not_empty(
    repository: JsonTodoRepository, data_path: Path, content: str
) -> None:
    original = write_text(data_path, content)

    with pytest.raises(PersistenceReadError):
        repository.load_all()

    assert data_path.read_bytes() == original


# REP-003: valid data round-trips


def test_valid_file_loads_completely_with_typed_values(
    repository: JsonTodoRepository, data_path: Path
) -> None:
    write_text(data_path, CANONICAL_TEXT)

    assert repository.load_all() == [FIRST_TODO, SECOND_TODO]


def test_load_returns_independent_lists(repository: JsonTodoRepository, data_path: Path) -> None:
    write_text(data_path, CANONICAL_TEXT)

    first = repository.load_all()
    first.clear()

    assert repository.load_all() == [FIRST_TODO, SECOND_TODO]


def test_load_then_save_reproduces_the_canonical_file(
    repository: JsonTodoRepository, data_path: Path
) -> None:
    write_text(data_path, CANONICAL_TEXT)

    repository.save_all(repository.load_all())

    assert data_path.read_text(encoding="utf-8") == CANONICAL_TEXT


def test_save_then_load_round_trips_typed_values(repository: JsonTodoRepository) -> None:
    repository.save_all([FIRST_TODO, SECOND_TODO])

    assert repository.load_all() == [FIRST_TODO, SECOND_TODO]


def test_loaded_created_at_is_aware_utc(repository: JsonTodoRepository, data_path: Path) -> None:
    write_text(data_path, CANONICAL_TEXT)

    created_at = repository.load_all()[0].created_at

    assert created_at.tzinfo is not None
    assert created_at.utcoffset() == timedelta(0)
    assert created_at == FIRST_TIME


# REP-004: malformed content and wrong roots


@pytest.mark.parametrize(
    "content",
    ["[{", "[1,]", "{", "not json", '{"id": 1}', '"text"', "null", "42", "true"],
    ids=[
        "truncated",
        "trailing-comma",
        "open-brace",
        "text",
        "object-root",
        "string-root",
        "null-root",
        "number-root",
        "bool-root",
    ],
)
def test_malformed_json_or_wrong_root_is_rejected_unchanged(
    repository: JsonTodoRepository, data_path: Path, content: str
) -> None:
    original = write_text(data_path, content)

    with pytest.raises(PersistenceReadError):
        repository.load_all()

    assert data_path.read_bytes() == original


def test_duplicate_json_object_key_is_rejected_unchanged(
    repository: JsonTodoRepository, data_path: Path
) -> None:
    original = write_text(
        data_path,
        '[{"id":"11111111-1111-4111-8111-111111111111",'
        '"id":"22222222-2222-4222-8222-222222222222",'
        '"title":"Task","description":null,"dueDate":null,'
        '"isCompleted":false,"createdAt":"2026-09-25T14:30:00Z"}]',
    )

    with pytest.raises(PersistenceReadError, match="duplicate key"):
        repository.load_all()

    assert data_path.read_bytes() == original


def test_invalid_utf8_is_rejected_unchanged(
    repository: JsonTodoRepository, data_path: Path
) -> None:
    data_path.parent.mkdir(parents=True)
    original = b'[{"id": "\xff\xfe"}]'
    data_path.write_bytes(original)

    with pytest.raises(PersistenceReadError):
        repository.load_all()

    assert data_path.read_bytes() == original


# REP-005: schema and record validation rejects the whole dataset


@pytest.mark.parametrize(
    "record",
    [
        record_without("id"),
        record_without("title"),
        record_without("description"),
        record_without("dueDate"),
        record_without("isCompleted"),
        record_without("createdAt"),
        record_with(updatedAt="2026-09-25T14:30:00Z"),
        record_with(priority=1),
        {**VALID_RECORD, "due_date": None, "dueDate": None},
    ],
    ids=[
        "no-id",
        "no-title",
        "no-description",
        "no-dueDate",
        "no-isCompleted",
        "no-createdAt",
        "extra-updatedAt",
        "extra-priority",
        "extra-snake-case",
    ],
)
def test_record_with_missing_or_extra_keys_is_rejected(
    repository: JsonTodoRepository, data_path: Path, record: dict[str, object]
) -> None:
    original = write_records(data_path, record)

    with pytest.raises(PersistenceReadError):
        repository.load_all()

    assert data_path.read_bytes() == original


@pytest.mark.parametrize(
    "record",
    [
        record_with(id=5),
        record_with(id=None),
        record_with(title=5),
        record_with(title=None),
        record_with(description=5),
        record_with(description=["text"]),
        record_with(dueDate=20260930),
        record_with(dueDate=True),
        record_with(isCompleted="true"),
        record_with(isCompleted=1),
        record_with(isCompleted=None),
        record_with(createdAt=1758810600),
        record_with(createdAt=None),
    ],
    ids=[
        "id-int",
        "id-null",
        "title-int",
        "title-null",
        "description-int",
        "description-list",
        "dueDate-int",
        "dueDate-bool",
        "isCompleted-str",
        "isCompleted-int",
        "isCompleted-null",
        "createdAt-int",
        "createdAt-null",
    ],
)
def test_record_with_wrong_value_type_is_rejected(
    repository: JsonTodoRepository, data_path: Path, record: dict[str, object]
) -> None:
    write_records(data_path, record)

    with pytest.raises(PersistenceReadError):
        repository.load_all()


@pytest.mark.parametrize(
    "record",
    [
        record_with(title=""),
        record_with(title="   "),
        record_with(title=" Padded"),
        record_with(title="x" * 201),
        record_with(description=""),
        record_with(description=" padded"),
        record_with(description="line\r\nbreak"),
        record_with(description="x" * 2001),
        record_with(dueDate="2026-9-4"),
        record_with(dueDate="2026/09/24"),
        record_with(dueDate="2026-02-30"),
        record_with(dueDate="2026-09-24T10:00"),
        record_with(dueDate="20260924"),
        record_with(dueDate="2026-W39-4"),
        record_with(dueDate=""),
    ],
    ids=[
        "empty-title",
        "blank-title",
        "untrimmed-title",
        "long-title",
        "empty-description",
        "untrimmed-description",
        "crlf-description",
        "long-description",
        "unpadded-date",
        "slash-date",
        "impossible-date",
        "datetime-date",
        "basic-iso-date",
        "iso-week-date",
        "empty-date",
    ],
)
def test_record_breaking_field_rules_is_rejected(
    repository: JsonTodoRepository, data_path: Path, record: dict[str, object]
) -> None:
    write_records(data_path, record)

    with pytest.raises(PersistenceReadError):
        repository.load_all()


@pytest.mark.parametrize("item", ["text", None, 1, ["11111111-1111-4111-8111-111111111111"]])
def test_non_object_record_is_rejected(
    repository: JsonTodoRepository, data_path: Path, item: object
) -> None:
    write_records(data_path, item)

    with pytest.raises(PersistenceReadError):
        repository.load_all()


def test_one_invalid_record_rejects_the_whole_dataset(
    repository: JsonTodoRepository, data_path: Path
) -> None:
    second = record_with(id=str(SECOND_ID), title="")
    original = write_records(data_path, VALID_RECORD, second)

    with pytest.raises(PersistenceReadError, match="record 1"):
        repository.load_all()

    assert data_path.read_bytes() == original


# REP-006: identifiers


def test_duplicate_ids_reject_the_whole_dataset(
    repository: JsonTodoRepository, data_path: Path
) -> None:
    write_records(data_path, VALID_RECORD, record_with(title="Another"))

    with pytest.raises(PersistenceReadError, match="duplicate"):
        repository.load_all()


@pytest.mark.parametrize(
    "raw_id",
    [
        "11111111-1111-1111-8111-111111111111",
        "11111111-1111-5111-8111-111111111111",
        "11111111-1111-4111-c111-111111111111",
        "ABCDEF12-1111-4111-8111-111111111111",
        "11111111111141118111111111111111",
        "{11111111-1111-4111-8111-111111111111}",
        "urn:uuid:11111111-1111-4111-8111-111111111111",
        "abc",
        "",
    ],
    ids=[
        "version-1",
        "version-5",
        "non-rfc-variant",
        "uppercase",
        "no-hyphens",
        "braces",
        "urn",
        "abc",
        "empty",
    ],
)
def test_non_v4_or_noncanonical_id_is_rejected(
    repository: JsonTodoRepository, data_path: Path, raw_id: str
) -> None:
    write_records(data_path, record_with(id=raw_id))

    with pytest.raises(PersistenceReadError):
        repository.load_all()


# REP-007: timestamps


@pytest.mark.parametrize(
    "created_at",
    [
        "2026-09-25T14:30:00",
        "2026-09-25T14:30:00+00:00",
        "2026-09-25T14:30:00-04:00",
        "2026-09-25T14:30:00.000Z",
        "2026-09-25T14:30:00.123456Z",
        "2026-09-25T14:30Z",
        "2026-09-25 14:30:00Z",
        "2026-09-25T14:30:00z",
        "2026-9-25T14:30:00Z",
        "2026-09-25T14:30:00Z ",
        "2026-09-25",
        "",
    ],
    ids=[
        "no-designator",
        "zero-offset",
        "negative-offset",
        "milliseconds",
        "microseconds",
        "no-seconds",
        "space-separator",
        "lowercase-z",
        "unpadded-month",
        "trailing-space",
        "date-only",
        "empty",
    ],
)
def test_noncanonical_timestamp_is_rejected(
    repository: JsonTodoRepository, data_path: Path, created_at: str
) -> None:
    write_records(data_path, record_with(createdAt=created_at))

    with pytest.raises(PersistenceReadError):
        repository.load_all()


# REP-008: only the primary file is read


def test_leftover_and_neighboring_files_are_ignored(
    repository: JsonTodoRepository, data_path: Path
) -> None:
    write_text(data_path, CANONICAL_TEXT)
    leftovers = {
        data_path.parent / ".todos.json.abc123.tmp": b"{ corrupt",
        data_path.parent / "todos.json.tmp": b"[]",
        data_path.parent / "other.json": b"not json",
    }
    for path, content in leftovers.items():
        path.write_bytes(content)

    assert repository.load_all() == [FIRST_TODO, SECOND_TODO]

    repository.save_all([SECOND_TODO])

    assert repository.load_all() == [SECOND_TODO]
    for path, content in leftovers.items():
        assert path.read_bytes() == content


def test_only_the_primary_file_is_created_when_missing(
    repository: JsonTodoRepository, data_path: Path
) -> None:
    (data_path.parent).mkdir(parents=True)
    (data_path.parent / ".todos.json.stale.tmp").write_bytes(b"garbage")

    assert repository.load_all() == []


# REP-009: first save creates the file with the exact schema


def test_first_save_creates_directory_and_canonical_file(
    repository: JsonTodoRepository, data_path: Path
) -> None:
    assert not data_path.parent.exists()

    repository.save_all([FIRST_TODO, SECOND_TODO])

    assert data_path.read_bytes() == CANONICAL_TEXT.encode("utf-8")
    assert temp_files(data_path.parent) == []


def test_saved_records_use_exactly_the_six_camel_case_keys(
    repository: JsonTodoRepository, data_path: Path
) -> None:
    repository.save_all([FIRST_TODO])

    records = json.loads(data_path.read_text(encoding="utf-8"))

    assert list(records[0]) == ["id", "title", "description", "dueDate", "isCompleted", "createdAt"]


def test_saved_unicode_is_not_escaped(repository: JsonTodoRepository, data_path: Path) -> None:
    repository.save_all([SECOND_TODO])

    assert "Café 日本語 😀" in data_path.read_text(encoding="utf-8")
    assert "\\u" not in data_path.read_text(encoding="utf-8")


def test_saving_an_empty_collection_writes_an_empty_array(
    repository: JsonTodoRepository, data_path: Path
) -> None:
    repository.save_all([])

    assert data_path.read_bytes() == b"[]\n"


def test_zero_offset_created_at_is_stored_with_z(
    repository: JsonTodoRepository, data_path: Path
) -> None:
    todo = FIRST_TODO.model_copy(
        update={"created_at": FIRST_TIME.astimezone(timezone(timedelta(0)))}
    )

    repository.save_all([todo])

    assert '"createdAt": "2026-09-25T14:30:00Z"' in data_path.read_text(encoding="utf-8")


def test_early_year_timestamp_is_stored_with_four_digits(
    repository: JsonTodoRepository, data_path: Path
) -> None:
    early = FIRST_TODO.model_copy(update={"created_at": datetime(1, 1, 1, tzinfo=UTC)})

    repository.save_all([early])

    stored = json.loads(data_path.read_text(encoding="utf-8"))
    assert stored[0]["createdAt"] == "0001-01-01T00:00:00Z"
    assert repository.load_all() == [early]


# REP-010: the next collection is validated before writing


@pytest.mark.parametrize(
    "todos",
    [
        [FIRST_TODO, FIRST_TODO.model_copy(update={"title": "Same id"})],
        [FIRST_TODO.model_copy(update={"title": ""})],
        [FIRST_TODO.model_copy(update={"title": " untrimmed"})],
        [FIRST_TODO.model_copy(update={"description": "a\r\nb"})],
        [FIRST_TODO.model_copy(update={"created_at": datetime(2026, 9, 25, 14, 30)})],
        [FIRST_TODO.model_copy(update={"created_at": FIRST_TIME.replace(microsecond=5)})],
        [FIRST_TODO.model_copy(update={"id": UUID("11111111-1111-1111-8111-111111111111")})],
    ],
    ids=[
        "duplicate-id",
        "empty-title",
        "untrimmed-title",
        "crlf-description",
        "naive-time",
        "microseconds",
        "non-v4-id",
    ],
)
def test_invalid_next_collection_is_rejected_before_replacing(
    repository: JsonTodoRepository, data_path: Path, todos: list[Todo]
) -> None:
    original = write_text(data_path, CANONICAL_TEXT)

    with pytest.raises(PersistenceWriteError):
        repository.save_all(todos)

    assert data_path.read_bytes() == original
    assert temp_files(data_path.parent) == []


# REP-011: the atomic write sequence


def test_successful_save_writes_flushes_fsyncs_closes_then_replaces(
    repository: JsonTodoRepository,
    data_path: Path,
    instrument: Callable[[str | None], list[str]],
) -> None:
    events = instrument(None)
    write_text(data_path, "[]\n")

    repository.save_all([FIRST_TODO])

    assert events[-4:-1] == ["flush", "fsync", "close"]
    assert events[-1].startswith("replace .todos.json.")
    assert events[-1].endswith(".tmp -> todos.json")
    assert events.index("flush") > events.index("write")
    assert temp_files(data_path.parent) == []
    assert repository.load_all() == [FIRST_TODO]


def test_temporary_file_is_created_in_the_destination_directory(
    repository: JsonTodoRepository, data_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def spy(src: Any, dst: Any) -> None:
        seen.append((Path(src), Path(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)

    repository.save_all([FIRST_TODO])

    assert len(seen) == 1
    source, destination = seen[0]
    assert destination == data_path
    assert source.parent == data_path.parent
    assert source != data_path
    assert source.suffix == ".tmp"


# REP-012: failures preserve the previous file


@pytest.mark.parametrize("step", ["write", "flush", "fsync", "close", "replace"])
def test_write_step_failure_preserves_previous_file_and_cleans_up(
    repository: JsonTodoRepository,
    data_path: Path,
    instrument: Callable[[str | None], list[str]],
    step: str,
) -> None:
    original = write_text(data_path, CANONICAL_TEXT)
    instrument(step)

    with pytest.raises(PersistenceWriteError) as exc_info:
        repository.save_all([SECOND_TODO])

    assert isinstance(exc_info.value.__cause__, OSError)
    assert f"injected {step} failure" in str(exc_info.value.__cause__)
    assert data_path.read_bytes() == original
    assert temp_files(data_path.parent) == []
    assert repository.load_all() == [FIRST_TODO, SECOND_TODO]


def test_failed_first_save_leaves_no_primary_file(
    repository: JsonTodoRepository,
    data_path: Path,
    instrument: Callable[[str | None], list[str]],
) -> None:
    instrument("replace")

    with pytest.raises(PersistenceWriteError):
        repository.save_all([FIRST_TODO])

    assert not data_path.exists()
    assert temp_files(data_path.parent) == []
    assert repository.load_all() == []


# REP-013: cleanup is best effort and leftovers are harmless


def test_cleanup_failure_does_not_mask_the_write_error(
    repository: JsonTodoRepository,
    data_path: Path,
    instrument: Callable[[str | None], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = write_text(data_path, CANONICAL_TEXT)
    instrument("replace")

    def failing_unlink(path: Any, *args: Any, **kwargs: Any) -> None:
        raise PermissionError("injected unlink failure")

    monkeypatch.setattr(os, "unlink", failing_unlink)

    with pytest.raises(PersistenceWriteError) as exc_info:
        repository.save_all([SECOND_TODO])

    assert "injected replace failure" in str(exc_info.value.__cause__)
    assert data_path.read_bytes() == original
    leftovers = temp_files(data_path.parent)
    assert len(leftovers) == 1

    monkeypatch.undo()

    assert repository.load_all() == [FIRST_TODO, SECOND_TODO]
    repository.save_all([SECOND_TODO])
    assert repository.load_all() == [SECOND_TODO]
    assert leftovers[0].exists()


# REP-014: I/O failures map to repository exceptions


def test_unreadable_primary_path_raises_read_error(tmp_path: Path) -> None:
    directory_as_file = tmp_path / "todos.json"
    directory_as_file.mkdir()

    with pytest.raises(PersistenceReadError):
        JsonTodoRepository(directory_as_file).load_all()


def test_unwritable_destination_raises_write_error(tmp_path: Path) -> None:
    blocker = tmp_path / "data"
    blocker.write_bytes(b"a file where the directory should be")

    with pytest.raises(PersistenceWriteError) as exc_info:
        JsonTodoRepository(blocker / "todos.json").save_all([FIRST_TODO])

    assert isinstance(exc_info.value.__cause__, OSError)
    assert blocker.read_bytes() == b"a file where the directory should be"


def test_read_failure_is_chained_to_the_os_error(tmp_path: Path) -> None:
    directory_as_file = tmp_path / "todos.json"
    directory_as_file.mkdir()

    with pytest.raises(PersistenceReadError) as exc_info:
        JsonTodoRepository(directory_as_file).load_all()

    assert isinstance(exc_info.value.__cause__, OSError)
