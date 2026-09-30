# Todo Application

A small, server-rendered FastAPI app for creating, listing, viewing, updating, completing, and deleting Todos. It needs no JavaScript or external database.

## Requirements

- Python 3.12 for local setup
- Docker, if you want to run the container instead

The runtime dependencies are pinned in `pyproject.toml`.

## Local Setup

From the repository root.

Windows (PowerShell):

```text
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

macOS or Linux:

```text
python3.12 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

If `venv` cannot run `ensurepip` on Windows, create the environment with `py -3.12 -m venv --without-pip .venv`, then run `py -3.12 -m pip --python .venv install -e ".[dev]"` before the commands above.

The `[dev]` extra adds pytest, coverage, Ruff, and mypy. It is not installed in the Docker image.

## Start the Application

Windows (PowerShell):

```text
.venv\Scripts\python -m uvicorn todo_app.main:app --host 127.0.0.1 --port 8000
```

macOS or Linux:

```text
.venv/bin/python -m uvicorn todo_app.main:app --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/).

Todos are stored in `./data/todos.json` unless you set `TODO_DATA_PATH`. A relative path is resolved from the process working directory. The directory and file are created on the first successful save. `./data/` is runtime state and is not part of the repository.

## Tests and Quality Checks

From the repository root, activate the virtual environment first.

Windows (PowerShell):

```text
.venv\Scripts\Activate.ps1
```

macOS or Linux:

```text
source .venv/bin/activate
```

The prompt includes `(.venv)` after activation. Then run:

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

Unmounted container data is disposable. A todo saved without a volume mounted at `/data` disappears when that container is removed. Do not attach more than one running application process to the same data file.

## Optional: Google Cloud Run

This section is supplementary. It is not required to build, test, or evaluate the assignment locally.

A live demo is deployed at [https://todo-app-gcs-281463039338.us-central1.run.app](https://todo-app-gcs-281463039338.us-central1.run.app). Data persists in a Google Cloud Storage bucket mounted at `/data` (the same path the Docker image uses for `TODO_DATA_PATH=/data/todos.json`).

**Prerequisites:** a GCP project with billing enabled, and a GCS bucket created beforehand. The Cloud Run service account needs permission to read and write that bucket (for example, `roles/storage.objectAdmin` on the bucket).

From the repository root:

```text
gcloud run deploy todo-app-gcs \
  --source . \
  --region us-central1 \
  --port 8000 \
  --max-instances 1 \
  --allow-unauthenticated \
  --add-volume name=todo-data,type=cloud-storage,bucket=BUCKET_NAME \
  --add-volume-mount volume=todo-data,mount-path=/data
```

Replace `BUCKET_NAME` with the bucket you created. `--port 8000` matches the Uvicorn port in the Dockerfile. `--max-instances 1` keeps a single writer on the JSON file, consistent with the one-worker constraint described above. The demo is publicly reachable and has no authentication; treat it as a demonstration only.

## Storage and Recovery

The data file is one JSON array. Each record has exactly `id`, `title`, `description`, `dueDate`, `isCompleted`, and `createdAt`; optional description and due date are `null`. A missing file is an empty list. An existing file that is empty, whitespace-only, or invalid is left unchanged: the app shows an error and refuses to write over it. Stop the app, keep a copy of the original bytes, replace the file with a valid array (or delete it to start empty), then start again.

## Design

The application has three layers. **Presentation** owns HTTP, forms, Jinja2 templates, and Pico.css. **Service** owns validation, ordering, and the create, update, complete, incomplete, and delete operations. **Repository** is the only code that reads and writes JSON, writing through a temporary file in the same directory and replacing the primary file only after the new contents are flushed. The service holds one in-process lock around each read and each complete read-modify-write. Time and UUID generation can be replaced in tests.

The list is ordered by creation time, newest first, with the canonical ID as a tie-breaker. Completed titles are struck through, and completion is also written as text. Due dates are shown as `YYYY-MM-DD` or `No due date`, with no overdue styling. The form takes a required title, an optional description, and an optional `YYYY-MM-DD` due date. A new item starts incomplete, and the app assigns its id and creation time.

Automated tests cover the domain rules, the service against an in-memory repository, JSON loading and atomic writes against temporary directories, and the HTML workflows through FastAPI's `TestClient`. Browser end-to-end tests and automated Docker tests are not part of the suite.

## Assumptions and Limitations

The application serves one person on a trusted machine. It has no accounts, authentication, or CSRF protection. One process should own a data file; multiple writers are not supported, which is why the container uses one worker. Full-file reads and writes are enough for a few hundred todos. Any invalid record blocks the whole file until it is repaired by hand.

Update replaces the title, description, and due date together. Complete and incomplete only change the completion flag and can be repeated safely. Delete is permanent and has no confirmation step. There is no backup or undo.

There is no REST API. Of the optional enhancements, input validation and Docker are included. A Cloud Run deployment with a GCS volume is documented above as a supplement. Filtering and user-controlled sorting were left out for time.
