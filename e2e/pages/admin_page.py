"""Page object for /admin — login gate, upload form, status poller, review queue.

Deliberately thin: this is a handful of pages behind one shared layout, not
a large app, so one small class per page (locators + the couple of actions
a test actually performs) is enough structure. A heavier Page Object Model
(explicit result objects, chained builders, etc.) would just be
indirection a two-person project has to maintain for no real benefit — see
CLAUDE.md's "don't gold-plate" guidance.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect


class AdminPage:
    def __init__(self, page: Page) -> None:
        self.page = page

    def goto(self) -> None:
        self.page.goto("/admin")

    # --- Login gate ---------------------------------------------------

    def login(self, username: str, password: str) -> None:
        self.page.get_by_placeholder("Username").fill(username)
        self.page.get_by_placeholder("Password").fill(password)
        self.page.get_by_role("button", name="Sign in").click()

    def expect_signed_in(self) -> None:
        expect(self.page.get_by_role("heading", name="Admin")).to_be_visible()

    def expect_login_error(self, message: str) -> None:
        expect(self.page.get_by_text(message)).to_be_visible()

    # --- Upload ---------------------------------------------------------

    def upload(self, file: dict) -> str:
        """Uploads `file` and returns the new episode's id.

        Captures the id from the real `POST /api/v1/episodes` response
        (`page.expect_response`) rather than scraping it out of the DOM
        afterwards — the review queue can (and, once this suite has run
        more than once against the same LocalStack volume, does) contain
        other episodes with the exact same stubbed title, so the id is the
        only thing that reliably identifies *this* upload later.
        """
        with self.page.expect_response(
            lambda r: r.request.method == "POST"
            and r.url.endswith("/api/v1/episodes")
        ) as response_info:
            self.page.locator('input[type="file"]').set_input_files(file)
        return response_info.value.json()["id"]

    def _review_link(self, episode_id: str):
        return self.page.locator(f'a[href="/admin/review?id={episode_id}"]')

    def wait_for_review_ready(self, episode_id: str, timeout_ms: int = 120_000) -> None:
        """Waits for `episode_id` to land in the review queue list.

        Note (a real bug found while writing this suite, not fixed here —
        see SESSIONS.md): app/admin/page.tsx's `UploadStatus` component
        calls its `onDone()` callback the instant the polled status leaves
        `IN_FLIGHT_STATUSES` — which unmounts `UploadStatus` (and clears
        `activeUploadId`) in the same tick that status becomes `review`, so
        its own "Review now" link is dead code: it can never actually
        render before the component that would show it disappears.
        `onDone()`'s `refreshQueue()` call is what actually surfaces the
        episode next, in the review-queue list below — that's the
        reachable path this fixture waits on instead.

        The real Phase 5 pipeline (S3 -> SQS -> worker -> ffmpeg -> AI_STUB
        transcription -> AI_STUB metadata -> DynamoDB) runs underneath this
        wait; the timeout is generous because it depends on the worker's
        own poll interval (WORKER_POLL_WAIT_SECONDS) too, not just
        page-side polling.
        """
        expect(self._review_link(episode_id)).to_be_visible(timeout=timeout_ms)

    def open_review(self, episode_id: str) -> None:
        self._review_link(episode_id).click()
