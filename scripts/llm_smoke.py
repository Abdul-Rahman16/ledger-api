"""
Smoke test for the LLM client.
  python -m scripts.llm_smoke           # tries Groq first, then Gemini
  python -m scripts.llm_smoke groq      # Groq only
  python -m scripts.llm_smoke gemini    # Gemini only
"""
import sys

from core.config import settings
from core.llm import complete_json
from core.llm_types import LLMUnavailable


def main() -> None:
    only = sys.argv[1].lower() if len(sys.argv) > 1 else None
    if only == "gemini":
        settings.groq_api_key = ""
    elif only == "groq":
        settings.gemini_api_key = ""
    elif only is not None:
        print("Usage: python -m scripts.llm_smoke [groq|gemini]")
        raise SystemExit(2)

    print("groq key set:", bool(settings.groq_api_key), "| gemini key set:", bool(settings.gemini_api_key))
    try:
        reply = complete_json('Reply with one JSON object: {"ok": true}', "ping")
    except LLMUnavailable as exc:
        print("FAILED:", exc)
        raise SystemExit(1)
    print(f"provider={reply.provider} model={reply.model} tokens={reply.tokens}")
    print("text:", reply.text)


if __name__ == "__main__":
    main()