"""The real user journey from manual.md's Phase 7 spec, start to finish:

    admin uploads an episode -> AI (stubbed) metadata appears -> admin edits
    it -> admin publishes -> the episode is visible on the public page ->
    the audio player loads and seeks.

One flow test, not a dozen tiny ones, because every later step genuinely
depends on the state the previous step left behind (you can't publish an
episode that hasn't reached `review`, and you can't check the public page
without a real published episode) — splitting it up would just mean each
"test" silently re-running the same setup, or an awkward shared fixture
doing what this function already does step by step. `test_admin_login.py`
and `test_public_page.py` carry the parts that genuinely stand alone.

This is also the only test in the suite that exercises the *real* Phase 5
pipeline underneath the browser (S3 upload -> SQS -> worker -> ffmpeg ->
AI_STUB transcription -> AI_STUB metadata -> DynamoDB `review`) — see
conftest.py's `tiny_audio_file` fixture docstring for why the upload has to
be a real, ffprobe-readable mp3, not arbitrary bytes.
"""

from __future__ import annotations

import re
import uuid

from playwright.sync_api import Page, expect

from pages.admin_page import AdminPage
from pages.public_page import PublicEpisodePage, PublicHomePage
from pages.review_page import ReviewPage

STUB_TITLE = "Stubbed Episode Title"


def test_upload_edit_publish_and_stream(
    page: Page, base_url: str, admin_key: str, tiny_audio_file: dict
) -> None:
    # A unique title so this run's episode is unambiguous even if earlier
    # runs left published episodes with the same stubbed default title
    # sitting in the shared LocalStack/DynamoDB volume.
    unique_title = f"E2E Episode {uuid.uuid4().hex[:8]}"

    # --- 1. Admin uploads an episode -----------------------------------
    admin = AdminPage(page)
    admin.goto()
    admin.login(admin_key)
    admin.expect_signed_in()

    episode_id = admin.upload(tiny_audio_file)
    # Real pipeline runs here: S3 event -> SQS -> worker -> ffmpeg preprocess
    # -> AI_STUB transcription -> AI_STUB metadata -> DynamoDB status=review.
    admin.wait_for_review_ready(episode_id)
    admin.open_review(episode_id)

    # --- 2. Stubbed AI metadata appears ---------------------------------
    review = ReviewPage(page)
    expect(review.title_input()).to_have_value(STUB_TITLE)
    expect(review.description_input()).not_to_have_value("")
    expect(review.audio_player()).to_have_count(1)

    # --- 3. Not visible publicly yet (still status=review) -------------
    public_detail = PublicEpisodePage(page)
    public_detail.goto(episode_id)
    public_detail.expect_not_found()

    # --- 4. Admin edits the metadata -------------------------------------
    review_url = f"{base_url}/admin/review?id={episode_id}"
    page.goto(review_url)
    review.set_title(unique_title)
    review.save()

    # Editing doesn't publish — still unreachable on the public site.
    public_home = PublicHomePage(page)
    public_home.goto()
    public_home.expect_episode_not_present(unique_title)

    # --- 5. Admin publishes ----------------------------------------------
    page.goto(review_url)
    review.publish()

    # --- 6. Episode visible on the public page ---------------------------
    public_home.goto()
    public_home.expect_episode_visible(unique_title)
    public_home.open_episode(unique_title)

    expect(page).to_have_url(re.compile(rf"episode\?id={episode_id}"))

    # --- 7. Player loads and seeks ---------------------------------------
    # The presigned S3 GET URL is what makes seeking work at all (S3 serves
    # byte-range requests on it with no extra config — see SESSIONS.md
    # Session 7's "Streaming: presigned GET, not CloudFront" decision).
    # Setting `currentTime` directly and reading it back afterward proves
    # the browser accepted a *real* seek against that URL (a byte-range
    # request the audio element made itself), not just that the tag exists.
    audio = public_detail.audio_player()
    expect(audio).to_be_visible()
    expect(audio).to_have_attribute("src", re.compile(r"^https?://"))

    # Wait for metadata (duration, seekable range) before attempting a seek.
    page.wait_for_function(
        "() => { const a = document.querySelector('audio'); "
        "return a && a.readyState >= 1 && a.duration > 0; }",
        timeout=15_000,
    )
    duration = audio.evaluate("el => el.duration")
    assert duration > 1, f"expected a multi-second clip, got duration={duration}"

    seek_target = min(1.5, duration / 2)
    audio.evaluate(f"el => {{ el.currentTime = {seek_target}; }}")
    page.wait_for_function(
        f"() => document.querySelector('audio').currentTime >= {seek_target - 0.25}",
        timeout=5_000,
    )
    current_time = audio.evaluate("el => el.currentTime")
    assert current_time >= seek_target - 0.25, (
        f"seek did not take effect: currentTime={current_time}, "
        f"expected >= {seek_target - 0.25}"
    )
