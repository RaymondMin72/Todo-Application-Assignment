"""HTML routes: map form submissions to service calls and results to server-rendered pages."""

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from todo_app.errors import InputValidationError
from todo_app.models import Todo
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
        todo_id: str,
        title: Annotated[str, Form()] = "",
        description: Annotated[str, Form()] = "",
        due_date: Annotated[str, Form(alias="dueDate")] = "",
    ) -> Response:
        # Declaring only the editable fields drops any submitted system-managed field.
        updated = service.update_todo(
            todo_id, {"title": title, "description": description, "due_date": due_date}
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


def _form_from_todo(todo: Todo) -> dict[str, str]:
    # Absent optional values are empty controls, so submitting them unchanged clears nothing new.
    return {
        "title": todo.title,
        "description": "" if todo.description is None else todo.description,
        "dueDate": "" if todo.due_date is None else todo.due_date.isoformat(),
    }
