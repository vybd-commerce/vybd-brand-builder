"""Deterministic fake providers for tests and CI. No network, no keys.

FakeLLM:
  - `complete` returns a stable string derived from a hash of the prompt.
  - `complete_structured` uses a registered handler for the schema if one
    exists, otherwise builds a minimal valid instance of the schema
    (lists get exactly one item, so e.g. curator extraction yields one claim).
FakeEmbedder:
  - hash-seeded unit vectors: same text -> same vector, any dim.
"""

from __future__ import annotations

import hashlib
import math
import random
import types
import typing
from collections.abc import Callable
from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel

from brain.providers.base import Embedder, LLMProvider, LLMResult, StructuredResult, T


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


class FakeLLM(LLMProvider):
    def __init__(
        self,
        model: str = "fake/llm",
        structured_handlers: dict[type[BaseModel], Callable[[str, str], BaseModel]] | None = None,
        text_handler: Callable[[str, str], str] | None = None,
    ):
        self.model = model
        self.structured_handlers = dict(structured_handlers or {})
        self.text_handler = text_handler
        self.calls: list[dict[str, Any]] = []

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LLMResult:
        self.calls.append({"kind": "complete", "system": system, "user": user})
        if self.text_handler:
            text = self.text_handler(system, user)
        else:
            text = f"[fake:{_digest(system, user)[:8]}] {user[:200]}"
        return LLMResult(
            text=text,
            model=self.model,
            input_tokens=_approx_tokens(system + user),
            output_tokens=_approx_tokens(text),
        )

    def complete_structured(
        self, system: str, user: str, schema: type[T], max_tokens: int = 2048
    ) -> StructuredResult[T]:
        self.calls.append({"kind": "structured", "system": system, "user": user, "schema": schema})
        handler = self.structured_handlers.get(schema)
        value = handler(system, user) if handler else build_default(schema, seed_text=user)
        text = value.model_dump_json()
        return StructuredResult(
            value=value,
            raw=LLMResult(
                text=text,
                model=self.model,
                input_tokens=_approx_tokens(system + user),
                output_tokens=_approx_tokens(text),
            ),
        )


def build_default(schema: type[T], seed_text: str = "") -> T:
    """Minimal valid instance of a Pydantic model, filled deterministically."""
    """Fills every field except Optional ones (left None) and non-str fields with defaults."""
    values: dict[str, Any] = {}
    for name, field in schema.model_fields.items():
        if not field.is_required():
            if _is_optional(field.annotation) or field.annotation is not str:
                continue
        values[name] = _default_for(field.annotation, name, seed_text)
    return schema.model_validate(values)


def _is_optional(annotation: Any) -> bool:
    return get_origin(annotation) in (typing.Union, types.UnionType) and type(None) in get_args(
        annotation
    )


def _default_for(annotation: Any, name: str, seed_text: str) -> Any:
    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin in (typing.Union, types.UnionType):
        non_none = [a for a in args if a is not type(None)]
        return _default_for(non_none[0], name, seed_text) if non_none else None
    if origin is Literal:
        return args[0]
    if origin in (list, tuple, set, frozenset):
        inner = args[0] if args else str
        return [_default_for(inner, name, seed_text)]
    if origin is dict:
        return {}
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return build_default(annotation, seed_text)
    if annotation is str:
        snippet = seed_text.strip().splitlines()[0][:120] if seed_text.strip() else ""
        return f"fake {name}: {snippet}" if snippet else f"fake {name}"
    if annotation is bool:
        return False
    if annotation is int:
        return 1
    if annotation is float:
        return 0.5
    if isinstance(annotation, type) and hasattr(annotation, "__members__"):  # Enum
        return next(iter(annotation.__members__.values()))
    return None


class FakeEmbedder(Embedder):
    def __init__(self, dim: int = 1024, model: str = "fake/embed"):
        self.dim = dim
        self.model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        rng = random.Random(int(_digest(text)[:16], 16))
        vec = [rng.gauss(0.0, 1.0) for _ in range(self.dim)]
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]
