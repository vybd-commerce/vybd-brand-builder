"""OpenAI-compatible chat + embeddings adapters (plain httpx, no vendor SDK).

Default target is OpenRouter (https://openrouter.ai/api/v1), free models only. The same
adapters work against any OpenAI-compatible server (Ollama, vLLM, OpenAI, Together, ...)
by changing base URL + model — that's the "agnostic" requirement.

OpenRouter specifics, used only when the base URL is OpenRouter:
  - free-only guard (`:free` suffix or the `openrouter/free` router) unless allow_paid
  - `models: [...]` fallback list
  - `usage.cost` (USD) if returned
See docs/PROVIDER_NOTES.md for which of these are confirmed live.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from typing import Any

import httpx
from pydantic import ValidationError

from brain.providers.base import (
    Embedder,
    LLMProvider,
    LLMResult,
    ProviderError,
    StructuredResult,
    T,
)

log = logging.getLogger("brain.providers")

OPENROUTER_FREE_ROUTER = "openrouter/free"
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


def is_openrouter(base_url: str) -> bool:
    return "openrouter.ai" in base_url


def is_free_model(model: str) -> bool:
    return model.endswith(":free") or model == OPENROUTER_FREE_ROUTER


def check_models_allowed(models: list[str], base_url: str, allow_paid: bool) -> None:
    if allow_paid or not is_openrouter(base_url):
        return
    paid = [m for m in models if not is_free_model(m)]
    if paid:
        raise ProviderError(
            f"Paid OpenRouter model(s) {paid} refused: only ':free' models are allowed. "
            "Set ALLOW_PAID_MODELS=true to lift this guard."
        )


class _HTTP:
    def __init__(self, base_url: str, api_key: str, *, timeout: float, max_retries: int,
                 client: httpx.Client | None, sleep=time.sleep):
        if not api_key:
            raise ProviderError("API key is empty (set LLM_API_KEY / EMBED_API_KEY)")
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self.sleep = sleep
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        if is_openrouter(base_url):
            headers["X-Title"] = "Vybd Brand Builder"
        self.client = client or httpx.Client(timeout=timeout)
        self.headers = headers

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        last: str = ""
        for attempt in range(self.max_retries + 1):
            if attempt:
                self.sleep(min(30.0, 2.0 ** attempt) + random.random())
            try:
                resp = self.client.post(f"{self.base_url}{path}", json=payload,
                                        headers=self.headers)
            except httpx.TransportError as e:
                last = f"transport error: {e}"
                continue
            if resp.status_code in RETRY_STATUS:
                last = f"HTTP {resp.status_code}: {resp.text[:300]}"
                retry_after = resp.headers.get("retry-after")
                if retry_after and retry_after.isdigit() and attempt < self.max_retries:
                    self.sleep(min(60.0, float(retry_after)))
                continue
            if resp.status_code >= 400:
                raise ProviderError(f"HTTP {resp.status_code} from {path}: {resp.text[:500]}",)
            data = resp.json()
            if isinstance(data, dict) and data.get("error"):
                # OpenRouter can return 200 with an error body (e.g. upstream failure).
                err = data["error"]
                code = err.get("code") if isinstance(err, dict) else None
                last = f"provider error {code}: {err}"
                if code in RETRY_STATUS:
                    continue
                raise ProviderError(last)
            return data
        raise ProviderError(f"{path} failed after {self.max_retries + 1} attempts; last: {last}")


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_json_object(text: str) -> Any:
    """Lenient JSON extraction: strip code fences, else take the outermost {...}."""
    cleaned = _FENCE.sub("", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(cleaned[start : end + 1])


class OpenAICompatLLM(LLMProvider):
    def __init__(self, *, base_url: str, api_key: str, model: str,
                 fallbacks: list[str] | None = None, allow_paid: bool = False,
                 timeout: float = 180.0, max_retries: int = 4,
                 min_max_tokens: int = 0, reasoning_effort: str | None = None,
                 client: httpx.Client | None = None, sleep=time.sleep):
        self.model = model
        # Reasoning models spend output tokens thinking before answering; a floor keeps small
        # max_tokens requests from ending empty. Effort hint is sent to OpenRouter only.
        self.min_max_tokens = min_max_tokens
        self.reasoning_effort = reasoning_effort
        self.fallbacks = [m for m in (fallbacks or []) if m and m != model]
        self.base_url = base_url
        check_models_allowed([model, *self.fallbacks], base_url, allow_paid)
        self.http = _HTTP(base_url, api_key, timeout=timeout, max_retries=max_retries,
                          client=client, sleep=sleep)
        self._json_schema_supported = True

    def _payload(self, system: str, user: str, max_tokens: int) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "max_tokens": max(max_tokens, self.min_max_tokens),
        }
        if is_openrouter(self.base_url):
            if self.fallbacks:
                payload["models"] = [self.model, *self.fallbacks]
            if self.reasoning_effort:
                payload["reasoning"] = {"effort": self.reasoning_effort}
        return payload

    def _call(self, payload: dict[str, Any]) -> LLMResult:
        try:
            return self._call_once(payload)
        except ProviderError as e:
            # Out of tokens while thinking: retry once with double the budget.
            if "finish_reason='length'" not in str(e):
                raise
            log.warning("empty completion at max_tokens=%s; retrying with 2x",
                        payload["max_tokens"])
            return self._call_once({**payload, "max_tokens": payload["max_tokens"] * 2})

    def _call_once(self, payload: dict[str, Any]) -> LLMResult:
        data = self.http.post("/chat/completions", payload)
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError(f"No choices in response: {str(data)[:500]}")
        msg = choices[0].get("message") or {}
        text = msg.get("content")
        if isinstance(text, list):  # some providers return content parts
            text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
        if not text or not str(text).strip():
            raise ProviderError(
                f"Empty completion (finish_reason={choices[0].get('finish_reason')!r}, "
                f"model={data.get('model')!r}). Reasoning models may spend the whole "
                "max_tokens budget thinking; raise max_tokens or pick another model."
            )
        usage = data.get("usage") or {}
        return LLMResult(
            text=str(text),
            model=data.get("model") or self.model,
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            cost_usd=float(usage.get("cost") or 0.0),
        )

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LLMResult:
        return self._call(self._payload(system, user, max_tokens))

    def complete_structured(self, system: str, user: str, schema: type[T],
                            max_tokens: int = 2048) -> StructuredResult[T]:
        json_schema = schema.model_json_schema()
        sys_prompt = (
            f"{system}\n\nReturn ONLY a JSON object matching this JSON Schema, no prose, "
            f"no code fences:\n{json.dumps(json_schema)}"
        )
        payload = self._payload(sys_prompt, user, max_tokens)
        if self._json_schema_supported:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "schema": json_schema, "strict": False},
            }
        try:
            first = self._call(payload)
        except ProviderError as e:
            if "response_format" not in payload or "400" not in str(e):
                raise
            # Model/provider rejected structured output: fall back to prompt-only JSON.
            log.warning("response_format rejected by %s; retrying prompt-only", self.model)
            self._json_schema_supported = False
            payload.pop("response_format")
            first = self._call(payload)

        totals = [first]
        try:
            value = schema.model_validate(parse_json_object(first.text))
        except (json.JSONDecodeError, ValidationError) as err:
            # One repair attempt with the validation error.
            repair = dict(payload)
            repair["messages"] = [
                *payload["messages"],
                {"role": "assistant", "content": first.text},
                {"role": "user", "content": f"That was invalid: {str(err)[:800]}\n"
                                            "Reply with the corrected JSON object only."},
            ]
            second = self._call(repair)
            totals.append(second)
            try:
                value = schema.model_validate(parse_json_object(second.text))
            except (json.JSONDecodeError, ValidationError) as err2:
                raise ProviderError(
                    f"{schema.__name__} output invalid after repair: {str(err2)[:500]}"
                ) from err2

        return StructuredResult(
            value=value,
            raw=LLMResult(
                text=totals[-1].text,
                model=totals[-1].model,
                input_tokens=sum(r.input_tokens for r in totals),
                output_tokens=sum(r.output_tokens for r in totals),
                cost_usd=sum(r.cost_usd for r in totals),
            ),
        )


class OpenAICompatEmbedder(Embedder):
    def __init__(self, *, base_url: str, api_key: str, model: str, dim: int,
                 allow_paid: bool = False, batch_size: int = 64, timeout: float = 60.0,
                 max_retries: int = 4, client: httpx.Client | None = None, sleep=time.sleep):
        self.model = model
        self.dim = dim
        self.batch_size = batch_size
        check_models_allowed([model], base_url, allow_paid)
        self.http = _HTTP(base_url, api_key, timeout=timeout, max_retries=max_retries,
                          client=client, sleep=sleep)

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            data = self.http.post("/embeddings", {"model": self.model, "input": batch})
            items = sorted(data.get("data") or [], key=lambda d: d.get("index", 0))
            if len(items) != len(batch):
                raise ProviderError(
                    f"Embeddings: asked for {len(batch)}, got {len(items)}: {str(data)[:300]}"
                )
            for item in items:
                vec = item.get("embedding")
                if not isinstance(vec, list) or len(vec) != self.dim:
                    got = len(vec) if isinstance(vec, list) else type(vec).__name__
                    raise ProviderError(
                        f"Embedding dimension mismatch: model {self.model} returned {got}, "
                        f"EMBED_DIM={self.dim}. Fix EMBED_DIM (and re-run the brain migration) "
                        "or choose a different model."
                    )
                out.append([float(x) for x in vec])
        return out
