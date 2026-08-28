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

import re
import uuid

from playwright.sync_api import Page, expect

from pages.admin_page import AdminPage
from pages.public_page import PublicEpisodePage, PublicHomePage
from pages.review_page import ReviewPage


def test_public_home_page_loads(page: Page, base_url: str) -> None:
    home = PublicHomePage(page)
    home.goto()
    # Doesn't assert on episode content (that depends on what else has
    # published in this run) — just that the shell renders without error.
    expect(page.get_by_role("heading", name="Episodes")).to_be_visible()


def test_unknown_episode_id_is_not_found(page: Page, base_url: str) -> None:
    detail = PublicEpisodePage(page)
    detail.goto("00000000-0000-0000-0000-000000000000")
    detail.expect_not_found()


def _publish_episode(
    page: Page, admin_credentials: tuple[str, str], tiny_audio_file: dict, title: str
) -> None:
    """Runs a real episode through upload -> review -> publish so it lands
    on the public page, per test_episode_flow.py's pattern."""
    admin = AdminPage(page)
    admin.goto()
    admin.login(*admin_credentials)
    admin.expect_signed_in()

    episode_id = admin.upload(tiny_audio_file)
    admin.wait_for_review_ready(episode_id)
    admin.open_review(episode_id)

    review = ReviewPage(page)
    # `open_review`'s click triggers client-side navigation; a bare `.fill()`
    # right after can catch the review page mid-transition and hit the
    # *admin* page's file input instead (a hard, non-retryable "Input of
    # type file cannot be filled" error, not a friendly timeout — see
    # test_episode_flow.py's equivalent wait). `audio_player()` doesn't prove
    # navigation happened (MiniPlayer mounts a persistent <audio> tag on
    # every route), so wait on the URL itself instead.
    expect(page).to_have_url(re.compile(r"/admin/review\?id="))
    review.set_title(title)
    review.save()
    review.publish()


def test_search_filters_public_episode_list(
    page: Page, base_url: str, admin_credentials: tuple[str, str], tiny_audio_file: dict
) -> None:
    unique_suffix = uuid.uuid4().hex[:8]
    alpha_title = f"Searchable {unique_suffix} Alpha"
    bravo_title = f"Searchable {unique_suffix} Bravo"

    _publish_episode(page, admin_credentials, tiny_audio_file, alpha_title)
    _publish_episode(page, admin_credentials, tiny_audio_file, bravo_title)

    home = PublicHomePage(page)
    home.goto()
    home.expect_episode_visible(alpha_title)
    home.expect_episode_visible(bravo_title)

    home.search("Alpha")
    home.expect_episode_visible(alpha_title)
    home.expect_episode_not_present(bravo_title)

    home.search("")
    home.expect_episode_visible(alpha_title)
    home.expect_episode_visible(bravo_title)
