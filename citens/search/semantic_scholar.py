"""Semantic Scholar search source.

Uses the ``/paper/search/bulk`` endpoint which is markedly more reliable than
the classic ``/paper/search`` (the latter is rate-limited / connection-reset
under modest load). Bulk ignores ``limit`` and returns up to 1000 ranked docs,
so we slice client-side.

Authenticated tier (``SEMANTIC_SCHOLAR_API_KEY``): the key MUST travel as an
``x-api-key`` header and is capped at 1 request/second **cumulative across all
endpoints** — so every S2 request in the process goes through one shared
limiter (``citens.net.limiter("semantic_scholar")``) that spaces request
starts, key or no key (the unauthenticated pool is throttled even harder, so
it gets a wider spacing). 429s, 5xx and connection resets are retried by the
client's transport (``citens.net.async_client``) with ``Retry-After`` honoured;
a query that is still failing after that is reported as failed — never as
"zero hits".
"""

from __future__ import annotations

import asyncio

import httpx

from citens import net
from citens.config import settings
from citens.models import Paper
from citens.search.base import SearchSource, register

_LIMITER = "semantic_scholar"


def _s2_headers() -> dict[str, str]:
    headers = {"User-Agent": "CiteLens/0.1"}
    if settings.semantic_scholar_api_key:
        headers["x-api-key"] = settings.semantic_scholar_api_key
    return headers


def s2_client(timeout: float = 30) -> httpx.AsyncClient:
    """An S2 client: shared process-wide spacing + retrying transport."""
    return net.async_client(_LIMITER, timeout=timeout, headers=_s2_headers())


async def _throttled_get(
    client: httpx.AsyncClient, url: str, *, params: dict,
    headers: dict | None = None,
) -> httpx.Response:
    """One S2 GET behind the shared S2 limiter.

    Kept for the callers that build their own client (expand / snowball /
    survey_seed): a plain httpx client still gets the spacing here; a client
    from ``s2_client()`` already waits in its transport and is not spaced
    twice. Retries are the transport's job either way.
    """
    if net.throttled_by(client) != _LIMITER:
        await net.limiter(_LIMITER).wait()
    return await client.get(url, params=params, headers=headers)


async def _throttled_post(
    client: httpx.AsyncClient, url: str, *, params: dict, json_body: dict
) -> httpx.Response:
    if net.throttled_by(client) != _LIMITER:
        await net.limiter(_LIMITER).wait()
    return await client.post(url, params=params, json=json_body)


@register("semantic_scholar")
class SemanticScholarSearcher(SearchSource):
    name = "Semantic Scholar"
    BASE_URL = "https://api.semanticscholar.org/graph/v1"

    def __init__(self) -> None:
        super().__init__()
        self.headers = _s2_headers()

    async def search(self, keywords: list[str], max_results: int) -> list[Paper]:
        per_keyword = max(max_results // max(len(keywords), 1), 5)
        from citens.search.base import SEARCH_CONCURRENCY

        sem = asyncio.Semaphore(SEARCH_CONCURRENCY)

        async def _guarded(q: str) -> list[Paper]:
            async with sem:
                return await self._one(client, q, per_keyword)

        async with s2_client() as client:
            results = await asyncio.gather(
                *(_guarded(kw) for kw in keywords), return_exceptions=True
            )
        return self._collect_cells(keywords, results)

    async def _one(self, client: httpx.AsyncClient, query: str, limit: int) -> list[Paper]:
        params: dict[str, str] = {
            "query": query,
            # openAccessPdf: free OA pdf link (preprints + green-OA deposits).
            # Without it S2 records carry no pdf_url and fulltext grounding
            # falls back to arXiv title lookup + Unpaywall.
            "fields": (
                "title,authors,year,abstract,citationCount,externalIds,url,"
                "venue,openAccessPdf"
            ),
        }
        if self.constraints and (self.constraints.year_from or self.constraints.year_to):
            import datetime

            yf = self.constraints.year_from or 1900
            yt = self.constraints.year_to or datetime.date.today().year
            params["year"] = f"{yf}-{yt}"
        resp = await client.get(f"{self.BASE_URL}/paper/search/bulk", params=params)
        resp.raise_for_status()
        data = resp.json().get("data", [])[:limit]
        papers = [self._to_paper(item) for item in data]
        for p in papers:
            p.matched_queries.append(query)  # retrieval provenance
        self.query_stats[query] = len(papers)
        return papers

    @staticmethod
    def _to_paper(item: dict) -> Paper:
        authors = [a.get("name", "") for a in item.get("authors", []) if a.get("name")]
        ext_ids = item.get("externalIds") or {}
        oa_pdf = (item.get("openAccessPdf") or {}).get("url") or ""
        return Paper(
            title=item.get("title", ""),
            authors=authors,
            year=item.get("year"),
            abstract=item.get("abstract") or "",
            source="Semantic Scholar",
            citation_count=item.get("citationCount", 0) or 0,
            url=item.get("url") or "",
            doi=ext_ids.get("DOI"),
            venue=item.get("venue") or "",
            pdf_url=oa_pdf or None,
        )


async def _batch_arxiv_lookup(ids: list[str]) -> dict[str, tuple[int, str | None]]:
    """One S2 batch call: arXiv id -> (citationCount, DOI), aligned response."""
    async with s2_client() as client:
        resp = await client.post(
            "https://api.semanticscholar.org/graph/v1/paper/batch",
            params={"fields": "citationCount,externalIds"},
            json={"ids": [f"ARXIV:{i}" for i in ids]},
        )
        resp.raise_for_status()
        data = resp.json()
    out: dict[str, tuple[int, str | None]] = {}
    for pid, item in zip(ids, data, strict=False):
        if item:
            out[pid] = (
                item.get("citationCount") or 0,
                (item.get("externalIds") or {}).get("DOI"),
            )
    return out


async def enrich_citations(
    papers: list[Paper], max_ids: int = 200, _lookup=None
) -> int:
    """Fill citation_count/doi on arXiv-leg captures via one S2 batch join.

    The arXiv API exposes no citation counts, so every arXiv-only capture
    carries citation_count=0 — a field-defining work then sorts as if
    uncited and blend_pool's citation trim drops it before the LLM filter
    ever sees it (measured on the RAG bench run: Lewis 2020, captured via
    the arXiv leg only, cut at the 24-cap). Joining by arXiv id restores
    the true count and gives the published DOI.

    Degrades to a no-op on any failure (returns 0): enrichment is an
    optimization for ranking, never a dependency of the run. Transient
    transport errors (the common failure here) are retried by the client's
    transport before they ever reach this fallback.
    """
    from citens.search.base import paper_arxiv_id

    targets = [
        p for p in papers if p.citation_count == 0 and paper_arxiv_id(p)
    ][:max_ids]
    if not targets:
        return 0
    lookup = _lookup or _batch_arxiv_lookup
    try:
        info = await lookup([paper_arxiv_id(p) or "" for p in targets])
    except Exception as e:  # noqa: BLE001 — a failed join must not fail the run
        print(
            "[enrich_citations] S2 batch join failed, "
            f"keeping citation_count=0: {e}"
        )
        return 0
    updated = 0
    for p in targets:
        hit = info.get(paper_arxiv_id(p) or "")
        if not hit:
            continue
        count, doi = hit
        p.citation_count = count
        if not p.doi and doi:
            p.doi = doi
        updated += 1
    return updated
