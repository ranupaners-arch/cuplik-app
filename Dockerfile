FROM node:26-bookworm-slim AS javascript
FROM python:3.12-slim AS base
COPY --from=javascript /usr/local/bin/node /usr/local/bin/node
COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /uvx /bin/
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH" DATA_DIR=/app/data
COPY pyproject.toml uv.lock ./
ARG TRANSCRIPTION_EXTRA=""
# Keep large OpenCV/NumPy/model dependencies cached when application code changes.
RUN --mount=type=cache,target=/root/.cache/uv if [ "$TRANSCRIPTION_EXTRA" = "transcription" ]; then uv sync --frozen --no-dev --no-install-project --extra transcription; else uv sync --frozen --no-dev --no-install-project; fi
COPY api ./api
COPY worker ./worker
COPY alembic.ini ./
RUN --mount=type=cache,target=/root/.cache/uv if [ "$TRANSCRIPTION_EXTRA" = "transcription" ]; then uv sync --frozen --no-dev --extra transcription; else uv sync --frozen --no-dev; fi
RUN useradd --create-home --uid 1000 cuplik && mkdir /app/data && chown cuplik:cuplik /app/data
USER cuplik
CMD ["uvicorn", "api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
