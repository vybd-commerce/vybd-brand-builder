"""Provider interfaces. Everything outside `brain.providers` depends only on these.

Ported pattern from the example-brand build (`brain/llm_gen.py`): one ABC per
capability, adapters behind it, so swapping vendor/model never touches
curator, runner or server code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass
class LLMResult:
    text: str
    model: str  # model that actually answered (may differ from requested when fallbacks fire)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class StructuredResult(Generic[T]):
    value: T
    raw: LLMResult


class LLMProvider(ABC):
    model: str

    @abstractmethod
    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LLMResult: ...

    @abstractmethod
    def complete_structured(
        self, system: str, user: str, schema: type[T], max_tokens: int = 2048
    ) -> StructuredResult[T]:
        """Return a validated instance of `schema`. Raise on unrecoverable invalid output."""


class Embedder(ABC):
    model: str
    dim: int

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class ProviderError(RuntimeError):
    """Raised for real provider failures (empty response, invalid output, auth, exhausted retries).

    Fail loudly — never silently return empty content (lesson from the example-brand build).
    """
