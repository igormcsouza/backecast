"""Unit tests for worker/audio.py — subprocess calls are mocked, no real
ffmpeg/ffprobe binary required (the docker-compose integration test proves
the real binaries work; this file proves the Python wrapper's logic).
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from worker import audio


def test_probe_duration_seconds_parses_ffprobe_json():
    fake_result = MagicMock(stdout=json.dumps({"format": {"duration": "125.5"}}))
    with patch("subprocess.run", return_value=fake_result) as mock_run:
        duration = audio.probe_duration_seconds("/tmp/some-file.mp3")

    assert duration == 125.5
    args = mock_run.call_args.args[0]
    assert args[0] == "ffprobe"
    assert "/tmp/some-file.mp3" in args


def test_transcode_to_compressed_mono_invokes_ffmpeg_with_mono_and_bitrate():
    with patch("subprocess.run") as mock_run:
        audio.transcode_to_compressed_mono("/tmp/src.mp3", "/tmp/dst.m4a")

    args = mock_run.call_args.args[0]
    assert args[0] == "ffmpeg"
    assert "/tmp/src.mp3" in args
    assert "/tmp/dst.m4a" in args
    assert "-ac" in args and args[args.index("-ac") + 1] == "1"
    assert "-b:a" in args and args[args.index("-b:a") + 1] == "32k"


def test_preprocess_rejects_over_cap_without_transcoding():
    fake_probe_result = MagicMock(stdout=json.dumps({"format": {"duration": "2000"}}))
    with patch("subprocess.run", return_value=fake_probe_result) as mock_run:
        with pytest.raises(audio.EpisodeTooLongError) as exc_info:
            audio.preprocess("/tmp/src.mp3", "/tmp/dst.m4a", max_duration_seconds=1500)

    assert exc_info.value.duration_seconds == 2000.0
    assert exc_info.value.cap_seconds == 1500
    # Only ffprobe ran — no ffmpeg transcode call for a rejected episode.
    assert mock_run.call_count == 1
    assert mock_run.call_args.args[0][0] == "ffprobe"


def test_preprocess_transcodes_when_under_cap():
    probe_result = MagicMock(stdout=json.dumps({"format": {"duration": "300"}}))
    with patch("subprocess.run", return_value=probe_result) as mock_run:
        audio.preprocess("/tmp/src.mp3", "/tmp/dst.m4a", max_duration_seconds=1500)

    assert mock_run.call_count == 2
    assert mock_run.call_args_list[0].args[0][0] == "ffprobe"
    assert mock_run.call_args_list[1].args[0][0] == "ffmpeg"


def test_cleanup_removes_existing_files_and_ignores_missing(tmp_path):
    present = tmp_path / "present.tmp"
    present.write_text("x")
    missing = tmp_path / "missing.tmp"

    audio.cleanup(str(present), str(missing), "", None)

    assert not present.exists()
