FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TODO_DATA_PATH=/data/todos.json

WORKDIR /app

# Stable runtime identity. Only /data is writable; the installed app stays root-owned.
RUN useradd \
        --system \
        --uid 10001 \
        --user-group \
        --no-create-home \
        --no-log-init \
        --home-dir /nonexistent \
        todo \
    && mkdir /data \
    && chown todo:todo /data

# Both inputs must be present before install. setuptools snapshots src into site-packages.
COPY pyproject.toml ./
COPY src/ ./src/

RUN python -m pip install --no-cache-dir .

USER todo:todo

EXPOSE 8000

# One worker matches the in-process service lock.
CMD ["uvicorn", "todo_app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
