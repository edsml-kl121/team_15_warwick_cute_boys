FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=never PATH="/app/.venv/bin:$PATH"
WORKDIR /app

RUN python -m pip install --no-cache-dir uv==0.11.28
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev
COPY app ./app

USER 10001:10001
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8001}\""]
