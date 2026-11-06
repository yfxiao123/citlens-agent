"""Measure the three candidate fixes on the 7 remaining missed golds.

  oa_relevance — ladder variants through OpenAlex `search=` (the endpoint the
                 oracle used, vs the production default.search filter)
  arxiv_probe  — q1's gold title words through the arXiv API (q1 is absent
                 from OpenAlex but present on arXiv/S2)
  deep40       — the production ladder wave at depth 40 (vs 20 in the
                 ablation): do the near-misses q7@34/q8@18/q10@18 come in?

    .venv/Scripts/python tools/measure_candidate_fixes.py
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

POOLS = Path(r"D:\Desktop\personal-knowledge\citlens\citens\bench_results\ranklab_pools.json")
LADDER = Path(__file__).parent / "results" / "ablation_ladder_queries.json"
SOURCES = ["arxiv", "semantic_scholar", "openalex", "openalex_relevance", "crossref"]

from citens.search.base import search_round  # noqa: E402

STOP = set("the a an of for in on with and or to is are was were be been by from as that this it its how why what".split())


def title_key(t: str) -> str:
    return " ".join(w for w in re.findall(r"[a-z0-9]{3,}", (t or "").lower()) if w not in STOP)


def match(gold: dict, gp: dict) -> bool:
    g_doi = (gold.get("doi") or "").strip().lower()
    p_doi = (gp.get("doi") or "").strip().lower()
    if g_doi and p_doi and g_doi == p_doi:
        return True
    a, b = title_key(gold.get("title", "")), title_key(gp.get("title", ""))
    aw, bw = set(a.split()), set(b.split())
    return bool(a) and bool(b) and len(aw & bw) / max(len(aw), 1) >= 0.8


async def oa_relevance(client, query: str, gold: dict) -> int | None:
    from citens.search.openalex import apply_api_key

    r = await client.get(
        "https://api.openalex.org/works",
        params=apply_api_key({"search": query, "per-page": 25,
                              "select": "display_name,doi"}),
    )
    r.raise_for_status()
    for i, w in enumerate(r.json().get("results", []), 1):
        if match(gold, {"title": w.get("display_name"), "doi": w.get("doi")}):
            return i
    return None


async def arxiv_title(gold: dict) -> int | None:
    words = title_key(gold.get("title", "")).split()[:6]
    q = " ".join(words)
    import httpx

    async with httpx.AsyncClient(timeout=30) as hc:
        r = await hc.get("http://export.arxiv.org/api/query", params={
            "search_query": f'all:"{q}"', "max_results": 10})
        titles = re.findall(r"<title>(.*?)</title>", r.text, re.S)[1:]
        for i, t in enumerate(titles, 1):
            if match(gold, {"title": t.replace("\n", " ")}):
                return i
        # fall back to AND of loose words
        r2 = await hc.get("http://export.arxiv.org/api/query", params={
            "search_query": " AND ".join(f"all:{w}" for w in words[:4]),
            "max_results": 20})
        titles2 = re.findall(r"<title>(.*?)</title>", r2.text, re.S)[1:]
        for i, t in enumerate(titles2, 1):
            if match(gold, {"title": t.replace("\n", " ")}):
                return i
    return None


async def main() -> int:
    from citens import net

    pools = json.loads(POOLS.read_text(encoding="utf-8"))
    ladder = json.loads(LADDER.read_text(encoding="utf-8"))
    missed = [e for e in pools if e.get("gold_rank_pool") is None]
    client = net.async_client("openalex", timeout=30, min_interval=0.3, url="https://api.openalex.org")
    try:
        print("== arm 1: ladder variants through OpenAlex relevance search= ==")
        for e in missed:
            gold = e["golds"][0]
            qid = str(e["i"])
            ranks = []
            for v in (ladder.get(qid) or [])[:3]:
                try:
                    r = await oa_relevance(client, v, gold)
                    ranks.append(r)
                except Exception as ex:  # noqa: BLE001
                    ranks.append(f"ERR:{str(ex)[:20]}")
            best = next((r for r in ranks if r), None)
            print(f"  q{qid}: relevance-search rank {best or 'MISS'} (per-variant {ranks}) | {gold['title'][:45]}")
        print("\n== arm 2: q1 gold title through arXiv API ==")
        q1 = next(e for e in missed if e["i"] == 1 or str(e["i"]) == "1")
        try:
            print(f"  q1 arxiv title probe -> rank {await arxiv_title(q1['golds'][0])}")
        except Exception as ex:  # noqa: BLE001
            print(f"  q1 arxiv probe errored: {str(ex)[:80]}")
    finally:
        await client.aclose()

    print("\n== arm 3: production ladder wave at depth 40 ==")
    for e in missed:
        gold = e["golds"][0]
        variants = (ladder.get(str(e["i"])) or [])[:3]
        if not variants:
            continue
        try:
            papers, _h, _s = await search_round(variants, max_results=40, sources=SOURCES)
            rank = next((i for i, p in enumerate(papers, 1) if match(gold, p.model_dump())), None)
            print(f"  q{e['i']}: depth-40 rank {rank or 'MISS'} | pool {len(papers)}")
        except Exception as ex:  # noqa: BLE001
            print(f"  q{e['i']}: errored {str(ex)[:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
