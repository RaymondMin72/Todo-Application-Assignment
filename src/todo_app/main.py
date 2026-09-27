"""Application factory and production wiring."""

from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader

from todo_app.config import Settings, load_settings
from todo_app.repository import JsonTodoRepository, TodoRepository
from todo_app.service import Clock, TodoService, UUIDFactory, utc_now
from todo_app.web import create_router

_PACKAGE_DIR = Path(__file__).parent


def create_app(
    settings: Settings | None = None,
    repository: TodoRepository | None = None,
    clock: Clock = utc_now,
    uuid_factory: UUIDFactory = uuid4,
) -> FastAPI:
    """Create one fully wired application instance.

    Each call builds its own repository, service (and therefore service lock), templates, and
    static-file mount. ``repository`` replaces the JSON repository entirely; otherwise the data
    path comes from ``settings`` or, if omitted, from the environment. ``clock`` and
    ``uuid_factory`` can be replaced for deterministic tests. Debug output and the generated API
    documentation are disabled.
    """
    if repository is None:
        repository = JsonTodoRepository((settings or load_settings()).data_path)
    service = TodoService(repository, clock=clock, uuid_factory=uuid_factory)
    # Autoescaping stays on for every template so user text is never rendered as markup.
    templates = Jinja2Templates(
        env=Environment(loader=FileSystemLoader(_PACKAGE_DIR / "templates"), autoescape=True)
    )

    app = FastAPI(debug=False, openapi_url=None, docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=_PACKAGE_DIR / "static"), name="static")
    app.include_router(create_router(service, templates))
    return app


app = create_app()
