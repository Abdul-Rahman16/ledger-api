import httpx

from core.config import settings
from core.llm_types import LLMReply, LLMUnavailable
from core.logging import log

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class _ProviderError(Exception):
    """One provider could not answer; the caller moves on to the next one."""


def _check(response: httpx.Response) -> dict:
    if response.status_code >= 400:
        raise _ProviderError(f"HTTP {response.status_code}: {response.text[:200]}")
    try:
        data = response.json()
    except ValueError:
        raise _ProviderError("response was not JSON") from None
    if not isinstance(data, dict):
        raise _ProviderError("unexpected response shape")
    return data


def _call_groq(client: httpx.Client, system: str, user: str) -> LLMReply:
    model = settings.groq_model
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
        "max_completion_tokens": settings.llm_max_output_tokens,
        "response_format": {"type": "json_object"},
    }
    if "gpt-oss" in model:
        body["reasoning_effort"] = "low"  # routing needs little reasoning; keeps latency and tokens down

    response = client.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {settings.groq_api_key}"},
        json=body,
    )
    data = _check(response)
    try:
        text = data["choices"][0]["message"]["content"] or ""
        tokens = int((data.get("usage") or {}).get("total_tokens") or 0)
    except (KeyError, IndexError, TypeError, ValueError):
        raise _ProviderError("unexpected response shape") from None
    if not text.strip():
        raise _ProviderError("empty reply")
    return LLMReply(text=text, provider="groq", model=model, tokens=tokens)


def _call_gemini(client: httpx.Client, system: str, user: str) -> LLMReply:
    model = settings.gemini_model
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": settings.llm_max_output_tokens,
            "responseMimeType": "application/json",
        },
    }
    response = client.post(
        GEMINI_URL.format(model=model),
        headers={"x-goog-api-key": settings.gemini_api_key},
        json=body,
    )
    data = _check(response)
    try:
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(
            part.get("text", "") for part in parts if isinstance(part, dict) and not part.get("thought")
        )
        tokens = int((data.get("usageMetadata") or {}).get("totalTokenCount") or 0)
    except (KeyError, IndexError, TypeError, ValueError):
        raise _ProviderError("no usable candidate (blocked or empty)") from None
    if not text.strip():
        raise _ProviderError("empty reply")
    return LLMReply(text=text, provider="gemini", model=model, tokens=tokens)


def complete_json(system: str, user: str, client: httpx.Client | None = None) -> LLMReply:
    """
    Ask for a JSON reply. Tries Groq first, then Gemini. Raises LLMUnavailable if none answer.
    The reply is still untrusted text: callers must validate it.
    """
    providers = []
    if settings.groq_api_key:
        providers.append(("groq", _call_groq))
    if settings.gemini_api_key:
        providers.append(("gemini", _call_gemini))
    if not providers:
        raise LLMUnavailable("No language model is configured.")

    owns_client = client is None
    http = client or httpx.Client(timeout=settings.llm_timeout_seconds)
    try:
        for name, call in providers:
            try:
                return call(http, system, user)
            except (httpx.HTTPError, _ProviderError) as exc:
                log.error("llm_provider_failed", provider=name, reason=f"{type(exc).__name__}: {str(exc)[:200]}")
    finally:
        if owns_client:
            http.close()
    raise LLMUnavailable("The language model is unavailable right now. Please try again shortly.")