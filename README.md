# Todo application

A single-user, server-rendered to-do list. The browser talks to a FastAPI application, which keeps every todo in one JSON file. Pages work without JavaScript.

## Requirements

- Python 3.12 for local setup
- Docker, if you want to run the container instead

The runtime dependencies are pinned in `pyproject.toml`.

## Local setup

From the repository root:

```text
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

On macOS or Linux, use `python3.12` and `.venv/bin/python` in place of the Windows commands above.

The `[dev]` extra adds pytest, coverage, Ruff, and mypy. It is not installed in the Docker image.

## Run locally

```text
.venv\Scripts\python -m uvicorn todo_app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/.

Todos are stored in `./data/todos.json` unless you set `TODO_DATA_PATH`. A relative path is resolved from the process working directory. The directory and file are created on the first successful save. `./data/` is runtime state and is not part of the repository.

## Tests and quality checks

From the repository root, with the virtual environment active:

```text
python -m pytest
ruff format --check .
ruff check .
mypy src/todo_app
```

`python -m pytest` is the canonical test command. It runs the unit and integration suites with branch coverage and fails if application coverage is below 85%. The tests use temporary files and fixed clocks and UUID sources. They do not read `./data/todos.json`.

## Docker

The image uses Python 3.12, installs the pinned runtime dependencies, listens on `0.0.0.0:8000`, and starts one Uvicorn process with one worker. It runs as the non-root user `todo`, which can write to `/data`. The container data file is `/data/todos.json`.

```text
docker build -t todo-app .
docker run --rm -p 8000:8000 -v todo-data:/data todo-app
```

`/data` is the persistent-volume location. Attach the same named volume to keep todos across container recreation.

Unmounted container data is disposable. A todo saved without a volume mounted at `/data` disappears when that container is removed.

### Volume persistence check

Use a disposable volume name:

1. `docker build -t todo-app .`
2. `docker run --name todo-smoke -p 8000:8000 -v todo-data:/data todo-app`
3. Open http://127.0.0.1:8000/ and create a todo.
4. `docker rm -f todo-smoke`
5. `docker run --name todo-smoke -p 8000:8000 -v todo-data:/data todo-app`
6. Confirm the todo is still listed.
7. `docker rm -f todo-smoke` and, when you no longer need the data, `docker volume rm todo-data`.

## Storage and recovery

The JSON file is a single array. Each record has exactly `id`, `title`, `description`, `dueDate`, `isCompleted`, and `createdAt`. Optional description and due date are JSON `null`. Writes go to a temporary file in the same directory and replace the primary file only after the new contents are flushed. A failed write leaves the previous file in place.

If the primary file is missing, the list is empty. If it exists but is empty, whitespace-only, or otherwise invalid, the application does not repair it, does not load part of it, and does not save over it. Requests then show a generic error page, and the details are written to the server log.

To recover:

1. Stop the application.
2. Repair or replace the primary JSON file with a valid array, or delete the file to start from an empty list.
3. Start the application again.

Do not try to recover by repeating a create or update while the file is still invalid. Those requests fail before writing.

## Design

The application has three layers. Presentation owns HTTP, forms, Jinja2 templates, and Pico.css. The service owns validation, ordering, and the create, update, complete, incomplete, and delete operations. The repository is the only code that reads and writes JSON. The service holds one in-process lock around each read and each complete read-modify-write. Time and UUID generation can be replaced in tests.

The list is ordered by creation time, newest first, with the canonical ID as a tie-breaker. Completed titles are struck through, and completion is also written as text. Due dates are shown as `YYYY-MM-DD` or `No due date`, with no overdue styling.

Automated tests cover the domain rules, the service against an in-memory repository, JSON loading and atomic writes against temporary directories, and the HTML workflows through FastAPI's `TestClient`. Browser end-to-end tests and automated Docker tests are not part of the suite. The container check above is manual.

## Assumptions and limitations

The application serves one person on a trusted machine. It has no accounts, authentication, or CSRF protection. One process should own a data file; multiple writers are not supported, which is why the container uses one worker.

Full-file reads and writes are enough for a few hundred todos. Any invalid record blocks the whole file until it is repaired by hand. There is no backup, undo, filtering, sorting control, or REST API. Update replaces the title, description, and due date together. Complete and incomplete only change the completion flag and can be repeated safely. Delete is permanent and has no confirmation step.
