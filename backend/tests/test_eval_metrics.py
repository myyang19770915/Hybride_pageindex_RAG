"""Unit tests for the pure eval metric functions."""

from eval.metrics import (
    GoldenItem,
    Outcome,
    RetrievedCitation,
    aggregate,
    citation_covers_page,
    reciprocal_rank,
    score_citations,
)


def _item(doc="doc_a", page=5) -> GoldenItem:
    return GoldenItem(id="t", query="q", document_id=doc, file_name="a.pdf", page_number=page)


def test_citation_covers_page_inclusive_bounds() -> None:
    c = RetrievedCitation("doc_a", 3, 5)
    assert citation_covers_page(c, "doc_a", 3) is True   # lower bound
    assert citation_covers_page(c, "doc_a", 5) is True   # upper bound
    assert citation_covers_page(c, "doc_a", 4) is True
    assert citation_covers_page(c, "doc_a", 6) is False  # outside range
    assert citation_covers_page(c, "doc_b", 4) is False  # wrong document


def test_score_citations_page_hit_sets_rank() -> None:
    item = _item(page=5)
    citations = [
        RetrievedCitation("doc_a", 1, 2),   # wrong page
        RetrievedCitation("doc_a", 4, 6),   # covers page 5 -> rank 2
    ]
    doc_hit, page_hit, rank = score_citations(item, citations)
    assert doc_hit is True
    assert page_hit is True
    assert rank == 2


def test_score_citations_doc_hit_without_page_hit() -> None:
    item = _item(page=99)
    citations = [RetrievedCitation("doc_a", 1, 2)]
    doc_hit, page_hit, rank = score_citations(item, citations)
    assert doc_hit is True
    assert page_hit is False
    assert rank is None


def test_score_citations_complete_miss() -> None:
    item = _item()
    doc_hit, page_hit, rank = score_citations(item, [RetrievedCitation("doc_x", 1, 9)])
    assert (doc_hit, page_hit, rank) == (False, False, None)


def test_reciprocal_rank() -> None:
    assert reciprocal_rank(1) == 1.0
    assert reciprocal_rank(2) == 0.5
    assert reciprocal_rank(None) == 0.0


def test_aggregate_empty_is_all_zero() -> None:
    agg = aggregate([])
    assert agg.n == 0
    assert agg.doc_hit_rate == 0.0
    assert agg.mrr == 0.0


def test_aggregate_rolls_up_rates_and_mrr() -> None:
    item = _item()
    outcomes = [
        Outcome(item, "answered", "a", [], 100.0, doc_hit=True, page_hit=True, rank=1),
        Outcome(item, "answered", "a", [], 300.0, doc_hit=True, page_hit=False, rank=None),
        Outcome(item, "insufficient", "a", [], 200.0, doc_hit=False, page_hit=False, rank=None),
    ]
    agg = aggregate(outcomes)
    assert agg.n == 3
    assert agg.doc_hit_rate == 2 / 3
    assert agg.page_hit_rate == 1 / 3
    assert agg.mrr == 1.0 / 3          # only the rank-1 hit contributes
    assert agg.answered_rate == 2 / 3
    assert agg.mean_latency_ms == 200.0
    assert agg.per_status == {"answered": 2, "insufficient": 1}
    assert agg.faithful_rate is None   # nothing judged


def test_aggregate_faithful_rate_only_counts_judged() -> None:
    item = _item()
    o1 = Outcome(item, "answered", "a", [], 1.0, doc_hit=True, page_hit=True, rank=1)
    o1.faithful = True
    o2 = Outcome(item, "answered", "a", [], 1.0, doc_hit=True, page_hit=True, rank=1)
    o2.faithful = False
    o3 = Outcome(item, "answered", "a", [], 1.0, doc_hit=True, page_hit=True, rank=1)  # unjudged
    agg = aggregate([o1, o2, o3])
    assert agg.faithful_rate == 0.5
