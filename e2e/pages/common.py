"""Shared locators used by more than one page object.

Kept as a plain function, not a base class — these page objects are thin
enough that a shared-attribute hierarchy would be more ceremony than the
one locator it'd save.
"""

from __future__ import annotations

from playwright.sync_api import Locator, Page


def audio_player(page: Page) -> Locator:
    return page.locator("audio")
