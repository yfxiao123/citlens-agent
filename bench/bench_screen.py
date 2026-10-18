#!/usr/bin/env python
"""bench_screen.py — measure the `screen` triage lever on the LitSearch bench.

The question this answers: on the SAME candidate pool, does the screen
scoring (semantic / lexical / consensus channels) move gold papers UP
compared with the order `search` returns today (RRF / family-seat)?

Design (lever isolation — everything except the ordering is shared):
  recall phase, run once per question and cached (bench_results/cells.json):
    agent family   the engine's FROZEN planned keyword queries (gen_cache.json,
                   zero LLM at bench time) — same queries the published
                   recall@20=33.3% adaptive leg started from
    raw family     the question verbatim
    4 sources x depth 20 per query (arxiv/s2/openalex/crossref), polite pools
  orderings of the one pool (the arms):
    A firstwins    family-seat order — exactly what `search` returns today
    B rrf_global   global RRF over all cells (the fused order)
    C screen_lex   screen score, semantic OFF (BM25 + consensus)
    D screen_full  screen score, all channels (bge embeddings + BM25 + votes)
    E sem_only     semantic channel alone (attribution: how much is the model)
  metrics: gold in-pool, recall@5/@10/@20, MRR@100 (match by DOI/arXiv/title,
    ported from the engine's match_gold).

Data: bench_data/litsearch/ + bench_results/gen_cache.json — gitignored;
copy or point --data/--gen at the engine repo's copies. pyarrow is needed
for the parquet read (not a runtime dependency of the package).

Run from the repo root:
  .venv/Scripts/python bench/bench_screen.py \
      --data <engine>/bench_data/litsearch --gen <engine>/bench_results/gen_cache.json \
      [--env <citlens home>/.env]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from citens.eval.litsearch import fuse_multi_query, search_one_query  # noqa: E402
from citens.models import Paper  # noqa: E402
from citens.search.base import paper_arxiv_id  # noqa: E402
from citens.screening import screen_papers  # noqa: E402

SOURCES = ["arxiv", "semantic_scholar", "openalex", "crossref"]
PER_SOURCE = 20
FAMILY_QUOTA = 30
MODEL_DEFAULT = "BAAI/bge-base-en-v1.5"


def _log(msg: str) -> None:
    print(f"[bench] {msg}", flush=True)


# --- gold matching (ported verbatim from the engine's eval/litsearch.py) ------


def _norm_doi(doi: str | None) -> str:
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", (doi or "").strip().lower())


def _title_tokens(title: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", (title or "").lower()) if len(t) > 2}


def match_gold(paper: Paper, golds: list[dict]) -> bool:
    pdoi = _norm_doi(paper.doi)
    parx = paper_arxiv_id(paper)
    ptok = _title_tokens(paper.title)
    for g in golds:
        if pdoi and g.get("doi") and pdoi == _norm_doi(g["doi"]):
            return True
        if parx and g.get("arxiv") and g["arxiv"] == parx:
            return True
        gtok = _title_tokens(g.get("title", ""))
        if len(ptok) >= 3 and len(gtok) >= 3 and ptok == gtok:
            return True
    return False


def first_gold_rank(ordered: list[Paper], golds: list[dict]) -> int | None:
    for i, p in enumerate(ordered, 1):
        if match_gold(p, golds):
            return i
    return None


def gold_hits_at(ordered: list[Paper], golds: list[dict], k: int) -> float:
    """Recall@k over the question's golds (each gold counted once)."""
    if not golds:
        return 0.0
    matched = 0
    for g in golds:
        if any(match_gold(p, [g]) for p in ordered[:k]):
            matched += 1
    return matched / len(golds)


# --- cells (network, cached) ---------------------------------------------------


def _load_cells(path: Path) -> dict:
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


async def _cell(query: str, cells_cache: dict, path: Path) -> dict[str, list[Paper]]:
    if query in cells_cache:
        return {
            s: [Paper(**p) for p in lst]
            for s, lst in cells_cache[query].items()
        }
    _log(f"  fetch cells: {query[:70]}")
    health: dict[str, list[int]] = {}
    got = await search_one_query(query, SOURCES, per_source=PER_SOURCE, health_out=health)
    failed = [s for s, b in health.items() if b[2] > 0]
    if failed:
        # a throttled source must not bake partial results into the cache —
        # leave uncached so the next run retries the query
        _log(f"    source failures, cell NOT cached (retried next run): {failed}")
        return got
    cells_cache[query] = {s: [p.model_dump() for p in lst] for s, lst in got.items()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cells_cache, ensure_ascii=False), encoding="utf-8")
    return got


def _first_wins(families: list[list[Paper]]) -> list[Paper]:
    """Seat-quota merge, first family wins ties (the recall driver's shape)."""
    pool, seen = [], set()
    for fam in families:
        for p in fam[:FAMILY_QUOTA]:
            k = _fuse_key(p)
            if k not in seen:
                seen.add(k)
                pool.append(p)
    return pool


def _fuse_key(p: Paper) -> str:
    from citens.eval.litsearch import _key_of

    return _key_of(p)


# --- the bench ------------------------------------------------------------------


def run(
    data_dir: Path,
    gen_cache_path: Path,
    n: int,
    model: str,
    out_dir: Path,
    results_dir: Path,
) -> int:
    import pyarrow.parquet as pq

    rows = pq.read_table(str(data_dir / "query.parquet")).to_pylist()
    gold_all = json.loads((data_dir / "gold_papers.json").read_text(encoding="utf-8"))
    gen = json.loads(gen_cache_path.read_text(encoding="utf-8"))
    # frozen planner generations: prefer the newest cache version per question
    planned_by_q: dict[str, list[str]] = {}
    for k, v in gen.items():
        parts = k.split(":planned:", 1)
        if len(parts) == 2 and v:
            q = parts[1]
            ver = int(parts[0]) if parts[0].isdigit() else 0
            if q not in planned_by_q or ver > planned_by_q[q + "#ver"]:
                planned_by_q[q] = v
                planned_by_q[q + "#ver"] = ver  # type: ignore[assignment]
    vers = {k: planned_by_q.pop(k) for k in list(planned_by_q) if k.endswith("#ver")}

    qs = [r for r in rows if r["query"] in planned_by_q]
    qs.sort(key=lambda r: (r["query_set"], r["query"]))
    if n and n < len(qs):
        qs = qs[:n]
    _log(f"{len(qs)} frozen questions "
         f"({dict(Counter(r['query_set'] for r in qs))}), gen versions {sorted(set(vers.values()))}")

    cells_path = out_dir / "cells.json"
    cells_cache = _load_cells(cells_path)

    arms = ["firstwins", "rrf_global", "screen_lex", "screen_full", "sem_only",
            "screen_union"]
    agg: dict[str, Counter] = {a: Counter() for a in arms}
    per_q: list[dict] = []

    t0 = time.time()
    for qi, row in enumerate(qs, 1):
        question = row["query"]
        golds = [gold_all[str(c)] for c in row["corpusids"] if str(c) in gold_all]
        planned = planned_by_q[question][:3]
        queries = [*planned, question]
        _log(f"[{qi}/{len(qs)}] ({row['query_set']}) {question[:80]}")

        cell_maps: dict[str, dict[str, list[Paper]]] = {}
        for q in queries:
            cell_maps[q] = asyncio.run(_cell(q, cells_cache, cells_path))
            time.sleep(0.3)  # polite spacing between query fan-outs

        fam_agent = fuse_multi_query({q: cell_maps[q] for q in planned}, SOURCES)
        fam_raw = fuse_multi_query({question: cell_maps[question]}, SOURCES)
        pool = _first_wins([fam_agent, fam_raw])
        if not pool:
            _log("  empty pool — skipped")
            continue
        votes: dict[str, set[str]] = {}
        for name, fam in (("agent", fam_agent), ("raw", fam_raw)):
            for p in fam[:FAMILY_QUOTA]:
                votes.setdefault(_fuse_key(p), set()).add(name)
        for p in pool:
            p.found_by = sorted(votes.get(_fuse_key(p), set()))

        screen_full = screen_papers(pool, queries, model=model, limit=len(pool))
        lex_rows = screen_papers(pool, queries, model="", limit=len(pool))
        by_key = {_fuse_key(p): p for p in pool}
        # union view: every distinct paper the cells returned (target=0 shape).
        # The quota pool is the production default; the union answers "does
        # screening also RESCUE golds the seat cut removed" — rrf_global sees
        # those golds, so screening deserves the same wider stage.
        union: dict[str, Paper] = {}
        for cells in cell_maps.values():
            for lst in cells.values():
                for p in lst:
                    union.setdefault(_fuse_key(p), p)
        union_list = list(union.values())
        for name, fam in (("agent", fam_agent), ("raw", fam_raw)):
            for p in fam:
                votes.setdefault(_fuse_key(p), set()).add(name)
        for p in union_list:
            p.found_by = sorted(votes.get(_fuse_key(p), set()))
        screen_union = screen_papers(union_list, queries, model=model, limit=len(union_list))
        u_by_key = {_fuse_key(p): p for p in union_list}
        orders: dict[str, list[Paper]] = {
            "firstwins": pool,
            "rrf_global": fuse_multi_query(cell_maps, SOURCES),
            "screen_lex": [by_key[_row_key(r)] for r in lex_rows["papers"]],
            "screen_full": [by_key[_row_key(r)] for r in screen_full["papers"]],
            "sem_only": [by_key[_row_key(r)] for r in
                         sorted(screen_full["papers"],
                                key=lambda r: -(r["channels"].get("semantic") or -1))],
            "screen_union": [u_by_key[_row_key(r)] for r in screen_union["papers"]],
        }

        qres: dict = {"question": question, "set": row["query_set"],
                      "pool": len(pool), "golds": len(golds)}
        for arm, ordered in orders.items():
            rank = first_gold_rank(ordered, golds)
            qres[arm] = {
                "in_pool": rank is not None,
                "first_rank": rank,
                "r5": gold_hits_at(ordered, golds, 5),
                "r10": gold_hits_at(ordered, golds, 10),
                "r20": gold_hits_at(ordered, golds, 20),
                "mrr100": (1.0 / rank) if rank and rank <= 100 else 0.0,
            }
            a = agg[arm]
            a["n"] += 1
            a["in_pool"] += int(qres[arm]["in_pool"])
            a["r5"] += qres[arm]["r5"]
            a["r10"] += qres[arm]["r10"]
            a["r20"] += qres[arm]["r20"]
            a["mrr100"] += qres[arm]["mrr100"]
        per_q.append(qres)
        b = qres["firstwins"]
        f = qres["screen_full"]
        _log(f"  pool {len(pool)} | gold in pool: {b['in_pool']} | "
             f"firstwins r20 {b['r20']:.2f} rank {b['first_rank']} -> "
             f"screen_full r20 {f['r20']:.2f} rank {f['first_rank']}")

    n_q = len(per_q)
    summary = {
        arm: {
            "n": c["n"],
            "in_pool%": round(100 * c["in_pool"] / max(c["n"], 1), 1),
            "recall@5": round(c["r5"] / max(c["n"], 1), 3),
            "recall@10": round(c["r10"] / max(c["n"], 1), 3),
            "recall@20": round(c["r20"] / max(c["n"], 1), 3),
            "MRR@100": round(c["mrr100"] / max(c["n"], 1), 3),
        }
        for arm, c in agg.items()
    }

    results_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    (results_dir / f"bench_screen_{ts}.json").write_text(
        json.dumps({"summary": summary, "per_question": per_q,
                    "model": model, "sources": SOURCES,
                    "elapsed_s": round(time.time() - t0)}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    _write_md(results_dir / "bench_screen_latest.md", summary, per_q, model, n_q)
    _log(f"done in {time.time() - t0:.0f}s -> {results_dir / 'bench_screen_latest.md'}")
    return 0


def _row_key(r: dict) -> str:
    return ("d:" + _norm_doi(r.get("doi"))) if r.get("doi") else (
        "t:" + " ".join(sorted(_title_tokens(r.get("title", ""))))
    )


def _write_md(path: Path, summary: dict, per_q: list[dict], model: str, n_q: int) -> None:
    hdr = "| arm | gold in pool % | R@5 | R@10 | R@20 | MRR@100 |"
    sep = "|---|---|---|---|---|---|"
    lines = [
        "# bench: screen triage vs. search order (LitSearch, frozen questions)",
        "",
        f"- questions: {n_q} (the engine's frozen-planner set — the published recall@20=33.3% sample)",
        f"- sources: {', '.join(SOURCES)} × depth {PER_SOURCE} · families: agent(planned, frozen) + raw",
        f"- semantic model: {model}",
        "- arms share the SAME recall pool; only the ordering differs",
        "",
        hdr, sep,
    ]
    for arm, s in summary.items():
        lines.append(
            f"| {arm} | {s['in_pool%']} | {s['recall@5']} | {s['recall@10']} "
            f"| {s['recall@20']} | {s['MRR@100']} |"
        )
    lines += ["", "## per question (gold first-rank; – = not in pool)", "",
              "| set | question (60c) | pool | firstwins | rrf | lex | full | sem | union |",
              "|---|---|---|---|---|---|---|---|---|"]
    for q in per_q:
        ranks = " | ".join(
            str(q[a]["first_rank"]) if q[a]["first_rank"] else "–"
            for a in ("firstwins", "rrf_global", "screen_lex", "screen_full", "sem_only", "screen_union")
        )
        lines.append(f"| {q['set']} | {q['question'][:60]} | {q['pool']} | {ranks} |")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="LitSearch bench for the screen lever")
    ap.add_argument("--data", required=True, help="engine bench_data/litsearch dir (query.parquet, gold_papers.json)")
    ap.add_argument("--gen", required=True, help="engine bench_results/gen_cache.json (frozen planner queries)")
    ap.add_argument("--env", default="", help="optional .env to load (keys raise rate limits only)")
    ap.add_argument("--n", type=int, default=0, help="cap questions (0 = all frozen)")
    ap.add_argument("--model", default=MODEL_DEFAULT)
    ap.add_argument("--out", default="bench_results", help="cells cache dir (gitignored)")
    ap.add_argument("--results", default=str(ROOT / "bench" / "results"))
    args = ap.parse_args()

    if args.env:
        for line in Path(args.env).read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"\s*([A-Z][A-Z0-9_]*)\s*=\s*(.+)\s*$", line)
            if m and m.group(1) not in ("LLM_API_KEY", "LLM_MODEL"):
                os_setenv_safe(m.group(1), m.group(2).strip().strip('"').strip("'"))

    return run(
        Path(args.data), Path(args.gen), args.n, args.model,
        Path(args.out), Path(args.results),
    )


def os_setenv_safe(k: str, v: str) -> None:
    import os

    os.environ.setdefault(k, v)


if __name__ == "__main__":
    sys.exit(main())
