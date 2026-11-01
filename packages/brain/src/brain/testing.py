"""Test helpers shared by brain, server and runner tests.

Also backs LLM_PROVIDER=fake (local dev, e2e-fake). Not used with real providers.
"""

from __future__ import annotations

import re

from brain.curator import ExtractedClaim, Extraction
from brain.providers import FakeLLM

_CONTENT = re.compile(r"<content>\n(.*)\n</content>", re.DOTALL)
_HINT = re.compile(r"default to section '([a-z0-9_]+)'")


def fake_curator(system: str, user: str) -> Extraction:
    """Deterministic curator: one claim per sentence of the content, in the hinted section."""
    m = _CONTENT.search(user)
    content = m.group(1) if m else user
    hint = _HINT.search(user)
    section = hint.group(1) if hint else "other"
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", content.strip()) if s.strip()]
    return Extraction(
        claims=[
            ExtractedClaim(text=s, section=section, kind="fact", confidence=0.8, excerpt=s)
            for s in sentences[:6]
        ]
    )


def fake_llm(**handlers) -> FakeLLM:
    """FakeLLM with the curator handler pre-registered; pass extra {Schema: fn} handlers."""
    return FakeLLM(structured_handlers={Extraction: fake_curator, **handlers})
