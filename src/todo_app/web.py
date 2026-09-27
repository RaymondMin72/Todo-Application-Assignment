"""HTML routes: map form submissions to service calls and results to server-rendered pages."""

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from todo_app.errors import InputValidationError
from todo_app.service import TodoService

# The service reports errors by Python field name; the form uses the documented field names.
_FORM_FIELD_NAMES = {"title": "title", "description": "description", "due_date": "dueDate"}
_EMPTY_FORM = {"title": "", "description": "", "dueDate": ""}


def create_router(service: TodoService, templates: Jinja2Templates) -> APIRouter:
    """Build the HTML routes bound to one service and one template environment.

    Handlers are plain functions: FastAPI parses any form body first and then runs the whole
    handler, including the service call that takes the service lock, in its thread pool.
    """
    router = APIRouter()

    def render_create_form(
        request: Request,
        form: dict[str, str],
        errors: dict[str, list[str]],
        status_code: int,
    ) -> Response:
        return templates.TemplateResponse(
            request,
            "todo_form.html",
            {
                "heading": "New todo",
                "action": "/todos",
                "submit_label": "Create todo",
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
        return render_create_form(request, _EMPTY_FORM, {}, 200)

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
            return render_create_form(request, raw_form, _form_errors(exc), 422)
        return RedirectResponse("/", status_code=303)

    @router.get("/todos/{todo_id}")
    def view_todo(request: Request, todo_id: str) -> Response:
        return templates.TemplateResponse(
            request, "todo_detail.html", {"todo": service.get_todo(todo_id)}
        )

    return router


def _form_errors(exc: InputValidationError) -> dict[str, list[str]]:
    return {_FORM_FIELD_NAMES[field]: messages for field, messages in exc.errors.items()}
