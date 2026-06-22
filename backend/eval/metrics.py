"""Pure, dependency-free metric functions for RAG evaluation.

Kept free of any `app.*` import so the metric math is unit-testable without
booting the stack. The eval runner adapts live `Citation` objects into the
lightweight tuples these functions expect.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GoldenItem:
    """One labelled question with its ground-truth source page."""

    id: str
    query: str
    document_id: str
    file_name: str
    page_number: int
    expected_answer: str = ""
    source_excerpt: str = ""


@dataclass(frozen=True)
class RetrievedCitation:
    """A citation the system returned, reduced to what scoring needs."""

    document_id: str
    start_page: int
    end_page: int


@dataclass
class Outcome:
    """Scored result for one golden item."""

    item: GoldenItem
    status: str
    answer: str
    citations: list[RetrievedCitation]
    latency_ms: float
    doc_hit: bool = False
    page_hit: bool = False
    rank: int | None = None  # 1-based position of first page-hit citation
    faithful: bool | None = None  # set only when --judge is used


def citation_covers_page(citation: RetrievedCitation, document_id: str, page: int) -> bool:
    """True when the citation is the right document AND its page range covers `page`.

    Page ranges are treated as inclusive on both ends, matching how the UI labels
    citations ("第 1-1 頁").
    """
    return (
        citation.document_id == document_id
        and citation.start_page <= page <= citation.end_page
    )


def score_citations(
    item: GoldenItem, citations: list[RetrievedCitation]
) -> tuple[bool, bool, int | None]:
    """Return (doc_hit, page_hit, rank) for one item against its citations.

    - doc_hit: the ground-truth document appears in any citation.
    - page_hit: some citation covers the ground-truth page.
    - rank: 1-based index of the FIRST citation that covers the page (None if no
      page hit). Citation order is the system's own ranking, so this drives MRR.
    """
    doc_hit = any(c.document_id == item.document_id for c in citations)
    rank: int | None = None
    for index, citation in enumerate(citations, start=1):
        if citation_covers_page(citation, item.document_id, item.page_number):
            rank = index
            break
    return doc_hit, rank is not None, rank


def reciprocal_rank(rank: int | None) -> float:
    """1/rank for a hit, 0.0 for a miss. Mean over items = MRR."""
    return 0.0 if rank is None else 1.0 / rank


@dataclass
class Aggregate:
    n: int = 0
    doc_hit_rate: float = 0.0
    page_hit_rate: float = 0.0
    mrr: float = 0.0
    answered_rate: float = 0.0
    faithful_rate: float | None = None
    mean_latency_ms: float = 0.0
    per_status: dict[str, int] = field(default_factory=dict)


def aggregate(outcomes: list[Outcome]) -> Aggregate:
    """Roll per-item outcomes into headline metrics. Empty input → all zeros."""
    n = len(outcomes)
    if n == 0:
        return Aggregate()

    per_status: dict[str, int] = {}
    for o in outcomes:
        per_status[o.status] = per_status.get(o.status, 0) + 1

    judged = [o for o in outcomes if o.faithful is not None]
    faithful_rate = (
        sum(1 for o in judged if o.faithful) / len(judged) if judged else None
    )

    return Aggregate(
        n=n,
        doc_hit_rate=sum(1 for o in outcomes if o.doc_hit) / n,
        page_hit_rate=sum(1 for o in outcomes if o.page_hit) / n,
        mrr=sum(reciprocal_rank(o.rank) for o in outcomes) / n,
        answered_rate=sum(1 for o in outcomes if o.status == "answered") / n,
        faithful_rate=faithful_rate,
        mean_latency_ms=sum(o.latency_ms for o in outcomes) / n,
        per_status=per_status,
    )
