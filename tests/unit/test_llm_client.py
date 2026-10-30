import json

import httpx
import pytest

from core import llm
from core.config import settings
from core.llm_types import LLMUnavailable

GROQ_OK = {"choices": [{"message": {"content": '{"metric": "total_revenue"}'}}], "usage": {"total_tokens": 123}}
GEMINI_OK = {
    "candidates": [{"content": {"parts": [{"text": '{"metric": "x"}'}]}}],
    "usageMetadata": {"totalTokenCount": 77},
}


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "groq-secret-key")
    monkeypatch.setattr(settings, "gemini_api_key", "gemini-secret-key")
    monkeypatch.setattr(settings, "groq_model", "openai/gpt-oss-120b")
    monkeypatch.setattr(settings, "gemini_model", "gemini-3.5-flash-lite")


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_groq_success_request_and_reply(keys):
    seen = {}

    def handler(request):
        seen["host"] = request.url.host
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=GROQ_OK)

    reply = llm.complete_json("SYS", "USER", client=client_for(handler))
    assert (reply.provider, reply.model, reply.tokens) == ("groq", "openai/gpt-oss-120b", 123)
    assert json.loads(reply.text) == {"metric": "total_revenue"}
    assert seen["host"] == "api.groq.com" and seen["auth"] == "Bearer groq-secret-key"
    body = seen["body"]
    assert body["model"] == "openai/gpt-oss-120b" and body["temperature"] == 0
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"] == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "USER"},
    ]


def test_reasoning_effort_only_for_gpt_oss(keys, monkeypatch):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=GROQ_OK)

    llm.complete_json("S", "U", client=client_for(handler))
    monkeypatch.setattr(settings, "groq_model", "some-other-model")
    llm.complete_json("S", "U", client=client_for(handler))
    assert bodies[0]["reasoning_effort"] == "low"
    assert "reasoning_effort" not in bodies[1]


def test_falls_back_to_gemini_when_groq_fails(keys):
    seen = {}

    def handler(request):
        if request.url.host == "api.groq.com":
            return httpx.Response(500, text="boom")
        seen["path"] = request.url.path
        seen["key"] = request.headers["x-goog-api-key"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=GEMINI_OK)

    reply = llm.complete_json("SYS", "USER", client=client_for(handler))
    assert (reply.provider, reply.model, reply.tokens) == ("gemini", "gemini-3.5-flash-lite", 77)
    assert seen["path"].endswith("/models/gemini-3.5-flash-lite:generateContent")
    assert seen["key"] == "gemini-secret-key"
    assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert seen["body"]["systemInstruction"]["parts"][0]["text"] == "SYS"


def test_gemini_reply_ignores_thought_parts(keys, monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "")
    payload = {
        "candidates": [{"content": {"parts": [{"text": "thinking...", "thought": True}, {"text": '{"a": 1}'}]}}],
        "usageMetadata": {"totalTokenCount": 5},
    }
    reply = llm.complete_json("S", "U", client=client_for(lambda request: httpx.Response(200, json=payload)))
    assert reply.text == '{"a": 1}'


def test_empty_groq_reply_falls_back(keys):
    empty = {"choices": [{"message": {"content": ""}}], "usage": {"total_tokens": 9}}

    def handler(request):
        if request.url.host == "api.groq.com":
            return httpx.Response(200, json=empty)
        return httpx.Response(200, json=GEMINI_OK)

    assert llm.complete_json("S", "U", client=client_for(handler)).provider == "gemini"


def test_network_errors_fall_back(keys):
    def handler(request):
        if request.url.host == "api.groq.com":
            raise httpx.ConnectTimeout("timed out")
        return httpx.Response(200, json=GEMINI_OK)

    assert llm.complete_json("S", "U", client=client_for(handler)).provider == "gemini"


def test_all_providers_failing_raises_unavailable_without_leaking_keys(keys):
    handler = lambda request: httpx.Response(503, text="overloaded")
    with pytest.raises(LLMUnavailable) as info:
        llm.complete_json("S", "U", client=client_for(handler))
    assert "secret" not in str(info.value)
    assert "unavailable" in str(info.value).lower()


def test_no_keys_configured(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    with pytest.raises(LLMUnavailable) as info:
        llm.complete_json("S", "U", client=client_for(lambda request: httpx.Response(200, json=GROQ_OK)))
    assert "No language model" in str(info.value)


def test_only_gemini_configured_skips_groq(keys, monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "")
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        return httpx.Response(200, json=GEMINI_OK)

    llm.complete_json("S", "U", client=client_for(handler))
    assert hosts == ["generativelanguage.googleapis.com"]