"""Live provider checks (OpenRouter free models). Run: make test-live

Needs LLM_API_KEY. Uses LLM_MODEL / EMBED_MODEL / EMBED_DIM from env.
Record results in docs/PROVIDER_NOTES.md.
"""

from __future__ import annotations

import os

import pytest

from brain.curator import extract
from brain.providers import get_llm
from brain.providers.openai_compat import OpenAICompatEmbedder, OpenAICompatLLM

pytestmark = pytest.mark.live

BASE = os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1")
KEY = os.environ.get("LLM_API_KEY", "")


@pytest.fixture(autouse=True)
def _need_key():
    if not KEY:
        pytest.skip("LLM_API_KEY not set")


def _llm() -> OpenAICompatLLM:
    os.environ.setdefault("LLM_PROVIDER", "openai_compat")
    llm = get_llm()  # same construction as the server (token floor, reasoning effort, fallbacks)
    assert isinstance(llm, OpenAICompatLLM), "set LLM_PROVIDER=openai_compat for live tests"
    return llm


def test_live_complete() -> None:
    r = _llm().complete("Reply with one word.", "Say hello.", max_tokens=400)
    print(f"\nmodel={r.model} in={r.input_tokens} out={r.output_tokens} cost={r.cost_usd}")
    assert r.text.strip()


def test_live_curator_extraction() -> None:
    claims, raw = extract(
        _llm(),
        "We make small-batch hot sauce with Kerala chillies for Indian-American home cooks "
        "who find supermarket sauces too sweet. A 5oz bottle is $9.",
        section_hint="one_liner",
    )
    print(f"\nmodel={raw.model}")
    for c in claims:
        print(f"  [{c.section}/{c.kind}/{c.confidence:.2f}] {c.text}")
    assert claims


def test_live_embeddings() -> None:
    emb = OpenAICompatEmbedder(
        base_url=os.environ.get("EMBED_BASE_URL", BASE),
        api_key=os.environ.get("EMBED_API_KEY") or KEY,
        model=os.environ.get("EMBED_MODEL", "liquid/lfm-2.5-embedding-350m:free"),
        dim=int(os.environ.get("EMBED_DIM", "1024")),
    )
    a, b = emb.embed(["hot sauce", "chilli condiment"])
    assert len(a) == emb.dim == len(b)
