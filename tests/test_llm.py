import json

import httpx
import pytest

from api.app.config import get_settings
from api.app.schemas import Selection
from worker.pipeline.llm import LLMClient, LLMError
from worker.pipeline.media import demo_transcript
from worker.pipeline.planning import validate_selection


def variables():
    return {
        "sentences": [s.model_dump() for s in demo_transcript().sentences],
        "requested_count": 3,
        "max_clip_seconds": 60,
    }


@pytest.mark.parametrize("provider", ["gemini", "anthropic", "ollama"])
def test_provider_transport_schema_and_parsing(client, monkeypatch, provider):
    monkeypatch.setenv("LLM_PROVIDER", provider)
    monkeypatch.setenv("LLM_MODEL_FAST", "test-model")
    monkeypatch.setenv("GEMINI_API_KEY", "do-not-log")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "do-not-log")
    get_settings.cache_clear()
    payload = LLMClient._mock("select", variables())
    requests = []

    def respond(request):
        requests.append(request)
        body = json.loads(request.content)
        assert "untrusted data" in json.dumps(body)
        if provider == "gemini":
            assert "responseJsonSchema" in body["generationConfig"]
            assert "do-not-log" not in str(request.url)
            return httpx.Response(
                200,
                json={
                    "candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}],
                    "usageMetadata": {"promptTokenCount": 20},
                },
            )
        if provider == "anthropic":
            assert body["tool_choice"]["name"] == "structured_result"
            return httpx.Response(
                200,
                json={
                    "content": [
                        {"type": "tool_use", "name": "structured_result", "input": payload}
                    ],
                    "usage": {"input_tokens": 20},
                },
            )
        assert body["format"]["type"] == "object" and body["stream"] is False
        return httpx.Response(
            200, json={"message": {"content": json.dumps(payload)}, "prompt_eval_count": 20}
        )

    llm = LLMClient(transport=httpx.MockTransport(respond))
    result = llm.call_json("select", variables(), Selection)
    assert len(result.candidates) == 3 and len(requests) == 1
    assert llm.usage[0]["input_tokens"] == 20
    assert "do-not-log" not in json.dumps(llm.usage)


def test_invalid_json_repaired_once_and_transient_retried(client, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_MODEL_FAST", "test-model")
    monkeypatch.setattr("worker.pipeline.llm.time.sleep", lambda _: None)
    get_settings.cache_clear()
    count = 0

    def respond(_):
        nonlocal count
        count += 1
        if count == 1:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": "bad-json"
                    if count == 2
                    else json.dumps(LLMClient._mock("select", variables()))
                }
            },
        )

    llm = LLMClient(transport=httpx.MockTransport(respond))
    assert len(llm.call_json("select", variables(), Selection).candidates) == 3
    assert count == 3 and llm.usage[-1]["repair"]


def test_provider_errors_do_not_return_raw_response_or_key(client, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_MODEL_FAST", "test-model")
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    get_settings.cache_clear()
    llm = LLMClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(401, text="secret-token-and-provider-internals")
        )
    )
    with pytest.raises(LLMError, match="HTTP 401") as exc:
        llm.call_json("select", variables(), Selection)
    assert "secret" not in str(exc.value)


def test_invented_sentence_ids_never_reach_renderer(client):
    selection = Selection.model_validate(LLMClient._mock("select", variables()))
    selection.candidates[0].start_id = "s9999"
    with pytest.raises(ValueError, match="ID kalimat"):
        validate_selection(selection, demo_transcript(), 60, 3)
