import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from todo_app.config import DATA_PATH_ENV, DEFAULT_DATA_PATH, Settings, load_settings
from todo_app.main import create_app
from todo_app.models import Todo
from todo_app.repository import JsonTodoRepository

FIRST_ID = UUID("11111111-1111-4111-8111-111111111111")
SECOND_ID = UUID("22222222-2222-4222-8222-222222222222")
THIRD_ID = UUID("33333333-3333-4333-8333-333333333333")
FIRST_TIME = datetime(2026, 9, 25, 14, 30, tzinfo=UTC)
LATER_TIME = datetime(2026, 9, 25, 14, 31, tzinfo=UTC)
LATEST_TIME = datetime(2026, 9, 25, 14, 32, tzinfo=UTC)

PROBE = '<script>alert("x")</script>'
ESCAPED_PROBE = "&lt;script&gt;alert(&#34;x&#34;)&lt;/script&gt;"


class FixedSequence:
    """Returns the given values in order, standing in for the clock or UUID source."""

    def __init__(self, *values: Any) -> None:
        self._values = list(values)

    def __call__(self) -> Any:
        return self._values.pop(0)


@pytest.fixture
def data_path(tmp_path: Path) -> Path:
    return tmp_path / "data" / "todos.json"


def make_client(
    data_path: Path,
    times: tuple[datetime, ...] = (FIRST_TIME, LATER_TIME, LATEST_TIME),
    ids: tuple[UUID, ...] = (FIRST_ID, SECOND_ID, THIRD_ID),
) -> TestClient:
    app = create_app(
        Settings(data_path=data_path),
        clock=FixedSequence(*times),
        uuid_factory=FixedSequence(*ids),
    )
    return TestClient(app)


def make_todo(todo_id: UUID = FIRST_ID, **overrides: Any) -> Todo:
    fields: dict[str, Any] = {
        "id": todo_id,
        "title": "Submit assignment",
        "description": None,
        "due_date": None,
        "is_completed": False,
        "created_at": FIRST_TIME,
    }
    fields.update(overrides)
    return Todo(**fields)


def seed(data_path: Path, *todos: Todo) -> None:
    JsonTodoRepository(data_path).save_all(todos)


def stored(data_path: Path) -> list[Todo]:
    return JsonTodoRepository(data_path).load_all()


def table_rows(html: str) -> list[str]:
    body = html.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    return re.findall(r"<tr>(.*?)</tr>", body, flags=re.DOTALL)


def input_tag(html: str, name: str) -> str:
    match = re.search(rf'<input [^>]*name="{name}"[^>]*>', html)
    assert match, f"no input named {name}"
    return match.group(0)


def textarea_content(html: str) -> str:
    match = re.search(r'<textarea [^>]*name="description"[^>]*>(.*?)</textarea>', html, re.DOTALL)
    assert match, "no description textarea"
    return match.group(1)


def create(client: TestClient, **fields: str) -> Any:
    return client.post("/todos", data=fields, follow_redirects=False)


# Application wiring and configuration


def test_load_settings_defaults_to_local_data_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DATA_PATH_ENV, raising=False)

    assert load_settings() == Settings(data_path=Path("data") / "todos.json")


def test_load_settings_reads_the_data_path_variable(
    monkeypatch: pytest.MonkeyPatch, data_path: Path
) -> None:
    monkeypatch.setenv(DATA_PATH_ENV, str(data_path))

    assert load_settings() == Settings(data_path=data_path)


def test_load_settings_treats_a_blank_variable_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DATA_PATH_ENV, "   ")

    assert load_settings() == Settings(data_path=DEFAULT_DATA_PATH)


def test_create_app_uses_the_environment_when_settings_are_omitted(
    monkeypatch: pytest.MonkeyPatch, data_path: Path
) -> None:
    monkeypatch.setenv(DATA_PATH_ENV, str(data_path))
    client = TestClient(
        create_app(clock=FixedSequence(FIRST_TIME), uuid_factory=FixedSequence(FIRST_ID))
    )

    assert create(client, title="From env").status_code == 303
    assert [todo.title for todo in stored(data_path)] == ["From env"]


def test_create_app_accepts_a_replacement_repository(tmp_path: Path) -> None:
    replacement = tmp_path / "replacement.json"
    ignored = tmp_path / "ignored.json"
    app = create_app(
        Settings(data_path=ignored),
        repository=JsonTodoRepository(replacement),
        clock=FixedSequence(FIRST_TIME),
        uuid_factory=FixedSequence(FIRST_ID),
    )

    assert create(TestClient(app), title="Replaced").status_code == 303
    assert [todo.title for todo in stored(replacement)] == ["Replaced"]
    assert not ignored.exists()


def test_each_application_instance_has_its_own_state(tmp_path: Path) -> None:
    first = make_client(tmp_path / "one.json")
    second = make_client(tmp_path / "two.json")

    create(first, title="Only in the first app")

    assert "Only in the first app" in first.get("/").text
    assert "Only in the first app" not in second.get("/").text


def test_debug_mode_and_generated_api_documentation_are_disabled(data_path: Path) -> None:
    app = create_app(Settings(data_path=data_path))
    client = TestClient(app)

    assert app.debug is False
    assert app.openapi_url is None
    for path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
        assert client.get(path).status_code == 404


def test_module_exposes_a_production_application() -> None:
    from todo_app.main import app

    assert isinstance(app, FastAPI)


# WEB-001: empty list, language, navigation, and local assets


def test_empty_list_offers_a_path_to_create(data_path: Path) -> None:
    response = make_client(data_path).get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "You have no todos yet." in response.text
    assert 'href="/todos/new"' in response.text
    assert not data_path.exists()


@pytest.mark.parametrize(
    "path", ["/", "/todos/new", f"/todos/{FIRST_ID}", f"/todos/{FIRST_ID}/edit"]
)
def test_every_page_is_english_with_list_navigation_local_styles_and_no_scripts(
    data_path: Path, path: str
) -> None:
    seed(data_path, make_todo())

    html = make_client(data_path).get(path).text

    assert '<html lang="en">' in html
    assert '<a href="/"><strong>All todos</strong></a>' in html
    stylesheets = re.findall(r'<link rel="stylesheet" href="([^"]+)">', html)
    assert stylesheets == ["/static/css/pico.min.css", "/static/css/app.css"]
    assert "<script" not in html


def test_vendored_pico_css_is_served_locally_with_its_license_notice(data_path: Path) -> None:
    response = make_client(data_path).get("/static/css/pico.min.css")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    header = response.text[:200]
    assert header.startswith('@charset "UTF-8";/*!')
    assert "Pico CSS" in header
    assert "v2.1.1" in header
    assert "Licensed under MIT" in header


def test_app_css_preserves_description_line_breaks(data_path: Path) -> None:
    response = make_client(data_path).get("/static/css/app.css")

    assert response.status_code == 200
    assert re.search(r"\.todo-description\s*\{\s*white-space:\s*pre-wrap;", response.text)


# WEB-002 and WEB-003: Create, List, and View through HTML routes


def test_create_list_and_view_workflow(data_path: Path) -> None:
    client = make_client(data_path)

    created = create(client, title="Buy milk", description="Two\nlines", dueDate="2026-09-30")

    assert created.status_code == 303
    assert created.headers["location"] == "/"

    rows = table_rows(client.get("/").text)
    assert len(rows) == 1
    assert f'<a href="/todos/{FIRST_ID}">Buy milk</a>' in rows[0]

    detail = client.get(f"/todos/{FIRST_ID}")
    assert detail.status_code == 200
    assert "Buy milk" in detail.text
    assert '<dd class="todo-description">Two\nlines</dd>' in detail.text
    assert "2026-09-30" in detail.text


def test_successful_create_redirects_to_the_list_with_303(data_path: Path) -> None:
    response = create(make_client(data_path), title="Buy milk")

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert [todo.title for todo in stored(data_path)] == ["Buy milk"]


def test_following_the_create_redirect_shows_the_new_todo(data_path: Path) -> None:
    response = make_client(data_path).post("/todos", data={"title": "Buy milk"})

    assert response.status_code == 200
    assert str(response.url).endswith("/")
    assert "Buy milk" in response.text


def test_create_form_has_labelled_controls_posting_to_create(data_path: Path) -> None:
    response = make_client(data_path).get("/todos/new")

    assert response.status_code == 200
    assert '<form method="post" action="/todos">' in response.text
    for name in ("title", "description", "dueDate"):
        assert f'<label for="{name}">' in response.text
        assert f'id="{name}" name="{name}"' in response.text
    assert "aria-invalid" not in response.text


# WEB-004: List content and ordering


def test_list_shows_title_due_date_and_explicit_status_in_service_order(data_path: Path) -> None:
    seed(
        data_path,
        make_todo(SECOND_ID, title="Tie with higher id", due_date=date(2000, 1, 1)),
        make_todo(THIRD_ID, title="Newest", created_at=LATER_TIME, is_completed=True),
        make_todo(FIRST_ID, title="Tie with lower id", due_date=date(2026, 9, 30)),
    )

    rows = table_rows(make_client(data_path).get("/").text)

    assert len(rows) == 3
    assert f'href="/todos/{THIRD_ID}"' in rows[0]
    assert "<s>Newest</s>" in rows[0]
    assert "<td>No due date</td>" in rows[0]
    assert "<td>Completed</td>" in rows[0]
    assert f'href="/todos/{FIRST_ID}">Tie with lower id</a>' in rows[1]
    assert "<td>2026-09-30</td>" in rows[1]
    assert "<td>Not completed</td>" in rows[1]
    assert f'href="/todos/{SECOND_ID}">Tie with higher id</a>' in rows[2]
    assert "<td>2000-01-01</td>" in rows[2]
    assert "<td>Not completed</td>" in rows[2]


def test_completed_titles_are_struck_through_and_incomplete_titles_are_not(
    data_path: Path,
) -> None:
    seed(
        data_path,
        make_todo(FIRST_ID, title="Done", is_completed=True),
        make_todo(SECOND_ID, title="Open", created_at=LATER_TIME),
    )

    html = make_client(data_path).get("/").text

    assert "<s>Done</s>" in html
    assert "<s>Open</s>" not in html
    assert ">Open</a>" in html


def test_past_due_dates_get_no_overdue_treatment(data_path: Path) -> None:
    seed(data_path, make_todo(due_date=date(2000, 1, 1)))

    html = make_client(data_path).get("/").text

    assert "2000-01-01" in html
    assert "overdue" not in html.lower()


# WEB-005: detail content


def test_detail_shows_all_six_fields(data_path: Path) -> None:
    seed(
        data_path,
        make_todo(
            title="Submit assignment",
            description="Review the implementation.",
            due_date=date(2026, 9, 30),
            is_completed=True,
        ),
    )

    html = make_client(data_path).get(f"/todos/{FIRST_ID}").text

    assert re.findall(r"<dt>(.*?)</dt>", html) == [
        "ID",
        "Title",
        "Description",
        "Due date",
        "Status",
        "Created",
    ]
    assert f"<code>{FIRST_ID}</code>" in html
    assert "<dd>Submit assignment</dd>" in html
    assert '<dd class="todo-description">Review the implementation.</dd>' in html
    assert "<dd>2026-09-30</dd>" in html
    assert "<dd>Completed</dd>" in html
    assert '<time datetime="2026-09-25T14:30:00Z">2026-09-25 14:30:00 UTC</time>' in html


def test_detail_shows_placeholders_for_absent_optional_values(data_path: Path) -> None:
    seed(data_path, make_todo(description=None, due_date=None))

    html = make_client(data_path).get(f"/todos/{FIRST_ID}").text

    assert "<dd>No description</dd>" in html
    assert "<dd>No due date</dd>" in html
    assert "<dd>Not completed</dd>" in html


def test_detail_preserves_line_breaks_and_escapes_description_markup(data_path: Path) -> None:
    seed(data_path, make_todo(description="First line\n\nThird <b>line</b>"))

    html = make_client(data_path).get(f"/todos/{FIRST_ID}").text

    assert '<dd class="todo-description">First line\n\nThird &lt;b&gt;line&lt;/b&gt;</dd>' in html
    assert "<b>line</b>" not in html


# WEB-007: invalid Create


def test_invalid_create_returns_422_with_all_errors_and_raw_values(data_path: Path) -> None:
    response = create(
        make_client(data_path), title="   ", description="x" * 2001, dueDate="2026-02-30"
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    assert 'value="   "' in input_tag(html, "title")
    assert textarea_content(html) == "\n" + "x" * 2001
    assert 'value="2026-02-30"' in input_tag(html, "dueDate")
    assert '<small id="title-error" class="field-error">Title is required.</small>' in html
    assert (
        '<small id="description-error" class="field-error">'
        "Description must be 2,000 characters or fewer.</small>"
    ) in html
    assert (
        '<small id="dueDate-error" class="field-error">'
        "Due date must be a real calendar date.</small>"
    ) in html
    assert not data_path.exists()


@pytest.mark.parametrize("name", ["title", "dueDate"])
def test_invalid_inputs_are_marked_and_linked_to_their_messages(data_path: Path, name: str) -> None:
    html = create(make_client(data_path), title="", dueDate="2026/09/24").text

    tag = input_tag(html, name)
    assert 'aria-invalid="true"' in tag
    assert f'aria-describedby="{name}-error"' in tag
    assert f'<small id="{name}-error"' in html


def test_invalid_description_is_marked_and_linked_to_its_message(data_path: Path) -> None:
    html = create(make_client(data_path), title="Fine", description="x" * 2001).text

    textarea = re.search(r"<textarea [^>]*>", html)
    assert textarea
    assert 'aria-invalid="true"' in textarea.group(0)
    assert 'aria-describedby="description-error"' in textarea.group(0)


def test_only_invalid_fields_are_marked_and_valid_raw_values_are_kept(data_path: Path) -> None:
    html = create(
        make_client(data_path),
        title="  Keep my spacing  ",
        description="\nStarts with a newline\r\nand has CRLF",
        dueDate="2026-9-4",
    ).text

    assert 'value="  Keep my spacing  "' in input_tag(html, "title")
    assert "aria-invalid" not in input_tag(html, "title")
    assert "title-error" not in html
    assert textarea_content(html) == "\n\nStarts with a newline\r\nand has CRLF"
    assert "description-error" not in html
    assert 'value="2026-9-4"' in input_tag(html, "dueDate")
    assert "Due date must use the YYYY-MM-DD format." in html


def test_missing_title_field_is_reported_as_required(data_path: Path) -> None:
    response = create(make_client(data_path), description="No title submitted")

    assert response.status_code == 422
    assert "Title is required." in response.text
    assert "No title submitted" in textarea_content(response.text)


def test_invalid_create_leaves_existing_data_unchanged(data_path: Path) -> None:
    seed(data_path, make_todo())
    before = data_path.read_bytes()

    response = create(make_client(data_path), title="", dueDate="not a date")

    assert response.status_code == 422
    assert data_path.read_bytes() == before


# WEB-011: escaping user markup


def test_user_markup_is_escaped_on_list_and_detail(data_path: Path) -> None:
    client = make_client(data_path)
    create(client, title=PROBE, description=PROBE)

    for html in (client.get("/").text, client.get(f"/todos/{FIRST_ID}").text):
        assert ESCAPED_PROBE in html
        assert PROBE not in html


def test_user_markup_is_escaped_in_the_redisplayed_form(data_path: Path) -> None:
    html = create(
        make_client(data_path), title=PROBE, description=PROBE, dueDate=f'"><{PROBE}'
    ).text

    assert f'value="{ESCAPED_PROBE}"' in input_tag(html, "title")
    assert textarea_content(html) == "\n" + ESCAPED_PROBE
    assert f'value="&#34;&gt;&lt;{ESCAPED_PROBE}"' in input_tag(html, "dueDate")
    assert PROBE not in html


# WEB-012: unexpected and system-managed fields


def test_create_ignores_submitted_system_managed_fields(data_path: Path) -> None:
    response = create(
        make_client(data_path),
        title="Buy milk",
        id=str(THIRD_ID),
        isCompleted="true",
        is_completed="true",
        createdAt="2000-01-01T00:00:00Z",
        created_at="2000-01-01T00:00:00Z",
        due_date="2026-09-30",
    )

    assert response.status_code == 303
    assert stored(data_path) == [make_todo(FIRST_ID, title="Buy milk")]


# WEB-014: restart persistence


def test_created_todos_remain_visible_to_a_new_application_instance(data_path: Path) -> None:
    first_run = make_client(data_path)
    create(first_run, title="Survives restart", description="Kept", dueDate="2026-09-30")

    second_run = make_client(data_path, times=(LATEST_TIME,), ids=(THIRD_ID,))

    rows = table_rows(second_run.get("/").text)
    assert len(rows) == 1
    assert f'href="/todos/{FIRST_ID}">Survives restart</a>' in rows[0]
    detail = second_run.get(f"/todos/{FIRST_ID}").text
    assert '<dd class="todo-description">Kept</dd>' in detail
    assert '<time datetime="2026-09-25T14:30:00Z">' in detail


def post_action(client: TestClient, path: str, **fields: str) -> Any:
    return client.post(path, data=fields or None, follow_redirects=False)


# WEB-002 and WEB-003: the complete HTML lifecycle and its redirects


def test_create_list_view_update_status_and_delete_lifecycle(data_path: Path) -> None:
    client = make_client(data_path)
    other = make_todo(SECOND_ID, title="Leave this one")
    created = create(client, title="Buy milk", description="Note", dueDate="2026-09-30")
    seed_after_create = stored(data_path)
    JsonTodoRepository(data_path).save_all([*seed_after_create, other])

    assert created.status_code == 303
    assert created.headers["location"] == "/"
    assert f'href="/todos/{FIRST_ID}">Buy milk</a>' in client.get("/").text

    detail = client.get(f"/todos/{FIRST_ID}")
    assert detail.status_code == 200
    assert "Note" in detail.text

    updated = post_action(
        client,
        f"/todos/{FIRST_ID}/edit",
        title="Bought milk",
        description="Updated note",
        dueDate="2026-10-01",
    )
    completed = post_action(client, f"/todos/{FIRST_ID}/complete")
    repeated = post_action(client, f"/todos/{FIRST_ID}/complete")
    reopened = post_action(client, f"/todos/{FIRST_ID}/incomplete")
    deleted = post_action(client, f"/todos/{FIRST_ID}/delete")

    assert updated.status_code == 303
    assert updated.headers["location"] == f"/todos/{FIRST_ID}"
    assert completed.status_code == 303
    assert completed.headers["location"] == f"/todos/{FIRST_ID}"
    assert repeated.status_code == 303
    assert repeated.headers["location"] == f"/todos/{FIRST_ID}"
    assert reopened.status_code == 303
    assert reopened.headers["location"] == f"/todos/{FIRST_ID}"
    assert deleted.status_code == 303
    assert deleted.headers["location"] == "/"
    assert stored(data_path) == [other]
    restarted = make_client(data_path, times=(LATEST_TIME,), ids=(THIRD_ID,))
    assert "Bought milk" not in restarted.get("/").text
    assert "Leave this one" in restarted.get("/").text


def test_update_and_status_redirect_to_detail_and_delete_redirects_to_list(
    data_path: Path,
) -> None:
    seed(data_path, make_todo(description="Keep", due_date=date(2026, 9, 30)))
    client = make_client(data_path)

    responses = [
        post_action(client, f"/todos/{FIRST_ID}/edit", title="Renamed"),
        post_action(client, f"/todos/{FIRST_ID}/complete"),
        post_action(client, f"/todos/{FIRST_ID}/incomplete"),
        post_action(client, f"/todos/{FIRST_ID}/delete"),
    ]

    assert [response.status_code for response in responses] == [303, 303, 303, 303]
    assert [response.headers["location"] for response in responses] == [
        f"/todos/{FIRST_ID}",
        f"/todos/{FIRST_ID}",
        f"/todos/{FIRST_ID}",
        "/",
    ]


# WEB-006: detail actions and the pre-filled Update form


@pytest.mark.parametrize("completed", [False, True], ids=["incomplete", "completed"])
def test_detail_offers_update_delete_and_only_the_applicable_status(
    data_path: Path, completed: bool
) -> None:
    seed(data_path, make_todo(is_completed=completed))

    html = make_client(data_path).get(f"/todos/{FIRST_ID}").text

    assert f'href="/todos/{FIRST_ID}/edit"' in html
    assert f'action="/todos/{FIRST_ID}/delete"' in html
    assert 'method="post"' in html
    if completed:
        assert f'action="/todos/{FIRST_ID}/incomplete"' in html
        assert f'action="/todos/{FIRST_ID}/complete"' not in html
        assert "Mark as not completed" in html
    else:
        assert f'action="/todos/{FIRST_ID}/complete"' in html
        assert f'action="/todos/{FIRST_ID}/incomplete"' not in html
        assert "Mark as completed" in html


def test_update_form_is_prefilled_and_every_control_has_a_label(data_path: Path) -> None:
    seed(
        data_path,
        make_todo(title="Submit assignment", description="Review it", due_date=date(2026, 9, 30)),
    )

    html = make_client(data_path).get(f"/todos/{FIRST_ID}/edit").text

    assert f'<form method="post" action="/todos/{FIRST_ID}/edit">' in html
    assert 'value="Submit assignment"' in input_tag(html, "title")
    assert textarea_content(html) == "\nReview it"
    assert 'value="2026-09-30"' in input_tag(html, "dueDate")
    for name in ("title", "description", "dueDate"):
        assert f'<label for="{name}">' in html
        assert f'id="{name}" name="{name}"' in html


def test_update_form_shows_empty_controls_for_absent_optional_values(data_path: Path) -> None:
    seed(data_path, make_todo(description=None, due_date=None))

    html = make_client(data_path).get(f"/todos/{FIRST_ID}/edit").text

    assert textarea_content(html) == "\n"
    assert 'value=""' in input_tag(html, "dueDate")


def test_blank_update_removes_optional_fields_without_changing_protected_ones(
    data_path: Path,
) -> None:
    original = make_todo(description="Remove me", due_date=date(2026, 9, 30), is_completed=True)
    seed(data_path, original)

    response = post_action(
        make_client(data_path),
        f"/todos/{FIRST_ID}/edit",
        title="  Kept title  ",
        description="  \r\n ",
        dueDate="   ",
    )

    assert response.status_code == 303
    assert stored(data_path) == [
        original.model_copy(update={"title": "Kept title", "description": None, "due_date": None})
    ]


def test_repeated_status_changes_are_idempotent(data_path: Path) -> None:
    seed(data_path, make_todo())
    client = make_client(data_path)

    first = post_action(client, f"/todos/{FIRST_ID}/complete")
    second = post_action(client, f"/todos/{FIRST_ID}/complete")

    assert first.status_code == second.status_code == 303
    assert stored(data_path) == [make_todo(is_completed=True)]

    post_action(client, f"/todos/{FIRST_ID}/incomplete")
    post_action(client, f"/todos/{FIRST_ID}/incomplete")

    assert stored(data_path) == [make_todo()]


def test_status_and_delete_leave_the_other_todos_unchanged(data_path: Path) -> None:
    first = make_todo(FIRST_ID, title="Target")
    second = make_todo(SECOND_ID, title="Other", created_at=LATER_TIME, is_completed=True)
    seed(data_path, first, second)
    client = make_client(data_path)

    post_action(client, f"/todos/{FIRST_ID}/complete")
    assert stored(data_path) == [first.model_copy(update={"is_completed": True}), second]

    deleted = post_action(client, f"/todos/{FIRST_ID}/delete")
    assert deleted.headers["location"] == "/"
    assert stored(data_path) == [second]


# WEB-012: Update ignores system-managed fields


def test_update_ignores_submitted_system_managed_fields(data_path: Path) -> None:
    original = make_todo(description="Keep", due_date=date(2026, 9, 30), is_completed=True)
    seed(data_path, original)

    response = post_action(
        make_client(data_path),
        f"/todos/{FIRST_ID}/edit",
        title="Renamed",
        description="Keep",
        dueDate="2026-09-30",
        id=str(THIRD_ID),
        isCompleted="false",
        is_completed="false",
        createdAt="2000-01-01T00:00:00Z",
        created_at="2000-01-01T00:00:00Z",
    )

    assert response.status_code == 303
    assert stored(data_path) == [original.model_copy(update={"title": "Renamed"})]


# WEB-013: mutations require POST and work without JavaScript


@pytest.mark.parametrize(
    "path",
    [
        f"/todos/{FIRST_ID}/edit",
        f"/todos/{FIRST_ID}/complete",
        f"/todos/{FIRST_ID}/incomplete",
        f"/todos/{FIRST_ID}/delete",
    ],
)
def test_get_does_not_mutate_a_todo(data_path: Path, path: str) -> None:
    seed(data_path, make_todo(description="Stay", due_date=date(2026, 9, 30)))
    before = data_path.read_bytes()

    make_client(data_path).get(path)

    assert data_path.read_bytes() == before


def test_mutation_forms_post_and_pages_need_no_javascript(data_path: Path) -> None:
    seed(data_path, make_todo())
    client = make_client(data_path)

    for html in (
        client.get(f"/todos/{FIRST_ID}").text,
        client.get(f"/todos/{FIRST_ID}/edit").text,
    ):
        assert "<script" not in html
        assert 'method="get"' not in html.lower()
    detail = client.get(f"/todos/{FIRST_ID}").text
    assert 'method="post"' in detail
    assert f'action="/todos/{FIRST_ID}/complete"' in detail
    assert f'action="/todos/{FIRST_ID}/delete"' in detail


# WEB-014: updates, status, and deletes survive a new application instance


def test_updates_and_status_remain_after_restart_and_deletes_stay_absent(
    data_path: Path,
) -> None:
    seed(data_path, make_todo(description="Original", due_date=date(2026, 9, 30)))
    first_run = make_client(data_path)
    post_action(
        first_run,
        f"/todos/{FIRST_ID}/edit",
        title="After restart",
        description="",
        dueDate="",
    )
    post_action(first_run, f"/todos/{FIRST_ID}/complete")

    second_run = make_client(data_path, times=(LATEST_TIME,), ids=(THIRD_ID,))
    detail = second_run.get(f"/todos/{FIRST_ID}").text
    assert "After restart" in detail
    assert "<dd>No description</dd>" in detail
    assert "<dd>No due date</dd>" in detail
    assert "<dd>Completed</dd>" in detail
    assert '<time datetime="2026-09-25T14:30:00Z">' in detail

    post_action(second_run, f"/todos/{FIRST_ID}/delete")
    third_run = make_client(data_path, times=(LATEST_TIME,), ids=(THIRD_ID,))
    assert "After restart" not in third_run.get("/").text
    assert stored(data_path) == []


# WEB-016: strikethrough follows Complete and Incomplete


def test_list_strikethrough_follows_complete_and_incomplete(data_path: Path) -> None:
    seed(data_path, make_todo(title="Toggle me"))
    client = make_client(data_path)

    assert "<s>Toggle me</s>" not in client.get("/").text

    post_action(client, f"/todos/{FIRST_ID}/complete")
    assert "<s>Toggle me</s>" in client.get("/").text
    assert "Mark as not completed" in client.get(f"/todos/{FIRST_ID}").text

    post_action(client, f"/todos/{FIRST_ID}/incomplete")
    assert "<s>Toggle me</s>" not in client.get("/").text
    assert ">Toggle me</a>" in client.get("/").text
