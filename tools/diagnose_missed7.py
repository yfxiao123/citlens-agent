"""Autopsy v2 of the 7-10 still-missed LitSearch golds — all-OpenAlex.

v1's S2 oracle drowned in 429s; v2 uses the keyed OpenAlex quota (separate
pool from title.search/search-anonymous throttling):

  oracle      — the gold's OWN title words into /works?search= : if perfect
                vocabulary misses at depth 25, it is ranking, not vocabulary
  ladder_gap  — new-discipline variants' overlap with the gold title
  ladder_wave — replay the ladder wave; where does the gold land?
  cite_1hop   — gold's OpenAlex referenced_works vs the wave's top-20
                titles (snowball savability given one on-topic seed)
  title_index — the F3 filter probe into title.search
  q1 sweep    — probe word-count sweep for the stubborn title

    .venv/Scripts/python tools/diagnose_missed7.py
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

POOLS = Path(r"D:\Desktop\personal-knowledge\citlens\citens\bench_results\ranklab_pools.json")
GEN = Path(r"D:\Desktop\personal-knowledge\citlens\citens\bench_results\gen_cache.json")
LADDER = Path(r"D:\Desktop\personal-knowledge\citlens\citlens-agent\tools\ablation_ladder_queries.json")
SOURCES = ["arxiv", "semantic_scholar", "openalex", "crossref"]
DEPTH = 20

from citens.eval.litsearch import oa_title_filter
from citens.search.base import search_round

STOP = set(["the", "a", "an", "of", "for", "in", "on", "with", "and", "or", "to", "is", "are", "was", "were", "be", "been", "by", "from", "as", "that", "this", "it", "its", "how", "why", "what", "when", "where", "which"])


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


def overlap(q: str, title: str) -> tuple[int, int]:
    qw = {w for w in re.findall(r"[a-z]{4,}", q.lower())} - STOP
    tw = set(title_key(title).split())
    return len(qw & tw), len(qw)


async def oa_get(params: dict) -> dict:
    from citens import net

    client = net.async_client("openalex", timeout=30, min_interval=0.3, url="https://api.openalex.org")
    try:
        from citens.search.openalex import apply_api_key

        r = await client.get("https://api.openalex.org/works", params=apply_api_key(params))
        r.raise_for_status()
        return r.json()
    finally:
        await client.aclose()


async def oracle_rank(gtitle: str) -> str:
    words = title_key(gtitle).split()[:8]
    try:
        data = await oa_get({"search": " ".join(words), "per-page": 25,
                             "select": "display_name,doi"})
        works = data.get("results", [])
        rank = next((i for i, w in enumerate(works, 1)
                     if match({"title": gtitle}, {"title": w.get("display_name"), "doi": w.get("doi")})), None)
        return f"rank {rank or 'MISS'} of {len(works)}"
    except Exception as ex:  # noqa: BLE001
        return f"errored {str(ex)[:60]}"


async def cite_1hop(gtitle: str, wave_titles: list[str]) -> str:
    try:
        gold = await oa_get({"filter": f"title.search:{gtitle[:80]}", "per-page": 3,
                             "select": "id,referenced_works"})
        hits = gold.get("results", [])
        if not hits:
            return "gold not in OpenAlex"
        ref_ids = (hits[0].get("referenced_works") or [])[:100]
        if not ref_ids:
            return "gold has no referenced_works recorded"
        ref_titles: set[str] = set()
        for i in range(0, len(ref_ids), 50):
            chunk = "|".join(w.split("/")[-1] for w in ref_ids[i:i + 50])
            data = await oa_get({"filter": f"openalex_id:{chunk}", "per-page": 50,
                                 "select": "display_name"})
            for w in data.get("results", []):
                ref_titles.add(title_key(w.get("display_name")))
        wave_keys = [title_key(t) for t in wave_titles if t]
        hit = [k for k in wave_keys if k and k in ref_titles]
        return (f"{len(ref_titles)} refs vs wave top-{len(wave_keys)} -> "
                f"{'1HOP: ' + str(hit[:2]) if hit else 'no overlap'}")
    except Exception as ex:  # noqa: BLE001
        return f"errored {str(ex)[:60]}"


async def main() -> int:
    pools = json.loads(POOLS.read_text(encoding="utf-8"))
    ladder = json.loads(LADDER.read_text(encoding="utf-8")) if LADDER.is_file() else {}
    missed = [e for e in pools if e.get("gold_rank_pool") is None]
    print(f"ladder variants loaded: {len(ladder)} questions\n", flush=True)

    for e in missed:
        qid = str(e["i"])
        gold = e["golds"][0]
        gtitle = gold.get("title", "")
        variants = ladder.get(qid) or []
        print(f"=== q{qid}: {gtitle[:70]}", flush=True)
        print(f"  ladder variants loaded: {len(variants)}", flush=True)
        for v in variants[:3]:
            hit, tot = overlap(v, gtitle)
            print(f"  ladder-gap: overlap {hit}/{tot} | {v[:66]}", flush=True)

        wave_titles: list[str] = []
        if variants:
            try:
                papers, _h, _s = await search_round(variants[:3], max_results=DEPTH, sources=SOURCES)
                rank = next((i for i, p in enumerate(papers, 1) if match(gold, p.model_dump())), None)
                wave_titles = [p.title for p in papers[:20]]
                print(f"  ladder-wave: gold rank {rank or 'MISS'} | pool {len(papers)}", flush=True)
            except Exception as ex:  # noqa: BLE001
                print(f"  ladder-wave: errored {str(ex)[:60]}", flush=True)

        print(f"  oracle:      {await oracle_rank(gtitle)}", flush=True)
        if wave_titles:
            print(f"  cite-1hop:   {await cite_1hop(gtitle, wave_titles)}", flush=True)
        try:
            from citens.eval.litsearch import oa_title_search

            tmap = await oa_title_search([gtitle])
            got = tmap.get(gtitle) or []
            hit = next((i for i, w in enumerate(got, 1) if match(gold, w.model_dump())), None)
            print(f"  title-index: probe '{oa_title_filter(gtitle)}' -> rank {hit or 'MISS'}", flush=True)
        except Exception as ex:  # noqa: BLE001
            print(f"  title-index: errored {str(ex)[:60]}", flush=True)
        await asyncio.sleep(0.5)

    # q1 special: the one title-index MISS — sweep probe word counts
    q1 = next((e for e in missed if e["i"] == "1"), None)
    if q1:
        gtitle = q1["golds"][0].get("title", "")
        print(f"\n=== q1 probe sweep: {gtitle[:60]}", flush=True)
        words = title_key(gtitle).split()
        for k in range(2, 7):
            filt = " ".join(words[:k])
            try:
                data = await oa_get({"filter": f"title.search:{filt}", "per-page": 10,
                                     "select": "display_name,doi"})
                works = data.get("results", [])
                rank = next((i for i, w in enumerate(works, 1)
                             if match({"title": gtitle}, {"title": w.get("display_name"), "doi": w.get("doi")})), None)
                print(f"  {k} words '{filt}' -> rank {rank or 'MISS'} ({len(works)} hits)", flush=True)
            except Exception as ex:  # noqa: BLE001
                print(f"  {k} words -> errored {str(ex)[:50]}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
