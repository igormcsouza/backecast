"""OpenAI transcription — Phase 5's `processing -> transcribing` work.

Cost (CLAUDE.md guardrail — state the cost before creating anything
billable): `gpt-4o-mini-transcribe` is priced at roughly $0.003/minute of
audio, i.e. about $0.18 for a full hour-long episode. Its higher-quality
sibling `gpt-4o-transcribe` costs roughly 2x that — a straightforward
quality-upgrade path (just change TRANSCRIBE_MODEL) if transcript quality
ever becomes the bottleneck, not something this MVP needs yet.

AI_STUB (settings.ai_stub, from the AI_STUB env var): when set, this module
never touches the network — no SSM read for the API key, no OpenAI call —
and returns a canned transcript string instead. Local dev
(`docker compose up`) and the automated test suite always run with
AI_STUB=1 so neither one can accidentally spend real money or need network
egress. Everything *downstream* of this function (writing the transcript to
S3, the LangChain metadata chain, the DynamoDB write) still runs for real
against the canned value — only this one network call is swapped out.
"""

from __future__ import annotations

import boto3
from botocore.config import Config
from openai import OpenAI

from app.core.settings import get_settings

settings = get_settings()

TRANSCRIBE_MODEL = "gpt-4o-mini-transcribe"

_STUB_TRANSCRIPT = (
    "This is a stubbed transcript, returned because AI_STUB=1. It stands in "
    "for a real OpenAI gpt-4o-mini-transcribe response so the rest of the "
    "pipeline — writing the transcript to S3, the LangChain metadata chain, "
    "and the final DynamoDB write — can be exercised end to end without "
    "spending real money or requiring network access to OpenAI."
)

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


def transcribe_audio(path: str) -> str:
    """Transcribe a local (already ffmpeg-preprocessed) audio file.

    Returns the transcript text. Under AI_STUB=1, returns the canned
    transcript without reading the file, hitting SSM, or calling OpenAI.
    """
    if settings.ai_stub:
        return _STUB_TRANSCRIPT

    client = _get_client()
    with open(path, "rb") as f:
        result = client.audio.transcriptions.create(model=TRANSCRIBE_MODEL, file=f)
    return result.text
