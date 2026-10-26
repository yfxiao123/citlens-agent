"""Seed-anchored pool expansion — the judgment feedback loop.

The full-set LitSearch bench (2026-10-24) measured WHY golds go missing: with
the natural-language question as the only query, 71% of missed golds share
<=2 content words with it — no re-ranking can rescue a paper the query's
vocabulary never reached. The two cures that bypass query vocabulary are
citation chaining and similarity recommendations, and the best seeds for
both are the papers the CALLING AGENT has already judged on-topic.

    search → screen → you judge a few records core
          → expand --seeds <those papers>          (this module)
          → their references / citers / neighbors join the pool

A seed is whatever the agent has in hand: a DOI, an arXiv id, or a title
(resolved via the S2 graph API; arXiv-only seeds get the DataCite DOI
``10.48550/arxiv.<id>`` synthesized so the OpenAlex citation directions can
resolve them — S2 itself reaches them as ``ARXIV:<id>``).

Mechanically this is the shipped snowball + S2-recommendation families
re-anchored on explicit seeds instead of the pool head, so every
provenance/health/cache discipline of those families applies unchanged.
Expansion is NOT a relevance judgment: every added record still goes through
the same screen/judge pipeline, with ``found_by: ["expand"]`` marking how it
arrived.
"""

from __future__ import annotations

import asyncio
import re

import httpx

from citens import cache
from citens.models import Paper
from citens.search.snowball import (
    _s2_headers,
    _s2_paper_id,
    _s2_recommended,
    _s2_to_paper,
    is_article_doi,
    snowball,
)

_S2_GRAPH = "https://api.semanticscholar.org/graph/v1/paper"
_S2_FIELDS = "title,authors,year,abstract,citationCount,externalIds,venue,url,openAccessPdf"
_MAX_SEEDS = 6  # snowball's own anchor cap; bound the API fan-out here too

_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
_ARXIV_RE = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$", re.IGNORECASE)


def seed_kind(seed: str) -> str:
    """Classify a seed string as "doi" | "arxiv" | "title"."""
    s = seed.strip()
    low = s.lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if low.startswith(prefix):
            s = s[len(prefix):]
            low = s.lower()
            break
    if _DOI_RE.match(low):
        return "doi"
    core = low
    for prefix in ("arxiv:", "https://arxiv.org/abs/", "http://arxiv.org/abs/"):
        if core.startswith(prefix):
            core = core[len(prefix):]
            break
    if _ARXIV_RE.match(core):
        return "arxiv"
    return "title"


def _s2_lookup_id(seed: str, kind: str) -> str:
    if kind == "doi":
        # _s2_paper_id routes arXiv's DataCite DOIs (10.48550/...) to ARXIV:
        # — S2 404s on DOI:10.48550/* (measured in the snowball family)
        return _s2_paper_id(seed.strip())
    if kind == "arxiv":
        core = seed.strip().lower()
        for prefix in ("arxiv:", "https://arxiv.org/abs/", "http://arxiv.org/abs/"):
            if core.startswith(prefix):
                core = core[len(prefix):]
                break
        return "ARXIV:" + re.sub(r"v\d+$", "", core)
    raise ValueError(f"title seeds resolve via the search endpoint, not lookup: {seed!r}")


async def resolve_seed(seed: str, fetch=None) -> tuple[Paper | None, str]:
    """Resolve one seed to a Paper via the S2 graph API (disk-cached).

    Returns ``(paper, note)``; paper is None with an honest reason when the
    seed cannot be resolved. ``fetch`` is injectable for offline tests and
    takes ``(url, params)``.
    """
    kind = seed_kind(seed)
    hit = cache.get("expand.seed", {"seed": seed})
    if isinstance(hit, dict):
        return (Paper(**hit["paper"]) if hit.get("paper") else None), hit.get("note", "")
    from citens.search.semantic_scholar import _throttled_get

    async def _default_fetch(url: str, params: dict) -> dict:
        async with httpx.AsyncClient(timeout=30, headers=_s2_headers()) as client:
            resp = await _throttled_get(client, url, params=params)
            if resp.status_code != 200:
                raise RuntimeError(f"s2 {resp.status_code}")
            return resp.json()

    fetch = fetch or _default_fetch
    item: dict | None = None
    try:
        if kind == "title":
            data = await fetch(
                _S2_GRAPH + "/search",
                {"query": seed.strip(), "limit": 1, "fields": _S2_FIELDS},
            )
            hits = data.get("data") or []
            item = hits[0] if hits else None
        else:
            item = await fetch(
                f"{_S2_GRAPH}/{_s2_lookup_id(seed, kind)}", {"fields": _S2_FIELDS}
            )
    except Exception as e:  # noqa: BLE001 — an unresolvable seed must not kill the rest
        cache.put("expand.seed", {"seed": seed}, {"paper": None, "note": f"resolve failed: {str(e)[:120]}"})
        return None, f"resolve failed: {str(e)[:120]}"

    if not item or not (item.get("title") or "").strip():
        note = "not found" if kind != "title" else "no search hit"
        cache.put("expand.seed", {"seed": seed}, {"paper": None, "note": note})
        return None, note

    from citens.search.semantic_scholar import SemanticScholarSearcher

    paper = SemanticScholarSearcher._to_paper(item)
    # snowball's OpenAlex directions key on a DOI; arXiv-only seeds carry none,
    # so synthesize the DataCite DOI arXiv mints for every preprint (S2 itself
    # keeps answering via ARXIV:<id> — _s2_paper_id converts it back)
    arx = (item.get("externalIds") or {}).get("ArXiv") or ""
    if not paper.doi and arx:
        paper.doi = f"10.48550/arxiv.{arx}"
    if not is_article_doi(paper.doi):
        cache.put("expand.seed", {"seed": seed},
                  {"paper": paper.model_dump(), "note": "resolved (non-article DOI — citation directions skipped)"})
        return paper, "resolved (non-article DOI — citation directions skipped)"
    cache.put("expand.seed", {"seed": seed}, {"paper": paper.model_dump(), "note": f"resolved via {kind}"})
    return paper, f"resolved via {kind}"


async def expand_from_seeds(
    seeds: list[str],
    existing_ids: set[str],
    *,
    directions: set[str] | None = None,
    relevance_terms: list[str] | None = None,
    limit_per_paper: int = 20,
    top: int = 30,
) -> dict:
    """Expand around explicit seed papers (see module docstring).

    Returns ``{"anchors", "unresolved", "papers", "counts"}``; ``papers`` are
    NEW to the pool (existing ids filtered), stamped ``found_by=["expand"]``.
    Triage, never judgment — relevance is still the caller's call.
    """
    directions = directions or {"backward", "forward", "related", "recs"}
    resolved = await asyncio.gather(*(resolve_seed(s) for s in seeds[:_MAX_SEEDS]))
    anchors: list[Paper] = []
    unresolved: list[dict] = []
    for seed, (paper, note) in zip(seeds[:_MAX_SEEDS], resolved, strict=True):
        if paper is None or not paper.doi:
            unresolved.append({"seed": seed, "reason": note})
        else:
            anchors.append(paper)
    if len(seeds) > _MAX_SEEDS:
        unresolved.append({"seed": f"(+{len(seeds) - _MAX_SEEDS} more)",
                           "reason": f"seed cap is {_MAX_SEEDS}"})

    out: dict[str, Paper] = {}
    snowballed: list[Paper] = []
    # citation directions resolve by DOI — non-article DOIs (figures,
    # reviews-of) only waste the fan-out, so only article DOIs anchor them
    snowball_anchors = [p for p in anchors if is_article_doi(p.doi)]
    if snowball_anchors and (directions & {"backward", "forward", "related"}):
        snowballed = await snowball(
            snowball_anchors,
            existing_ids,
            backward="backward" in directions,
            forward="forward" in directions,
            related="related" in directions,
            relevance_terms=relevance_terms,
            limit_per_paper=limit_per_paper,
            top=top,
        )
    recommended: list[Paper] = []
    if anchors and "recs" in directions:
        rec_dois = [p.doi for p in anchors if is_article_doi(p.doi)][:5]
        if rec_dois:
            items = await _s2_recommended(rec_dois, limit=top)
            recommended = [
                r for r in (
                    _s2_to_paper(item, "expand-recs", ",".join(rec_dois)[:30])
                    for item in items
                ) if r is not None
            ]
    for p in [*snowballed, *recommended]:
        if p.id not in existing_ids:
            p.found_by = ["expand"]
            out.setdefault(p.id, p)
    return {
        "anchors": [
            {"title": p.title, "doi": p.doi, "citation_count": p.citation_count}
            for p in anchors
        ],
        "unresolved": unresolved,
        "papers": list(out.values()),
        "counts": {
            "seeds": len(seeds), "resolved": len(anchors),
            "snowball": len(snowballed), "recs": len(recommended),
            "new": len(out),
        },
    }
