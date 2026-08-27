"""ffmpeg preprocessing: shrink the raw upload to something OpenAI can eat whole.

Why this step exists at all: OpenAI's transcription endpoint caps input at
25MB and (in practice, at typical podcast bitrates) around 25 minutes.
Podcast uploads arrive as high-bitrate stereo mp3/m4a — easily 50-100MB for
an hour of audio — which blows straight past that. Re-encoding to a
low-bitrate MONO track (32kbps AAC/.m4a here) shrinks a 25-minute episode to
roughly 6MB, comfortably inside the cap. That means the pipeline never has
to *chunk* long audio into multiple transcription calls and stitch the
partial transcripts back together — the standard approach real pipelines
use for content that can't be shrunk under the limit, and meaningfully more
complex (aligning timestamps, deduping overlaps) than this MVP needs.

Why ffmpeg specifically, and why it forces the worker Lambda to ship as a
**container image** instead of a zip (see infra/stacks/pipeline_stack.py /
backend/worker/Dockerfile): ffmpeg is a native binary with its own shared
library dependencies, not a Python package `uv add` can install. A zip-based
Lambda deployment *can* bundle native binaries via a Lambda Layer, but
layers have their own size ceiling and are an awkward fit for a binary this
size — a container image (up to 10GB) just installs ffmpeg like any Linux
box would, no separate layer-publishing step to manage.

Implemented as two plain `subprocess` calls (`ffprobe` for duration,
`ffmpeg` for the transcode) rather than the `ffmpeg-python` package —
subprocess is simpler for two straightforward command invocations, and this
module doesn't need `ffmpeg-python`'s fluent filter-graph API.
"""

from __future__ import annotations

import json
import os
import subprocess

DEFAULT_MAX_DURATION_SECONDS = 25 * 60

# Bitrate/channel choice: 32kbps mono is comfortably intelligible for speech
# (this isn't music) and is what gets a 25-minute episode down to ~6MB.
_TARGET_AUDIO_BITRATE = "32k"


class EpisodeTooLongError(Exception):
    """Raised when the source audio exceeds the transcription duration cap."""

    def __init__(self, duration_seconds: float, cap_seconds: int) -> None:
        self.duration_seconds = duration_seconds
        self.cap_seconds = cap_seconds
        super().__init__(
            f"duration {duration_seconds:.1f}s exceeds cap of {cap_seconds}s"
        )


def probe_duration_seconds(path: str) -> float:
    """Read the audio duration via ffprobe, without decoding/transcoding anything.

    Run *before* any transcoding: if the episode is going to be rejected for
    being too long, we want to know that from the cheapest possible check,
    before spending any ffmpeg CPU time on a transcode nobody will use.
    """
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            path,
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def transcode_to_compressed_mono(src_path: str, dst_path: str) -> None:
    """Re-encode `src_path` to a 32kbps mono AAC (.m4a) file at `dst_path`."""
    subprocess.run(
        [
            "ffmpeg",
            "-y",  # overwrite dst_path if a previous attempt left one behind
            "-i",
            src_path,
            "-ac",
            "1",  # mono
            "-b:a",
            _TARGET_AUDIO_BITRATE,
            "-vn",  # no video/album-art stream, audio only
            dst_path,
        ],
        capture_output=True,
        check=True,
        timeout=240,
    )


def preprocess(
    src_path: str,
    dst_path: str,
    max_duration_seconds: int = DEFAULT_MAX_DURATION_SECONDS,
) -> float:
    """Validate duration then transcode `src_path` into `dst_path` in place.

    Raises EpisodeTooLongError (and never touches ffmpeg) if the source
    exceeds `max_duration_seconds`.
    """
    duration = probe_duration_seconds(src_path)
    if duration > max_duration_seconds:
        raise EpisodeTooLongError(duration, max_duration_seconds)
    transcode_to_compressed_mono(src_path, dst_path)
    return duration


def cleanup(*paths: str) -> None:
    """Best-effort removal of temp files — /tmp is container-local and finite."""
    for path in paths:
        if path and os.path.exists(path):
            os.remove(path)
