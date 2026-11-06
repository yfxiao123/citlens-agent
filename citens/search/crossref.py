"""Crossref search + enrichment source (free, no key, huge DOI coverage).

Two roles:
  * a SearchSource registered as "crossref" (metadata + abstracts by relevance);
  * :func:`fetch_by_doi` — used by the enrichment step to fill missing abstracts
    via direct DOI lookup (Crossref deposits JATS abstracts for many works).
"""

from __future__ import annotations

import asyncio
import re

import httpx

from citens import net
from citens.config import settings
from citens.models import Paper
from citens.search.base import SearchSource, register

_BASE = "https://api.crossref.org"
_JATS_RE = re.compile(r"<[^>]+>")
_LIMITER = "crossref"
_UA = {"User-Agent": "CiteLens/0.1"}


def _polite_params() -> dict:
    return {"mailto": settings.crossref_email} if settings.crossref_email else {}


def _clean_abstract(raw: str | None) -> str:
    if not raw:
        return ""
    return re.sub(r"\s+", " ", _JATS_RE.sub(" ", raw)).strip()


# Crossref indexes supplementary files, appendices and media attachments as
# separate "works". They are not papers: they have titles like "Appendix",
# "Supplemental Information 2: …" or "…_sup", and DOIs ending in /mm1 or
# /supp-2. Left in, they entered the pool as ordinary records and produced
# junk references (third-party report, live-recall P2-5).
_COMPONENT_TITLE_RE = re.compile(
    r"^(?:appendix|appendices|supplement(?:ary|al)?\b|supporting information\b|"
    r"supplementary material\b)",
    re.IGNORECASE,
)
_COMPONENT_DOI_RE = re.compile(r"(?:/mm\d+|/suppl?-\d+|/suppl?ement\w*)$", re.IGNORECASE)
_COMPONENT_TYPE = {"component", "dataset", "peer-review", "grant", "annotation"}


def _is_component(item: dict) -> bool:
    """True for Crossref supplementary/attachment records, not real works."""
    if (item.get("type") or "").strip().lower() in _COMPONENT_TYPE:
        return True
    title = ((item.get("title") or [""])[0] or "").strip()
    if _COMPONENT_TITLE_RE.match(title):
        return True
    if title.lower().endswith(("_sup", "_supp", " appendix")):
        return True
    return bool(_COMPONENT_DOI_RE.search((item.get("DOI") or "").strip()))


@register("crossref")
class CrossrefSearcher(SearchSource):
    name = "Crossref"

    async def search(self, keywords: list[str], max_results: int) -> list[Paper]:
        per_keyword = max(max_results // max(len(keywords), 1), 5)
        from citens.search.base import SEARCH_CONCURRENCY

        sem = asyncio.Semaphore(SEARCH_CONCURRENCY)

        async def _guarded(q: str) -> list[Paper]:
            async with sem:
                return await self._one(client, q, per_keyword)

        async with net.async_client(_LIMITER, timeout=30, headers=_UA) as client:
            results = await asyncio.gather(
                *(_guarded(kw) for kw in keywords), return_exceptions=True
            )
        return self._collect_cells(keywords, results)

    async def _one(self, client: httpx.AsyncClient, query: str, limit: int) -> list[Paper]:
        params: dict[str, str | int] = {
            "query.bibliographic": query,
            "rows": min(limit, 30),
            **_polite_params(),
        }
        # native Crossref date filters for the clarification year window
        filters: list[str] = []
        if self.constraints and self.constraints.year_from:
            filters.append(f"from-pub-date:{self.constraints.year_from}-01-01")
        if self.constraints and self.constraints.year_to:
            filters.append(f"until-pub-date:{self.constraints.year_to}-12-31")
        if filters:
            params["filter"] = ",".join(filters)
        resp = await client.get(f"{_BASE}/works", params=params)
        resp.raise_for_status()
        items = resp.json().get("message", {}).get("items", [])
        out = [self._to_paper(it) for it in items if not _is_component(it)]
        for p in out:
            p.matched_queries.append(query)  # retrieval provenance
        self.query_stats[query] = len(out)
        return out

    @staticmethod
    def _to_paper(item: dict) -> Paper:
        authors = []
        for a in item.get("author", []):
            name = (a.get("given", "") + " " + a.get("family", "")).strip()
            if name:
                authors.append(name)
        doi = item.get("DOI")
        links = [
            lk.get("URL") for lk in item.get("link", []) if lk.get("content-type") == "application/pdf"
        ]
        return Paper(
            title=(item.get("title") or [""])[0],
            authors=authors,
            year=_year(item),
            abstract=_clean_abstract(item.get("abstract")),
            source="Crossref",
            citation_count=item.get("is-referenced-by-count", 0) or 0,
            url=item.get("URL", "") or (f"https://doi.org/{doi}" if doi else ""),
            doi=doi,
            pdf_url=links[0] if links else None,
            venue=(item.get("container-title") or [""])[0] or "",
            volume=str(item.get("volume") or ""),
            issue=str(item.get("issue") or ""),
            pages=str(item.get("page") or "").replace("–", "-"),
        )


def _year(item: dict) -> int | None:
    for key in ("published-print", "published-online", "issued", "created"):
        parts = (item.get(key) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            return int(parts[0][0])
    return None


def fetch_abstract_by_doi(doi: str) -> str:
    """Direct DOI lookup → cleaned abstract (empty string if unavailable)."""
    if not doi:
        return ""
    try:
        with net.sync_client(name=_LIMITER, timeout=20, headers=_UA) as client:
            r = client.get(f"{_BASE}/works/{doi}", params=_polite_params())
            if r.status_code != 200:
                return ""
            return _clean_abstract(r.json()["message"].get("abstract"))
    except Exception:  # noqa: BLE001
        return ""


def fetch_work_by_doi(doi: str) -> dict:
    """Best-effort metadata for a bare DOI (title/authors/year/abstract/venue).

    `fetch --doi` on a paywalled paper used to report "abstract-only" with an
    EMPTY abstract because nothing looked the record up (third-party report
    P2-8). One Crossref call fills it; failure degrades to {}.
    """
    if not doi:
        return {}
    try:
        with net.sync_client(name=_LIMITER, timeout=20, headers=_UA) as client:
            r = client.get(f"{_BASE}/works/{doi}", params=_polite_params())
            if r.status_code != 200:
                return {}
            p = CrossrefSearcher._to_paper(r.json()["message"])
            return {
                "title": p.title, "authors": p.authors, "year": p.year,
                "abstract": p.abstract, "venue": p.venue, "doi": p.doi,
            }
    except Exception:  # noqa: BLE001
        return {}
