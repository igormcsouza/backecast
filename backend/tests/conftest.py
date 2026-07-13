"""Shared pytest fixtures."""

import pytest

from app.shared.abstracts import RepositoryAbstract


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
