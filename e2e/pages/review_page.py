"""Page object for /admin/review?id=... — edit AI-generated metadata, publish."""

from __future__ import annotations

from playwright.sync_api import Page, expect

from pages.common import audio_player


class ReviewPage:
    def __init__(self, page: Page) -> None:
        self.page = page

    def title_input(self):
        return self.page.get_by_label("Title")

    def description_input(self):
        return self.page.get_by_label("Description")

    def set_title(self, title: str) -> None:
        self.title_input().fill(title)

    def save(self) -> None:
        self.page.get_by_role("button", name="Save changes").click()
        expect(self.page.get_by_text("Saved.")).to_be_visible()

    def publish(self) -> None:
        self.page.get_by_role("button", name="Publish").click()
        expect(self.page.get_by_text("Published.")).to_be_visible()

    def audio_player(self):
        return audio_player(self.page)
