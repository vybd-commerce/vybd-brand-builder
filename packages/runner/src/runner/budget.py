"""Run budget: wraps every LLM call, meters tokens/cost/steps/wall time, stops cleanly.

A budget stop is not a failure: the runner skips remaining research phases, still writes the
report, and completes the run with `spent.stopped_by` set.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from brain.providers import LLMProvider, LLMResult, StructuredResult
from brain.providers.base import T

# budget key -> spent key
LIMITS = {
    "max_steps": "steps",
    "max_tokens": "tokens",
    "max_cost_usd": "cost_usd",
    "max_wall_seconds": "wall_seconds",
}


class BudgetExceeded(Exception):
    def __init__(self, limit: str, spent: float, cap: float):
        super().__init__(f"budget limit {limit} reached ({spent:g} >= {cap:g})")
        self.limit = limit


class BudgetTracker:
    def __init__(self, budget: dict[str, Any], spent: dict[str, Any] | None = None, *,
                 on_change: Callable[[dict[str, Any], LLMResult | None, str], None] | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.budget = dict(budget or {})
        prev = dict(spent or {})
        self._base_wall = float(prev.get("wall_seconds", 0.0))
        self._t0 = clock()
        self._clock = clock
        self.steps = int(prev.get("steps", 0))
        self.input_tokens = int(prev.get("input_tokens", 0))
        self.output_tokens = int(prev.get("output_tokens", 0))
        self.cost_usd = float(prev.get("cost_usd", 0.0))
        self.stopped_by: str | None = prev.get("stopped_by")
        self.on_change = on_change

    @property
    def spent(self) -> dict[str, Any]:
        out = {
            "steps": self.steps,
            "tokens": self.input_tokens + self.output_tokens,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "wall_seconds": round(self._base_wall + (self._clock() - self._t0), 2),
        }
        if self.stopped_by:
            out["stopped_by"] = self.stopped_by
        return out

    def check(self) -> None:
        spent = self.spent
        for limit, key in LIMITS.items():
            cap = self.budget.get(limit)
            if cap is not None and spent[key] >= cap:
                self.stopped_by = limit
                raise BudgetExceeded(limit, spent[key], cap)

    def record(self, result: LLMResult, label: str) -> None:
        self.input_tokens += result.input_tokens
        self.output_tokens += result.output_tokens
        self.cost_usd += result.cost_usd
        if self.on_change:
            self.on_change(self.spent, result, label)


class BudgetedLLM(LLMProvider):
    """LLMProvider that checks the budget before each call and records usage after it."""

    def __init__(self, inner: LLMProvider, tracker: BudgetTracker):
        self.inner = inner
        self.tracker = tracker
        self.model = inner.model

    def _start(self) -> None:
        self.tracker.check()
        self.tracker.steps += 1

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LLMResult:
        self._start()
        r = self.inner.complete(system, user, max_tokens)
        self.tracker.record(r, "complete")
        return r

    def complete_structured(self, system: str, user: str, schema: type[T],
                            max_tokens: int = 2048) -> StructuredResult[T]:
        self._start()
        r = self.inner.complete_structured(system, user, schema, max_tokens)
        self.tracker.record(r.raw, f"structured:{schema.__name__}")
        return r
