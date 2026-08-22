# --- deps: resolve + install project dependencies (cached until pyproject/uv.lock change)
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS deps
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# --- runtime: neutral default (no reload) — docker-compose overrides `command` for local dev
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS runtime
WORKDIR /app
# ffmpeg: needed by the docker-compose `worker` service (worker/audio.py) so
# local dev exercises the *real* ffmpeg preprocessing step, not a mock of
# it — same business-logic-only-exists-once philosophy as
# worker/local_poller.py's docstring. The real Lambda ships ffmpeg via a
# separate container image (worker/Dockerfile, AWS's own Lambda base image
# + a static ffmpeg build); this apt package is simpler and is fine for a
# throwaway local dev container that also happens to run the `api` service
# (which never calls ffmpeg, so the extra ~80MB here costs it nothing but
# image size).
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY --from=deps /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
