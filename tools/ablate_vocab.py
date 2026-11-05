"""Ablation: how much of the vocabulary-mismatch recall gap does each fix close?

One-off measurement harness (tools/, not part of the test suite). Arms on
the SAME 10 missed LitSearch questions (depth=20/source for keyword arms):

  raw        the question as one query            (baseline; measured 0/10)
  planned    the August planner's 3 queries        (reproduces the miss)
  hyde_old   August HyDE titles, OLD probe filter  (first-5-words, no stoplist)
  hyde_new   same titles, NEW probe filter         (F3: stopword-free 5 words)
  ladder     register-ladder variants generated with the new SKILL.md
             discipline (F1+F2, LLM-simulated via the configured endpoint)
  pivot      mechanical second wave from the corroborated head (F5), run on
             top of the ladder arm's corroboration analog (production shape)

Gold match: arXiv id, or DOI, or >=80% title-word overlap.

    .venv/Scripts/python tools/ablate_vocab.py [--arms raw,planned,hyde,...]
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

POOLS = Path(r"D:\Desktop\personal-knowledge\citlens\citens\bench_results\ranklab_pools.json")
GEN = Path(r"D:\Desktop\personal-knowledge\citlens\citens\bench_results\gen_cache.json")
OUT = Path(__file__).parent / "ablation_vocab.json"
SOURCES = ["arxiv", "semantic_scholar", "openalex", "crossref"]
DEPTH = 20

from citens.eval.litsearch import oa_title_filter
from citens.search.base import search_round
from citens.search.pivot import build_pivot_queries

STOP = {
    "the", "a", "an", "of", "for", "in", "on", "with", "and", "or", "to", "is", "are", "was", "were", "be", "been", "by", "from", "as", "that", "this", "it", "its"}


def title_key(t: str) -> str:
    return " ".join(w for w in re.findall(r"[a-z0-9]{3,}", t.lower()) if w not in STOP)


def match(gold: dict, gp: dict) -> bool:
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


def old_filter(title: str) -> str:
    """The pre-F3 probe: first 5 tokens >2 chars, no stoplist."""
    words = [w for w in re.findall(r"[A-Za-z0-9]+", title) if len(w) > 2]
    return " ".join(words[:5])


async def oa_probe(filt: str) -> list[dict]:
    from citens.search.openalex import apply_api_key, oa_client

    async with oa_client(timeout=25) as hc:
        r = await hc.get(
            "https://api.openalex.org/works",
            params=apply_api_key({"filter": f"title.search:{filt}", "per-page": 20}),
        )
        if r.status_code != 200:
            return []
        return [
            {"title": w.get("display_name") or "", "doi": (w.get("doi") or "").replace("https://doi.org/", "")}
            for w in r.json().get("results", [])
        ]


async def keyword_arm(queries_per_question: dict[str, list[str]]) -> dict[str, int | None]:
    """search_round over each question's query bundle; return gold rank."""
    ranks: dict[str, int | None] = {}
    for qid, queries in queries_per_question.items():
        try:
            papers, _h, _s = await search_round(queries, max_results=DEPTH, sources=SOURCES)
        except Exception as ex:  # noqa: BLE001 — an arm failing must not kill the run  # noqa: BLE001
            print(f"    [{qid}] wave errored: {str(ex)[:70]}")
            ranks[qid] = None
            continue
        gold = GOLD_BY_QID[qid]
        ranks[qid] = next((i for i, p in enumerate(papers, 1) if match(gold, p.model_dump())), None)
        await asyncio.sleep(0.2)
    return ranks


async def hyde_arm(use_new_filter: bool) -> dict[str, int | None]:
    ranks: dict[str, int | None] = {}
    for qid, titles in HYDE_BY_QID.items():
        gold = GOLD_BY_QID[qid]
        ranks[qid] = None
        for t in titles:
            filt = oa_title_filter(t) if use_new_filter else old_filter(t)
            if not filt:
                continue
            try:
                for i, w in enumerate(await oa_probe(filt), 1):
                    if match(gold, w):
                        ranks[qid] = i
                        break
            except Exception as ex:  # noqa: BLE001 — an arm failing must not kill the run  # noqa: BLE001
                print(f"    [{qid}] oa probe errored: {str(ex)[:70]}")
            if ranks[qid]:
                break
    return ranks


LADDER_PROMPT = (
    "You are a literature-search planner. Restate the research question in "
    "your own words, then write {n} DIFFERENT English search queries an expert "
    "would use to find the paper that answers it. Rules: use paper-side "
    "terminology (method names, task names, dataset names, community jargon) "
    "rather than the question's own words; each query from a different angle "
    "(mechanism / task / community). Output ONLY the queries, one per line, "
    "no numbering.\n\nResearch question: {q}"
)


async def ladder_variants(question: str, n: int = 3) -> list[str]:
    """Register-ladder variants via the configured endpoint, THROUGH the
    citlens net layer (retry + throttle + settings proxy) — a raw httpx call
    died on one transient ConnectError and killed a 20-minute run."""
    from citens import net
    from citens.config import settings

    base = (settings.llm_api_base or "").strip().rstrip("/")
    key = (settings.llm_api_key or "").strip()
    model = (settings.llm_model or "").strip()
    if not (base and key and model):
        raise RuntimeError("LLM endpoint not configured (LLM_API_*)")
    client = net.async_client(
        "ladder_llm", timeout=60.0, url=base, headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        },
    )
    try:
        r = await client.post(
            base + "/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": LADDER_PROMPT.format(n=n, q=question)}],
                "max_tokens": 200,
                "temperature": 0.4,
            },
        )
        r.raise_for_status()
        lines = [l.strip("-•* ").strip() for l in r.json()["choices"][0]["message"]["content"].splitlines()]
        return [l for l in lines if l][:n]
    finally:
        await client.aclose()


GOLD_BY_QID: dict[str, dict] = {}
HYDE_BY_QID: dict[str, list[str]] = {}
PLANNED_BY_QID: dict[str, list[str]] = {}
QQUESTION: dict[str, str] = {}


async def main() -> int:
    arms = (sys.argv[1].split(",") if len(sys.argv) > 1
            else ["raw", "planned", "hyde_old", "hyde_new", "ladder", "ladder_pivot"])
    pools = json.loads(POOLS.read_text(encoding="utf-8"))
    gen = json.loads(GEN.read_text(encoding="utf-8"))
    missed = [e for e in pools if e.get("gold_rank_pool") is None]
    for e in missed:
        qid = e["i"]
        GOLD_BY_QID[qid] = e["golds"][0]
        QQUESTION[qid] = e["query"]
        HYDE_BY_QID[qid] = list(gen.get(f"3:hyde:{e['query']}") or [])
        PLANNED_BY_QID[qid] = list(gen.get(f"3:planned:{e['query']}") or [])
    print(f"arms={arms} on {len(missed)} missed questions\n", flush=True)

    results: dict[str, dict] = {}

    def _save() -> None:
        OUT.write_text(
            json.dumps({"summary": {a: {"found": sum(1 for v in r.values() if v), "of": len(r)}
                                     for a, r in results.items()},
                        "ranks": results}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )

    if "raw" in arms:
      try:
        print("[raw] question as one query...", flush=True)
        results["raw"] = await keyword_arm({qid: [QQUESTION[qid]] for qid in GOLD_BY_QID})
        _save()
      except Exception as ex:  # noqa: BLE001 — an arm failing must not kill the run
        print(f"[raw] arm failed: {str(ex)[:120]}", flush=True)
    if "planned" in arms:
      try:
        print("[planned] August planner queries...", flush=True)
        results["planned"] = await keyword_arm(PLANNED_BY_QID)
        _save()
      except Exception as ex:  # noqa: BLE001 — an arm failing must not kill the run
        print(f"[planned] arm failed: {str(ex)[:120]}", flush=True)
    if "hyde_old" in arms:
      try:
        print("[hyde_old] HyDE titles, OLD probe filter...", flush=True)
        results["hyde_old"] = await hyde_arm(use_new_filter=False)
        _save()
      except Exception as ex:  # noqa: BLE001 — an arm failing must not kill the run
        print(f"[hyde_old] arm failed: {str(ex)[:120]}", flush=True)
    if "hyde_new" in arms:
      try:
        print("[hyde_new] HyDE titles, NEW probe filter (F3)...", flush=True)
        results["hyde_new"] = await hyde_arm(use_new_filter=True)
        _save()
      except Exception as ex:  # noqa: BLE001 — an arm failing must not kill the run
        print(f"[hyde_new] arm failed: {str(ex)[:120]}", flush=True)
    if "ladder" in arms:
      try:
        print("[ladder] register-ladder variants (F1+F2, LLM-simulated)...", flush=True)
        bundles = {}
        for qid, q in QQUESTION.items():
            bundles[qid] = await ladder_variants(q)
            await asyncio.sleep(0.3)
        results["ladder"] = await keyword_arm(bundles)
        _save()
      except Exception as ex:  # noqa: BLE001 — an arm failing must not kill the run
        print(f"[ladder] arm failed: {str(ex)[:120]}", flush=True)
        OUT_LADDER = OUT.with_name("ablation_ladder_queries.json")
        OUT_LADDER.write_text(json.dumps(bundles, ensure_ascii=False, indent=1), encoding="utf-8")
    if "ladder_pivot" in arms:
      try:
        print("[ladder_pivot] ladder wave + mechanical pivot (F5, production shape)...", flush=True)
        bundles = {}
        lp = OUT.with_name("ablation_ladder_queries.json")
        if lp.is_file():
            bundles = json.loads(lp.read_text(encoding="utf-8"))
        ranks: dict[str, int | None] = {}
        for qid, gold0 in GOLD_BY_QID.items():
            queries = bundles.get(qid) or await ladder_variants(QQUESTION[qid])
            papers, _h, _s = await search_round(queries, max_results=DEPTH, sources=SOURCES)
            gold = gold0
            rank = next((i for i, p in enumerate(papers, 1) if match(gold, p.model_dump())), None)
            if rank is None and len(papers) >= 6:
                # corroborated-head analog: in production found_by>=2 across
                # families; here the ladder variants play the families, so the
                # head is the top-cited third — same seeds the driver would pick
                head = sorted(papers[:9], key=lambda p: -(p.citation_count or 0))[:6]
                pqs = build_pivot_queries(head, papers, n_queries=2)
                if pqs:
                    p2, _h2, _s2 = await search_round(pqs, max_results=DEPTH, sources=SOURCES)
                    merged = {title_key(p.title): p for p in papers}
                    for p in p2:
                        merged.setdefault(title_key(p.title), p)
                    flat = list(merged.values())
                    rank = next((i for i, p in enumerate(flat, 1) if match(gold, p.model_dump())), None)
                    if rank and rank <= len(papers):
                        pass  # found in wave 1
                    elif rank:
                        rank = len(papers) + rank  # mark as pivot-recovered
            ranks[qid] = rank
            await asyncio.sleep(0.2)
        results["ladder_pivot"] = ranks
        _save()
      except Exception as ex:  # noqa: BLE001 — an arm failing must not kill the run
        print(f"[ladder_pivot] arm failed: {str(ex)[:120]}", flush=True)

    print("\n== per-question gold rank by arm (None = miss) ==")
    qids = list(GOLD_BY_QID)
    header = "qid  " + "  ".join(f"{a[:12]:>13}" for a in results)
    print(header)
    for qid in qids:
        row = "  ".join(f"{results[a].get(qid)!s:>13}" for a in results)
        print(f"{qid:>4}  {row}")
    print("\n== summary ==")
    summary = {}
    for a, ranks in results.items():
        found = sum(1 for v in ranks.values() if v)
        summary[a] = {"found": found, "of": len(ranks)}
        print(f"  {a:>13}: {found}/{len(ranks)}")
    OUT.write_text(json.dumps({"summary": summary, "ranks": results}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    sys.exit(asyncio.run(main()))
