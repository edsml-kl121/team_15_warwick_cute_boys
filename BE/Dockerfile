FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.10.8 /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_NO_CACHE=1
WORKDIR /app
COPY requirements.txt ./
RUN uv pip install --system -r requirements.txt
COPY main.py demo.py integrations.py service.py storage.py telephony.py ./
COPY zippy_assets ./zippy_assets
RUN mkdir /app/data && chown 10001:10001 /app/data
USER 10001:10001
CMD ["sh", "-c", "exec uvicorn main:app --host \"${HOST:-0.0.0.0}\" --port \"${PORT:-8000}\" --ws-max-size 65536"]
