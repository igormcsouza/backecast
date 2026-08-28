"""Page objects for the public, unauthenticated pages: / and /episode?id=..."""

from __future__ import annotations

from playwright.sync_api import Page, expect

from pages.common import audio_player


class PublicHomePage:
    def __init__(self, page: Page) -> None:
        self.page = page

    def goto(self) -> None:
        self.page.goto("/")

    def episode_link(self, title: str):
        return self.page.get_by_role("link", name=title)

    def expect_episode_visible(self, title: str) -> None:
        expect(self.episode_link(title)).to_be_visible()

    def expect_episode_not_present(self, title: str) -> None:
        # The public list is fetched client-side after mount (see
        # app/page.tsx's useEffect), so right after goto() the list is
        # still empty and `episode_link(title)` already has count 0 —
        # a negative to_have_count(0) assertion would pass trivially
        # without ever proving the fetch actually resolved and still
        # excluded this episode. Synchronize on the loading indicator
        # going away first, so the count-0 check below runs against the
        # real, loaded list.
        expect(self.page.get_by_text("Loading episodes…")).to_have_count(0)
        expect(self.episode_link(title)).to_have_count(0)

    def open_episode(self, title: str) -> None:
        self.episode_link(title).click()

    def search_input(self):
        return self.page.get_by_placeholder("Search episodes…")

    def search(self, term: str) -> None:
        self.search_input().fill(term)


class PublicEpisodePage:
    def __init__(self, page: Page) -> None:
        self.page = page

    def goto(self, episode_id: str) -> None:
        self.page.goto(f"/episode?id={episode_id}")

    def audio_player(self):
        return audio_player(self.page)

    def expect_not_found(self) -> None:
        expect(self.page.get_by_text("Episode not found.")).to_be_visible()
