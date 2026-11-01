"""Curator v0: one LLM call per ingest → atomic claims (section, kind, confidence, excerpt).

# STUB: no dedup/merge/supersede against existing claims. The real version reconciles new
claims against the current brief (Brand Brain v2 design doc). v0 only extracts and adds.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from brain.providers import LLMProvider, LLMResult
from brain.types import BRIEF_SECTIONS, CLAIM_KINDS, ClaimKind


class ExtractedClaim(BaseModel):
    text: str = Field(min_length=1, description="One atomic statement, in the author's words")
    section: str = Field(description="Brief section key")
    kind: ClaimKind
    confidence: float = Field(ge=0.0, le=1.0)
    excerpt: str | None = Field(
        default=None, description="Verbatim span from the content that supports this claim"
    )


class Extraction(BaseModel):
    claims: list[ExtractedClaim]


SYSTEM = (
    "You extract atomic brand-knowledge claims from text a founder wrote about their own brand.\n"
    "Rules:\n"
    "- Each claim is ONE self-contained statement (understandable without the others).\n"
    "- Keep the founder's meaning and wording; never add facts they did not state.\n"
    "- Prefer 1-6 claims. Skip filler, greetings and questions.\n"
    f"- section: one of {list(BRIEF_SECTIONS)}; if none fits, a short snake_case name.\n"
    f"- kind: one of {list(CLAIM_KINDS)}. Facts = stated as true; hypothesis = belief not yet "
    "tested; decision = a choice made; constraint = a hard limit; preference = taste; "
    "idea = possibility.\n"
    "- confidence: how clearly the text supports the claim (0-1).\n"
    "- excerpt: the shortest verbatim span of the content supporting the claim.\n"
    'Respond with JSON: {"claims": [{"text", "section", "kind", "confidence", "excerpt"}]}'
)


def build_user_prompt(content: str, section_hint: str | None) -> str:
    hint = (
        f"This was written in answer to the '{section_hint}' question, so default to "
        f"section '{section_hint}' unless a claim clearly belongs elsewhere.\n"
        if section_hint
        else ""
    )
    return f"{hint}<content>\n{content}\n</content>"


_SECTION_RE = re.compile(r"[^a-z0-9]+")


def normalize_section(section: str | None, hint: str | None) -> str:
    cleaned = _SECTION_RE.sub("_", (section or "").strip().lower()).strip("_")[:64]
    return cleaned or hint or "other"


def extract(
    llm: LLMProvider, content: str, section_hint: str | None = None
) -> tuple[list[ExtractedClaim], LLMResult]:
    result = llm.complete_structured(SYSTEM, build_user_prompt(content, section_hint), Extraction)
    claims = []
    for c in result.value.claims:
        text = c.text.strip()
        if not text:
            continue
        claims.append(
            c.model_copy(
                update={
                    "text": text,
                    "section": normalize_section(c.section, section_hint),
                    "excerpt": (c.excerpt or "").strip() or None,
                }
            )
        )
    if not claims:
        # Never drop what the founder wrote: keep the whole input as one low-confidence claim.
        claims = [
            ExtractedClaim(
                text=content.strip()[:2000],
                section=section_hint or "other",
                kind="fact",
                confidence=0.3,
            )
        ]
    return claims, result.raw
