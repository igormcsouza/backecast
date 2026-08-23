# Runs the E2E suite as a container on the same compose network as
# `frontend`/`api`/`worker`/`localstack` — see conftest.py's module
# docstring for why that's required (presigned S3 URLs only resolve inside
# that network) rather than a sandbox/CI convenience.
#
# Based on Microsoft's official Playwright Python image instead of a plain
# python:3.12 + `playwright install --with-deps`: that install step needs
# root + apt (fonts, libnss3, and a dozen other shared libs for headless
# Chromium) which isn't always available in every environment this might
# run in (it wasn't in the sandbox this suite was first verified in — see
# SESSIONS.md). The official image ships Chromium and all its OS
# dependencies already installed and version-matched to the `playwright`
# PyPI package pinned in uv.lock, so there's nothing left to install at
# container-build time beyond this project's own Python dependencies.
FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

# ffmpeg: needed by conftest.py's `tiny_audio_file` fixture to generate a
# real, ffprobe-readable mp3 at test time (see that fixture's docstring) —
# not shipped in the Playwright base image.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY . .
RUN uv sync --frozen

# No CMD override needed at `docker compose up` time — `docker compose run
# --rm e2e` (see docker-compose.e2e.yml) is how this is meant to be
# invoked, same as the backend's own
# `docker compose run --rm api uv run pytest tests/integration` convention.
CMD ["uv", "run", "pytest", "-v"]
