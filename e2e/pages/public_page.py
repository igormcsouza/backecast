"""Page objects for the public, unauthenticated pages: / and /episode?id=..."""

from __future__ import annotations

from playwright.sync_api import Page, expect


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
        expect(self.episode_link(title)).to_have_count(0)

    def open_episode(self, title: str) -> None:
        self.episode_link(title).click()


class PublicEpisodePage:
    def __init__(self, page: Page) -> None:
        self.page = page

    def goto(self, episode_id: str) -> None:
        self.page.goto(f"/episode?id={episode_id}")

    def audio_player(self):
        return self.page.locator("audio")

    def expect_not_found(self) -> None:
        expect(self.page.get_by_text("Episode not found.")).to_be_visible()
