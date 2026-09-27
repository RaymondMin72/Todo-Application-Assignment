FROM python:3.12-slim

# The application allows one writer. A single Uvicorn worker matches that limit.
ENV TODO_DATA_PATH=/data/todos.json \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN useradd --create-home --uid 1000 appuser \
    && mkdir /data \
    && chown appuser:appuser /data

COPY pyproject.toml ./
COPY src ./src

# Install the same pinned runtime dependencies declared in pyproject.toml.
RUN pip install --no-cache-dir .

USER appuser

EXPOSE 8000

CMD ["uvicorn", "todo_app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
