"""Unit tests for worker/metadata.py.

AI_STUB=1 is set globally (conftest.py). These tests cover the stub path
(never touches SSM or an LLM), the provider-swap seam (settings.llm_model
drives init_chat_model, never a hardcoded provider), and the Phase 5
mandatory sabotage exercise (an invalid resource shape must fail Pydantic
validation, not silently persist).
"""

import pydantic
import pytest
from langchain_core.runnables import RunnableLambda

from app.episodes.schemas import EpisodeMetadata
from worker import metadata


def test_stub_path_returns_valid_metadata_without_ssm(monkeypatch):
    monkeypatch.setattr(metadata.settings, "ai_stub", True)
    monkeypatch.setattr(metadata, "SABOTAGE_INVALID_METADATA", False)

    def _fail(*args, **kwargs):
        raise AssertionError("must not touch SSM when AI_STUB=1")

    monkeypatch.setattr(metadata._ssm, "get_parameter", _fail)

    result = metadata.generate_metadata("some transcript")

    assert isinstance(result, EpisodeMetadata)
    assert result.title == "Stubbed Episode Title"
    assert str(result.resources[0].url) == "https://example.com/resource"


def test_sabotage_flag_makes_the_stub_return_an_invalid_resource_shape(monkeypatch):
    """The mandatory Phase 5 sabotage exercise: a malformed resource URL
    must be rejected by Pydantic before it ever reaches DynamoDB."""
    monkeypatch.setattr(metadata.settings, "ai_stub", True)
    monkeypatch.setattr(metadata, "SABOTAGE_INVALID_METADATA", True)

    with pytest.raises(pydantic.ValidationError):
        metadata.generate_metadata("some transcript")


def test_non_stub_path_builds_chain_from_settings_llm_model(monkeypatch):
    """Provider-swap seam: init_chat_model() is called with whatever
    settings.llm_model says (a "<provider>:<model>" string) — this file
    never imports ChatOpenAI/ChatAnthropic directly, so swapping providers
    is an env var change, not a code change."""
    monkeypatch.setattr(metadata.settings, "ai_stub", False)
    monkeypatch.setattr(
        metadata.settings, "llm_model", "anthropic:claude-3-5-haiku-latest"
    )
    monkeypatch.setattr(metadata, "_chain", None)
    monkeypatch.setattr(
        metadata._ssm,
        "get_parameter",
        lambda Name, WithDecryption: {"Parameter": {"Value": "sk-fake"}},
    )

    captured = {}

    class FakeModel:
        def with_structured_output(self, schema):
            captured["schema"] = schema
            # A real Runnable (not a hand-rolled __or__/__ror__ stand-in) so
            # it composes correctly with the real ChatPromptTemplate via `|`.
            return RunnableLambda(
                lambda _messages: EpisodeMetadata(
                    title="t", description="d", resources=[]
                )
            )

    def _fake_init_chat_model(*, model, api_key):
        captured["model"] = model
        captured["api_key"] = api_key
        return FakeModel()

    monkeypatch.setattr(metadata, "init_chat_model", _fake_init_chat_model)

    result = metadata.generate_metadata("a transcript")

    assert captured["model"] == "anthropic:claude-3-5-haiku-latest"
    assert captured["api_key"] == "sk-fake"
    assert isinstance(result, EpisodeMetadata)
