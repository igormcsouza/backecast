"""OpenAI transcription — Phase 5's `processing -> transcribing` work.

Cost (CLAUDE.md guardrail — state the cost before creating anything
billable): `whisper-1` is priced at roughly $0.006/minute of audio, i.e.
about $0.36 for a full hour-long episode. This is 2x `gpt-4o-mini-
transcribe`'s $0.003/min, deliberately paid (see GitHub issue #15) because
that cheaper model has a hard 2,000-output-token cap that silently
truncates any episode over ~10-12 minutes mid-sentence — `whisper-1` is
purpose-built for long-form audio and has no such ceiling.

`whisper-1` is also the only OpenAI transcription model that supports
`response_format="verbose_json"` with word-level timestamps
(`timestamp_granularities=["segment", "word"]`) — required for the
frontend's karaoke-style word highlighting during playback
(`frontend/app/episode/page.tsx`'s `TranscriptDisclosure`). The structured
response (full text + segments + word timestamps) is what gets stored to
S3 by the worker, not just the plain text.

AI_STUB (settings.ai_stub, from the AI_STUB env var): when set, this module
never touches the network — no SSM read for the API key, no OpenAI call —
and returns a canned structured transcript instead. Local dev
(`docker compose up`) and the automated test suite always run with
AI_STUB=1 so neither one can accidentally spend real money or need network
egress. Everything *downstream* of this function (writing the transcript to
S3, the LangChain metadata chain, the DynamoDB write) still runs for real
against the canned value — only this one network call is swapped out.
"""

from __future__ import annotations

from typing import TypedDict

import boto3
from botocore.config import Config
from openai import OpenAI

from app.core.settings import get_settings

settings = get_settings()

TRANSCRIBE_MODEL = "whisper-1"


class TranscriptWord(TypedDict):
    word: str
    start: float
    end: float


class TranscriptSegment(TypedDict):
    text: str
    start: float
    end: float
    words: list[TranscriptWord]


class Transcript(TypedDict):
    text: str
    segments: list[TranscriptSegment]


_STUB_TRANSCRIPT: Transcript = {
    "text": (
        "This is a stubbed transcript, returned because AI_STUB=1. It stands "
        "in for a real OpenAI whisper-1 response so the rest of the "
        "pipeline can be exercised end to end without spending real money "
        "or requiring network access to OpenAI."
    ),
    "segments": [
        {
            "text": "This is a stubbed transcript, returned because AI_STUB=1.",
            "start": 0.0,
            "end": 3.0,
            "words": [
                {"word": "This", "start": 0.0, "end": 0.3},
                {"word": "is", "start": 0.3, "end": 0.5},
                {"word": "a", "start": 0.5, "end": 0.6},
                {"word": "stubbed", "start": 0.6, "end": 1.1},
                {"word": "transcript,", "start": 1.1, "end": 1.7},
                {"word": "returned", "start": 1.7, "end": 2.2},
                {"word": "because", "start": 2.2, "end": 2.6},
                {"word": "AI_STUB=1.", "start": 2.6, "end": 3.0},
            ],
        },
        {
            "text": (
                "It stands in for a real OpenAI whisper-1 response so the "
                "rest of the pipeline can be exercised end to end without "
                "spending real money or requiring network access to "
                "OpenAI."
            ),
            "start": 3.0,
            "end": 8.0,
            "words": [],
        },
    ],
}

# The SSM client is initialized at module level (Lambda best practice: pay
# the connection-setup cost once per cold start, reuse it across warm
# invocations) even though AI_STUB=1 never uses it — constructing a boto3
# client does no network I/O by itself, so this costs nothing when stubbed.
_ssm = boto3.client(
    "ssm",
    region_name=settings.aws_region,
    endpoint_url=settings.aws_endpoint_url,
    config=Config(connect_timeout=2, read_timeout=5, retries={"max_attempts": 1}),
)

# The OpenAI client itself can't be built at module level: it needs the API
# key, which has to come from an SSM read. Lazily built and cached at module
# scope on first real (non-stub) use — the same warm-container-reuse pattern
# app/core/auth.py uses for the admin key.
_openai_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        response = _ssm.get_parameter(
            Name=settings.openai_api_key_param_name, WithDecryption=True
        )
        _openai_client = OpenAI(api_key=response["Parameter"]["Value"])
    return _openai_client


def transcribe_audio(path: str) -> Transcript:
    """Transcribe a local (already ffmpeg-preprocessed) audio file.

    Returns the structured transcript (full text + segment/word timestamps).
    Under AI_STUB=1, returns the canned transcript without reading the
    file, hitting SSM, or calling OpenAI.
    """
    if settings.ai_stub:
        return _STUB_TRANSCRIPT

    client = _get_client()
    with open(path, "rb") as f:
        result = client.audio.transcriptions.create(
            model=TRANSCRIBE_MODEL,
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["segment", "word"],
        )

    words_by_segment: dict[int, list[TranscriptWord]] = {}
    for word in result.words or []:
        # verbose_json returns words as a flat list, not nested under their
        # segment — bucket them back onto the segment whose [start, end)
        # window contains the word so the frontend can render per-segment
        # word timestamps without re-deriving this alignment itself.
        for i, segment in enumerate(result.segments or []):
            if segment.start <= word.start < segment.end or (
                i == len(result.segments) - 1 and word.start <= segment.end
            ):
                words_by_segment.setdefault(i, []).append(
                    {"word": word.word, "start": word.start, "end": word.end}
                )
                break

    segments: list[TranscriptSegment] = [
        {
            "text": segment.text.strip(),
            "start": segment.start,
            "end": segment.end,
            "words": words_by_segment.get(i, []),
        }
        for i, segment in enumerate(result.segments or [])
    ]

    return {"text": result.text, "segments": segments}
