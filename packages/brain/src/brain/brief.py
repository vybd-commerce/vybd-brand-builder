"""Builds the BriefView (sections → accepted claims) from claims."""

from __future__ import annotations

import hashlib

from brain.types import BRIEF_SECTIONS, BriefSection, BriefView, Claim


def brief_version(claims: list[Claim]) -> str:
    """Stable hash of the accepted claim set; changes on any add/supersede/edit."""
    h = hashlib.sha256()
    for c in sorted(claims, key=lambda c: c.id):
        h.update(f"{c.id}:{c.updated_at.isoformat()}|".encode())
    return h.hexdigest()[:16]


def _title(key: str) -> str:
    return BRIEF_SECTIONS.get(key) or key.replace("_", " ").capitalize()


def build_brief(brand_id: str, claims: list[Claim]) -> BriefView:
    by_section: dict[str, list[Claim]] = {}
    for c in claims:
        by_section.setdefault(c.section, []).append(c)

    sections = [
        BriefSection(key=k, title=t, claims=by_section.get(k, []))
        for k, t in BRIEF_SECTIONS.items()
    ]
    other = [
        BriefSection(key=k, title=_title(k), claims=v)
        for k, v in sorted(by_section.items())
        if k not in BRIEF_SECTIONS
    ]
    return BriefView(
        brand_id=brand_id,
        version=brief_version(claims),
        sections=sections,
        other=other,
        claim_count=len(claims),
    )
