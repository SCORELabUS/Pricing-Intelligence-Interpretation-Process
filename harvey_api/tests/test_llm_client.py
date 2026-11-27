from __future__ import annotations

from typing import Any

import pytest

from harvey_api import llm_client
from harvey_api.llm_client import OpenAIClient, OpenAIClientConfig


class RecordingOpenAI:
    calls: list[dict[str, Any]] = []

    def __init__(self, **kwargs: Any) -> None:
        RecordingOpenAI.calls.append(kwargs)


@pytest.fixture(autouse=True)
def recording_openai(monkeypatch: pytest.MonkeyPatch):
    RecordingOpenAI.calls = []
    monkeypatch.setattr(llm_client, "OpenAI", RecordingOpenAI)


def test_passes_base_url_when_defined():
    OpenAIClient(
        OpenAIClientConfig(
            api_key="key", model="qwen3:32b", base_url="http://host.docker.internal:11434/v1"
        )
    )

    assert RecordingOpenAI.calls == [
        {"api_key": "key", "base_url": "http://host.docker.internal:11434/v1"}
    ]


def test_does_not_pass_base_url_when_none():
    OpenAIClient(OpenAIClientConfig(api_key="key", model="gpt-5-nano"))

    assert RecordingOpenAI.calls == [{"api_key": "key"}]
    assert "base_url" not in RecordingOpenAI.calls[0]
