"""Provider factory — env-driven selection (pattern ported from example-brand `config.py`).

LLM_PROVIDER   = fake | openai_compat   (openai_compat = OpenRouter by default)
EMBED_PROVIDER = fake | openai_compat
EMBED_DIM      = embedding dimension (must match the brain migration's vector size)
"""

from __future__ import annotations

import os

from brain.providers.base import Embedder, LLMProvider, LLMResult, ProviderError, StructuredResult
from brain.providers.fake import FakeEmbedder, FakeLLM

__all__ = [
    "Embedder",
    "FakeEmbedder",
    "FakeLLM",
    "LLMProvider",
    "LLMResult",
    "ProviderError",
    "StructuredResult",
    "embed_dim",
    "get_embedder",
    "get_llm",
]

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


def embed_dim() -> int:
    return int(os.environ.get("EMBED_DIM", "1024"))


def _allow_paid() -> bool:
    return os.environ.get("ALLOW_PAID_MODELS", "false").lower() in ("1", "true", "yes")


def _role_env(role: str | None, name: str, default: str = "") -> str:
    """`<ROLE>_<NAME>` overrides `<NAME>`, e.g. RUNNER_LLM_MODEL over LLM_MODEL."""
    if role:
        v = os.environ.get(f"{role.upper()}_{name}")
        if v:
            return v
    return os.environ.get(name, default)


def get_llm(role: str | None = None) -> LLMProvider:
    """role: optional per-consumer override prefix (e.g. "runner" → RUNNER_LLM_MODEL)."""
    provider = os.environ.get("LLM_PROVIDER", "fake")
    if provider == "fake":
        # Curator-aware fake so a dev server / e2e-fake run produces sensible briefs.
        from brain.testing import fake_llm

        return fake_llm()
    if provider == "openai_compat":
        from brain.providers.openai_compat import OpenAICompatLLM

        fallbacks = [m.strip() for m in _role_env(role, "LLM_MODELS").split(",") if m.strip()]
        return OpenAICompatLLM(
            base_url=os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL),
            api_key=os.environ.get("LLM_API_KEY", ""),
            model=_role_env(role, "LLM_MODEL", "openrouter/free"),
            fallbacks=fallbacks,
            allow_paid=_allow_paid(),
            min_max_tokens=int(_role_env(role, "LLM_MIN_MAX_TOKENS", "4000")),
            reasoning_effort=_role_env(role, "LLM_REASONING_EFFORT") or None,
        )
    raise ValueError(f"Unknown LLM_PROVIDER={provider!r}. Valid: 'fake', 'openai_compat'.")


def get_embedder() -> Embedder:
    provider = os.environ.get("EMBED_PROVIDER", "fake")
    if provider == "fake":
        return FakeEmbedder(dim=embed_dim())
    if provider == "openai_compat":
        from brain.providers.openai_compat import OpenAICompatEmbedder

        return OpenAICompatEmbedder(
            base_url=os.environ.get("EMBED_BASE_URL")
            or os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL),
            api_key=os.environ.get("EMBED_API_KEY") or os.environ.get("LLM_API_KEY", ""),
            model=os.environ.get("EMBED_MODEL", "liquid/lfm-2.5-embedding-350m:free"),
            dim=embed_dim(),
            allow_paid=_allow_paid(),
        )
    raise ValueError(f"Unknown EMBED_PROVIDER={provider!r}. Valid: 'fake', 'openai_compat'.")
