"""Covers the public detail route's "never confirm an unpublished episode
exists" contract (app/episodes/service.py's `get_public_episode` 404s for
both a missing id *and* one that exists but isn't published).

A random, never-issued id is enough to exercise the "missing" half of that
contract without needing a running pipeline — the "exists but unpublished"
half is covered by test_episode_flow.py's mid-flow assertion (before the
episode is published, it isn't in the public list or reachable by id),
since that half genuinely needs a real in-flight episode to test against.
"""

from __future__ import annotations

from playwright.sync_api import Page

from pages.public_page import PublicEpisodePage, PublicHomePage


def test_public_home_page_loads(page: Page, base_url: str) -> None:
    home = PublicHomePage(page)
    home.goto()
    # Doesn't assert on episode content (that depends on what else has
    # published in this run) — just that the shell renders without error.
    from playwright.sync_api import expect

    expect(page.get_by_role("heading", name="Episodes")).to_be_visible()


def test_unknown_episode_id_is_not_found(page: Page, base_url: str) -> None:
    detail = PublicEpisodePage(page)
    detail.goto("00000000-0000-0000-0000-000000000000")
    detail.expect_not_found()
