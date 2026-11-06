"""Full 15-question end-to-end retest of the search pipeline AS SHIPPED.

Every previous measurement was per-arm (ablation vocab, relevance probes,
fused-wave spot checks). This one runs the whole recall shape the driver
uses, with the shipped defaults, over every ranklab question:

  arm A "raw5+ladder" — the question itself + the register-ladder variants
        through the FIVE default sources (incl. openalex_relevance, the
        6d894d7 addition), RRF-fused exactly like the driver's planned leg
  arm B "A+pivot"     — + the mechanical pivot wave (citens/search/pivot.py,
        the vocabulary-mismatch escape hatch): queries from the terms of
        corroborated seeds (found_by >= 2 distinct sources)

Gold rank per question (hit = rank <= 20, the union@20 ceiling the August
ranklab run was scored under). Incremental save after each question so a
killed run keeps its evidence. One-off measurement artifact (tools/).

    .venv/Scripts/python tools/retest_full_bench.py
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# repo root, NOT parents[1]: the outer workspace has a sibling folder literally
# named `citens/` (the engine repo root) which -I mode imports as a namespace
# package that shadows the real one (measured: ModuleNotFoundError on launch).
sys.path.insert(0, str(HERE.parent))

from citens.eval.litsearch import _key_of, fuse_multi_query, search_one_query

POOLS = Path(r"D:\Desktop\personal-knowledge\citlens\citens\bench_results\ranklab_pools.json")
LADDER = HERE / "results" / "ablation_ladder_queries.json"
OUT = HERE / "results" / "full_bench_retest.json"
PER = 20

STOP = {
    "the", "a", "an", "of", "for", "in", "on", "with", "and", "or", "to", "is",
    "are", "was", "were", "be", "been", "by", "from", "as", "that", "this",
    "it", "its",
}


def title_key(t: str) -> str:
    ws = [w for w in re.findall(r"[a-z0-9]{3,}", t.lower()) if w not in STOP]
    return " ".join(ws)


def match(gold: dict, paper) -> bool:
    gp = paper if isinstance(paper, dict) else paper.model_dump()
    g_arx = (gold.get("arxiv") or "").strip()
    p_arx = (gp.get("arxiv_id") or gp.get("arxiv") or "").strip()
    if g_arx and p_arx and (g_arx in p_arx or p_arx in g_arx):
        return True
    g_doi = (gold.get("doi") or "").strip().lower()
    p_doi = (gp.get("doi") or "").strip().lower()
    if g_doi and p_doi and g_doi == p_doi:
        return True
    a, b = title_key(gold.get("title", "")), title_key(gp.get("title", ""))
    return bool(a and b and (a == b or a in b or b in a))


def gold_rank(gold: dict, papers: list) -> int | None:
    for i, p in enumerate(papers, 1):
        if match(gold, p):
            return i
    return None


async def main() -> None:
    from citens.config import settings

    sources = [s.strip() for s in settings.search_sources.split(",") if s.strip()]
    pools = json.loads(POOLS.read_text(encoding="utf-8"))
    ladder = json.loads(LADDER.read_text(encoding="utf-8"))
    results: dict[str, dict] = (
        json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    )
    health: dict[str, list[int]] = {}

    for e in pools:
        qid = str(e["i"])
        if qid in results and results[qid].get("done"):
            continue
        queries = [e["query"]] + (ladder.get(qid) or [])
        try:
            cells: dict[str, dict] = {}
            for j, q in enumerate(queries):
                # mirror the driver's shipped depths exactly: the raw topic
                # leg at PER_SOURCE=20, agent-crafted (ladder) queries at
                # AGENT_DEPTH=40 (drivers/citlens_recall.py:50-51) — the
                # first full run did everything at 20, stricter than shipped,
                # and moved boundary golds (q10 @24-at-20 vs @5-at-40).
                depth = PER if j == 0 else 40
                cells[q] = await search_one_query(q, sources, depth, health)
            fused = fuse_multi_query(cells, sources)
            rank_a = gold_rank(e["golds"][0], fused)

            # pivot arm: corroborated head = seen by >= 2 distinct sources
            srcs_of: dict[str, set[str]] = {}
            for per in cells.values():
                for s, lst in per.items():
                    for p in lst:
                        srcs_of.setdefault(_key_of(p), set()).add(s)
            seeds = [p for p in fused if len(srcs_of.get(_key_of(p), ())) >= 2]
            rank_b, pivot_qs = rank_a, []
            if len(seeds) >= 3:
                from citens.search.pivot import build_pivot_queries

                pivot_qs = build_pivot_queries(seeds, fused, n_queries=2)
                if pivot_qs:
                    pcells = {
                        q: await search_one_query(q, sources, PER, health)
                        for q in pivot_qs
                    }
                    fused_b = fuse_multi_query({**cells, **pcells}, sources)
                    rank_b = gold_rank(e["golds"][0], fused_b)

            results[qid] = {
                "done": True, "query": e["query"][:70],
                "gold": e["golds"][0].get("title", "")[:70],
                "queries": len(queries), "pool": len(fused),
                "rank_A": rank_a, "rank_B": rank_b, "pivot": pivot_qs,
                "seeds": len(seeds),
            }
            print(
                f"q{qid}: A={rank_a or 'MISS'} B={rank_b or 'MISS'} "
                f"pool={len(fused)} seeds={len(seeds)} | {e['golds'][0]['title'][:50]}",
                flush=True,
            )
        except Exception as ex:  # noqa: BLE001 — keep the bench alive
            results[qid] = {"done": False, "error": f"{type(ex).__name__}: {ex}"[:120]}
            print(f"q{qid}: ERRORED {ex}", flush=True)
        OUT.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

    hit_a = sum(1 for r in results.values() if (r.get("rank_A") or 99) <= PER)
    hit_b = sum(1 for r in results.values() if (r.get("rank_B") or 99) <= PER)
    print(f"\nTOTAL: A(raw5+ladder) {hit_a}/15  B(+pivot) {hit_b}/15  health={health}")


if __name__ == "__main__":
    asyncio.run(main())
