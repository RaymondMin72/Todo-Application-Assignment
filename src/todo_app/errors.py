"""Application-specific exception types shared across layers."""

from collections.abc import Mapping, Sequence


class TodoNotFound(Exception):
    """Raised when a Todo ID is malformed or does not match a stored Todo."""


class InputValidationError(Exception):
    """Raised when editable input fails validation.

    ``errors`` maps each invalid field name to all messages detected for it.
    """

    errors: dict[str, list[str]]

    def __init__(self, errors: Mapping[str, Sequence[str]]) -> None:
        self.errors = {field: list(messages) for field, messages in errors.items()}
        super().__init__(f"Invalid input for: {', '.join(sorted(self.errors))}")


class PersistenceError(Exception):
    """Base class for failures of the persistence boundary."""


class PersistenceReadError(PersistenceError):
    """Raised when stored data cannot be read or is invalid."""


class PersistenceWriteError(PersistenceError):
    """Raised when a new collection cannot be stored."""
