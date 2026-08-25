"""LangChain metadata chain — Phase 5's `transcribing -> generating` work.

LangChain is used ONLY here (per CLAUDE.md / manual.md §5: never as a
general wrapper anywhere else in the codebase). Its payoff for this one step
is `.with_structured_output()`: it turns an LLM's free-text response into a
validated Pydantic instance (`EpisodeMetadata`, from
app/episodes/schemas.py), using the provider's native structured-output /
tool-calling support so "did the model actually return the shape we asked
for" is enforced by Pydantic, not by hand-rolled JSON parsing.

Cost (CLAUDE.md guardrail): a full episode transcript is roughly
4,000-6,000 tokens for a 25-minute episode, plus a short system prompt and a
small structured JSON response (well under a thousand tokens). At
gpt-4o-mini's per-token pricing that's on the order of a fraction of a cent
per episode — negligible next to the ~$0.18/hour transcription cost, but
worth naming explicitly before flipping AI_STUB off against real infra.

Provider swap seam: `settings.llm_model` is a "<provider>:<model>" string
(e.g. "openai:gpt-4o-mini" or "anthropic:claude-3-5-haiku-latest") passed
straight into LangChain's `init_chat_model()`, which resolves the right
chat-model class from the prefix. Swapping providers is an env var change
(LLM_MODEL, read via Settings), never a code change in this file — nothing
here imports a provider-specific class.

AI_STUB (settings.ai_stub): short-circuits before any SSM read or LLM call
and returns a canned metadata payload instead — run through the *same*
`EpisodeMetadata` Pydantic validation a real LLM response would go through,
so the rest of the pipeline (DynamoDB write) is exercised for real. See
SABOTAGE_INVALID_METADATA below for how this module also drives the
Phase 5 mandatory sabotage exercise.
"""

from __future__ import annotations

import os

import boto3
from botocore.config import Config
from langchain.chat_models import init_chat_model
from langchain_core.prompts import ChatPromptTemplate

from app.core.settings import get_settings
from app.episodes.schemas import EpisodeMetadata

settings = get_settings()

_ssm = boto3.client(
    "ssm",
    region_name=settings.aws_region,
    endpoint_url=settings.aws_endpoint_url,
    config=Config(connect_timeout=2, read_timeout=5, retries={"max_attempts": 1}),
)

_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are producing publish-ready metadata for a podcast episode "
            "from its transcript. Write a concise, engaging title (at most "
            "12 words) and a one-to-two sentence description. List any "
            "resources (tools, books, links, people) explicitly mentioned "
            "in the transcript with a real, well-formed http(s) URL for "
            "each; if none are mentioned, return an empty list rather than "
            "inventing one.",
        ),
        ("human", "Transcript:\n\n{transcript}"),
    ]
)

# --- Sabotage hook (Phase 5 mandatory exercise) -----------------------------
# WORKER_SABOTAGE_INVALID_METADATA=1 (default off, same pattern as the
# Phase 4 WORKER_SABOTAGE_* toggles in worker/handler.py): makes the stub
# path return a resource with a malformed URL instead of a valid one, so the
# exercise can be run for real against docker-compose (AI_STUB=1, so no real
# LLM involved) instead of a throwaway script. See SESSIONS.md for what was
# observed running it.
SABOTAGE_INVALID_METADATA = os.environ.get("WORKER_SABOTAGE_INVALID_METADATA") == "1"

_STUB_METADATA_VALID = {
    "title": "Stubbed Episode Title",
    "description": (
        "A stubbed description, returned because AI_STUB=1. It stands in "
        "for a real LangChain metadata-chain response so the rest of the "
        "pipeline (Pydantic validation, DynamoDB write) can be exercised "
        "end to end without spending real money."
    ),
    "resources": [{"label": "Example Resource", "url": "https://example.com/resource"}],
}

# Sabotage payload: a resource whose "url" isn't a URL at all (no scheme,
# no host) — the shape `EpisodeMetadata`/`Resource` (app/episodes/schemas.py)
# must reject via Pydantic's `HttpUrl` type before anything is persisted.
_STUB_METADATA_INVALID_SHAPE = {
    "title": "Stubbed Episode Title",
    "description": "Same stub description, but with a broken resource link.",
    "resources": [{"label": "Broken Resource", "url": "not-a-url"}],
}

_chain = None


def _get_chain():
    global _chain
    if _chain is None:
        response = _ssm.get_parameter(
            Name=settings.llm_api_key_param_name, WithDecryption=True
        )
        model = init_chat_model(
            model=settings.llm_model, api_key=response["Parameter"]["Value"]
        )
        # method="function_calling", not the (default) strict json_schema
        # mode: `Resource.url` is a Pydantic `HttpUrl`, which serializes to
        # a JSON Schema `{"type": "string", "format": "uri"}` — OpenAI's
        # strict structured-output mode rejects `format: uri` outright
        # ("'uri' is not a valid format"). function-calling mode validates
        # the *response* against the same Pydantic model (still real
        # validation, still raises on a malformed URL — see
        # SABOTAGE_INVALID_METADATA below) without asking OpenAI's stricter
        # schema-compilation step to accept a format keyword it doesn't
        # support.
        _chain = _PROMPT | model.with_structured_output(
            EpisodeMetadata, method="function_calling"
        )
    return _chain


def generate_metadata(transcript: str) -> EpisodeMetadata:
    """Turn a transcript into a validated title/description/resources.

    Under AI_STUB=1, validates a canned payload through the real
    `EpisodeMetadata` model instead of calling an LLM — including, when
    WORKER_SABOTAGE_INVALID_METADATA=1, a deliberately malformed one, so
    `EpisodeMetadata.model_validate()` raises `pydantic.ValidationError`
    exactly as it would for a real LLM response that didn't respect the
    schema. The caller (worker/handler.py) doesn't special-case this at
    all — it just sees generate_metadata() raise, same as any other failure
    in this stage, and reacts the same way (status=failed, re-raise for
    SQS to retry / eventually DLQ).
    """
    if settings.ai_stub:
        raw = (
            _STUB_METADATA_INVALID_SHAPE
            if SABOTAGE_INVALID_METADATA
            else _STUB_METADATA_VALID
        )
        return EpisodeMetadata.model_validate(raw)

    chain = _get_chain()
    return chain.invoke({"transcript": transcript})
