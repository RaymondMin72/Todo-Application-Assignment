"""HTML routes: map form submissions to service calls and results to server-rendered pages."""

import logging
import sys
from typing import Annotated, TextIO

from fastapi import APIRouter, FastAPI, Form, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException

from todo_app.errors import InputValidationError, PersistenceError, TodoNotFound
from todo_app.models import Todo
from todo_app.service import TodoService

_logger = logging.getLogger("todo_app.web")
_stderr_logging_ready = False

# The service reports errors by Python field name; the form uses the documented field names.
_FORM_FIELD_NAMES = {"title": "title", "description": "description", "due_date": "dueDate"}
_EMPTY_FORM = {"title": "", "description": "", "dueDate": ""}
_NOT_FOUND_MESSAGE = "That todo or page could not be found."
_METHOD_NOT_ALLOWED_MESSAGE = "That action is not supported for this page."
_GENERIC_ERROR_MESSAGE = "The request could not be completed."
_SERVER_ERROR_MESSAGE = "Something went wrong while handling the request. Please try again later."


def create_router(service: TodoService, templates: Jinja2Templates) -> APIRouter:
    """Build the HTML routes bound to one service and one template environment.

    Handlers are plain functions: FastAPI parses any form body first and then runs the whole
    handler, including the service call that takes the service lock, in its thread pool.
    """
    router = APIRouter()

    def render_form(
        request: Request,
        *,
        heading: str,
        action: str,
        submit_label: str,
        form: dict[str, str],
        errors: dict[str, list[str]],
        status_code: int,
    ) -> Response:
        return templates.TemplateResponse(
            request,
            "todo_form.html",
            {
                "heading": heading,
                "action": action,
                "submit_label": submit_label,
                "form": form,
                "errors": errors,
            },
            status_code=status_code,
        )

    @router.get("/")
    def list_todos(request: Request) -> Response:
        return templates.TemplateResponse(
            request, "todo_list.html", {"todos": service.list_todos()}
        )

    @router.get("/todos/new")
    def new_todo(request: Request) -> Response:
        return render_form(
            request,
            heading="New todo",
            action="/todos",
            submit_label="Create todo",
            form=_EMPTY_FORM,
            errors={},
            status_code=200,
        )

    @router.post("/todos")
    def create_todo(
        request: Request,
        title: Annotated[str, Form()] = "",
        description: Annotated[str, Form()] = "",
        due_date: Annotated[str, Form(alias="dueDate")] = "",
    ) -> Response:
        # Only the three editable fields are declared, so any other submitted field is ignored.
        try:
            service.create_todo({"title": title, "description": description, "due_date": due_date})
        except InputValidationError as exc:
            # Redisplay the raw submitted text, not the normalized values.
            raw_form = {"title": title, "description": description, "dueDate": due_date}
            return render_form(
                request,
                heading="New todo",
                action="/todos",
                submit_label="Create todo",
                form=raw_form,
                errors=_form_errors(exc),
                status_code=422,
            )
        return RedirectResponse("/", status_code=303)

    @router.get("/todos/{todo_id}")
    def view_todo(request: Request, todo_id: str) -> Response:
        return templates.TemplateResponse(
            request, "todo_detail.html", {"todo": service.get_todo(todo_id)}
        )

    @router.get("/todos/{todo_id}/edit")
    def edit_todo(request: Request, todo_id: str) -> Response:
        todo = service.get_todo(todo_id)
        return render_form(
            request,
            heading="Edit todo",
            action=f"/todos/{todo.id}/edit",
            submit_label="Save changes",
            form=_form_from_todo(todo),
            errors={},
            status_code=200,
        )

    @router.post("/todos/{todo_id}/edit")
    def update_todo(
        request: Request,
        todo_id: str,
        title: Annotated[str, Form()] = "",
        description: Annotated[str, Form()] = "",
        due_date: Annotated[str, Form(alias="dueDate")] = "",
    ) -> Response:
        # Declaring only the editable fields drops any submitted system-managed field.
        raw_form = {"title": title, "description": description, "dueDate": due_date}
        try:
            updated = service.update_todo(
                todo_id, {"title": title, "description": description, "due_date": due_date}
            )
        except InputValidationError as exc:
            # Redisplay the raw submitted text, not the normalized values.
            return render_form(
                request,
                heading="Edit todo",
                action=f"/todos/{todo_id}/edit",
                submit_label="Save changes",
                form=raw_form,
                errors=_form_errors(exc),
                status_code=422,
            )
        return RedirectResponse(f"/todos/{updated.id}", status_code=303)

    @router.post("/todos/{todo_id}/complete")
    def complete_todo(todo_id: str) -> Response:
        updated = service.set_completed(todo_id, True)
        return RedirectResponse(f"/todos/{updated.id}", status_code=303)

    @router.post("/todos/{todo_id}/incomplete")
    def incomplete_todo(todo_id: str) -> Response:
        updated = service.set_completed(todo_id, False)
        return RedirectResponse(f"/todos/{updated.id}", status_code=303)

    @router.post("/todos/{todo_id}/delete")
    def delete_todo(todo_id: str) -> Response:
        service.delete_todo(todo_id)
        return RedirectResponse("/", status_code=303)

    return router


def _form_errors(exc: InputValidationError) -> dict[str, list[str]]:
    return {_FORM_FIELD_NAMES[field]: messages for field, messages in exc.errors.items()}


def register_exception_handlers(app: FastAPI, templates: Jinja2Templates) -> None:
    """Render controlled HTML for not-found, method, persistence, and unexpected failures.

    Diagnostic detail is written to standard error. The pages themselves use fixed text, so a
    response cannot reveal a path, stored content, stack trace, or configuration.
    """
    _ensure_stderr_logging()

    def render_error(request: Request, status_code: int, heading: str, message: str) -> Response:
        return templates.TemplateResponse(
            request,
            "error.html",
            {"heading": heading, "message": message},
            status_code=status_code,
        )

    @app.exception_handler(TodoNotFound)
    def todo_not_found(request: Request, exc: TodoNotFound) -> Response:
        del exc
        return render_error(request, 404, "Not found", _NOT_FOUND_MESSAGE)

    @app.exception_handler(HTTPException)
    def http_error(request: Request, exc: HTTPException) -> Response:
        if exc.status_code == 405:
            response = render_error(request, 405, "Method not allowed", _METHOD_NOT_ALLOWED_MESSAGE)
            # Replace the framework JSON body, but keep the Allow header it computed.
            allow = _allow_header(exc)
            if allow is not None:
                response.headers["allow"] = allow
            return response
        if exc.status_code == 404:
            return render_error(request, 404, "Not found", _NOT_FOUND_MESSAGE)
        return render_error(request, exc.status_code, "Request error", _GENERIC_ERROR_MESSAGE)

    @app.exception_handler(PersistenceError)
    def persistence_error(request: Request, exc: PersistenceError) -> Response:
        _logger.error("Persistence failure", exc_info=exc)
        return render_error(request, 500, "Something went wrong", _SERVER_ERROR_MESSAGE)

    @app.exception_handler(Exception)
    def unexpected_error(request: Request, exc: Exception) -> Response:
        _logger.error("Unexpected failure", exc_info=exc)
        return render_error(request, 500, "Something went wrong", _SERVER_ERROR_MESSAGE)


class _CurrentStderrHandler(logging.StreamHandler[TextIO]):
    """Write to whatever ``sys.stderr`` is when the record is emitted.

    Binding the stream once would miss output captured later by a test runner.
    """

    def __init__(self) -> None:
        super().__init__(sys.stderr)

    def emit(self, record: logging.LogRecord) -> None:
        self.stream = sys.stderr
        super().emit(record)


def _ensure_stderr_logging() -> None:
    global _stderr_logging_ready
    if _stderr_logging_ready:
        return
    handler = _CurrentStderrHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s [%(name)s] %(message)s"))
    _logger.setLevel(logging.ERROR)
    _logger.addHandler(handler)
    _stderr_logging_ready = True


def _allow_header(exc: HTTPException) -> str | None:
    if not exc.headers:
        return None
    for key, value in exc.headers.items():
        if key.lower() == "allow":
            return value
    return None


def _form_from_todo(todo: Todo) -> dict[str, str]:
    # Absent optional values are empty controls, so submitting them unchanged clears nothing new.
    return {
        "title": todo.title,
        "description": "" if todo.description is None else todo.description,
        "dueDate": "" if todo.due_date is None else todo.due_date.isoformat(),
    }
