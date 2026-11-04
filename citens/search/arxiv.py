"""arXiv search source (free, no key). The official client is synchronous and
sleeps between pages; we run it in a worker thread so it never blocks the
event loop while other sources query concurrently."""

from __future__ import annotations

import asyncio

import arxiv

from citens.models import Paper
from citens.search.base import SearchSource, failure_reason, register


@register("arxiv")
class ArxivSearcher(SearchSource):
    name = "arXiv"

    # Whole-call budget. arXiv server-side rate-limits shared egress IPs
    # (measured: 16s-to-respond 429s, then read timeouts) and the arxiv
    # client's urllib layer has NO per-request timeout — an unlucky network
    # crawled 20+ minutes and still returned nothing. Cut the loss instead:
    # the other sources continue, and the run is honest about arXiv's
    # absence — the timeout is RAISED, so it reads as "failed", not "empty",
    # and feeds the circuit breaker (the recall leg runs its queries one
    # after another; without the breaker 15 queries meant 15 x 90 s).
    SOURCE_TIMEOUT_S = 90

    async def search(self, keywords: list[str], max_results: int) -> list[Paper]:
        self.failed_queries = {}
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._search_sync, keywords, max_results),
                timeout=self.SOURCE_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"arXiv gave no response within {self.SOURCE_TIMEOUT_S}s "
                "(export.arxiv.org throttles some egress IPs)"
            ) from None

    def _search_sync(self, keywords: list[str], max_results: int) -> list[Paper]:
        client = arxiv.Client(page_size=100, delay_seconds=3, num_retries=3)
        # floor of 5 matches the other sources: with 10+ queries the share
        # drops to 1 and arXiv — the source where nearly every hit carries a
        # fetchable PDF — contributes almost nothing to the pool
        per_kw = max(max_results // max(len(keywords), 1), 5)
        out: list[Paper] = []
        last_err: BaseException | None = None
        for kw in keywords:
            try:
                search = arxiv.Search(
                    query=kw,
                    max_results=per_kw,
                    sort_by=arxiv.SortCriterion.Relevance,
                )
                hits = [self._to_paper(result) for result in client.results(search)]
                # arXiv has no client-friendly date filter in this wrapper —
                # the clarification year window is applied post-hoc (arXiv
                # records always carry a published date, so None-year never
                # silently drops here)
                if self.constraints:
                    hits = [p for p in hits if self.constraints.matches_paper(p)]
                for p in hits:
                    p.matched_queries.append(kw)  # retrieval provenance
                self.query_stats[kw] = len(hits)
                out.extend(hits)
            except Exception as e:  # noqa: BLE001 — one dead query ≠ dead source
                self.failed_queries[kw] = failure_reason(e)
                last_err = e
        if last_err is not None and len(self.failed_queries) == len(keywords):
            raise last_err
        return out

    @staticmethod
    def _to_paper(result: arxiv.Result) -> Paper:
        return Paper(
            title=result.title,
            authors=[a.name for a in result.authors],
            year=result.published.year if result.published else None,
            abstract=result.summary,
            source="arXiv",
            citation_count=0,  # arXiv exposes no citation counts
            url=result.entry_id,
            doi=result.doi,
            venue=getattr(result, "journal_ref", "") or "",
        )
