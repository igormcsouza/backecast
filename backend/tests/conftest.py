"""Shared pytest fixtures."""

import os

import pytest

from app.shared.abstracts import RepositoryAbstract

# Set as soon as conftest.py executes — pytest fully imports every conftest.py
# before importing any test module, so this always runs before a test module
# (and, transitively, worker.transcription / worker.metadata, both of which
# read this via app.core.settings.get_settings() at *import* time) can import
# anything. Belt-and-suspenders with docker-compose's own AI_STUB=1 default:
# no automated test run, local or CI, may ever place a real network call to
# OpenAI or Anthropic. setdefault() so a test that explicitly wants to
# exercise the AI_STUB=0 code path (mocking the SDK client boundary itself,
# never a real network call) can still override it.
os.environ.setdefault("AI_STUB", "1")


class FakeRepository(RepositoryAbstract):
    """In-memory stand-in for a real repository — no AWS, no Docker."""

    def __init__(self, items: list[dict] | None = None) -> None:
        self.items = items or []

    async def list(self) -> list[dict]:
        return self.items


@pytest.fixture
def fake_repository_factory():
    """Returns a factory so each test can seed its own canned items."""

    def _factory(items: list[dict] | None = None) -> FakeRepository:
        return FakeRepository(items)

    return _factory
