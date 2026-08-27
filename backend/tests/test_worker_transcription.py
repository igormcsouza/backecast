"""Unit tests for worker/transcription.py.

AI_STUB=1 is set globally (backend/tests/conftest.py) — these tests confirm
the stub path never touches SSM or the OpenAI client, and (via monkeypatch)
that the real path would if AI_STUB were off.
"""

from unittest.mock import MagicMock

from worker import transcription


def test_stub_path_returns_canned_transcript_without_ssm_or_openai(monkeypatch):
    monkeypatch.setattr(transcription.settings, "ai_stub", True)

    def _fail(*args, **kwargs):
        raise AssertionError("must not touch SSM or OpenAI when AI_STUB=1")

    monkeypatch.setattr(transcription._ssm, "get_parameter", _fail)

    result = transcription.transcribe_audio("/tmp/unused.m4a")

    assert result == transcription._STUB_TRANSCRIPT


def test_non_stub_path_fetches_key_from_ssm_and_calls_openai(monkeypatch, tmp_path):
    monkeypatch.setattr(transcription.settings, "ai_stub", False)
    monkeypatch.setattr(transcription, "_openai_client", None)

    monkeypatch.setattr(
        transcription._ssm,
        "get_parameter",
        lambda Name, WithDecryption: {"Parameter": {"Value": "sk-fake"}},
    )

    fake_segment = MagicMock(text=" real transcript. ", start=0.0, end=2.0)
    fake_word = MagicMock(word="real", start=0.0, end=0.5)
    fake_client = MagicMock()
    fake_client.audio.transcriptions.create.return_value = MagicMock(
        text="real transcript.",
        segments=[fake_segment],
        words=[fake_word],
    )
    monkeypatch.setattr(transcription, "OpenAI", lambda api_key: fake_client)

    audio_file = tmp_path / "audio.m4a"
    audio_file.write_bytes(b"fake-audio-bytes")

    result = transcription.transcribe_audio(str(audio_file))

    assert result == {
        "text": "real transcript.",
        "segments": [
            {
                "text": "real transcript.",
                "start": 0.0,
                "end": 2.0,
                "words": [{"word": "real", "start": 0.0, "end": 0.5}],
            }
        ],
    }
    # Cached for the next call within the same (warm) container.
    assert transcription._openai_client is fake_client
