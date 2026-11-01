"""OpenAI-compatible adapter against a mocked HTTP transport (no network)."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel

from brain.providers import ProviderError
from brain.providers.openai_compat import (
    OpenAICompatEmbedder,
    OpenAICompatLLM,
    check_models_allowed,
    parse_json_object,
)

OR = "https://openrouter.ai/api/v1"


class Out(BaseModel):
    answer: str


def _chat(content: str, model: str = "x/y:free", **usage) -> dict:
    return {
        "model": model,
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, **usage},
    }


def _client(responses: list, seen: list | None = None) -> httpx.Client:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(json.loads(request.content))
        status, body = queue.pop(0)
        return httpx.Response(status, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _llm(responses, seen=None, **kw) -> OpenAICompatLLM:
    return OpenAICompatLLM(base_url=OR, api_key="k", model=kw.pop("model", "x/y:free"),
                           client=_client(responses, seen), sleep=lambda s: None, **kw)


def test_free_only_guard() -> None:
    check_models_allowed(["a/b:free", "openrouter/free"], OR, allow_paid=False)
    with pytest.raises(ProviderError, match="Paid"):
        check_models_allowed(["openai/gpt-x"], OR, allow_paid=False)
    check_models_allowed(["openai/gpt-x"], OR, allow_paid=True)
    check_models_allowed(["llama3"], "http://localhost:11434/v1", allow_paid=False)  # not OR
    with pytest.raises(ProviderError):
        OpenAICompatLLM(base_url=OR, api_key="k", model="a/b:free", fallbacks=["paid/model"])


def test_complete_sends_fallbacks_and_reads_usage() -> None:
    seen: list = []
    llm = _llm([(200, _chat("hi", model="z/w:free", cost=0.0))], seen,
               fallbacks=["z/w:free"])
    r = llm.complete("sys", "user", max_tokens=50)
    assert r.text == "hi" and r.model == "z/w:free"
    assert (r.input_tokens, r.output_tokens) == (10, 5)
    assert seen[0]["models"] == ["x/y:free", "z/w:free"]
    assert seen[0]["messages"][0] == {"role": "system", "content": "sys"}


def test_retries_on_429_then_succeeds() -> None:
    llm = _llm([(429, {"error": "rate"}), (503, {}), (200, _chat("ok"))])
    assert llm.complete("s", "u").text == "ok"


def test_gives_up_after_max_retries() -> None:
    llm = _llm([(429, {})] * 3, max_retries=2)
    with pytest.raises(ProviderError, match="after 3 attempts"):
        llm.complete("s", "u")


def test_empty_content_fails_loudly() -> None:
    with pytest.raises(ProviderError, match="Empty completion"):
        _llm([(200, _chat(""))]).complete("s", "u")


def test_structured_parses_fenced_json() -> None:
    llm = _llm([(200, _chat('```json\n{"answer": "42"}\n```'))])
    res = llm.complete_structured("s", "u", Out)
    assert res.value.answer == "42"


def test_structured_falls_back_when_response_format_rejected() -> None:
    seen: list = []
    llm = _llm([(400, {"error": "response_format not supported"}),
                (200, _chat('{"answer": "a"}'))], seen)
    assert llm.complete_structured("s", "u", Out).value.answer == "a"
    assert "response_format" in seen[0] and "response_format" not in seen[1]


def test_structured_repairs_once_and_sums_tokens() -> None:
    llm = _llm([(200, _chat('{"wrong": 1}')), (200, _chat('{"answer": "fixed"}'))])
    res = llm.complete_structured("s", "u", Out)
    assert res.value.answer == "fixed"
    assert res.raw.input_tokens == 20


def test_structured_raises_after_failed_repair() -> None:
    llm = _llm([(200, _chat("nope")), (200, _chat("still nope"))])
    with pytest.raises(ProviderError, match="invalid after repair"):
        llm.complete_structured("s", "u", Out)


def test_parse_json_object_finds_embedded_object() -> None:
    assert parse_json_object('Sure! {"a": 1} hope that helps') == {"a": 1}


def test_embedder_orders_by_index_and_checks_dim() -> None:
    body = {"data": [{"index": 1, "embedding": [0.0, 1.0]}, {"index": 0, "embedding": [1.0, 0.0]}]}
    emb = OpenAICompatEmbedder(base_url=OR, api_key="k", model="e/m:free", dim=2,
                               client=_client([(200, body)]), sleep=lambda s: None)
    assert emb.embed(["a", "b"]) == [[1.0, 0.0], [0.0, 1.0]]

    bad = OpenAICompatEmbedder(base_url=OR, api_key="k", model="e/m:free", dim=3,
                               client=_client([(200, body)]), sleep=lambda s: None)
    with pytest.raises(ProviderError, match="dimension mismatch"):
        bad.embed(["a", "b"])


def test_missing_api_key() -> None:
    with pytest.raises(ProviderError, match="API key"):
        OpenAICompatLLM(base_url=OR, api_key="", model="a/b:free")


def test_token_floor_reasoning_hint_and_length_retry() -> None:
    seen: list = []
    empty = {"model": "m", "choices": [{"message": {"content": ""}, "finish_reason": "length"}]}
    llm = _llm([(200, empty), (200, _chat("ok"))], seen, min_max_tokens=4000,
               reasoning_effort="low")
    assert llm.complete("s", "u", max_tokens=100).text == "ok"
    assert seen[0]["max_tokens"] == 4000 and seen[1]["max_tokens"] == 8000
    assert seen[0]["reasoning"] == {"effort": "low"}
