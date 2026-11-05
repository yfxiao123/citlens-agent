"""Live retest: does TODAY's retrieval still miss the 10 ranklab golds?

For each question missed by the August ranklab run:
  arm "raw"    — search_round([question]) exactly as the raw leg would run it
  arm "title"  — the gold's own title into OpenAlex title.search (index check:
                 if the title lookup can't find the gold either, it is an
                 index-coverage problem, not a retrieval problem)

One-off measurement artifact (tools/, not part of the test suite).

    .venv/Scripts/python tools/retest_missed_gold.py
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

POOLS = Path(r"D:\Desktop\personal-knowledge\citlens\citens\bench_results\ranklab_pools.json")
SOURCES = ["arxiv", "semantic_scholar", "openalex", "crossref"]
DEPTH = 20

STOP = {
    "the", "a", "an", "of", "for", "in", "on", "with", "and", "or", "to", "is", "are", "was", "were", "be", "been", "by", "from", "as", "that", "this", "it", "its"}


def title_key(t: str) -> str:
    ws = [w for w in re.findall(r"[a-z0-9]{3,}", t.lower()) if w not in STOP]
    return " ".join(ws)


def match(gold: dict, paper) -> bool:
    """Match on arXiv id, DOI (when both present), else title-word overlap."""
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
    if not a or not b:
        return False
    aw, bw = set(a.split()), set(b.split())
    return len(aw & bw) / max(len(aw), 1) >= 0.8


async def main() -> int:
    from citens.eval.litsearch import oa_title_search  # the title-index family leg
    from citens.search.base import search_round

    pools = json.loads(POOLS.read_text(encoding="utf-8"))
    missed = [e for e in pools if e.get("gold_rank_pool") is None]
    print(f"re-testing {len(missed)} missed questions (depth={DEPTH}/source)\n")

    found_raw = found_title = 0
    for e in missed:
        gold = e["golds"][0]
        raw_rank = title_rank = None
        try:
            papers, _health, _stats = await search_round([e["query"]], max_results=DEPTH, sources=SOURCES)
            for i, p in enumerate(papers, 1):
                if match(gold, p):
                    raw_rank = i
                    break
        except Exception as ex:  # noqa: BLE001
            print(f"  [{e['i']:>2}] raw leg errored: {str(ex)[:80]}")
        try:
            t_map = await oa_title_search([gold.get("title", "")])
            t_papers = (t_map.get(gold.get("title", "")) or [])
            for i, p in enumerate(t_papers, 1):
                if match(gold, p):
                    title_rank = i
                    break
        except Exception as ex:  # noqa: BLE001
            print(f"  [{e['i']:>2}] title leg errored: {str(ex)[:80]}")
        raw_ok = "hit@" + str(raw_rank) if raw_rank else "MISS"
        title_ok = "indexed@" + str(title_rank) if title_rank else "not-in-index"
        found_raw += bool(raw_rank)
        found_title += bool(title_rank)
        print(f"  [{e['i']:>2}] raw: {raw_ok:<8} | title-index: {title_ok:<14} | "
              f"gold: {gold.get('title', '')[:60]}")

    print(f"\nsummary: raw query finds {found_raw}/10 | title-index finds {found_title}/10")
    print("raw hits = the miss was rank/threshold; still-missed + indexed = "
          "vocabulary/planner problem; not-in-index = index coverage problem")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
