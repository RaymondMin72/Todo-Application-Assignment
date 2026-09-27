from datetime import UTC, date, datetime, timedelta, timezone
from uuid import UUID

import pytest

from todo_app.errors import InputValidationError
from todo_app.models import Todo, TodoInput

FIRST_ID = UUID("11111111-1111-4111-8111-111111111111")
CREATED_AT = datetime(2026, 9, 25, 14, 30, tzinfo=UTC)

TITLE_REQUIRED = "Title is required."
TITLE_TOO_LONG = "Title must be 200 characters or fewer."
DESCRIPTION_TOO_LONG = "Description must be 2,000 characters or fewer."
DUE_DATE_FORMAT = "Due date must use the YYYY-MM-DD format."
DUE_DATE_NOT_REAL = "Due date must be a real calendar date."


def parse(**values: str) -> TodoInput:
    return TodoInput.from_mapping({"title": "Buy milk", **values})


def field_errors(values: dict[str, object]) -> dict[str, list[str]]:
    with pytest.raises(InputValidationError) as exc_info:
        TodoInput.from_mapping(values)  # type: ignore[arg-type]
    return exc_info.value.errors


def make_todo(**overrides: object) -> Todo:
    fields: dict[str, object] = {
        "id": FIRST_ID,
        "title": "Submit assignment",
        "description": None,
        "due_date": None,
        "is_completed": False,
        "created_at": CREATED_AT,
    }
    fields.update(overrides)
    return Todo(**fields)  # type: ignore[arg-type]


# MOD-001: title trimming and required title


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("  Buy milk  ", "Buy milk"), ("\tBuy milk\n", "Buy milk"), ("Buy milk", "Buy milk")],
)
def test_title_is_trimmed(raw: str, expected: str) -> None:
    assert parse(title=raw).title == expected


@pytest.mark.parametrize(
    "values",
    [{}, {"title": ""}, {"title": "   "}, {"title": " \t\r\n "}],
    ids=["missing", "empty", "spaces", "mixed-whitespace"],
)
def test_missing_or_blank_title_is_rejected(values: dict[str, object]) -> None:
    assert field_errors(values) == {"title": [TITLE_REQUIRED]}


def test_non_text_values_are_rejected_per_field() -> None:
    errors = field_errors({"title": 5, "description": 1.5, "due_date": date(2026, 9, 24)})

    assert errors == {
        "title": ["Title must be text."],
        "description": ["Description must be text."],
        "due_date": ["Due date must be text."],
    }


# MOD-002: title length boundaries and Unicode


@pytest.mark.parametrize(
    "title",
    ["a", "x" * 200, "é" * 200, "日" * 200, "😀" * 200, "Café 日本語 😀"],
    ids=["one-char", "200-ascii", "200-accented", "200-cjk", "200-emoji", "mixed-unicode"],
)
def test_title_within_limit_is_accepted_unchanged(title: str) -> None:
    assert parse(title=title).title == title


def test_200_character_title_surrounded_by_whitespace_is_stored_trimmed() -> None:
    result = parse(title="   " + "x" * 200 + " \t ")

    assert result.title == "x" * 200


@pytest.mark.parametrize(
    "title",
    ["x" * 201, "😀" * 201, "  " + "x" * 201 + "  "],
    ids=["201-ascii", "201-emoji", "201-after-trim"],
)
def test_title_over_200_code_points_is_rejected(title: str) -> None:
    assert field_errors({"title": title}) == {"title": [TITLE_TOO_LONG]}


def test_duplicate_titles_are_allowed() -> None:
    assert parse(title="Same").title == parse(title="Same").title


# MOD-003: description normalization


@pytest.mark.parametrize(
    "values",
    [{}, {"description": ""}, {"description": "   "}, {"description": "\r\n\t \n\r"}],
    ids=["missing", "empty", "spaces", "line-breaks-only"],
)
def test_missing_or_blank_description_becomes_absent(values: dict[str, str]) -> None:
    assert TodoInput.from_mapping({"title": "Buy milk", **values}).description is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("first\nsecond", "first\nsecond"),
        ("first\r\nsecond", "first\nsecond"),
        ("first\rsecond", "first\nsecond"),
        ("a\r\n\rb\n\r\nc", "a\n\nb\n\nc"),
        ("  padded text \t", "padded text"),
        ("\r\n  inner\r\nlines  \r\n", "inner\nlines"),
    ],
    ids=["lf", "crlf", "bare-cr", "mixed", "trimmed", "trimmed-crlf"],
)
def test_description_line_breaks_are_normalized_and_trimmed(raw: str, expected: str) -> None:
    assert parse(description=raw).description == expected


# MOD-004: description length boundaries


def test_2000_code_point_description_after_newline_normalization_is_accepted() -> None:
    raw = "\r\n".join(["x" * 9] * 200) + "x"
    assert len(raw) > 2000

    description = parse(description=raw).description

    assert description is not None
    assert len(description) == 2000
    assert "\r" not in description


@pytest.mark.parametrize("description", ["x" * 2000, "😀" * 2000], ids=["ascii", "emoji"])
def test_2000_code_point_description_is_accepted(description: str) -> None:
    assert parse(description=description).description == description


@pytest.mark.parametrize(
    "description",
    ["x" * 2001, "é" * 2001, "\r\n".join(["x" * 9] * 200) + "xx"],
    ids=["ascii", "accented", "after-newline-normalization"],
)
def test_description_over_2000_code_points_is_rejected(description: str) -> None:
    errors = field_errors({"title": "Buy milk", "description": description})

    assert errors == {"description": [DESCRIPTION_TOO_LONG]}


# MOD-005: due date parsing


@pytest.mark.parametrize(
    "values",
    [{}, {"due_date": ""}, {"due_date": "   "}],
    ids=["missing", "empty", "spaces"],
)
def test_missing_or_blank_due_date_becomes_absent(values: dict[str, str]) -> None:
    assert TodoInput.from_mapping({"title": "Buy milk", **values}).due_date is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2024-02-29", date(2024, 2, 29)),
        ("2000-01-01", date(2000, 1, 1)),
        ("2026-09-24", date(2026, 9, 24)),
        ("  2026-09-24 ", date(2026, 9, 24)),
    ],
    ids=["leap-day", "past-date", "regular", "trimmed"],
)
def test_real_exact_due_date_is_accepted(raw: str, expected: date) -> None:
    assert parse(due_date=raw).due_date == expected


@pytest.mark.parametrize("raw", ["2025-02-29", "2026-02-30", "2026-13-01", "0000-01-01"])
def test_impossible_calendar_date_is_rejected(raw: str) -> None:
    assert field_errors({"title": "Buy milk", "due_date": raw}) == {"due_date": [DUE_DATE_NOT_REAL]}


@pytest.mark.parametrize(
    "raw",
    [
        "2026/09/24",
        "24-09-2026",
        "2026-9-4",
        "2026-09-24T10:00",
        "20260924",
        "2026-W39-4",
        "\uff12\uff10\uff12\uff16-\uff10\uff19-\uff12\uff14",
    ],
    ids=["slashes", "day-first", "unpadded", "with-time", "basic-iso", "iso-week", "fullwidth"],
)
def test_non_exact_due_date_format_is_rejected(raw: str) -> None:
    assert field_errors({"title": "Buy milk", "due_date": raw}) == {"due_date": [DUE_DATE_FORMAT]}


# MOD-006: aggregated field errors


def test_all_independent_field_errors_are_reported_together() -> None:
    errors = field_errors({"title": " ", "description": "x" * 2001, "due_date": "2026-02-30"})

    assert errors == {
        "title": [TITLE_REQUIRED],
        "description": [DESCRIPTION_TOO_LONG],
        "due_date": [DUE_DATE_NOT_REAL],
    }


def test_valid_fields_are_not_reported_alongside_invalid_ones() -> None:
    errors = field_errors({"title": "Valid", "description": "Fine", "due_date": "2026/09/24"})

    assert errors == {"due_date": [DUE_DATE_FORMAT]}


def test_input_validation_error_copies_the_supplied_errors() -> None:
    source = {"title": [TITLE_REQUIRED]}

    error = InputValidationError(source)
    source["title"].append("changed")

    assert error.errors == {"title": [TITLE_REQUIRED]}
    assert "title" in str(error)


def test_unexpected_and_system_managed_keys_are_ignored() -> None:
    result = TodoInput.from_mapping(
        {
            "title": "Buy milk",
            "id": "22222222-2222-4222-8222-222222222222",
            "is_completed": "true",
            "created_at": "2000-01-01T00:00:00Z",
            "dueDate": "2026-09-24",
        }
    )

    assert result.model_dump() == {"title": "Buy milk", "description": None, "due_date": None}


# MOD-007: Todo fields and types


def test_todo_exposes_exactly_the_six_domain_fields() -> None:
    todo = make_todo(description="Details", due_date=date(2026, 9, 30))

    assert todo.model_dump() == {
        "id": FIRST_ID,
        "title": "Submit assignment",
        "description": "Details",
        "due_date": date(2026, 9, 30),
        "is_completed": False,
        "created_at": CREATED_AT,
    }


def test_todo_accepts_absent_optional_values_as_none() -> None:
    todo = make_todo(description=None, due_date=None)

    assert todo.description is None
    assert todo.due_date is None


@pytest.mark.parametrize(
    "missing", ["id", "title", "description", "due_date", "is_completed", "created_at"]
)
def test_todo_requires_every_field(missing: str) -> None:
    fields = make_todo().model_dump()
    del fields[missing]

    with pytest.raises(ValueError, match=missing):
        Todo(**fields)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", str(FIRST_ID)),
        ("title", 5),
        ("title", None),
        ("description", 5),
        ("due_date", "2026-09-30"),
        ("due_date", datetime(2026, 9, 30, tzinfo=UTC)),
        ("is_completed", "false"),
        ("is_completed", 1),
        ("is_completed", None),
        ("created_at", "2026-09-25T14:30:00Z"),
    ],
)
def test_todo_rejects_invalid_python_types(field: str, value: object) -> None:
    with pytest.raises(ValueError, match=field):
        make_todo(**{field: value})


def test_todo_rejects_fields_outside_the_data_model() -> None:
    with pytest.raises(ValueError, match="updated_at"):
        make_todo(updated_at=CREATED_AT)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", ""),
        ("title", " Submit"),
        ("title", "x" * 201),
        ("description", ""),
        ("description", "   "),
        ("description", " padded"),
        ("description", "first\r\nsecond"),
        ("description", "first\rsecond"),
        ("description", "x" * 2001),
    ],
)
def test_todo_rejects_editable_values_that_break_input_rules(field: str, value: str) -> None:
    with pytest.raises(ValueError, match=field):
        make_todo(**{field: value})


def test_todo_accepts_normalized_boundary_values() -> None:
    todo = make_todo(title="😀" * 200, description="line one\nline two" + "x" * 1983)

    assert len(todo.title) == 200
    assert todo.description is not None
    assert len(todo.description) == 2000


# MOD-008: UUID v4 and aware UTC creation time


@pytest.mark.parametrize(
    "todo_id",
    [
        UUID("11111111-1111-1111-8111-111111111111"),
        UUID("11111111-1111-5111-8111-111111111111"),
        UUID("11111111-1111-4111-c111-111111111111"),
    ],
    ids=["version-1", "version-5", "non-rfc-variant"],
)
def test_todo_id_must_be_uuid_version_4(todo_id: UUID) -> None:
    with pytest.raises(ValueError, match="UUID version 4"):
        make_todo(id=todo_id)


def test_todo_created_at_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        make_todo(created_at=datetime(2026, 9, 25, 14, 30))


def test_todo_created_at_must_be_utc() -> None:
    offset = timezone(timedelta(hours=2))

    with pytest.raises(ValueError, match="in UTC"):
        make_todo(created_at=datetime(2026, 9, 25, 16, 30, tzinfo=offset))


def test_todo_accepts_any_zero_offset_timezone_as_utc() -> None:
    created_at = datetime(2026, 9, 25, 14, 30, tzinfo=timezone(timedelta(0)))

    assert make_todo(created_at=created_at).created_at == CREATED_AT


# MOD-009: immutability


def test_todo_is_immutable() -> None:
    todo = make_todo()

    with pytest.raises(ValueError, match="frozen"):
        todo.title = "Changed"  # type: ignore[misc]

    assert todo.title == "Submit assignment"


def test_state_change_creates_a_distinct_value_without_mutating_the_original() -> None:
    original = make_todo()

    completed = original.model_copy(update={"is_completed": True})

    assert completed is not original
    assert completed.is_completed is True
    assert original.is_completed is False
    assert completed.model_dump(exclude={"is_completed"}) == original.model_dump(
        exclude={"is_completed"}
    )


def test_todo_input_is_immutable() -> None:
    todo_input = parse()

    with pytest.raises(ValueError, match="frozen"):
        todo_input.title = "Changed"  # type: ignore[misc]
