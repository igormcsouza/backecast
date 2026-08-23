"""Covers the admin login gate in isolation (app/admin/page.tsx's
AdminPage component) — a wrong key must never reach the dashboard, and a
correct key must.

Kept separate from the full journey test (test_episode_flow.py) so a
regression in auth shows up as its own small, fast failure instead of
being buried inside a multi-minute end-to-end run.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect

from pages.admin_page import AdminPage


def test_wrong_admin_key_is_rejected(page: Page, base_url: str) -> None:
    admin = AdminPage(page)
    admin.goto()
    admin.login("definitely-not-the-admin-key")
    admin.expect_login_error("Invalid admin key.")
    # Still on the sign-in form, not the dashboard.
    expect(page.get_by_role("heading", name="Admin sign in")).to_be_visible()


def test_correct_admin_key_reaches_dashboard(
    page: Page, base_url: str, admin_key: str
) -> None:
    admin = AdminPage(page)
    admin.goto()
    admin.login(admin_key)
    admin.expect_signed_in()
    # The dashboard's "Sign out" control is the clearest marker that the
    # login gate actually opened, not just that no error rendered.
    expect(page.get_by_role("button", name="Sign out")).to_be_visible()
