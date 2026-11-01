"""Search provider interface for market_scan. v0 ships only a fake."""

from __future__ import annotations

import hashlib
import os
from typing import Protocol

from pydantic import BaseModel


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str


class Search(Protocol):
    name: str

    def query(self, q: str) -> list[SearchResult]: ...


class FakeSearch:
    """Deterministic, clearly-labelled fake results (no network)."""

    name = "fake"

    def query(self, q: str) -> list[SearchResult]:
        h = hashlib.sha256(q.encode()).hexdigest()[:6]
        return [
            SearchResult(
                title=f"[fake result {i + 1}] {q}",
                url=f"https://example.com/fake-search/{h}/{i + 1}",
                snippet=f"Placeholder snippet {i + 1} for '{q}'. No real search was run.",
            )
            for i in range(3)
        ]


def get_search() -> Search:
    provider = os.environ.get("SEARCH_PROVIDER", "fake")
    if provider == "fake":
        return FakeSearch()
    # STUB: real provider (free search API or a web-enabled OpenRouter model) behind this
    # interface; see docs/IDEAS.md.
    raise NotImplementedError(f"SEARCH_PROVIDER={provider!r} is not implemented yet (use 'fake')")
