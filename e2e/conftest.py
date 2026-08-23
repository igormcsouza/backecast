"""Shared Playwright fixtures for the E2E suite.

Why headless Chromium only (see pyproject.toml's `addopts`): this MVP has
one supported browser target and running the whole suite against Firefox
and WebKit too would multiply CI time and local-sandbox setup cost (browser
binaries + OS deps per engine) for a signal nothing in this project's spec
asks for. `--browser firefox`/`webkit` can be added the day a real
cross-browser bug shows up.

Why the suite runs inside the docker-compose network (see the repo root's
`docker-compose.e2e.yml`), not from the bare host: presigned S3 URLs the
backend hands back are signed against `http://localstack:4566` — a hostname
that only resolves *inside* the compose network's internal DNS, never from
a process on the host. `backend/tests/integration/conftest.py` hits the same
wall for `httpx`, and Session 7 (SESSIONS.md) notes it blocked a real
click-through from the host browser. Running the frontend *and* the
Playwright-driven browser as containers on that same compose network means
every hostname the pages construct (`api`, `localstack`, `frontend`)
resolves exactly the way it would in a real deployment, so this suite
exercises real URLs, not a workaround.
"""

from __future__ import annotations

import os
import subprocess

import pytest

ADMIN_KEY = os.environ.get("ADMIN_KEY", "local-dev-admin-key")
API_URL = os.environ.get("API_URL", "http://localhost:8989").rstrip("/")


@pytest.fixture(scope="session")
def base_url() -> str:
    """Overrides pytest-playwright/pytest-base-url's default
    (http://localhost:8080) so `page.goto("/...")` resolves relative URLs
    against the frontend under test.

    Read from FRONTEND_URL rather than hardcoded so the exact same suite
    works locally (`docker compose -f docker-compose.yml -f
    docker-compose.e2e.yml run --rm e2e`, where FRONTEND_URL=
    http://frontend:3000, the container's compose-network DNS name) and, if
    ever pointed at a real deployed environment, by overriding one env var —
    no code change.
    """
    return os.environ.get("FRONTEND_URL", "http://localhost:3000")


@pytest.fixture(scope="session")
def admin_key() -> str:
    """The shared admin secret. Fixed for local/CI by
    `scripts/init-localstack.sh` (which seeds it into SSM as
    `local-dev-admin-key`) — never a real secret, see CLAUDE.md."""
    return ADMIN_KEY


@pytest.fixture(scope="session")
def api_url() -> str:
    """Base URL for direct API calls the tests make outside the browser
    (currently unused by the tests themselves, kept for any fixture/helper
    that wants to hit the API directly rather than through the UI)."""
    return API_URL


@pytest.fixture(scope="session")
def tiny_audio_file() -> dict:
    """A real, ~1s silent mp3, generated at test time via ffmpeg's `lavfi`
    silence source.

    Mirrors `backend/tests/integration/conftest.py`'s `tiny_audio_bytes`
    fixture and exists for the same reason: the worker's Phase 5 pipeline
    runs real ffprobe/ffmpeg on whatever gets uploaded (`worker/audio.py`),
    so a fake byte string fails ffprobe and the episode ends up `failed`,
    not `review` — this suite needs the episode to actually reach `review`
    to test the edit/publish flow. Generated instead of committed as a
    binary fixture for the same reason the backend suite does: a one-line
    ffmpeg invocation is smaller and more obviously correct than a
    checked-in binary nobody can diff. `e2e/Dockerfile` installs ffmpeg for
    exactly this fixture.

    Returned as the dict shape Playwright's `set_input_files` accepts
    (`name`/`mimeType`/`buffer`) instead of a file path — the file only
    ever exists as in-memory bytes, no temp file, no cleanup to worry
    about.
    """
    # 3s, not the backend suite's 1s: the seek assertion in
    # test_episode_flow.py needs enough duration to seek *into* (seeking to
    # 1.5s only means something if the clip is longer than that).
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=8000:cl=mono",
            "-t",
            "3",
            "-q:a",
            "9",
            "-f",
            "mp3",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    )
    return {
        "name": "e2e-episode.mp3",
        "mimeType": "audio/mpeg",
        "buffer": result.stdout,
    }
