"""Todo domain models, editable-input normalization, and field validation.

The models hold typed Python values only. Mapping to persisted JSON keys and string encodings
belongs to the repository.
"""

import re
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
from pydantic_core import PydanticCustomError

from todo_app.errors import InputValidationError

TITLE_MAX_LENGTH = 200
DESCRIPTION_MAX_LENGTH = 2000
EDITABLE_FIELDS = ("title", "description", "due_date")

# ASCII digits only: ``\d`` would also accept non-ASCII Unicode digits.
_DUE_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _field_error(message: str) -> PydanticCustomError:
    return PydanticCustomError("todo_field", message)


def _optional_text(value: object, label: str) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise _field_error(f"{label} must be text.")


def _normalize_title(value: str) -> str:
    return value.strip()


def _normalize_description(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    return text or None


def _normalize_due_date(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def _check_title(title: str) -> str:
    # len() counts Unicode code points, as required for length limits.
    if not title:
        raise _field_error("Title is required.")
    if len(title) > TITLE_MAX_LENGTH:
        raise _field_error(f"Title must be {TITLE_MAX_LENGTH} characters or fewer.")
    return title


def _check_description(description: str | None) -> str | None:
    if description is not None and len(description) > DESCRIPTION_MAX_LENGTH:
        raise _field_error(f"Description must be {DESCRIPTION_MAX_LENGTH:,} characters or fewer.")
    return description


def _parse_due_date(text: str) -> date:
    # Check the exact shape first: date.fromisoformat() also accepts other ISO 8601 forms.
    if not _DUE_DATE_PATTERN.fullmatch(text):
        raise _field_error("Due date must use the YYYY-MM-DD format.")
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise _field_error("Due date must be a real calendar date.") from None


class TodoInput(BaseModel):
    """Normalized and validated editable Todo fields, shared by Create and Update.

    Raw text is normalized before it is validated: the title is trimmed; the description has
    CRLF and CR converted to LF, is trimmed, and becomes ``None`` when blank; the due date is
    trimmed, becomes ``None`` when blank, and otherwise must be an exact, real ``YYYY-MM-DD``
    date.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str
    description: str | None
    due_date: date | None

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> Self:
        """Build validated input from raw submitted text values.

        Only the ``title``, ``description``, and ``due_date`` keys are read; any other keys are
        ignored. A missing key is treated as empty input. All detected field errors are raised
        together as an :class:`InputValidationError`.
        """
        try:
            return cls.model_validate({name: values.get(name) for name in EDITABLE_FIELDS})
        except ValidationError as exc:
            errors: dict[str, list[str]] = {}
            for error in exc.errors():
                errors.setdefault(str(error["loc"][0]), []).append(error["msg"])
            raise InputValidationError(errors) from None

    @field_validator("title", mode="before")
    @classmethod
    def _validate_title(cls, value: object) -> str:
        return _check_title(_normalize_title(_optional_text(value, "Title") or ""))

    @field_validator("description", mode="before")
    @classmethod
    def _validate_description(cls, value: object) -> str | None:
        return _check_description(_normalize_description(_optional_text(value, "Description")))

    @field_validator("due_date", mode="before")
    @classmethod
    def _validate_due_date(cls, value: object) -> date | None:
        text = _normalize_due_date(_optional_text(value, "Due date"))
        return None if text is None else _parse_due_date(text)


class Todo(BaseModel):
    """An immutable Todo item holding typed, already-normalized domain values.

    Editable fields must already satisfy the :class:`TodoInput` rules; they are validated but
    never silently normalized, so invalid stored data cannot be repaired by accident. ``id``
    must be a UUID version 4 and ``created_at`` a timezone-aware UTC datetime. Derive changed
    values with ``model_copy(update=...)``.
    """

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    id: UUID
    title: str
    description: str | None
    due_date: date | None
    is_completed: bool
    created_at: datetime

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: UUID) -> UUID:
        # UUID.version is None for non-RFC 4122 variants, so this also rejects them.
        if value.version != 4:
            raise _field_error("Todo ID must be a UUID version 4.")
        return value

    @field_validator("title")
    @classmethod
    def _validate_title(cls, value: str) -> str:
        if _normalize_title(value) != value:
            raise _field_error("Title must not have surrounding whitespace.")
        return _check_title(value)

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: str | None) -> str | None:
        if value is not None and _normalize_description(value) != value:
            raise _field_error(
                "Description must be non-blank, use LF line breaks, "
                "and have no surrounding whitespace."
            )
        return _check_description(value)

    @field_validator("due_date", mode="before")
    @classmethod
    def _validate_due_date(cls, value: object) -> object:
        # datetime subclasses date, but a due date carries no time of day.
        if isinstance(value, datetime):
            raise _field_error("Due date must be a date without a time.")
        return value

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: datetime) -> datetime:
        offset = value.utcoffset()
        if offset is None:
            raise _field_error("Creation time must be timezone-aware.")
        if offset != timedelta(0):
            raise _field_error("Creation time must be in UTC.")
        return value
