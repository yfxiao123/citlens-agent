"""LitSearch retrieval primitives — the LLM-free half of the bench module.

Provenance: these functions are copied VERBATIM from the CiteLens engine's
``citens/eval/litsearch.py`` (the LitSearch gold-paper bench, where every
constant below was measured). The engine module also contains the bench
harness and the LLM legs (planner / HyDE / pivot / cascade rerank); this
build has no LLM, so those stay in the engine repo and the calling AGENT
replaces them — it crafts the queries, and it judges relevance.

What lives here and why it matters:

* ``search_one_query`` — per-source cells with honest health buckets
  (ok / empty / failed): a throttled 429 must never be reportable as
  "zero hits".
* ``fuse_multi_query`` — Reciprocal Rank Fusion (score = Σ 1/(60 + rank)
  over query × source cells): score-free consensus fusion.
* ``oa_title_search`` — OpenAlex ``title.search`` cells, the dedicated
  title index that near-exact-title probes need.
* ``_key_of`` — the DOI/title identity used for dedup and fusion.

Do not "improve" these: the constants encode bench measurements.
"""

from __future__ import annotations

import asyncio
import re

from citens import cache
from citens.models import Paper
from citens.search.base import search_round

PER_SOURCE = 20  # per-source cell depth (== the union@20 ceiling)


# --- record identity ----------------------------------------------------------


def _norm_doi(doi: str | None) -> str:
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", (doi or "").strip().lower())


def _title_tokens(title: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", (title or "").lower()) if len(t) > 2}


def _key_of(p: Paper) -> str:
    return ("d:" + _norm_doi(p.doi)) if p.doi else (
        "t:" + " ".join(sorted(_title_tokens(p.title)))
    )


# --- per-source cells ---------------------------------------------------------


async def search_one_query(
    query: str,
    sources: list[str],
    per_source: int = PER_SOURCE,
    health_out: dict[str, list[int]] | None = None,
) -> dict[str, list[Paper]]:
    """Per-source result lists for one question (native relevance order).

    ``health_out`` accumulates per-source cell buckets [ok, empty, failed]
    across every call that passes it — an exhausted provider 429s into
    empty results that are indistinguishable from "the words didn't match"
    unless counted (measured: OpenAlex dies mid-day and silently zeros
    whole bench legs).
    """

    async def _one(s: str) -> list[Paper]:
        try:
            papers, health, _stats = await search_round(
                [query], max_results=per_source, sources=[s]
            )
            if health_out is not None:
                b = health_out.setdefault(s, [0, 0, 0])
                b[0] += 1
                if not papers:
                    h = health.get(s, "")
                    if h.startswith("failed"):
                        b[2] += 1
                        b[0] -= 1
                    else:
                        b[1] += 1
            return papers
        except Exception:  # noqa: BLE001 — a dead source must not kill the bench
            if health_out is not None:
                health_out.setdefault(s, [0, 0, 0])[2] += 1
            return []

    results = await asyncio.gather(*(_one(s) for s in sources))
    return dict(zip(sources, results, strict=True))


# --- OpenAlex title index -----------------------------------------------------


def oa_title_filter(title: str) -> str:
    """OpenAlex ``filter=title.search:`` payload for one candidate title.

    The relevance endpoint ranks full-text-ish matches; title.search is the
    dedicated title-index — for HyDE-generated titles it is precisely the
    near-exact-title matching shape that our dissection found to be the
    only reliable lexical retrieval form. HARD TRUNCATION to 5 informative
    words: title.search ANDs every term, and the 6-10-word conjunction of a
    SYNTHETIC title returns count=0 (bench 153205: the whole channel came
    back empty on 14/15 questions); the same gold probed at 4-5 words
    returns the gold itself at rank 1. The front-loaded words of a
    descriptive title is its concept core."""
    words = [w for w in re.findall(r"[A-Za-z0-9]+", title) if len(w) > 2]
    return " ".join(words[:5])


async def oa_title_search(
    titles: list[str], per_page: int = 20, fetch=None
) -> dict[str, list[Paper]]:
    """One OpenAlex title.search cell per candidate title (title-probe family).

    Cached like search results; empty responses are NOT cached (a throttled
    provider must not poison retries). ``fetch`` is injectable for tests.
    Skips entirely when the daily OpenAlex budget is spent — this channel is
    an optional precision add-on, never worth burning core-search quota for.
    """
    import httpx

    from citens.config import settings
    from citens.search.openalex import budget_exceeded, note_openalex_calls

    if budget_exceeded():
        return {}

    async def _default_fetch(filt: str) -> list[dict]:
        headers = {}
        if settings.openalex_email:
            headers["User-Agent"] = f"mailto:{settings.openalex_email}"
        from citens.search.openalex import apply_api_key

        async with httpx.AsyncClient(timeout=25, headers=headers) as hc:
            r = await hc.get(
                "https://api.openalex.org/works",
                params=apply_api_key(
                    {"filter": f"title.search:{filt}", "per-page": per_page}
                ),
            )
            note_openalex_calls()
            if r.status_code != 200:
                raise RuntimeError(f"openalex {r.status_code}")
            await asyncio.sleep(0.2)
            return r.json().get("results", [])

    fetch = fetch or _default_fetch
    out: dict[str, list[Paper]] = {}
    for t in titles:
        cache_ns, cache_key = "eval.oa-title", {"t": t}
        cached = cache.get(cache_ns, cache_key)
        if cached is None:
            try:
                works = await fetch(oa_title_filter(t))
            except Exception as e:  # noqa: BLE001 — a dead OA stays dead
                print(f"[oa-title] {t[:40]}… failed: {e}", flush=True)
                out[t] = []
                continue
            cached = [
                {
                    "title": w.get("display_name") or "",
                    "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
                    "year": w.get("publication_year"),
                    "cited": w.get("cited_by_count") or 0,
                    "abstract": "",
                }
                for w in works
            ]
            if any(c["title"] for c in cached):
                cache.put(cache_ns, cache_key, cached)
        out[t] = [
            Paper(
                title=c["title"],
                authors=[],
                year=c["year"],
                doi=c["doi"] or None,
                citation_count=c["cited"],
                source="oa-title",
            )
            for c in cached
        ]
    return out


# --- fusion -------------------------------------------------------------------


def interleave(per_source: dict[str, list[Paper]], order: list[str]) -> list[Paper]:
    """Round-robin fusion: rank r from every source before rank r+1 from any.
    Score-free, deterministic, and the fairest 'no-LLM' baseline."""
    merged: list[Paper] = []
    seen: set[str] = set()
    for r in range(PER_SOURCE):
        for s in order:
            if r >= len(per_source.get(s, [])):
                continue
            p = per_source[s][r]
            key = _key_of(p)
            if key in seen:
                continue
            seen.add(key)
            merged.append(p)
    return merged


def fuse_multi_query(
    per_query: dict[str, dict[str, list[Paper]]], sources: list[str]
) -> list[Paper]:
    """Production-style pool fusion for the planned leg: Reciprocal Rank
    Fusion — score = sum over (query, source) cells of 1/(60 + rank), the
    standard score-free combiner. Round-robin interleave buried papers that
    ranked high in ONE cell (measured: a gold at cell-rank ~5 landed fused
    #29); RRF promotes consensus plus single-cell excellence."""
    scores: dict[str, float] = {}
    papers_by_key: dict[str, Paper] = {}
    for qlists in per_query.values():
        for s in sources:
            for r, p in enumerate(qlists.get(s, [])):
                # score by KEY, not object identity: the same work returns
                # as distinct Paper objects from different cells
                key = _key_of(p)
                scores[key] = scores.get(key, 0.0) + 1.0 / (60 + r)
                papers_by_key.setdefault(key, p)
    return sorted(papers_by_key.values(), key=lambda p: -scores[_key_of(p)])
