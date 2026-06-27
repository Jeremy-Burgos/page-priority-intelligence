"""Provider abstraction for OpenAI and Claude (Anthropic).

The SDKs are optional and are not in the MVP requirements. These classes import
fine without them; the SDK is only imported lazily inside complete(), and
is_available() checks for both the key and the installed package without
importing it. If neither is present, the provider reports unavailable and the
caller falls back to the rule-based writer.

Nothing here logs prompts or responses, per the privacy rules.
"""

from __future__ import annotations

import importlib.util
import os
from abc import ABC, abstractmethod
from typing import Optional


class Provider(ABC):
    """Minimal text-completion provider interface."""

    name: str = "provider"
    _package: str = ""
    _env_key: str = ""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.environ.get(self._env_key, "")
        self.model = model or self._default_model

    @property
    def _default_model(self) -> str:
        return ""

    def is_available(self) -> bool:
        """True only when both an API key and the SDK package are present."""
        if not self.api_key:
            return False
        return importlib.util.find_spec(self._package) is not None

    @abstractmethod
    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Return the model's raw text response (expected to be JSON)."""
        raise NotImplementedError


class OpenAIProvider(Provider):
    name = "openai"
    _package = "openai"
    _env_key = "OPENAI_API_KEY"

    @property
    def _default_model(self) -> str:
        return os.environ.get("PPI_OPENAI_MODEL", "gpt-4o-mini")

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        from openai import OpenAI  # lazy import; optional dependency

        client = OpenAI(api_key=self.api_key)
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        return response.choices[0].message.content or ""


class ClaudeProvider(Provider):
    name = "claude"
    _package = "anthropic"
    _env_key = "ANTHROPIC_API_KEY"

    @property
    def _default_model(self) -> str:
        return os.environ.get("PPI_CLAUDE_MODEL", "claude-sonnet-4-20250514")

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        import anthropic  # lazy import; optional dependency

        client = anthropic.Anthropic(api_key=self.api_key)
        message = client.messages.create(
            model=self.model,
            max_tokens=1024,
            temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        parts = [block.text for block in message.content if getattr(block, "type", "") == "text"]
        return "".join(parts)


_PROVIDERS = {
    "openai": OpenAIProvider,
    "claude": ClaudeProvider,
}


def get_provider(name: Optional[str]) -> Optional[Provider]:
    """Return a provider instance by name, or None if name is unknown or empty.

    The returned provider may still be unavailable (missing key or SDK); callers
    should check is_available() before use.
    """
    if not name:
        return None
    cls = _PROVIDERS.get(name.strip().lower())
    return cls() if cls else None
