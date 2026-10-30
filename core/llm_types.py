"""Types shared by the LLM client and its callers (pure Python)."""

from dataclasses import dataclass


class LLMUnavailable(Exception):
    """No configured language-model provider could answer. The message is safe to show."""


@dataclass(frozen=True)
class LLMReply:
    text: str
    provider: str
    model: str
    tokens: int