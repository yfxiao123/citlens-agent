"""Policy-research corpus — NBER, Federal Reserve Board, IMF, via Crossref.

Why this source exists: the scholarly families speak journal/preprint
vocabulary. A FEDS Note or an NBER working paper enters those pools only when
a journal query happens to match its title, and once inside nothing
distinguishes policy-side research from journal evidence. All three
institutions deposit DOIs with Crossref (measured 2026-10-28: NBER 36k works
under 10.3386; Fed Board ~5k under 10.17016 including 789 FEDS Notes and the
FEDS/IFDP working-paper series; IMF 106k under 10.5089), and the
``/prefixes/{id}/works`` route accepts relevance queries — one mechanical
channel, no scraping, no keys, no LLM.

Not covered: regional Fed banks, BIS, ECB — their policy papers carry no
Crossref DOIs (measured same day: BIS prefix 404, ECB 14 works), so they stay
behind the web bridge, which is the documented posture for DOI-less corpora.

Registered as "policy" but deliberately NOT imported by
``citens/search/__init__.py`` (the websearch pattern): the family runs only
when the recall driver enables it, so the raw multi-source search never pays
for orgs it did not ask about.
"""

from __future__ import annotations

import asyncio

import httpx

from citens.models import Paper
from citens.search.base import SearchSource, register

_CROSSREF = "https://api.crossref.org/prefixes"
_OPENALEX_WORK = "https://api.openalex.org/works/doi:"

# DOI prefixes of policy-research institutions that deposit with Crossref.
POLICY_ORGS: dict[str, dict] = {
    "10.3386": {"org": "NBER"},
    "10.17016": {"org": "Federal Reserve Board"},
    "10.5089": {"org": "IMF"},
}


def _policy_kind(prefix: str, venue: str) -> str:
    """Document kind inside a policy org, by deposited container-title.

    The container strings are stable and typo-tolerant matched ("Finanace and
    Economics Discussion Series" is a real deposited variant): FEDS Notes /
    IFDP Notes are the short policy notes written for decision-makers, the
    Discussion Series are technical working papers, the Bulletin and datasets
    are reports. NBER deposits everything as bare reports with no container.
    """
    v = (venue or "").lower()
    if "note" in v:
        return "policy_note"
    if "discussion" in v:
        return "working_paper"
    if prefix == "10.5089":
        return "working_paper" if "working paper" in v else "report"
    if prefix == "10.17016":
        return "report"
    return "working_paper"  # NBER


def classify_doc_type(p: Paper) -> tuple[str, str]:
    """(doc_type, policy_org) for ANY pool record — journal family or policy.

    Mechanical: DOI prefix first (exact), then URL/venue heuristics for
    preprints and undeposited working-paper series. Unknown records get
    ("", "") and stay untagged rather than guessed.
    """
    doi = (p.doi or "").lower()
    for prefix, meta in POLICY_ORGS.items():
        if doi.startswith(prefix + "/"):
            return _policy_kind(prefix, p.venue), meta["org"]
    if (
        doi.startswith("10.48550/")
        or "arxiv.org" in (p.url or "").lower()
        or (p.venue or "").lower().startswith("arxiv")
    ):
        return "preprint", ""
    venue = (p.venue or "").lower()
    if "ssrn" in venue or "working paper" in venue:
        return "working_paper", ""
    if venue.endswith("notes") or "policy note" in venue or "bulletin" in venue:
        return "policy_note", ""
    if p.venue:
        return "journal", ""
    return "", ""


def stamp_doc_types(papers: list[Paper]) -> None:
    """Fill doc_type/policy_org in place, never overwriting existing tags
    (the policy source stamps its own records with the richer prefix+container
    rule; this pass covers everything the other families surfaced)."""
    for p in papers:
        if not p.doc_type and not p.policy_org:
            p.doc_type, p.policy_org = classify_doc_type(p)


async def enrich_abstracts(
    papers: list[Paper], limit: int = 14, transport: httpx.AsyncBaseTransport | None = None
) -> int:
    """Fill empty abstracts/pdf_urls from OpenAlex single-record DOI views.

    Crossref deposits no abstracts for NBER/Fed records (measured), and
    abstract-less records screen badly. Single-record views cost no credits
    (VIEW_CREDITS = 0), so this enrichment is free; failures are silent — the
    record joins the pool either way, tagged by title only.
    """
    from citens.search.openalex import OpenAlexSearcher, apply_api_key

    targets = sorted(
        (p for p in papers if not p.abstract and p.doi),
        key=lambda p: p.citation_count, reverse=True,
    )[:limit]
    if not targets:
        return 0
    sem = asyncio.Semaphore(4)

    async def _one(p: Paper) -> int:
        async with sem:
            try:
                async with httpx.AsyncClient(
                    timeout=20, headers={"User-Agent": "CiteLens/0.1"}, transport=transport
                ) as client:
                    r = await client.get(
                        _OPENALEX_WORK + p.doi,
                        params=apply_api_key({
                            "select": "abstract_inverted_index,best_oa_location,"
                                      "primary_location,open_access"
                        }),
                    )
                if r.status_code != 200:
                    return 0
                w = r.json()
                if not p.abstract:
                    p.abstract = OpenAlexSearcher.decode_abstract(
                        w.get("abstract_inverted_index")
                    )
                if not p.pdf_url:
                    loc = w.get("best_oa_location") or (w.get("primary_location") or {})
                    p.pdf_url = ((loc or {}).get("pdf_url") or "").strip() or None
                return 1
            except Exception:  # noqa: BLE001 — enrichment must never kill retrieval
                return 0

    return sum(await asyncio.gather(*(_one(p) for p in targets)))


@register("policy")
class PolicySearchSource(SearchSource):
    name = "Policy corpus (NBER/Fed/IMF)"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        super().__init__()
        # honest buckets per org: [ok, empty, failed] counted per query — an
        # org the queries cannot reach must read as "empty", an org Crossref
        # failed on as "failed", never both as "zero hits"
        self.health: dict[str, list[int]] = {}
        self._transport = transport  # tests inject MockTransport here

    async def search(self, keywords: list[str], max_results: int) -> list[Paper]:
        from citens.search.base import SEARCH_CONCURRENCY

        keywords = [k for k in keywords if k.strip()]
        if not keywords:
            return []
        per_kw = max(max_results // len(keywords), 5)
        sem = asyncio.Semaphore(SEARCH_CONCURRENCY)

        async with httpx.AsyncClient(
            timeout=30, headers={"User-Agent": "CiteLens/0.1"}, transport=self._transport
        ) as client:

            async def _run(prefix: str, q: str):
                # one retry: Crossref prefix routes answered 500 to isolated
                # cells on the live smoke (2026-10-28) — transient, and a
                # failed cell must not fake an empty org
                async with sem:
                    last: Exception | None = None
                    for attempt in range(2):
                        try:
                            return prefix, q, await self._one(client, prefix, q, per_kw), None
                        except Exception as e:  # noqa: BLE001 — one dead cell ≠ dead source
                            last = e
                            if attempt:
                                break
                            await asyncio.sleep(1.5)
                    return prefix, q, [], last

            results = await asyncio.gather(
                *(_run(prefix, q) for prefix in POLICY_ORGS for q in keywords)
            )

        out: list[Paper] = []
        per_q: dict[str, int] = {}
        for prefix, q, items, err in results:
            bucket = self.health.setdefault(POLICY_ORGS[prefix]["org"], [0, 0, 0])
            if err is not None:
                bucket[2] += 1
                continue
            bucket[0 if items else 1] += 1
            per_q[q] = per_q.get(q, 0) + len(items)
            for p in items:
                p.matched_queries.append(q)
            out.extend(items)
        self.query_stats = per_q
        await enrich_abstracts(out, transport=self._transport)
        return out

    async def _one(
        self, client: httpx.AsyncClient, prefix: str, query: str, limit: int
    ) -> list[Paper]:
        from citens.search.crossref import _polite_params

        params: dict = {
            "query": query,
            "rows": min(limit, 20),
            "select": (
                "DOI,title,author,issued,container-title,is-referenced-by-count,"
                "type,URL,link"
            ),
            **_polite_params(),
        }
        # year window rides Crossref's native date filters, same as the
        # crossref source — policy questions are often "recent stance" questions
        filters: list[str] = []
        if self.constraints and self.constraints.year_from:
            filters.append(f"from-pub-date:{self.constraints.year_from}-01-01")
        if self.constraints and self.constraints.year_to:
            filters.append(f"until-pub-date:{self.constraints.year_to}-12-31")
        if filters:
            params["filter"] = ",".join(filters)
        resp = await client.get(f"{_CROSSREF}/{prefix}/works", params=params)
        resp.raise_for_status()
        items = resp.json().get("message", {}).get("items", [])
        return [
            self._to_paper(prefix, it)
            for it in items
            if (it.get("title") or [""])[0].strip()
        ]

    @staticmethod
    def _to_paper(prefix: str, item: dict) -> Paper:
        from citens.search.crossref import CrossrefSearcher

        p = CrossrefSearcher._to_paper(item)
        meta = POLICY_ORGS[prefix]
        p.source = f"policy ({meta['org']})"
        p.doc_type = _policy_kind(prefix, p.venue)
        p.policy_org = meta["org"]
        if prefix == "10.3386":
            # NBER deposits bare reports with no container-title; the series IS
            # the venue, and the paper id in the DOI maps to the landing page
            p.venue = "NBER Working Papers"
            wid = (item.get("DOI") or "").rsplit("/", 1)[-1]
            p.url = f"https://www.nber.org/papers/{wid}"
        return p
