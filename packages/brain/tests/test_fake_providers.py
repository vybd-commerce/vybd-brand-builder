from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field

from brain.providers import FakeEmbedder, FakeLLM, get_embedder, get_llm


class _Claim(BaseModel):
    text: str
    section: str
    kind: Literal["fact", "decision", "constraint", "hypothesis", "idea", "preference"]
    confidence: float = Field(ge=0, le=1)


class _Extraction(BaseModel):
    claims: list[_Claim]
    note: str | None = None


def test_fake_embedder_is_deterministic_unit_vectors() -> None:
    emb = FakeEmbedder(dim=16)
    a1, a2, b = emb.embed(["hot sauce", "hot sauce", "streetwear"])
    assert a1 == a2
    assert a1 != b
    assert len(a1) == 16
    assert math.isclose(sum(v * v for v in a1), 1.0, rel_tol=1e-9)


def test_fake_llm_complete_is_stable_and_metered() -> None:
    llm = FakeLLM()
    r1 = llm.complete("sys", "hello")
    r2 = llm.complete("sys", "hello")
    assert r1.text == r2.text
    assert r1.input_tokens > 0 and r1.output_tokens > 0
    assert r1.model == "fake/llm"


def test_fake_llm_structured_default_fills_nested_schema() -> None:
    res = FakeLLM().complete_structured("sys", "Small-batch hot sauce", _Extraction)
    assert len(res.value.claims) == 1
    claim = res.value.claims[0]
    assert claim.kind == "fact"
    assert "Small-batch hot sauce" in claim.text
    assert res.value.note is None


def test_fake_llm_structured_handler_overrides_default() -> None:
    def handler(system: str, user: str) -> _Extraction:
        return _Extraction(
            claims=[_Claim(text="custom", section="customer", kind="idea", confidence=0.9)]
        )

    llm = FakeLLM(structured_handlers={_Extraction: handler})
    assert llm.complete_structured("s", "u", _Extraction).value.claims[0].text == "custom"


def test_factory_defaults_to_fakes(monkeypatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("EMBED_DIM", "8")
    assert isinstance(get_llm(), FakeLLM)
    assert get_embedder().dim == 8
