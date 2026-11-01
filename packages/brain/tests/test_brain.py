"""BrandBrain behavior against real Postgres + fake providers."""

from __future__ import annotations

import uuid

import pytest

from brain import BrandBrain, BrandSpaceNotFound, ProposalAlreadyDecided
from brain.providers import FakeEmbedder, embed_dim
from brain.testing import fake_llm

pytestmark = pytest.mark.db


@pytest.fixture
def brain(session_factory) -> BrandBrain:
    return BrandBrain(session_factory, fake_llm(), FakeEmbedder(dim=embed_dim()))


@pytest.fixture
def brand(brain: BrandBrain) -> str:
    brand_id = f"test-{uuid.uuid4().hex[:12]}"
    brain.create_brand_space(brand_id)
    return brand_id


def test_create_brand_space_is_idempotent(brain, brand) -> None:
    brain.create_brand_space(brand)
    assert brain.brief(brand).claim_count == 0


def test_unknown_brand_raises(brain) -> None:
    with pytest.raises(BrandSpaceNotFound):
        brain.brief("nope-" + uuid.uuid4().hex)


def test_ingest_challenge_answer_creates_accepted_claims_in_hinted_section(brain, brand) -> None:
    res = brain.ingest(
        brand, "Nurses on 12-hour shifts. They hate how scrubs fit.",
        source_type="challenge_answer", author="u1", section_hint="customer",
        source_ref="customer",
    )
    assert len(res.claims) == 2
    assert {c.section for c in res.claims} == {"customer"}
    assert {c.status for c in res.claims} == {"accepted"}
    assert all(c.evidence and c.evidence[0].raw_input_id == res.raw_input_id for c in res.claims)

    brief = brain.brief(brand)
    customer = next(s for s in brief.sections if s.key == "customer")
    assert [c.text for c in customer.claims] == [
        "Nurses on 12-hour shifts.", "They hate how scrubs fit.",
    ]
    assert "one_liner" in brief.empty_sections


def test_reanswer_supersedes_only_that_challenges_claims(brain, brand) -> None:
    brain.ingest(brand, "Women 25-40.", source_type="challenge_answer", author="u1",
                 section_hint="customer", source_ref="customer")
    brain.ingest(brand, "Customers love bright colours.", source_type="note", author="u1",
                 section_hint="customer")
    v1 = brain.brief(brand).version

    res = brain.ingest(brand, "ICU nurses in Texas.", source_type="challenge_answer",
                       author="u1", section_hint="customer", source_ref="customer")
    assert len(res.superseded_claim_ids) == 1

    texts = [c.text for c in next(s for s in brain.brief(brand).sections
                                  if s.key == "customer").claims]
    assert "Women 25-40." not in texts
    assert "Customers love bright colours." in texts  # note survives
    assert "ICU nurses in Texas." in texts
    assert brain.brief(brand).version != v1


def test_unknown_section_goes_to_other(brain, brand) -> None:
    brain.ingest(brand, "We ship from Austin.", source_type="note", author="u1",
                 section_hint="logistics")
    brief = brain.brief(brand)
    assert [s.key for s in brief.other] == ["logistics"]


def test_run_output_cannot_ingest_directly(brain, brand) -> None:
    with pytest.raises(ValueError, match="propose"):
        brain.ingest(brand, "x", source_type="run", author="runner")


def test_search_ranks_exact_text_first(brain, brand) -> None:
    brain.ingest(brand, "Hot sauce made in small batches. Sold at farmers markets.",
                 source_type="note", author="u1")
    hits = brain.search(brand, "Sold at farmers markets.", k=2)
    assert hits[0].text == "Sold at farmers markets."
    assert hits[0].score == pytest.approx(1.0, abs=1e-6)
    assert brain.search(brand, "anything", sections=["customer"]) == []


def test_context_pack_full_and_trimmed(brain, brand) -> None:
    brain.ingest(brand, "Small-batch hot sauce. " * 1 + "Made with Kerala chillies.",
                 source_type="challenge_answer", author="u1", section_hint="one_liner",
                 source_ref="one_liner")
    for i in range(30):
        brain.ingest(brand, f"Competitor number {i} sells mass-market sauce.", source_type="note",
                     author="u1", section_hint="competitors")
    full = brain.context_pack(brand, "pricing", max_tokens=100_000)
    assert "## One-liner" in full and "Competitor number 29" in full

    small = brain.context_pack(brand, "Made with Kerala chillies.", max_tokens=120)
    assert "Made with Kerala chillies." in small
    assert "omitted for length" in small
    assert len(small) // 4 <= 140


def test_proposal_accept_writes_claim(brain, brand) -> None:
    p = brain.propose(brand, "Position as the hot sauce for curry lovers.", section="positioning",
                      kind="idea", rationale="Matches customer language", origin="run",
                      origin_ref="run-1")
    assert [x.id for x in brain.list_proposals(brand)] == [p.id]

    claim = brain.accept_proposal(brand, p.id, by="u1")
    assert claim.status == "accepted" and claim.authority == "user_approved"
    assert brain.list_proposals(brand) == []
    decided = brain.list_proposals(brand, status="accepted")[0]
    assert decided.resulting_claim_id == claim.id
    pos = next(s for s in brain.brief(brand).sections if s.key == "positioning")
    assert pos.claims[0].text == "Position as the hot sauce for curry lovers."

    with pytest.raises(ProposalAlreadyDecided):
        brain.accept_proposal(brand, p.id, by="u1")


def test_proposal_reject_records_decision_claim(brain, brand) -> None:
    p = brain.propose(brand, "Price at $25.", section="price", kind="decision",
                      rationale="premium", origin="run", origin_ref="run-1")
    brain.reject_proposal(brand, p.id, by="u1", reason="Too expensive for grocery shelves")

    rejected = brain.list_proposals(brand, status="rejected")[0]
    assert rejected.decision_note == "Too expensive for grocery shelves"
    assert rejected.resulting_claim_id is None
    price = next(s for s in brain.brief(brand).sections if s.key == "price")
    assert len(price.claims) == 1
    c = price.claims[0]
    assert c.kind == "decision"
    assert "Price at $25." in c.text and "Too expensive" in c.text
